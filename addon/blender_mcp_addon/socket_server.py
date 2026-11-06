"""TCP socket server for the Meshwire addon using bpy.app.timers.

Every socket is non-blocking and every client is a small state machine with a
bounded read buffer and a bounded write buffer. A tick reads what is there, runs
each complete request, queues the reply and sends as much of it as the socket will
take. Nothing here ever waits on a peer.
"""

import atexit
import errno
import hmac
import json
import re
import socket
import sys
import time
import traceback
from pathlib import Path

import bpy

from . import wire
from .handlers import CommandHandlers

MAX_LINE = 32 * 1024 * 1024  # largest request line accepted
MAX_WBUF = 256 * 1024 * 1024  # most unsent reply bytes held for one client
MAX_CLIENTS = 8  # authenticated clients, closing ones included
MAX_PENDING = 16  # sockets that have not finished the handshake; the oldest is dropped past this
READ_PER_TICK = 4 * 1024 * 1024  # most bytes read from one client per tick
SEND_CHUNK = 1024 * 1024
PRE_AUTH_DISCARD = (
    64 * 1024
)  # most a failing pre-auth client may make the add-on read after its error
LISTEN_BACKLOG = 64  # connections the kernel holds for a busy Blender; Windows refuses past it
MAX_CLOSING = 16  # clients already told to go; past this a refusal closes with no reply
CLOSE_GRACE = 2.0  # seconds a closing client has to read its last reply, drained or not
WRITE_STALL = 30.0  # seconds a client may leave unsent reply bytes without taking any


NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
PROOF_RE = re.compile(r"[0-9a-f]{64}")


class TokenError(RuntimeError):
    """The token file could not be read or created, or holds an unusable token."""


class BindError(RuntimeError):
    """No listening socket could be bound. The message says why, in words for the user."""


def _configure_listener(sock) -> None:
    """Socket options for the listener.

    Windows: SO_EXCLUSIVEADDRUSE and never SO_REUSEADDR, which there lets a second
    process bind a port that is already taken. Elsewhere SO_REUSEADDR stays on so a
    restart is not blocked by TIME_WAIT.
    """
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def _port_taken(error: OSError) -> bool:
    """Is this the error for a port someone else holds, so the scan should try the next?

    Windows reports Winsock codes in ``winerror``: 10048 (address in use) and 10013
    (access denied, which an exclusive bind gives when another socket holds the port).
    """
    if getattr(error, "winerror", None) in (10048, 10013):
        return True
    return error.errno in (errno.EADDRINUSE, errno.EACCES)


def bind_listener(host: str, port: int) -> tuple[socket.socket, int]:
    """Bind and listen. Port 0 takes the first free port of the shared range.

    Any other port is bound exactly or not at all. Returns the non-blocking listening
    socket and the port it holds. Raises BindError with a message fit to show.
    """
    if port == 0:
        candidates = range(wire.PORT_FIRST, wire.PORT_LAST + 1)
    elif wire.PORT_MIN <= port <= wire.PORT_MAX:
        candidates = [port]
    else:
        raise BindError(f"Port must be 0 (automatic) or {wire.PORT_MIN} to {wire.PORT_MAX}")
    for candidate in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            _configure_listener(sock)
            sock.setblocking(False)
            sock.bind((host, candidate))
            sock.listen(LISTEN_BACKLOG)
            return sock, candidate
        except OSError as e:
            sock.close()
            if not _port_taken(e):
                raise BindError(f"Could not listen on {host}:{candidate}: {e.strerror or e}") from e
    if port == 0:
        raise BindError(
            f"No free port on {host} from {wire.PORT_FIRST} to {wire.PORT_LAST}: every one is "
            "in use. Close a Blender server you no longer need, or set a port in Preferences"
        )
    raise BindError(
        f"Port {port} on {host} is already in use. Pick another port in Preferences, "
        "or set it to 0 to take the first free one"
    )


class _Client:
    """One connection: its socket, its buffers and where it is in its life."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.rbuf = bytearray()  # bytes received, not yet a complete line
        self.wbuf = bytearray()  # reply bytes not yet sent
        self.authed = False  # set by a good hello_proof; until then only the handshake is read
        self.stage = "hello"  # "hello", then "proof", then authed
        self.nonce_c = ""  # the client's nonce, kept for its proof
        self.nonce_s = ""  # this add-on's nonce for the connection
        self.deadline = 0.0  # monotonic time by which the current handshake step must finish; unused once authed
        self.discard_left = (
            PRE_AUTH_DISCARD  # input a failed pre-auth client may still make us read
        )
        self.closing = False  # close once wbuf drains; read nothing more
        self.close_at = 0.0  # monotonic time a closing client is dropped, drained or not
        self.eof = False  # the peer shut its sending side; read nothing more
        self.half_closed = False  # SHUT_WR sent after the last reply byte left
        self.last_progress = 0.0  # when wbuf last became non-empty or last moved bytes
        self.dead = False  # drop on this tick's cleanup pass


def _error(code: int, message: str, msg_id=None, data=None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "error": error, "id": msg_id}


class MCPSocketServer:
    """
    Non-blocking TCP socket server that runs in Blender's event loop.

    Uses bpy.app.timers for non-blocking I/O since Blender's Python
    runs single-threaded.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9876):
        self.host = host
        self.requested_port = port  # 0 means the first free port; start() scans afresh each time
        self.port = port  # the port held while running
        self.discovery_warning = ""  # set when the instance file could not be written
        self.socket: socket.socket | None = None
        self.clients: dict[socket.socket, _Client] = {}
        self.is_running = False
        self.handlers = CommandHandlers()
        self._timer_registered = False
        self._now = time.monotonic  # one clock for every timer; tests replace it
        self._token = ""  # the secret both sides prove they hold; set by start()
        self._instance_path = None  # the file start() published, removed by stop()

    @property
    def token(self) -> str:
        """The token this server accepts. Never log it."""
        return self._token

    @property
    def client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self.clients)

    def start(self) -> bool:
        """Start the socket server on the port given, or the first free one when it is 0.

        Raises BindError when no port can be bound and TokenError when the token cannot
        be used. Returns False if already running. On success ``self.port`` is the port
        actually held.
        """
        if self.is_running:
            return False
        self.discovery_warning = ""

        self._token = self._load_token()
        self.socket, self.port = bind_listener(self.host, self.requested_port)
        try:
            self.is_running = True

            # Register the timer callback
            if not self._timer_registered:
                bpy.app.timers.register(self._tick, persistent=True)
                self._timer_registered = True
        except Exception:
            self.is_running = False
            self.socket.close()
            self.socket = None
            raise

        self._publish_instance()
        print(f"MCP Server started on {self.host}:{self.port}")
        return True

    @staticmethod
    def _text(value) -> str:
        return value if isinstance(value, str) else ""

    def _publish_instance(self) -> None:
        """Tell the MCP server this Blender is here. A failure costs discovery, not the server."""
        try:
            wire.clean_stale_temps()
            version = self._text(getattr(bpy.app, "version_string", ""))
            self._instance_path = wire.write_instance(
                self.port,
                {
                    "host": self.host,
                    "addon": self._addon_version(),
                    "blender": version or "unknown",
                    "blend": self._text(getattr(bpy.data, "filepath", "")),
                },
            )
            # A normal quit does not always run stop(), and a file left behind is never
            # cleaned up on Windows, where a refused probe is too slow to prove it stale.
            atexit.register(self._unpublish_at_exit)
        except Exception as e:
            reason = e.strerror if isinstance(e, OSError) and e.strerror else e
            where = wire.instances_dir() / f"{self.port}.json"
            self.discovery_warning = (
                f"Discovery is off: could not write the instance file at {where}: {reason}. "
                f"Clients need --port {self.port}."
            )
            print(self.discovery_warning)

    def _unpublish_at_exit(self) -> None:
        """Remove this server's instance file when Python exits with the server still up."""
        wire.remove_instance(self.port)

    @staticmethod
    def _load_token() -> str:
        try:
            token = wire.ensure_token()
        except Exception as e:
            raise TokenError(
                f"Could not read or create the Meshwire token at {wire.token_path()}: {e}"
            ) from e
        if len(token) < wire.MIN_TOKEN:
            raise TokenError(
                f"The Meshwire token at {wire.token_path()} is too short to use "
                f"(under {wire.MIN_TOKEN} characters). Delete it and start the server again"
            )
        return token

    def stop(self):
        """Stop the socket server."""
        self.is_running = False

        # Close all client connections
        for client in list(self.clients.keys()):
            try:
                client.close()
            except Exception:
                pass
        self.clients.clear()

        # Unpublish before the port is freed: once it is free, another Blender may bind it
        # and publish its own file under the same name, which this must not delete.
        if self._instance_path is not None:
            wire.remove_instance(self.port)
            atexit.unregister(self._unpublish_at_exit)
            self._instance_path = None
        self.discovery_warning = ""

        # Close server socket
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

        # Unregister timer
        if self._timer_registered:
            try:
                bpy.app.timers.unregister(self._tick)
            except Exception:
                pass
            self._timer_registered = False

        print("MCP Server stopped")

    def _tick(self) -> float | None:
        """Timer callback - processes socket events. Returns interval or None to stop."""
        if not self.is_running:
            self._timer_registered = False
            return None

        try:
            self._accept_clients()
            self._process_clients()
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            # Not only Exception: a SystemExit that got this far would unregister the timer
            # (or quit Blender) and leave the server deaf.
            print(f"MCP Server tick error: {e!r}")
            traceback.print_exc()

        # Return interval in seconds (10ms)
        return 0.01

    def _accept_clients(self):
        """Accept pending connections. Past MAX_CLIENTS the newcomer is told why and closed."""
        if self.socket is None:
            return

        while True:
            try:
                sock, addr = self.socket.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError as e:
                print(f"Error accepting client: {e}")
                return
            sock.setblocking(False)
            client = _Client(sock)
            client.deadline = self._now() + wire.HELLO_SECONDS
            pending = [sk for sk, c in self.clients.items() if not c.authed]
            if len(pending) >= MAX_PENDING:
                # Sockets that have not proved the token cannot crowd out ones that can:
                # the oldest of them goes, with no reply. The client sees a close before
                # any reply and stops with an error; it never moves on to another Blender.
                oldest = pending[0]
                self._drop(oldest, self.clients[oldest])
            print(f"MCP client connected: {addr}")
            self.clients[sock] = client

    def _process_clients(self):
        """Read, run and answer every client, then drop the ones that are finished."""
        now = self._now()
        for client in list(self.clients.values()):
            try:
                self._read(client)
                self._run_lines(client)
                self._flush(client)
                if not client.authed and not client.closing and now >= client.deadline:
                    # Read first: the server cannot tell "sent late" from "read late", so a
                    # stall of Blender's own main thread must not cost a client that answered.
                    client.dead = True  # still no good step in time: close, no reply
                    continue
                self._expire(client, now)
            except Exception as e:
                print(f"Error processing client: {e}")
                traceback.print_exc()
                client.dead = True

        for sock, client in list(self.clients.items()):
            if client.dead:
                self._drop(sock, client)

    def _read(self, client: _Client):
        """Take up to READ_PER_TICK bytes. A closing client's input is thrown away.

        A client with unsent reply bytes is not read at all: TCP pushes back on a peer
        that sends requests but does not take the answers.
        """
        taken = 0
        while taken < READ_PER_TICK and not client.dead and not client.eof and not client.wbuf:
            want = min(1024 * 1024, READ_PER_TICK - taken)
            if not client.authed and not client.closing:
                # Before the handshake is done nothing may buffer past one hello line.
                # (A closing client's input is thrown away, so it reads at full size.)
                want = min(want, wire.HELLO_MAX + 1 - len(client.rbuf))
                if want <= 0:
                    return
            elif not client.authed:
                # A failed pre-auth client has no token. It gets its error, then a bounded
                # amount of its input is thrown away; past that it is cut off.
                want = min(want, client.discard_left)
            try:
                data = client.sock.recv(want)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                client.dead = True
                return
            if not data:
                # The peer will send no more but may still read (a half-close). It is
                # served like a live client: every complete line it sent is answered
                # under the usual backpressure and WRITE_STALL, a trailing partial line
                # is dropped, and it closes once nothing is left to run or send.
                client.eof = True
                return
            taken += len(data)
            if not client.closing:
                client.rbuf += data
            elif not client.authed:
                client.discard_left -= len(data)
                if client.discard_left <= 0:
                    client.dead = True
                    return

    def _run_lines(self, client: _Client):
        """Run each complete line in rbuf, one at a time, while no reply is waiting to leave.

        A bad line queues an error and ends the client. A closing client runs nothing,
        except one whose peer half-closed, which still gets its complete lines answered.
        """
        while not client.dead and not client.wbuf and (not client.closing or client.eof):
            end = client.rbuf.find(b"\n")
            if not client.authed and (end if end >= 0 else len(client.rbuf)) > wire.HELLO_MAX:
                client.dead = True  # a first line past HELLO_MAX is not a hello: close, no reply
                return
            if end < 0:
                if client.eof:
                    client.rbuf.clear()  # a partial last line is dropped
                elif len(client.rbuf) > MAX_LINE:
                    self._too_large(client)
                return
            if end > MAX_LINE:
                self._too_large(client)
                return
            line = bytes(client.rbuf[:end])
            del client.rbuf[: end + 1]
            if not line.strip():
                continue
            if client.authed:
                self._handle_line(client, line)
            else:
                self._handle_hello(client, line)
            self._flush(client)

    def _too_large(self, client: _Client):
        self._fail(
            client,
            wire.E_TOO_LARGE,
            f"Request too large: a line may be at most {MAX_LINE} bytes",
        )

    def _handle_hello(self, client: _Client, line: bytes):
        """One pre-auth line. One try: a bad line gets one reply or none, then a close.

        The handshake is two lines. The client sends hello with a nonce and no token; the
        add-on answers with its own nonce and a proof that it holds the token. The client
        checks that proof, then sends hello_proof with its own, and only then is it authed.
        """
        try:
            message = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError):
            message = None
        if not isinstance(message, dict):
            if client.stage == "proof":
                self._fail(client, wire.E_UNAUTHORIZED, self._unauthorized_text())
            else:
                client.dead = True  # HTTP, garbage, binary: not a Meshwire client, so no reply
            return
        if self._refuse_bad_id(client, message):
            return
        msg_id = message.get("id")
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if client.stage == "proof":
            self._handle_proof(client, message, params, msg_id)
        else:
            self._handle_first(client, message, params, msg_id)

    def _refuse_bad_id(self, client: _Client, message: dict) -> bool:
        """JSON-RPC ids are a string, an integer (not a bool) or null. Nothing else is echoed."""
        value = message.get("id")
        if value is None or type(value) is str or type(value) is int:
            return False
        self._fail(client, -32600, "Invalid request: id must be a string, an integer or null")
        return True

    def _handle_first(self, client: _Client, message: dict, params: dict, msg_id):
        if message.get("method") != "hello":
            self._fail(
                client,
                wire.E_PROTOCOL,
                "This Meshwire add-on needs a newer Meshwire server. "
                "Update it, for example `uvx meshwire@latest`.",
                msg_id,
            )
            return
        theirs = params.get("protocol")
        if type(theirs) is not int or theirs != wire.PROTOCOL:
            newer = type(theirs) is int and theirs > wire.PROTOCOL
            side = "the Meshwire add-on in Blender" if newer else "the Meshwire server"
            self._fail(
                client,
                wire.E_PROTOCOL,
                f"Protocol mismatch: this add-on speaks protocol {wire.PROTOCOL}, "
                f"the client speaks {theirs!r}. Update {side}.",
                msg_id,
                {"protocol": wire.PROTOCOL},  # numbers only, so a client can act on it unread
            )
            return
        nonce = params.get("nonce")
        if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
            self._fail(
                client,
                wire.E_PROTOCOL,
                "hello needs a nonce of 16 to 128 URL-safe characters (A-Z a-z 0-9 _ -).",
                msg_id,
            )
            return
        if len(self._token) < wire.MIN_TOKEN:
            client.dead = True  # no usable token: serve nobody
            return
        client.nonce_c = nonce
        client.nonce_s = wire.new_nonce()
        client.stage = "proof"
        client.deadline = self._now() + wire.HELLO_SECONDS  # the proof gets its own 2 s
        # The address these bytes actually arrived at. It is inside the proof, so a relay
        # that forwards the exchange from another address or port cannot keep it valid.
        local = client.sock.getsockname()
        seen = wire.endpoint(str(local[0]), int(local[1]))
        result = {
            "protocol": wire.PROTOCOL,
            "addon": self._addon_version(),
            "port": self.port,
            "nonce": client.nonce_s,
            "seen": seen,
            "proof": wire.proof(self._token, wire.ADDON_LABEL, nonce, client.nonce_s, seen),
        }
        self._queue(client, {"jsonrpc": "2.0", "result": result, "id": msg_id}, msg_id)

    @staticmethod
    def _unauthorized_text() -> str:
        return (
            "Unauthorized: the proof did not match. The token must match the one in "
            "Blender's Meshwire tab."
        )

    def _handle_proof(self, client: _Client, message: dict, params: dict, msg_id):
        theirs = params.get("proof")
        expected = wire.proof(self._token, wire.CLIENT_LABEL, client.nonce_s, client.nonce_c)
        good = (
            message.get("method") == "hello_proof"
            and isinstance(theirs, str)
            and PROOF_RE.fullmatch(theirs) is not None
            and hmac.compare_digest(theirs.encode("ascii"), expected.encode("ascii"))
        )
        if not good:
            self._fail(client, wire.E_UNAUTHORIZED, self._unauthorized_text(), msg_id)
            return
        authed = sum(1 for c in self.clients.values() if c.authed)
        if authed >= MAX_CLIENTS:
            closing = sum(1 for c in self.clients.values() if c.closing)
            if closing >= MAX_CLOSING:
                client.dead = True  # refusals are capped too: no reply, no slot
                return
            self._fail(
                client,
                wire.E_TOO_MANY,
                f"Too many clients: this add-on serves at most {MAX_CLIENTS} at once",
                msg_id,
            )
            return
        client.authed = True
        client.deadline = 0.0
        self._queue(client, {"jsonrpc": "2.0", "result": {"ok": True}, "id": msg_id}, msg_id)

    @staticmethod
    def _addon_version() -> str:
        """The version in the manifest that sits next to this package's files."""
        try:
            try:
                import tomllib
            except (
                ModuleNotFoundError
            ):  # Blender's Python always has it; only 3.10 unit tests lack it
                import tomli as tomllib
            path = Path(__file__).resolve().parent / "blender_manifest.toml"
            return str(tomllib.loads(path.read_text(encoding="utf-8"))["version"])
        except Exception:
            return "unknown"

    def _handle_line(self, client: _Client, line: bytes):
        try:
            message = json.loads(line.decode("utf-8"))
        except UnicodeDecodeError:
            self._fail(client, wire.E_PARSE, "Parse error: request is not valid UTF-8")
            return
        except (ValueError, RecursionError) as e:
            self._fail(client, wire.E_PARSE, f"Parse error: {e}")
            return
        if not isinstance(message, dict):
            self._fail(client, wire.E_PARSE, "Parse error: request must be a JSON object")
            return
        if self._refuse_bad_id(client, message):
            return
        self._queue(client, self._handle_message(message), message.get("id"))

    def _fail(self, client: _Client, code: int, text: str, msg_id=None, data=None):
        """Queue an error reply, then close once it has been sent."""
        client.rbuf.clear()
        self._queue(client, _error(code, text, msg_id, data), msg_id)
        client.closing = True
        now = self._now()
        client.close_at = now + CLOSE_GRACE
        if not client.authed and client.deadline:
            # Failing a hello must not extend the client's stay past its hello deadline.
            client.close_at = min(client.close_at, max(client.deadline, now))

    def _queue(self, client: _Client, response: dict, msg_id):
        """Encode a reply into wbuf, never past MAX_WBUF: an overflowing reply becomes an error reply."""
        try:
            data = (json.dumps(response, default=self._json_default) + "\n").encode("utf-8")
        except Exception as e:
            data = None
            problem = f"Reply could not be encoded: {e}"
            code = -32603
        else:
            problem = (
                f"Reply too large: {len(data)} bytes does not fit the {MAX_WBUF} byte write buffer"
            )
            code = wire.E_REPLY_TOO_LARGE
        if data is None or len(client.wbuf) + len(data) > MAX_WBUF:
            data = (json.dumps(_error(code, problem, msg_id)) + "\n").encode("utf-8")
            if len(client.wbuf) + len(data) > MAX_WBUF:
                # Not even the error fits: the bound beats the reply. Hang up.
                if not client.closing:
                    client.closing = True
                    client.close_at = self._now() + CLOSE_GRACE
                return
        if not client.wbuf:
            client.last_progress = self._now()
        client.wbuf += data

    def _flush(self, client: _Client):
        """Send from wbuf until the socket stops taking bytes."""
        while client.wbuf and not client.dead:
            # Release both views before wbuf is touched again: a send that raised keeps its
            # arguments alive in the traceback, and a live view forbids resizing wbuf.
            view = memoryview(client.wbuf)
            chunk = view[:SEND_CHUNK]
            failed = False
            try:
                sent = client.sock.send(chunk)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                failed = True
                sent = 0
            finally:
                chunk.release()
                view.release()
            if failed:
                client.dead = True
                client.wbuf.clear()
                return
            del client.wbuf[:sent]
            if sent:
                client.last_progress = self._now()

    def _expire(self, client: _Client, now: float):
        """Apply the clocks: a closing client leaves at close_at, a stalled writer at WRITE_STALL.

        Once a closing client's reply is out it is half-closed so the peer sees EOF.
        """
        if client.dead:
            return
        if client.eof and not client.wbuf and b"\n" not in client.rbuf:
            client.dead = True  # every complete line was answered and sent
            return
        if client.closing:
            if now >= client.close_at:
                client.dead = True
            elif not client.wbuf and not client.half_closed:
                client.half_closed = True
                try:
                    client.sock.shutdown(socket.SHUT_WR)
                except OSError:
                    client.dead = True
        if client.wbuf and now - client.last_progress >= WRITE_STALL:
            client.dead = True

    def _drop(self, sock: socket.socket, client: _Client):
        client.wbuf.clear()
        client.rbuf.clear()
        try:
            sock.close()
        except Exception:
            pass
        self.clients.pop(sock, None)
        print("MCP client disconnected")

    def _handle_message(self, message: dict) -> dict:
        """Run one parsed JSON-RPC request and return its reply."""
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        if not method:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Invalid request: missing method"},
                "id": msg_id,
            }

        try:
            result = self.handlers.handle(method, params)
            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": msg_id,
            }
        except (Exception, SystemExit) as e:
            traceback.print_exc()
            text = (
                "A handler called exit(); Blender keeps running."
                if isinstance(e, SystemExit)
                else str(e)
            )
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": text},
                "id": msg_id,
            }

    @staticmethod
    def _json_default(obj):
        """JSON serializer for objects not serializable by default."""
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, dict)):
            return list(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

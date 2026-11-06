"""TCP socket server for the Meshwire addon using bpy.app.timers.

Every socket is non-blocking and every client is a small state machine with a
bounded read buffer and a bounded write buffer. A tick reads what is there, runs
each complete request, queues the reply and sends as much of it as the socket will
take. Nothing here ever waits on a peer.
"""

import hmac
import json
import re
import socket
import sys
import time
import traceback

import bpy

from . import wire
from .handlers import CommandHandlers

MAX_LINE = 32 * 1024 * 1024  # largest request line accepted
MAX_WBUF = 256 * 1024 * 1024  # most unsent reply bytes held for one client
MAX_CLIENTS = 8  # authenticated clients, closing ones included
MAX_PENDING = 16  # sockets that have not finished the handshake; the oldest is dropped past this
READ_PER_TICK = 4 * 1024 * 1024  # most bytes read from one client per tick
SEND_CHUNK = 1024 * 1024
MAX_CLOSING = 16  # clients already told to go; past this a refusal closes with no reply
CLOSE_GRACE = 2.0  # seconds a closing client has to read its last reply, drained or not
WRITE_STALL = 30.0  # seconds a client may leave unsent reply bytes without taking any


NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
PROOF_RE = re.compile(r"[0-9a-f]{64}")


class TokenError(RuntimeError):
    """The token file could not be read or created, or holds an unusable token."""


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
        self.deadline = 0.0  # monotonic time by which the handshake must finish; unused once authed
        self.closing = False  # close once wbuf drains; read nothing more
        self.close_at = 0.0  # monotonic time a closing client is dropped, drained or not
        self.eof = False  # the peer shut its sending side; read nothing more
        self.half_closed = False  # SHUT_WR sent after the last reply byte left
        self.last_progress = 0.0  # when wbuf last became non-empty or last moved bytes
        self.dead = False  # drop on this tick's cleanup pass


def _error(code: int, message: str, msg_id=None) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": msg_id}


class MCPSocketServer:
    """
    Non-blocking TCP socket server that runs in Blender's event loop.

    Uses bpy.app.timers for non-blocking I/O since Blender's Python
    runs single-threaded.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9876):
        self.host = host
        self.port = port
        self.socket: socket.socket | None = None
        self.clients: dict[socket.socket, _Client] = {}
        self.is_running = False
        self.handlers = CommandHandlers()
        self._timer_registered = False
        self._now = time.monotonic  # one clock for every timer; tests replace it
        self._token = ""  # the secret both sides prove they hold; set by start()

    @property
    def token(self) -> str:
        """The token this server accepts. Never log it."""
        return self._token

    @property
    def client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self.clients)

    def start(self) -> bool:
        """Start the socket server."""
        if self.is_running:
            return False

        self._token = self._load_token()
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setblocking(False)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.is_running = True

            # Register the timer callback
            if not self._timer_registered:
                bpy.app.timers.register(self._tick, persistent=True)
                self._timer_registered = True

            print(f"MCP Server started on {self.host}:{self.port}")
            return True

        except Exception as e:
            print(f"Failed to start MCP server: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False

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
        except Exception as e:
            print(f"MCP Server tick error: {e}")
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
                # the oldest of them goes, with no reply.
                oldest = pending[0]
                self._drop(oldest, self.clients[oldest])
            print(f"MCP client connected: {addr}")
            self.clients[sock] = client

    def _process_clients(self):
        """Read, run and answer every client, then drop the ones that are finished."""
        now = self._now()
        for client in list(self.clients.values()):
            try:
                if not client.authed and not client.closing and now >= client.deadline:
                    client.dead = True  # no good hello in time: close, whatever it sent
                    continue
                self._read(client)
                self._run_lines(client)
                self._flush(client)
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
            if not client.authed:
                # Before the handshake is done nothing may buffer past one hello line.
                want = min(want, wire.HELLO_MAX + 1 - len(client.rbuf))
                if want <= 0:
                    return
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
        msg_id = message.get("id")
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if client.stage == "proof":
            self._handle_proof(client, message, params, msg_id)
        else:
            self._handle_first(client, message, params, msg_id)

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
        result = {
            "protocol": wire.PROTOCOL,
            "addon": self._addon_version(),
            "port": self.port,
            "nonce": client.nonce_s,
            "proof": wire.proof(self._token, wire.ADDON_LABEL, nonce, client.nonce_s),
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
        info = getattr(sys.modules.get(__package__ or ""), "bl_info", None)
        version = info.get("version") if isinstance(info, dict) else None
        if isinstance(version, (tuple, list)):
            return ".".join(map(str, version))
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
        self._queue(client, self._handle_message(message), message.get("id"))

    def _fail(self, client: _Client, code: int, text: str, msg_id=None):
        """Queue an error reply, then close once it has been sent."""
        client.rbuf.clear()
        self._queue(client, _error(code, text, msg_id), msg_id)
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
            try:
                with memoryview(client.wbuf) as view:
                    sent = client.sock.send(view[:SEND_CHUNK])
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
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
        except Exception as e:
            traceback.print_exc()
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)},
                "id": msg_id,
            }

    @staticmethod
    def _json_default(obj):
        """JSON serializer for objects not serializable by default."""
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, dict)):
            return list(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

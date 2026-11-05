"""TCP socket server for the Meshwire addon using bpy.app.timers.

Every socket is non-blocking and every client is a small state machine with a
bounded read buffer and a bounded write buffer. A tick reads what is there, runs
each complete request, queues the reply and sends as much of it as the socket will
take. Nothing here ever waits on a peer.
"""

import json
import socket
import time
import traceback

import bpy

from . import wire
from .handlers import CommandHandlers

MAX_LINE = 32 * 1024 * 1024  # largest request line accepted
MAX_WBUF = 256 * 1024 * 1024  # most unsent reply bytes held for one client
MAX_CLIENTS = 8
READ_PER_TICK = 4 * 1024 * 1024  # most bytes read from one client per tick
SEND_CHUNK = 1024 * 1024
CLOSE_GRACE = 1.0  # seconds a closing client may take to read its last reply


class _Client:
    """One connection: its socket, its buffers and where it is in its life."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.rbuf = bytearray()  # bytes received, not yet a complete line
        self.wbuf = bytearray()  # reply bytes not yet sent
        self.authed = False  # token auth sets this (nothing checks it yet)
        self.deadline = 0.0  # monotonic time by which auth must finish; 0 means none
        self.closing = False  # close once wbuf drains; read nothing more
        self.close_at = 0.0  # set once wbuf drained while closing
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

    @property
    def client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self.clients)

    def start(self) -> bool:
        """Start the socket server."""
        if self.is_running:
            return False

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
            live = sum(1 for c in self.clients.values() if not c.closing)
            if live >= MAX_CLIENTS:
                self._fail(
                    client,
                    wire.E_TOO_MANY,
                    f"Too many clients: this add-on serves at most {MAX_CLIENTS} at once",
                )
                print(f"MCP client refused (limit {MAX_CLIENTS}): {addr}")
            else:
                print(f"MCP client connected: {addr}")
            self.clients[sock] = client

    def _process_clients(self):
        """Read, run and answer every client, then drop the ones that are finished."""
        now = time.monotonic()
        for client in list(self.clients.values()):
            try:
                self._read(client)
                if not client.closing:
                    self._run_lines(client)
                self._flush(client)
                self._finish_closing(client, now)
            except Exception as e:
                print(f"Error processing client: {e}")
                traceback.print_exc()
                client.dead = True

        for sock, client in list(self.clients.items()):
            if client.dead:
                self._drop(sock, client)

    def _read(self, client: _Client):
        """Take up to READ_PER_TICK bytes. A closing client's input is thrown away."""
        taken = 0
        while taken < READ_PER_TICK and not client.dead:
            try:
                data = client.sock.recv(min(1024 * 1024, READ_PER_TICK - taken))
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                client.dead = True
                return
            if not data:
                client.dead = True  # peer closed; anything unsent has nowhere to go
                return
            taken += len(data)
            if not client.closing:
                client.rbuf += data

    def _run_lines(self, client: _Client):
        """Run each complete line in rbuf. A bad line queues an error and ends the client."""
        while not client.closing:
            end = client.rbuf.find(b"\n")
            if end < 0:
                if len(client.rbuf) > MAX_LINE:
                    self._too_large(client)
                return
            if end > MAX_LINE:
                self._too_large(client)
                return
            line = bytes(client.rbuf[:end])
            del client.rbuf[: end + 1]
            if not line.strip():
                continue
            self._handle_line(client, line)

    def _too_large(self, client: _Client):
        self._fail(
            client,
            wire.E_TOO_LARGE,
            f"Request too large: a line may be at most {MAX_LINE} bytes",
        )

    def _handle_line(self, client: _Client, line: bytes):
        try:
            message = json.loads(line.decode("utf-8"))
        except UnicodeDecodeError:
            self._fail(client, wire.E_PARSE, "Parse error: request is not valid UTF-8")
            return
        except ValueError as e:
            self._fail(client, wire.E_PARSE, f"Parse error: {e}")
            return
        if not isinstance(message, dict):
            self._fail(client, wire.E_PARSE, "Parse error: request must be a JSON object")
            return
        self._queue(client, self._handle_message(message), message.get("id"))

    def _fail(self, client: _Client, code: int, text: str):
        """Queue an error reply, then close once it has been sent."""
        client.rbuf.clear()
        self._queue(client, _error(code, text), None)
        client.closing = True

    def _queue(self, client: _Client, response: dict, msg_id):
        """Encode a reply into wbuf. One that would overflow MAX_WBUF becomes an error reply."""
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

    def _finish_closing(self, client: _Client, now: float):
        """Once a closing client's reply is out, half-close and give the peer a moment to read."""
        if not client.closing or client.dead or client.wbuf:
            return
        if client.close_at == 0.0:
            try:
                client.sock.shutdown(socket.SHUT_WR)
            except OSError:
                client.dead = True
                return
            client.close_at = now + CLOSE_GRACE
        elif now >= client.close_at:
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

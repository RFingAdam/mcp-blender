"""TCP socket server for Blender MCP addon using bpy.app.timers."""

import json
import socket
import traceback

import bpy

from .handlers import CommandHandlers


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
        self.clients: dict[socket.socket, bytes] = {}  # client -> buffer
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
        """Accept any pending client connections."""
        if self.socket is None:
            return

        try:
            while True:
                try:
                    client, addr = self.socket.accept()
                    client.setblocking(False)
                    self.clients[client] = b""
                    print(f"MCP client connected: {addr}")
                except BlockingIOError:
                    # No pending connections
                    break
        except Exception as e:
            print(f"Error accepting client: {e}")

    def _process_clients(self):
        """Process data from all connected clients."""
        disconnected = []

        for client, buffer in list(self.clients.items()):
            try:
                # Try to receive data
                try:
                    data = client.recv(65536)
                    if not data:
                        # Client disconnected
                        disconnected.append(client)
                        continue
                    buffer += data
                    self.clients[client] = buffer
                except BlockingIOError:
                    # No data available
                    pass
                except ConnectionResetError:
                    disconnected.append(client)
                    continue

                # Process complete messages (newline-delimited JSON)
                buffer = self.clients[client]
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self.clients[client] = buffer

                    if line.strip():
                        response = self._handle_message(line)
                        self._send_response(client, response)

            except Exception as e:
                print(f"Error processing client: {e}")
                traceback.print_exc()
                disconnected.append(client)

        # Clean up disconnected clients
        for client in disconnected:
            try:
                client.close()
            except Exception:
                pass
            if client in self.clients:
                del self.clients[client]
            print("MCP client disconnected")

    def _handle_message(self, data: bytes) -> dict:
        """Handle an incoming JSON-RPC message."""
        try:
            message = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as e:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": f"Parse error: {e}"},
                "id": None,
            }

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

    def _send_response(self, client: socket.socket, response: dict):
        """Send a JSON response to a client."""
        try:
            data = json.dumps(response, default=self._json_default) + "\n"
            client.sendall(data.encode("utf-8"))
        except Exception as e:
            print(f"Error sending response: {e}")

    @staticmethod
    def _json_default(obj):
        """JSON serializer for objects not serializable by default."""
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, dict)):
            return list(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

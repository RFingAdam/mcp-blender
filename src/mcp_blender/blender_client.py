"""Async TCP client for communicating with the Meshwire addon."""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from . import __version__, wire

logger = logging.getLogger("meshwire.client")

# The add-on holds at most 256 MiB of reply per client, so no honest reply line is longer.
MAX_REPLY_LINE = 256 * 1024 * 1024 + 1024 * 1024
READ_SIZE = 1024 * 1024


class BlenderConnectionError(Exception):
    """Raised when connection to Blender fails."""

    pass


class BlenderCommandError(Exception):
    """Raised when a Blender command fails."""

    pass


class BlenderClient:
    """
    Async TCP client for communicating with the Meshwire addon.

    Uses JSON-RPC 2.0 protocol over TCP with newline-delimited messages.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9876):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._connected = False
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None
        self._epoch = 0  # bumped by disconnect(); an _open() that straddles one is void

    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._writer is not None

    async def connect(self, timeout: float = 5.0) -> None:
        """
        Connect to the Blender addon socket server.

        Args:
            timeout: Connection timeout in seconds

        Raises:
            BlenderConnectionError: If connection fails
        """
        if self._connected:
            return

        # Concurrent callers queue here; the ones after the first find it connected.
        async with self._connect_lock:
            if self._connected:
                return
            await self._open(timeout)

    async def _open(self, timeout: float) -> None:
        """Connect, say hello and read its one reply. Only then is the client connected.

        The token is read afresh on every connect, so a token that changed since the
        last connection is noticed here and not cached past a restart of Blender.
        """
        token = wire.read_token()
        if not token:
            raise BlenderConnectionError(
                f"No Meshwire token found at {wire.token_path()}. "
                "Start the server in Blender's Meshwire tab first."
            )
        epoch = self._epoch
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout,
            )
            reader, writer = self._reader, self._writer
            await self._hello(reader, writer, token, timeout)
            if epoch != self._epoch:
                raise BlenderConnectionError("Disconnected")
            # No await between here and the end: a disconnect() cannot slip in and
            # leave _connected True over a closed writer.
            self._connected = True
            logger.info(f"Connected to Blender at {self.host}:{self.port}")
            self._read_task = asyncio.create_task(self._read_loop())

        except asyncio.TimeoutError:
            await self._abandon(epoch)
            raise BlenderConnectionError(
                f"Connection to Blender timed out ({self.host}:{self.port})"
            )
        except ConnectionRefusedError:
            await self._abandon(epoch)
            raise BlenderConnectionError(
                f"Connection refused. Is Blender running with MCP addon enabled? ({self.host}:{self.port})"
            )
        except BlenderConnectionError:
            await self._abandon(epoch)
            raise
        except OSError as e:
            await self._abandon(epoch)
            raise BlenderConnectionError(f"Connection failed: {e}")

    async def _abandon(self, epoch: int) -> None:
        """Close a half-open connection, unless a disconnect() already did."""
        if epoch == self._epoch:
            await self.disconnect()

    async def _hello(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        token: str,
        timeout: float,
    ) -> None:
        """Send the hello line and check the add-on's one reply."""
        request = wire.hello_request(token, str(uuid.uuid4()), client=f"meshwire {__version__}")
        writer.write((json.dumps(request) + "\n").encode("utf-8"))
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        except (ValueError, asyncio.LimitOverrunError):
            raise BlenderConnectionError("Blender sent an unreadable reply to the hello")
        except (ConnectionError, asyncio.IncompleteReadError):
            line = b""
        if not line.strip():
            raise BlenderConnectionError(
                "Blender closed the connection during the handshake. "
                f"Is this a Meshwire add-on? ({self.host}:{self.port})"
            )
        try:
            reply = json.loads(line.decode("utf-8"))
        except ValueError:
            reply = None
        if not isinstance(reply, dict):
            raise BlenderConnectionError(
                f"Whatever answered on {self.host}:{self.port} is not a Meshwire add-on"
            )
        error = reply.get("error")
        if error is not None:
            raise self._hello_error(error)
        result = reply.get("result")
        if not isinstance(result, dict) or result.get("protocol") != wire.PROTOCOL:
            raise BlenderConnectionError(
                "The Meshwire add-on in Blender speaks a different protocol "
                f"({result.get('protocol') if isinstance(result, dict) else None!r}, "
                f"this server speaks {wire.PROTOCOL}). Update the older side."
            )

    @staticmethod
    def _hello_error(error: Any) -> BlenderConnectionError:
        code = error.get("code") if isinstance(error, dict) else None
        message = str(error.get("message", error)) if isinstance(error, dict) else str(error)
        if code == wire.E_UNAUTHORIZED:
            text = (
                f"Blender refused the Meshwire token. The token must match the one in "
                f"Blender's Meshwire tab; this server reads {wire.token_path()}."
            )
            if os.environ.get("MESHWIRE_TOKEN", "").strip():
                text += (
                    " MESHWIRE_TOKEN is set and overrides that file. "
                    "Restart the MCP client after changing it."
                )
            else:
                text += " If the token changed, restart the MCP client."
            return BlenderConnectionError(text)
        # A v0.4.0 add-on has no hello: its dispatcher raises ValueError("Unknown
        # method: hello") and the server wraps that as -32603. A -32601 is accepted too.
        if code == -32601 or (code == -32603 and message.startswith("Unknown method")):
            return BlenderConnectionError(
                "The Meshwire add-on in Blender is older than this server. Update the add-on."
            )
        return BlenderConnectionError(message)

    async def disconnect(self) -> None:
        """Disconnect from Blender."""
        self._connected = False
        self._epoch += 1  # voids an _open() still waiting on its hello

        # Take everything this connection owns before the first await below, so a
        # send_command that reconnects meanwhile installs state we never touch.
        read_task, self._read_task = self._read_task, None
        writer, self._writer = self._writer, None
        self._reader = None
        pending = list(self._pending_requests.values())
        self._pending_requests.clear()

        # The read loop disconnects itself when the socket closes; it cannot await itself.
        if read_task and read_task is not asyncio.current_task():
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass

        if writer:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        # Cancel any pending requests
        for future in pending:
            if not future.done():
                future.set_exception(BlenderConnectionError("Disconnected"))

        logger.info("Disconnected from Blender")

    async def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """
        Send a command to Blender and wait for the response.

        Args:
            method: The command method name
            params: Command parameters
            timeout: Response timeout in seconds

        Returns:
            The result from Blender

        Raises:
            BlenderConnectionError: If not connected
            BlenderCommandError: If the command fails
            asyncio.TimeoutError: If response times out
        """
        if not self._connected:
            await self.connect()

        if not self._writer:
            raise BlenderConnectionError("Not connected to Blender")

        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Build JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            # Send request
            async with self._lock:
                message = json.dumps(request) + "\n"
                self._writer.write(message.encode("utf-8"))
                await self._writer.drain()

            logger.debug(f"Sent command: {method}")

            # Wait for response
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise asyncio.TimeoutError(f"Command '{method}' timed out after {timeout}s")

        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

    async def _read_loop(self) -> None:
        """Background task to read responses from Blender."""
        buffer = bytearray()
        scanned = 0  # bytes of buffer already known to hold no newline

        while self._connected and self._reader:
            try:
                data = await self._reader.read(READ_SIZE)
                if not data:
                    # Connection closed
                    logger.warning("Connection closed by Blender")
                    await self.disconnect()
                    break

                buffer += data

                # Process complete messages
                while (end := buffer.find(b"\n", scanned)) >= 0:
                    line = bytes(buffer[:end])
                    del buffer[: end + 1]
                    scanned = 0
                    if line.strip():
                        await self._handle_response(line)
                scanned = len(buffer)

                if len(buffer) > MAX_REPLY_LINE:
                    self._fail_pending(
                        BlenderConnectionError(
                            f"Reply from Blender too large (over {MAX_REPLY_LINE} bytes)"
                        )
                    )
                    await self.disconnect()
                    break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Read error: {e}")
                await self.disconnect()
                break

    def _fail_pending(self, exc: Exception) -> None:
        """Fail every request still waiting for a reply with ``exc``."""
        pending = list(self._pending_requests.values())
        self._pending_requests.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)

    async def _handle_response(self, data: bytes) -> None:
        """Handle a JSON-RPC response from Blender."""
        try:
            response = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response: {e}")
            return

        if not isinstance(response, dict):
            logger.error("Reply from Blender is not a JSON object")
            return

        request_id = response.get("id")
        if request_id is None:
            # The add-on could not tell which request was bad (parse error, too many
            # clients, oversize line) and is about to close the connection. Every
            # waiting request gets its reason.
            error = response.get("error")
            if error:
                message = (
                    error.get("message", str(error)) if isinstance(error, dict) else str(error)
                )
                self._fail_pending(BlenderCommandError(message))
            else:
                logger.warning("Received response without ID")
            return

        future = self._pending_requests.pop(request_id, None)
        if future is None:
            logger.warning(f"Received response for unknown request: {request_id}")
            return

        if "error" in response:
            error = response["error"]
            error_msg = error.get("message", str(error))
            future.set_exception(BlenderCommandError(error_msg))
        else:
            future.set_result(response.get("result"))

    async def ping(self, timeout: float = 5.0) -> bool:
        """
        Test connectivity to Blender.

        Returns:
            True if connected and responsive
        """
        try:
            result = await self.send_command("ping", timeout=timeout)
            return result.get("pong", False)
        except Exception:
            return False

    async def __aenter__(self) -> "BlenderClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

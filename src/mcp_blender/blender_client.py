"""Async TCP client for communicating with the Blender MCP addon."""

import asyncio
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger("mcp-blender.client")


class BlenderConnectionError(Exception):
    """Raised when connection to Blender fails."""

    pass


class BlenderCommandError(Exception):
    """Raised when a Blender command fails."""

    pass


class BlenderClient:
    """
    Async TCP client for communicating with the Blender MCP addon.

    Uses JSON-RPC 2.0 protocol over TCP with newline-delimited messages.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9876):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None

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

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout,
            )
            self._connected = True
            logger.info(f"Connected to Blender at {self.host}:{self.port}")

            # Start background reader task
            self._read_task = asyncio.create_task(self._read_loop())

        except asyncio.TimeoutError:
            raise BlenderConnectionError(
                f"Connection to Blender timed out ({self.host}:{self.port})"
            )
        except ConnectionRefusedError:
            raise BlenderConnectionError(
                f"Connection refused. Is Blender running with MCP addon enabled? ({self.host}:{self.port})"
            )
        except OSError as e:
            raise BlenderConnectionError(f"Connection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from Blender."""
        self._connected = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        # Cancel any pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(BlenderConnectionError("Disconnected"))
        self._pending_requests.clear()

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
        future: asyncio.Future = asyncio.get_event_loop().create_future()
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
        buffer = b""

        while self._connected and self._reader:
            try:
                # Read data
                data = await self._reader.read(65536)
                if not data:
                    # Connection closed
                    logger.warning("Connection closed by Blender")
                    await self.disconnect()
                    break

                buffer += data

                # Process complete messages
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        await self._handle_response(line)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Read error: {e}")
                await self.disconnect()
                break

    async def _handle_response(self, data: bytes) -> None:
        """Handle a JSON-RPC response from Blender."""
        try:
            response = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response: {e}")
            return

        request_id = response.get("id")
        if request_id is None:
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

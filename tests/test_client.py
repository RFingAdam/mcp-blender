"""Tests for Blender client."""

import asyncio
import json

import pytest

from mcp_blender.blender_client import (
    BlenderClient,
    BlenderCommandError,
    BlenderConnectionError,
)


class MockBlenderServer:
    """Mock Blender server for testing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._server = None
        self._responses: dict[str, dict] = {}

    async def start(self):
        """Start the mock server."""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )
        # Get the actual port if 0 was specified
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        """Stop the mock server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def set_response(self, method: str, result: dict):
        """Set a mock response for a method."""
        self._responses[method] = result

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a client connection."""
        buffer = b""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break

                buffer += data

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        request = json.loads(line.decode("utf-8"))
                        response = self._process_request(request)
                        writer.write((json.dumps(response) + "\n").encode("utf-8"))
                        await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _process_request(self, request: dict) -> dict:
        """Process a request and return response."""
        method = request.get("method")
        request_id = request.get("id")

        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "result": {"pong": True, "blender_version": "4.2.0 (mock)"},
                "id": request_id,
            }

        if method in self._responses:
            return {
                "jsonrpc": "2.0",
                "result": self._responses[method],
                "id": request_id,
            }

        return {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": request_id,
        }

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


@pytest.fixture
async def mock_server():
    """Provide a mock Blender server."""
    async with MockBlenderServer() as server:
        yield server


class TestBlenderClient:
    """Tests for BlenderClient."""

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_server):
        """Client should connect successfully."""
        client = BlenderClient(mock_server.host, mock_server.port)
        await client.connect()
        assert client.connected
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_refused(self):
        """Client should raise error when connection refused."""
        client = BlenderClient("127.0.0.1", 59999)  # Non-existent port
        with pytest.raises(BlenderConnectionError):
            await client.connect(timeout=1.0)

    @pytest.mark.asyncio
    async def test_ping(self, mock_server):
        """Client should ping successfully."""
        async with BlenderClient(mock_server.host, mock_server.port) as client:
            result = await client.ping()
            assert result is True

    @pytest.mark.asyncio
    async def test_send_command(self, mock_server):
        """Client should send commands and receive responses."""
        mock_server.set_response(
            "scene_info",
            {
                "name": "Scene",
                "frame_start": 1,
                "frame_end": 250,
            },
        )

        async with BlenderClient(mock_server.host, mock_server.port) as client:
            result = await client.send_command("scene_info")
            assert result["name"] == "Scene"
            assert result["frame_start"] == 1

    @pytest.mark.asyncio
    async def test_send_command_with_params(self, mock_server):
        """Client should send commands with parameters."""
        mock_server.set_response(
            "object_create",
            {
                "name": "Cube",
                "type": "MESH",
            },
        )

        async with BlenderClient(mock_server.host, mock_server.port) as client:
            result = await client.send_command("object_create", {"type": "cube"})
            assert result["name"] == "Cube"

    @pytest.mark.asyncio
    async def test_command_error(self, mock_server):
        """Client should handle command errors."""
        async with BlenderClient(mock_server.host, mock_server.port) as client:
            with pytest.raises(BlenderCommandError):
                await client.send_command("nonexistent_method")

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_server):
        """Client should disconnect cleanly."""
        client = BlenderClient(mock_server.host, mock_server.port)
        await client.connect()
        assert client.connected
        await client.disconnect()
        assert not client.connected

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_server):
        """Client should work as async context manager."""
        async with BlenderClient(mock_server.host, mock_server.port) as client:
            assert client.connected
        # Should be disconnected after context exits

    @pytest.mark.asyncio
    async def test_reconnect_on_command(self, mock_server):
        """Client should auto-connect when sending command if not connected."""
        client = BlenderClient(mock_server.host, mock_server.port)
        assert not client.connected

        mock_server.set_response("scene_info", {"name": "Scene"})
        result = await client.send_command("scene_info")
        assert result["name"] == "Scene"
        assert client.connected

        await client.disconnect()


class RawServer:
    """A server that writes exactly the bytes a test gives it after the first request."""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.port = 0
        self._server = None

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            await reader.readline()
            writer.write(self.payload)
            await writer.drain()
            await asyncio.sleep(0.3)
        except ConnectionError:
            pass
        finally:
            writer.close()


@pytest.mark.asyncio
async def test_client_reads_32mib_reply():
    """A reply far past asyncio's 64 KiB stream limit still arrives whole."""
    size = 32 * 1024 * 1024
    big = "x" * size

    class Echo(MockBlenderServer):
        def _process_request(self, request):
            return {"jsonrpc": "2.0", "result": big, "id": request["id"]}

    async with Echo() as server:
        async with BlenderClient(server.host, server.port) as client:
            result = await client.send_command("big", timeout=60.0)
    assert len(result) == size


@pytest.mark.asyncio
async def test_id_null_error_fails_pending_with_its_message():
    """The add-on answers a bad line with id null, then closes; say why, not 'Disconnected'."""
    error = {
        "jsonrpc": "2.0",
        "error": {"code": -32700, "message": "Parse error: nope"},
        "id": None,
    }
    async with RawServer(json.dumps(error).encode() + b"\n") as server:
        client = BlenderClient("127.0.0.1", server.port)
        with pytest.raises(BlenderCommandError, match="Parse error: nope"):
            await client.send_command("ping", timeout=5.0)
        await client.disconnect()


@pytest.mark.asyncio
async def test_reply_line_over_the_cap_is_refused():
    from mcp_blender import blender_client

    old = blender_client.MAX_REPLY_LINE
    blender_client.MAX_REPLY_LINE = 100_000
    try:
        async with RawServer(b"x" * 300_000) as server:
            client = BlenderClient("127.0.0.1", server.port)
            with pytest.raises(BlenderConnectionError, match="too large"):
                await client.send_command("ping", timeout=5.0)
            await client.disconnect()
    finally:
        blender_client.MAX_REPLY_LINE = old


@pytest.mark.asyncio
async def test_reconnect_during_disconnect_is_not_wiped_out(mock_server):
    """A connect() that lands while disconnect() awaits wait_closed() keeps its writer."""
    client = BlenderClient(mock_server.host, mock_server.port)
    await client.connect()
    real = client._writer

    class Slow:
        def close(self):
            real.close()

        async def wait_closed(self):
            await client.connect()  # the reconnect happens inside the await
            await real.wait_closed()

    client._writer = Slow()
    await client.disconnect()
    assert client.connected
    assert await client.ping() is True
    await client.disconnect()

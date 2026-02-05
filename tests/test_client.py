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
        mock_server.set_response("scene_info", {
            "name": "Scene",
            "frame_start": 1,
            "frame_end": 250,
        })

        async with BlenderClient(mock_server.host, mock_server.port) as client:
            result = await client.send_command("scene_info")
            assert result["name"] == "Scene"
            assert result["frame_start"] == 1

    @pytest.mark.asyncio
    async def test_send_command_with_params(self, mock_server):
        """Client should send commands with parameters."""
        mock_server.set_response("object_create", {
            "name": "Cube",
            "type": "MESH",
        })

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

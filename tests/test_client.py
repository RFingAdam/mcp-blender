"""Tests for Blender client."""

import asyncio
import json

import pytest

from mcp_blender import wire
from mcp_blender.blender_client import (
    BlenderClient,
    BlenderCommandError,
    BlenderConnectionError,
)

# What a v0.4.0 add-on really sends for a method it does not know: its dispatcher
# raises ValueError("Unknown method: hello") and the socket server wraps it as -32603.
V040_UNKNOWN_METHOD = {"code": -32603, "message": "Unknown method: hello"}


@pytest.fixture(autouse=True)
def token(monkeypatch, tmp_path):
    """Each test gets its own config dir with a token in it, and no ambient override."""
    monkeypatch.delenv("MESHWIRE_TOKEN", raising=False)
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "meshwire"))
    return wire.ensure_token()


def hello_ok(msg_id) -> dict:
    return {
        "jsonrpc": "2.0",
        "result": {"protocol": wire.PROTOCOL, "addon": "0.5.0", "port": 1},
        "id": msg_id,
    }


class MockBlenderServer:
    """Mock Blender server for testing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._server = None
        self._responses: dict[str, dict] = {}
        self.hello_error: dict | None = None  # answer every hello with this error
        self.hello_gate: asyncio.Event | None = None  # hold the hello reply until set
        self.hello_seen = asyncio.Event()
        self.hellos: list[dict] = []

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
                        if request.get("method") == "hello":
                            self.hellos.append(request)
                            self.hello_seen.set()
                            if self.hello_gate is not None:
                                await self.hello_gate.wait()
                            response = self._hello_reply(request)
                            writer.write((json.dumps(response) + "\n").encode("utf-8"))
                            await writer.drain()
                            if "error" in response:
                                return
                            continue
                        response = self._process_request(request)
                        writer.write((json.dumps(response) + "\n").encode("utf-8"))
                        await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _hello_reply(self, request: dict) -> dict:
        if self.hello_error is not None:
            return {"jsonrpc": "2.0", "error": self.hello_error, "id": request["id"]}
        if request["params"].get("token") != wire.read_token():
            error = {"code": wire.E_UNAUTHORIZED, "message": "Unauthorized"}
            return {"jsonrpc": "2.0", "error": error, "id": request["id"]}
        return hello_ok(request["id"])

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
            hello = json.loads(await reader.readline())
            writer.write((json.dumps(hello_ok(hello["id"])) + "\n").encode())
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


@pytest.mark.asyncio
async def test_concurrent_send_command_opens_one_connection(mock_server):
    accepted = []
    original = mock_server._handle_client

    async def counting(reader, writer):
        accepted.append(1)
        await original(reader, writer)

    mock_server._server.close()
    await mock_server._server.wait_closed()
    mock_server._server = await asyncio.start_server(counting, mock_server.host, 0)
    mock_server.port = mock_server._server.sockets[0].getsockname()[1]

    client = BlenderClient(mock_server.host, mock_server.port)
    try:
        first, second = await asyncio.gather(
            client.send_command("ping", timeout=5.0),
            client.send_command("ping", timeout=5.0),
        )
    finally:
        await client.disconnect()
    assert first["pong"] and second["pong"]
    assert len(accepted) == 1


# --- token and hello --------------------------------------------------------------


@pytest.mark.asyncio
async def test_hello_carries_the_token_and_protocol(mock_server, token):
    async with BlenderClient(mock_server.host, mock_server.port):
        pass
    (hello,) = mock_server.hellos
    assert hello["params"]["token"] == token
    assert hello["params"]["protocol"] == wire.PROTOCOL
    assert hello["params"]["client"].startswith("meshwire ")


@pytest.mark.asyncio
async def test_old_addon_reported_by_hello(mock_server):
    mock_server.hello_error = V040_UNKNOWN_METHOD
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    assert str(info.value) == (
        "The Meshwire add-on in Blender is older than this server. Update the add-on."
    )
    assert not client.connected


@pytest.mark.asyncio
async def test_wrong_token_error_names_the_token_path(mock_server, tmp_path):
    wire.token_path().write_text("a-different-token\n")
    # The mock accepts only the file's token, so make the client read another one.
    mock_server.hello_error = {"code": wire.E_UNAUTHORIZED, "message": "Unauthorized"}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert str(wire.token_path()) in message
    assert "Meshwire tab" in message
    assert "restart the MCP client" in message
    assert "a-different-token" not in message
    assert "Disconnected" not in message
    assert not client.connected


@pytest.mark.asyncio
async def test_wrong_env_token_error_says_the_variable_overrides(mock_server, monkeypatch):
    monkeypatch.setenv("MESHWIRE_TOKEN", "secret-from-env")
    mock_server.hello_error = {"code": wire.E_UNAUTHORIZED, "message": "Unauthorized"}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert "MESHWIRE_TOKEN" in message and "overrides" in message
    assert "Restart the MCP client" in message
    assert str(wire.token_path()) in message
    assert "secret-from-env" not in message


@pytest.mark.asyncio
async def test_no_token_names_the_path_and_the_meshwire_tab(mock_server):
    wire.token_path().unlink()
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert str(wire.token_path()) in message
    assert "Meshwire tab" in message and "first" in message
    assert mock_server.hellos == []  # nothing was sent


@pytest.mark.asyncio
async def test_token_is_read_again_on_every_connect(mock_server):
    client = BlenderClient(mock_server.host, mock_server.port)
    await client.connect()
    await client.disconnect()
    wire.token_path().write_text("rotated-token\n")
    await client.connect()  # the mock compares with the file, so this passes only if re-read
    await client.disconnect()
    assert [h["params"]["token"] for h in mock_server.hellos][-1] == "rotated-token"


@pytest.mark.asyncio
async def test_silent_server_does_not_hang_the_handshake(mock_server):
    mock_server.hello_gate = asyncio.Event()  # never set
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError, match="timed out"):
        await client.connect(timeout=0.3)
    assert not client.connected
    assert client._writer is None
    mock_server.hello_gate.set()


@pytest.mark.asyncio
async def test_server_that_hangs_up_during_hello_is_reported(mock_server):
    async def hang_up(reader, writer):
        writer.close()

    mock_server._server.close()
    await mock_server._server.wait_closed()
    mock_server._server = await asyncio.start_server(hang_up, mock_server.host, 0)
    port = mock_server._server.sockets[0].getsockname()[1]
    client = BlenderClient(mock_server.host, port)
    with pytest.raises(BlenderConnectionError, match="handshake"):
        await client.connect(timeout=5.0)
    assert not client.connected


@pytest.mark.asyncio
async def test_not_connected_until_the_hello_reply_arrives(mock_server):
    mock_server.hello_gate = asyncio.Event()
    client = BlenderClient(mock_server.host, mock_server.port)
    task = asyncio.create_task(client.connect(timeout=5.0))
    await asyncio.wait_for(mock_server.hello_seen.wait(), 5)
    assert not client.connected and client._read_task is None
    mock_server.hello_gate.set()
    await task
    assert client.connected
    await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_during_hello_leaves_the_client_disconnected(mock_server):
    mock_server.hello_gate = asyncio.Event()
    client = BlenderClient(mock_server.host, mock_server.port)
    task = asyncio.create_task(client.connect(timeout=5.0))
    await asyncio.wait_for(mock_server.hello_seen.wait(), 5)
    await client.disconnect()
    mock_server.hello_gate.set()
    with pytest.raises(BlenderConnectionError):
        await task
    assert not client.connected
    assert client._writer is None and client._read_task is None


@pytest.mark.asyncio
async def test_disconnect_after_the_reply_is_read_voids_the_open(mock_server):
    """The reply is already buffered when disconnect() runs; the open must still lose."""
    client = BlenderClient(mock_server.host, mock_server.port)
    original = client._hello

    async def hello_then_disconnect(*args):
        await original(*args)
        await client.disconnect()  # lands after the good reply, before _connected is set

    client._hello = hello_then_disconnect
    with pytest.raises(BlenderConnectionError):
        await client.connect(timeout=5.0)
    assert not client.connected
    assert client._read_task is None

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


def hello_reply(request: dict, bad_proof=False, **overrides) -> tuple[dict, str]:
    """What a real add-on answers to a hello. Returns (reply, server nonce)."""
    ns = wire.new_nonce()
    pa = wire.proof(wire.read_token(), wire.ADDON_LABEL, request["params"]["nonce"], ns)
    if bad_proof:
        pa = "0" * 64
    result = {"protocol": wire.PROTOCOL, "addon": "0.5.0", "port": 1, "nonce": ns, "proof": pa}
    result.update(overrides)
    return {"jsonrpc": "2.0", "result": result, "id": request["id"]}, ns


class MockBlenderServer:
    """Mock Blender server for testing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._server = None
        self._responses: dict[str, dict] = {}
        self.hello_error: dict | None = None  # answer every hello with this error
        self.proof_error: dict | None = None  # answer every hello_proof with this error
        self.bad_proof = False  # an impostor: prove with the wrong key
        self.hello_overrides: dict = {}  # fields to change in the hello result
        self.hello_gate: asyncio.Event | None = None  # hold the hello reply until set
        self.hello_seen = asyncio.Event()
        self.received = bytearray()  # every byte any client wrote
        self.hellos: list[dict] = []
        self.proofs: list[dict] = []
        self.commands: list[dict] = []

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
        nonce_c = nonce_s = ""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                self.received += data
                buffer += data

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    request = json.loads(line.decode("utf-8"))
                    method = request.get("method")
                    if method == "hello":
                        self.hellos.append(request)
                        self.hello_seen.set()
                        if self.hello_gate is not None:
                            await self.hello_gate.wait()
                        if self.hello_error is not None:
                            response = {"jsonrpc": "2.0", "error": self.hello_error}
                            response["id"] = request["id"]
                        else:
                            response, nonce_s = hello_reply(
                                request, self.bad_proof, **self.hello_overrides
                            )
                            nonce_c = request["params"]["nonce"]
                    elif method == "hello_proof":
                        self.proofs.append(request)
                        good = wire.proof(wire.read_token(), wire.CLIENT_LABEL, nonce_s, nonce_c)
                        if self.proof_error is not None:
                            error = self.proof_error
                        elif request["params"]["proof"] != good:
                            error = {"code": wire.E_UNAUTHORIZED, "message": "Unauthorized"}
                        else:
                            error = None
                        response = {"jsonrpc": "2.0", "id": request["id"]}
                        response.update({"error": error} if error else {"result": {"ok": True}})
                    else:
                        self.commands.append(request)
                        response = self._process_request(request)
                    writer.write((json.dumps(response) + "\n").encode("utf-8"))
                    await writer.drain()
                    if "error" in response and method in ("hello", "hello_proof"):
                        return
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
            hello = json.loads(await reader.readline())
            reply, ns = hello_reply(hello)
            writer.write((json.dumps(reply) + "\n").encode())
            await reader.readline()  # hello_proof
            writer.write(
                (json.dumps({"jsonrpc": "2.0", "result": {"ok": True}, "id": 2}) + "\n").encode()
            )
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


# --- token and handshake ----------------------------------------------------------


@pytest.mark.asyncio
async def test_handshake_sends_a_nonce_and_a_proof_never_the_token(mock_server, token):
    async with BlenderClient(mock_server.host, mock_server.port):
        pass
    (hello,) = mock_server.hellos
    assert "token" not in hello["params"]
    assert hello["params"]["protocol"] == wire.PROTOCOL
    assert hello["params"]["client"].startswith("meshwire ")
    assert len(hello["params"]["nonce"]) >= 16
    (proof,) = mock_server.proofs
    assert set(proof["params"]) == {"proof"} and len(proof["params"]["proof"]) == 64


@pytest.mark.asyncio
async def test_token_never_sent(mock_server, token, monkeypatch):
    async with BlenderClient(mock_server.host, mock_server.port) as client:
        await client.send_command("ping")
    assert token.encode() not in bytes(mock_server.received)
    monkeypatch.setenv("MESHWIRE_TOKEN", "env-secret-value-0123456789abcdef-xyz")
    async with BlenderClient(mock_server.host, mock_server.port) as client:
        await client.send_command("ping")
    assert b"env-secret-value" not in bytes(mock_server.received)


@pytest.mark.asyncio
async def test_impostor_gets_no_command(mock_server, token):
    mock_server.bad_proof = True
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.send_command("object_create", {"type": "cube"})
    message = str(info.value)
    assert str(wire.token_path()) in message
    assert "Meshwire tab" in message and "Copy token" in message
    assert "MESHWIRE_TOKEN" in message and "restart" in message.lower()
    assert f"port {mock_server.port}" in message
    assert token not in message
    assert mock_server.proofs == [] and mock_server.commands == []
    assert not client.connected and client._writer is None
    assert token.encode() not in bytes(mock_server.received)


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
async def test_wrong_token_error_names_the_token_path(mock_server):
    mock_server.proof_error = {"code": wire.E_UNAUTHORIZED, "message": "Unauthorized"}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert str(wire.token_path()) in message
    assert "Meshwire tab" in message
    assert "restart the MCP client" in message
    assert "Disconnected" not in message
    assert not client.connected


@pytest.mark.asyncio
async def test_wrong_env_token_error_says_the_variable_overrides(mock_server, monkeypatch):
    monkeypatch.setenv("MESHWIRE_TOKEN", "secret-from-env-0123456789abcdef-012345")
    mock_server.proof_error = {"code": wire.E_UNAUTHORIZED, "message": "Unauthorized"}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert "MESHWIRE_TOKEN" in message and "overrides" in message
    assert "restart the MCP client" in message
    assert str(wire.token_path()) in message
    assert "secret-from-env" not in message


@pytest.mark.asyncio
async def test_too_many_clients_message_is_passed_on(mock_server):
    mock_server.proof_error = {"code": wire.E_TOO_MANY, "message": "Too many clients: at most 8"}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError, match="Too many clients"):
        await client.connect(timeout=5.0)


@pytest.mark.asyncio
async def test_no_token_names_the_path_and_the_fixes(mock_server):
    wire.token_path().unlink()
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert message == (
        f"No Meshwire token at {wire.token_path()}. Start the server in Blender's Meshwire tab, "
        "which writes it there. If Blender keeps its token elsewhere (MESHWIRE_TOKEN set only "
        "in Blender, or a sandboxed Blender such as Flatpak), use Copy token in the Meshwire "
        "tab and set MESHWIRE_TOKEN for the MCP client."
    )
    assert mock_server.hellos == []


@pytest.mark.asyncio
async def test_token_is_read_again_on_every_connect(mock_server):
    client = BlenderClient(mock_server.host, mock_server.port)
    await client.connect()
    await client.disconnect()
    wire.token_path().write_text("rotated-token-0123456789abcdef-0123456789\n")
    await client.connect()  # the mock compares with the file, so this passes only if re-read
    await client.disconnect()
    assert len(mock_server.proofs) == 2


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


@pytest.mark.parametrize(
    "override",
    [
        {"proof": None},
        {"proof": 12},
        {"nonce": None},
        {"nonce": "short"},
        {"nonce": "x" * 200},
        {"nonce": "has space in it!!"},
        {"proof": "\ud800" * 64},
    ],
)
@pytest.mark.asyncio
async def test_malformed_addon_proof_fields_are_an_impostor(mock_server, override):
    mock_server.hello_overrides = override
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError):
        await client.connect(timeout=5.0)
    assert mock_server.proofs == [] and mock_server.commands == []


@pytest.mark.asyncio
async def test_addon_with_a_higher_protocol_says_update_the_server(mock_server):
    mock_server.hello_overrides = {"protocol": 2}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    message = str(info.value)
    assert "2" in message and message.endswith("Update the Meshwire server.")
    assert mock_server.proofs == []


@pytest.mark.asyncio
async def test_addon_with_a_lower_protocol_says_update_the_addon(mock_server):
    mock_server.hello_overrides = {"protocol": 0}
    client = BlenderClient(mock_server.host, mock_server.port)
    with pytest.raises(BlenderConnectionError) as info:
        await client.connect(timeout=5.0)
    assert str(info.value).endswith("Update the Meshwire add-on in Blender.")


@pytest.mark.asyncio
async def test_not_connected_until_the_handshake_finishes(mock_server):
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
async def test_disconnect_after_the_handshake_is_read_voids_the_open(mock_server):
    """The replies are already read when disconnect() runs; the open must still lose."""
    client = BlenderClient(mock_server.host, mock_server.port)
    original = client._hello
    seen = []

    async def hello_then_disconnect(*args):
        seen.append(args[1])
        await original(*args)
        await client.disconnect()  # lands after the good replies, before _connected is set

    client._hello = hello_then_disconnect
    with pytest.raises(BlenderConnectionError):
        await client.connect(timeout=5.0)
    assert not client.connected
    assert client._read_task is None and client._writer is None
    assert seen[0].is_closing()  # the socket this open made was closed, not leaked


@pytest.mark.asyncio
async def test_disconnect_during_open_connection_leaves_no_open_socket(mock_server, monkeypatch):
    from mcp_blender import blender_client

    started, release = asyncio.Event(), asyncio.Event()
    opened = []
    real = asyncio.open_connection

    async def slow_open(*args, **kwargs):
        started.set()
        await release.wait()
        pair = await real(*args, **kwargs)
        opened.append(pair[1])
        return pair

    monkeypatch.setattr(blender_client.asyncio, "open_connection", slow_open)
    client = BlenderClient(mock_server.host, mock_server.port)
    task = asyncio.create_task(client.connect(timeout=5.0))
    await asyncio.wait_for(started.wait(), 5)
    await client.disconnect()  # lands while open_connection is in flight
    release.set()
    with pytest.raises(BlenderConnectionError):
        await task
    assert not client.connected
    assert client._writer is None and client._reader is None
    (writer,) = opened
    assert writer.is_closing()

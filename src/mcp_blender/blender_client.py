"""Async TCP client for communicating with the Meshwire addon."""

import asyncio
import hmac
import json
import logging
import os
import socket
import uuid
from typing import Any

from . import __version__, wire

logger = logging.getLogger("meshwire.client")

# The add-on holds at most 256 MiB of reply per client, so no honest reply line is longer.
MAX_REPLY_LINE = 256 * 1024 * 1024 + 1024 * 1024
READ_SIZE = 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class BlenderConnectionError(Exception):
    """Raised when connection to Blender fails."""

    pass


class _NotMeshwire(BlenderConnectionError):
    """The peer showed it is not a Meshwire add-on holding our token.

    The only failure discovery moves past: refused, closed before any reply byte, a reply
    that is not a JSON object, or a missing or wrong add-on proof. Anything else may be
    the right Blender, slow or full, and stops the search.
    """


class _Unproven(BlenderConnectionError):
    """A stop caused by a peer that has not proved it is a Meshwire add-on.

    It may be a Blender that is busy, full or outdated, or a program squatting on a stale
    port. The message calls it "the program", and names the instance file and its process
    ID so that a stale file can be told from a busy Blender.
    """


class _NoAnswer(_Unproven):
    """A connect or handshake step ran out of time."""

    def __init__(self, message: str, seconds: float):
        super().__init__(message)
        self.seconds = seconds


class _ClosedEarly(_Unproven):
    """Accepted, then closed or reset before any reply byte: an eviction or a full server."""


class BlenderCommandError(Exception):
    """Raised when a Blender command fails."""

    pass


class BlenderClient:
    """
    Async TCP client for communicating with the Meshwire addon.

    Uses JSON-RPC 2.0 protocol over TCP with newline-delimited messages.
    """

    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        """``port=None`` finds the Blender to use on every connect (see ``_open``)."""
        self.host = host
        self._fixed_port = port
        self.port = port if port is not None else wire.PORT_FIRST  # the port in use now
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

    async def _discover(self) -> list[dict]:
        """Live instances to try, newest first. Empty when the port is fixed or the host remote.

        Blender can start, restart or move after this server did, so this runs at every
        open. Discovery makes blocking probes, so it runs off the event loop.
        """
        if self._fixed_port is not None or self.host.lower() not in LOOPBACK_HOSTS:
            return []
        return await asyncio.to_thread(wire.live_instances)

    @staticmethod
    def _log_pick(pick: dict, total: int) -> None:
        more = f", the most recently started of {total}" if total > 1 else ""
        logger.info(
            "Using the Blender on port %s (Blender %r, file %r)%s",
            pick["port"],
            pick["blender"],
            pick["blend"] or "unsaved",
            more,
        )

    async def _open(self, timeout: float) -> None:
        """Connect, run the handshake and only then become connected.

        The token is read afresh on every connect, so a token that changed since the
        last connection is noticed here. The reader and writer stay local until the
        handshake is done and no disconnect() has intervened; they are installed
        together, with no await after the last check, so a disconnect can never leave
        _connected True over a closed writer, or an open socket nobody owns.

        With no fixed port, each live instance is tried in turn, newest first, with the
        full handshake, until one accepts. A port that is live but not Meshwire (a crashed
        Blender's port taken by another program) so cannot shadow a healthy older Blender.
        """
        try:
            token = wire.read_token()
        except OSError as e:
            raise BlenderConnectionError(str(e)) from None
        if not token:
            raise BlenderConnectionError(
                f"No Meshwire token at {wire.token_path()}. Start the server in Blender's "
                "Meshwire tab, which writes it there. If Blender keeps its token elsewhere "
                "(MESHWIRE_TOKEN set only in Blender, or a sandboxed Blender such as "
                "Flatpak), use Copy token in the Meshwire tab and set MESHWIRE_TOKEN for "
                "the MCP client."
            )
        epoch = self._epoch
        if self._fixed_port is not None:
            self.port = self._fixed_port
            await self._connect_to(token, timeout, epoch)
            return
        found = await self._discover()
        if epoch != self._epoch:
            raise BlenderConnectionError("Disconnected")
        if not found:
            self.port = wire.PORT_FIRST
            await self._connect_to(token, timeout, epoch)
            return
        failures = []
        for position, instance in enumerate(found):
            self.port = instance["port"]
            if position == 0:
                self._log_pick(instance, len(found))
            else:
                logger.info("Trying the next Blender, on port %s", instance["port"])
            try:
                await self._connect_to(token, timeout, epoch)
                return
            except _NotMeshwire as e:
                if epoch != self._epoch:
                    raise
                reason = str(e).splitlines()[0] if str(e) else type(e).__name__
                failures.append((instance, reason))
            except BlenderConnectionError as e:
                if epoch != self._epoch:
                    raise
                raise self._stopped_at(instance, position, e, timeout) from None
        lines = [
            f"  port {i['port']} ({self._instance_file(i)}): {reason}" for i, reason in failures
        ]
        raise BlenderConnectionError(
            "Could not connect to any of the Meshwire instances found:\n"
            + "\n".join(lines)
            + "\nA file here may be stale, or another program may hold that port. "
            "Pass --port or set MESHWIRE_PORT to pick the Blender to use."
        )

    @staticmethod
    def _instance_file(instance: dict) -> Any:
        return wire.instances_dir() / f"{instance['port']}.json"

    def _stopped_at(
        self, instance: dict, position: int, error: BlenderConnectionError, timeout: float
    ) -> BlenderConnectionError:
        """The one error for an instance that may be a real Meshwire: no switching to another."""
        port, file = instance["port"], self._instance_file(instance)
        way_out = "pass --port or set MESHWIRE_PORT to pick one"
        if not isinstance(error, _Unproven):
            # The add-on proved itself, so this is a genuine Blender's own answer.
            return BlenderConnectionError(
                f"{error}\nThis came from the Blender on port {port} (instance file {file}). "
                f"Not trying another Blender, because this one is the right one. You can {way_out}."
            )
        stale = (
            f"If no Blender with process ID {instance['pid']} is running, that file is stale: "
            "delete it."
        )
        where = f"The program on port {port} (instance file {file})"
        if isinstance(error, _NoAnswer):
            return BlenderConnectionError(
                f"{where} did not answer within {error.seconds:g} s; if it is a Blender, it may "
                f"be busy. Try again, or {way_out}. {stale}"
            )
        if isinstance(error, _ClosedEarly):
            return BlenderConnectionError(
                f"{where} closed the connection before answering. A busy or full Meshwire "
                f"add-on does this. Try again, or {way_out}. {stale}"
            )
        return BlenderConnectionError(
            f"{error}\nThis came from {where[0].lower() + where[1:]}. Not trying another "
            f"Blender, because this one may be the right one. You can {way_out}. {stale}"
        )

    async def _connect_to(self, token: str, timeout: float, epoch: int) -> None:
        """One connection attempt at ``self.port``: connect, handshake, install."""

        def voided() -> None:
            """Stop at once if a disconnect() ran while this open was waiting."""
            if epoch != self._epoch:
                raise BlenderConnectionError("Disconnected")

        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout,
            )
            voided()
            await self._hello(reader, writer, token, timeout, voided)
            voided()
            self._reader, self._writer = reader, writer
            self._connected = True
            logger.info(f"Connected to Blender at {self.host}:{self.port}")
            self._read_task = asyncio.create_task(self._read_loop())
        except BaseException as exc:
            if writer is not None:
                writer.close()  # whatever failed, this socket is ours to close
            if isinstance(exc, asyncio.TimeoutError):
                raise _NoAnswer(
                    f"Connection to Blender timed out ({self.host}:{self.port})", timeout
                ) from None
            if isinstance(exc, ConnectionRefusedError):
                raise _NotMeshwire(
                    f"Connection refused. Is Blender running with MCP addon enabled? ({self.host}:{self.port})"
                ) from None
            if isinstance(exc, OSError):
                raise BlenderConnectionError(f"Connection failed: {exc}") from None
            raise

    def _token_help(self) -> str:
        text = (
            f"The token must match the one in Blender's Meshwire tab (Copy token); "
            f"this server reads {wire.token_path()}."
        )
        text += (
            " MESHWIRE_TOKEN, when set, overrides that file"
            + (" (it is set here)" if os.environ.get("MESHWIRE_TOKEN", "").strip() else "")
            + ". If the token or MESHWIRE_TOKEN changed, restart the MCP client."
        )
        return text

    async def _send(self, writer: asyncio.StreamWriter, message: dict, timeout: float) -> None:
        writer.write((json.dumps(message) + "\n").encode("utf-8"))
        await asyncio.wait_for(writer.drain(), timeout=timeout)

    async def _read_reply(
        self,
        reader: asyncio.StreamReader,
        timeout: float,
        peer: str,
        verified: bool = False,
    ) -> dict:
        """One reply line of the handshake, as a dict.

        Until the add-on has proved it holds the token (``verified``), nothing the peer
        wrote is shown to the user or the model: its errors become fixed text built from
        codes and numbers only.
        """
        # Before the add-on has proved itself, a bad reply shows it is not ours.
        unproven = BlenderConnectionError if verified else _NotMeshwire
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        except (ValueError, asyncio.LimitOverrunError):
            raise unproven(f"The program on {peer} did not complete the Meshwire handshake.")
        except (ConnectionError, asyncio.IncompleteReadError):
            line = b""
        if not line.strip():
            closed = BlenderConnectionError if verified else _ClosedEarly
            raise closed(
                "Blender closed the connection during the handshake. "
                f"Is this a Meshwire add-on? ({self.host}:{self.port})"
            )
        try:
            reply = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError):  # not JSON, or nested past the parser's limit
            reply = None
        if not isinstance(reply, dict):
            raise unproven(f"The program on {peer} did not complete the Meshwire handshake.")
        if reply.get("error") is not None:
            raise self._hello_error(reply["error"], peer, verified)
        return reply

    async def _hello(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        token: str,
        timeout: float,
        voided=lambda: None,
    ) -> None:
        """Mutual proof of the token, bound to the address reached. The token never goes out.

        hello carries a nonce. The add-on answers with its own nonce, the address its
        socket saw the bytes arrive at, and a proof over all three that it holds the
        token. Only if that checks out, and the address is the one dialed, does this side
        send its own proof. Anything else listening learns nothing and gets no command.
        """
        peername = writer.get_extra_info("peername") or (self.host, self.port)
        peer = wire.endpoint(str(peername[0]), int(peername[1]))
        nonce_c = wire.new_nonce()
        request = wire.hello_request(nonce_c, str(uuid.uuid4()), client=f"meshwire {__version__}")
        await self._send(writer, request, timeout)
        voided()
        reply = await self._read_reply(reader, timeout, peer)
        voided()
        result = reply.get("result")
        result = result if isinstance(result, dict) else {}

        theirs = result.get("protocol")
        if type(theirs) is not int:  # no protocol number: whatever answered is not our add-on
            raise _NotMeshwire(str(self._protocol_error(theirs)))
        if theirs != wire.PROTOCOL:
            raise self._protocol_error(theirs)
        nonce_s, seen, proof_a = result.get("nonce"), result.get("seen"), result.get("proof")
        well_formed = (
            isinstance(nonce_s, str)
            and 16 <= len(nonce_s) <= 128
            and all(c.isascii() and (c.isalnum() or c in "_-") for c in nonce_s)
            and isinstance(seen, str)
            and 0 < len(seen) <= 200
            and isinstance(proof_a, str)
            and len(proof_a) == 64
            and all(c in "0123456789abcdef" for c in proof_a)
        )
        expected = (
            wire.proof(token, wire.ADDON_LABEL, nonce_c, nonce_s, seen) if well_formed else ""
        )
        if not well_formed or not hmac.compare_digest(
            proof_a.encode("utf-8"), expected.encode("utf-8")
        ):
            # Not the add-on that made this token. Say nothing more to it.
            raise _NotMeshwire(
                f"The program answering on {self.host}:{self.port} did not prove it holds the "
                "Meshwire token, so nothing was sent to it. "
                f"{self._token_help()} Another program may be using port {self.port}."
            )
        # The proof is genuine, so `seen` is where the real add-on received the bytes.
        # It must be where this connection went, or something is relaying it.
        override = os.environ.get("MESHWIRE_ADDON_ADDRESS", "").strip()
        voided()
        if override:
            endpoints = await self._override_endpoints(override, timeout)
            voided()
            if seen not in endpoints:
                raise BlenderConnectionError(
                    f"MESHWIRE_ADDON_ADDRESS is set to {override}, but the add-on that answered "
                    f"is listening on {seen}. That variable is what this server compared "
                    f"against, not the address it connected to ({peer}). Set it to {seen} if "
                    "that is the tunnel or port forward you meant."
                )
        elif seen != peer:
            raise BlenderConnectionError(
                f"The Meshwire add-on that answered is listening on {seen}, but this server "
                f"connected to {peer}. Another program may be relaying the connection. "
                "If you use an SSH tunnel or port forward on purpose, set "
                f"MESHWIRE_ADDON_ADDRESS={seen} for the MCP client."
            )

        proof_c = wire.proof(token, wire.CLIENT_LABEL, nonce_s, nonce_c)
        await self._send(writer, wire.hello_proof_request(proof_c, str(uuid.uuid4())), timeout)
        voided()
        ok = (await self._read_reply(reader, timeout, peer, verified=True)).get("result")
        voided()
        if not (isinstance(ok, dict) and ok.get("ok") is True):
            raise BlenderConnectionError("The Meshwire add-on did not accept the handshake")

    @staticmethod
    async def _override_endpoints(value: str, timeout: float) -> set[str]:
        """Every ``host:port`` MESHWIRE_ADDON_ADDRESS can mean, normalised like ``seen``.

        A literal address is normalised (brackets, IPv4-mapped prefix). A hostname such as
        ``localhost:9876`` is resolved, within ``timeout``, and any of its addresses
        matches. A port outside 0 to 65535 matches nothing.
        """
        if value.startswith("["):
            host, _, rest = value[1:].partition("]")
            port_text = rest.lstrip(":")
        elif value.count(":") == 1:
            host, _, port_text = value.partition(":")
        else:  # a bare IPv6 literal with the port after the last colon
            host, _, port_text = value.rpartition(":")
        if not port_text.isdigit() or int(port_text) > 65535:
            return set()  # getaddrinfo would wrap 70000 to 4464
        port = int(port_text)
        found = {wire.endpoint(host, port)}
        try:
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
                timeout=timeout,
            )
        except (OSError, UnicodeError, asyncio.TimeoutError):
            # Unresolvable, unencodable (``a..b``) or too slow: only the literal form matches.
            return found
        found.update(wire.endpoint(str(info[4][0]), int(info[4][1])) for info in infos)
        return found

    @staticmethod
    def _protocol_error(addon_protocol: Any) -> BlenderConnectionError:
        """From the add-on's protocol number alone: which side is older?"""
        if type(addon_protocol) is int and addon_protocol > wire.PROTOCOL:
            side = "Update the Meshwire server."
        elif type(addon_protocol) is int and addon_protocol < wire.PROTOCOL:
            side = "Update the Meshwire add-on in Blender."
        else:
            side = "Update the Meshwire server and the add-on to the same release."
        if type(addon_protocol) is int:
            return _Unproven(
                f"The Meshwire add-on in Blender speaks protocol {addon_protocol}, this server "
                f"speaks {wire.PROTOCOL}. {side}"
            )
        return _Unproven(
            f"The Meshwire add-on in Blender and this server speak different protocols. {side}"
        )

    def _hello_error(self, error: Any, peer: str, verified: bool) -> BlenderConnectionError:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        message = message if isinstance(message, str) else ""
        if verified:
            # The add-on has proved it holds the token, so its own words can be shown.
            if code == wire.E_UNAUTHORIZED:
                return BlenderConnectionError(
                    "The Meshwire add-on in Blender rejected this server's proof. "
                    f"{self._token_help()}"
                )
            return BlenderConnectionError(message or f"Blender refused the handshake ({code})")
        # Before that, a peer's text could be anything. Use codes and numbers only.
        # A v0.4.0 add-on has no hello: its dispatcher raises ValueError("Unknown
        # method: hello") and the socket server wraps that as -32603.
        if code == -32603 and message.startswith("Unknown method"):
            return _Unproven(
                "The Meshwire add-on in Blender is older than this server. Update the add-on."
            )
        if code == wire.E_PROTOCOL:
            data = error.get("data") if isinstance(error, dict) else None
            number = data.get("protocol") if isinstance(data, dict) else None
            return self._protocol_error(number)
        return _NotMeshwire(f"The program on {peer} did not complete the Meshwire handshake.")

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

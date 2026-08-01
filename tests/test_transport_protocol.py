from __future__ import annotations

import pytest

from schideron import ConnectionClosedError, ProtocolError
from schideron.transport import SocketIOTransport, _gateway_url


class FakeWebSocket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.closed = False
        self.fail_send = fail_send
        self.sent: list[str] = []

    async def send_str(self, value: str) -> None:
        if self.fail_send:
            raise RuntimeError("closed")
        self.sent.append(value)


def test_gateway_url_normalization() -> None:
    assert _gateway_url("192.0.2.1", 3001, "socket.io") == (
        "ws://192.0.2.1:3001/socket.io/?transport=websocket&EIO=4"
    )
    assert _gateway_url("https://example.com:4000", 3001, "/custom/") == (
        "wss://example.com:4000/custom/?transport=websocket&EIO=4"
    )
    with pytest.raises(ValueError, match="host"):
        _gateway_url("", 3001, "socket.io")


def test_transport_constructor_validation() -> None:
    with pytest.raises(ValueError, match="connect_timeout"):
        SocketIOTransport("192.0.2.1", connect_timeout=0)


async def test_transport_packet_codec() -> None:
    connected = 0
    disconnected = 0
    statuses: list[object] = []

    async def on_connect() -> None:
        nonlocal connected
        connected += 1

    async def on_disconnect() -> None:
        nonlocal disconnected
        disconnected += 1

    async def on_status(payload: object) -> None:
        statuses.append(payload)

    transport = SocketIOTransport("192.0.2.1")
    transport.set_handlers(
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_status=on_status,
    )
    websocket = FakeWebSocket()
    transport._websocket = websocket  # type: ignore[assignment]

    await transport._handle_text(
        '0{"sid":"session","upgrades":[],"pingInterval":25000,"pingTimeout":20000}'
    )
    await transport._handle_text('40["connect",{}]')
    await transport._handle_text('40["connect",{}]')
    await transport._handle_text('42["updateStatus",[{"definition":"unknown"}]]')
    await transport._handle_text('42["otherEvent",{}]')
    await transport._handle_text("2")
    await transport._handle_text("3")
    await transport._handle_text("1")
    await transport._handle_text("unsupported")

    assert connected == 1
    assert statuses == [[{"definition": "unknown"}]]
    assert websocket.sent == ["3"]

    await transport._mark_disconnected()
    assert disconnected == 1
    assert not transport.connected


@pytest.mark.parametrize(
    "packet",
    [
        "not-json",
        "{}",
        '{"sid":"session"}',
        '{"sid":"session","pingInterval":5000,"pingTimeout":0}',
    ],
)
def test_transport_rejects_invalid_open_packets(packet: str) -> None:
    transport = SocketIOTransport("192.0.2.1")
    with pytest.raises(ProtocolError):
        transport._parse_open_packet(packet)


@pytest.mark.parametrize("packet", ["not-json", "{}", "[1,{}]"])
async def test_transport_rejects_invalid_event_packets(packet: str) -> None:
    transport = SocketIOTransport("192.0.2.1")
    with pytest.raises(ProtocolError):
        await transport._handle_event(packet)


async def test_transport_rejects_commands_without_connection() -> None:
    transport = SocketIOTransport("192.0.2.1")
    with pytest.raises(ConnectionClosedError):
        await transport.send_command({"definition": "test"})


async def test_transport_maps_send_failure_to_connection_error() -> None:
    transport = SocketIOTransport("192.0.2.1")
    transport._connected = True
    transport._websocket = FakeWebSocket(fail_send=True)  # type: ignore[assignment]
    with pytest.raises(ConnectionClosedError):
        await transport.send_command({"definition": "test"})


async def test_transport_requires_active_session_and_websocket() -> None:
    transport = SocketIOTransport("192.0.2.1", connect_timeout=0.001)
    with pytest.raises(ConnectionClosedError):
        await transport._connect_once()
    with pytest.raises(ConnectionClosedError):
        await transport._read_messages()
    with pytest.raises(ConnectionClosedError):
        await transport._wait_for_connection()

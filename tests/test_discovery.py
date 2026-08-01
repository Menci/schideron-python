import asyncio
import socket

import pytest

from schideron import ProtocolError, discover_gateways, parse_discovery_response
from schideron.constants import DISCOVERY_MESSAGE


def test_parse_discovery_response() -> None:
    gateway = parse_discovery_response(b"192.0.2.158:3001_schideron_test-gateway\x00\x00")
    assert gateway.host == "192.0.2.158"
    assert gateway.port == 3001
    assert gateway.uid == "schideron_test-gateway"


def test_parse_discovery_response_uses_default_port() -> None:
    gateway = parse_discovery_response(b"192.0.2.10_schideron_example")
    assert gateway.port == 3001


@pytest.mark.parametrize("payload", [b"", b"_schideron_invalid", b"\xff"])
def test_parse_discovery_response_rejects_invalid_payload(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_discovery_response(payload)


async def test_discover_gateways_over_udp() -> None:
    loop = asyncio.get_running_loop()
    responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    responder.setblocking(False)
    responder.bind(("127.0.0.1", 0))
    port = responder.getsockname()[1]

    async def reply() -> None:
        payload, address = await loop.sock_recvfrom(responder, 2048)
        assert payload == DISCOVERY_MESSAGE
        await loop.sock_sendto(
            responder,
            b"192.0.2.10:3001_schideron_test-gateway",
            address,
        )

    reply_task = asyncio.create_task(reply())
    try:
        gateways = await discover_gateways(
            timeout=0.1,
            broadcast_address="127.0.0.1",
            port=port,
        )
        await reply_task
    finally:
        responder.close()
    assert [(gateway.host, gateway.port, gateway.uid) for gateway in gateways] == [
        ("192.0.2.10", 3001, "schideron_test-gateway")
    ]

from __future__ import annotations

import asyncio
import socket
from urllib.parse import urlsplit

from .constants import DEFAULT_PORT, DISCOVERY_MESSAGE, DISCOVERY_PORT
from .exceptions import ProtocolError
from .models import GatewayInfo


def parse_discovery_response(payload: bytes) -> GatewayInfo:
    try:
        response = payload.decode("utf-8").rstrip("\x00").strip()
    except UnicodeDecodeError as error:
        raise ProtocolError("discovery response is not UTF-8") from error
    if not response:
        raise ProtocolError("discovery response is empty")

    endpoint = response.split("_", 1)[0]
    parsed = urlsplit(endpoint if "://" in endpoint else f"//{endpoint}")
    if not parsed.hostname:
        raise ProtocolError("discovery response has no gateway host")
    uid_index = response.find("schideron_")
    uid = response[uid_index:].split("\x00", 1)[0] if uid_index >= 0 else None
    return GatewayInfo(
        host=parsed.hostname,
        port=parsed.port or DEFAULT_PORT,
        uid=uid,
        raw_response=response,
    )


async def discover_gateways(
    *,
    timeout: float = 1.5,
    broadcast_address: str = "255.255.255.255",
    port: int = DISCOVERY_PORT,
) -> tuple[GatewayInfo, ...]:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 0))
    discovered: dict[tuple[str, int, str | None], GatewayInfo] = {}
    try:
        await loop.sock_sendto(sock, DISCOVERY_MESSAGE, (broadcast_address, port))
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            try:
                payload, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), remaining)
            except TimeoutError:
                break
            gateway = parse_discovery_response(payload)
            discovered[(gateway.host, gateway.port, gateway.uid)] = gateway
    finally:
        sock.close()
    return tuple(discovered.values())

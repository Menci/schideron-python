from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from aiohttp import web

from schideron import SchideronClient

GatewayFixture = tuple[
    str,
    asyncio.Queue[dict[str, object]],
    asyncio.Event,
]


@pytest.fixture
async def fake_gateway(unused_tcp_port: int) -> AsyncIterator[GatewayFixture]:
    app = web.Application()
    commands: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    heartbeat_received = asyncio.Event()

    async def socketio(request: web.Request) -> web.WebSocketResponse:
        assert request.query == {"transport": "websocket", "EIO": "4"}
        websocket = web.WebSocketResponse(max_msg_size=2**20)
        await websocket.prepare(request)
        await websocket.send_str(
            '0{"sid":"test-session","upgrades":[],"pingInterval":50,"pingTimeout":500}'
        )
        await websocket.send_str('40["connect",{}]')
        await websocket.send_str(
            "42"
            + json.dumps(
                [
                    "updateStatus",
                    [
                        {
                            "definition": "airconControl",
                            "device_id": "1",
                            "device_name": "1",
                            "state": "2",
                            "mode": "1",
                            "fanspeed": "4",
                            "set_temperature": "270",
                            "room_temperature": "280",
                            "PB": "1",
                            "interface": "USB3",
                        }
                    ],
                ],
                separators=(",", ":"),
            )
        )
        async for message in websocket:
            if message.type is web.WSMsgType.TEXT and message.data == "2":
                heartbeat_received.set()
                await websocket.send_str("3")
            elif message.type is web.WSMsgType.TEXT and message.data.startswith("42"):
                event, data = json.loads(message.data[2:])
                assert event == "sendCommand"
                await commands.put(data)
            elif message.type is web.WSMsgType.TEXT and message.data.startswith("["):
                event, uid, options = json.loads(message.data)
                assert event == "getPiStatus"
                assert uid == "schideron_test-gateway"
                assert options == {"language": "en"}
                await websocket.send_str(
                    '42["updateStatus",['
                    '{"definition":"lightControl","product_model":"SDR-RL-C08",'
                    '"brand":"Schideron","category":"Lighting","interface":"S-Net"},'
                    '{"device_id":"5","channel":"0","status":"1","type":1}'
                    "]]"
                )
        return websocket

    app.router.add_get("/socket.io/", socketio)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{unused_tcp_port}", commands, heartbeat_received
    finally:
        await runner.cleanup()


async def test_transport_handles_legacy_connect_heartbeat_and_large_commands(
    fake_gateway: GatewayFixture,
) -> None:
    url, commands, heartbeat_received = fake_gateway
    async with SchideronClient(url) as client:
        await client.wait_until_ready(timeout=2)
        await asyncio.wait_for(heartbeat_received.wait(), 2)
        await client.send_command({"definition": "test", "padding": "x" * 70_000})
        command = await asyncio.wait_for(commands.get(), 2)
        assert len(command["padding"]) == 70_000
        snapshot = await client.get_pi_status(
            "schideron_test-gateway",
            response_timeout=1,
            quiet_period=0.02,
        )
        assert len(snapshot) == 1
        assert next(iter(client.lighting.values())).is_on

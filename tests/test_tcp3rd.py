import asyncio

import pytest

from schideron import SchideronClient
from schideron.tcp3rd import (
    HANDSHAKE_REQUEST,
    HANDSHAKE_RESPONSE,
    TCP3rdFrame,
    TCP3rdFrameParser,
    TCP3rdStatusTransport,
)

from .test_client import FakeTransport


def frame(device_id: int, payload: bytes) -> bytes:
    return (
        b"\x55\xaa" + device_id.to_bytes(2, "big") + bytes([len(payload)]) + payload + b"\x0d\x0a"
    )


def test_tcp3rd_parser_handles_handshake_chunks_and_concatenation() -> None:
    parser = TCP3rdFrameParser()
    relay_5 = frame(5, b"\x92\x41\x00")
    relay_6 = frame(6, b"\x92\x80\x00")
    stream = b"garbage" + HANDSHAKE_RESPONSE + relay_5 + relay_6
    result = []
    for byte in stream:
        result.extend(parser.feed(bytes([byte])))
    assert result == [
        TCP3rdFrame(0, b"\x80\x02"),
        TCP3rdFrame(5, b"\x92\x41\x00"),
        TCP3rdFrame(6, b"\x92\x80\x00"),
    ]


def test_tcp3rd_parser_resynchronizes_after_invalid_terminator() -> None:
    parser = TCP3rdFrameParser()
    invalid = b"\x55\xaa\x00\x05\x03\x92\x01\x00\x00\x00"
    valid = frame(5, b"\x92\xff\x01")
    assert parser.feed(invalid + valid) == (TCP3rdFrame(5, b"\x92\xff\x01"),)


def test_tcp3rd_transport_rejects_invalid_host() -> None:
    async def nothing() -> None:
        return None

    async def frame_handler(_: TCP3rdFrame) -> None:
        return None

    with pytest.raises(ValueError, match="host"):
        TCP3rdStatusTransport(
            "",
            on_connect=nothing,
            on_disconnect=nothing,
            on_frame=frame_handler,
        )


async def test_tcp3rd_transport_handshake_and_status(unused_tcp_port: int) -> None:
    connected = asyncio.Event()
    disconnected = asyncio.Event()
    status_requested = asyncio.Event()
    received: asyncio.Queue[TCP3rdFrame] = asyncio.Queue()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(len(HANDSHAKE_REQUEST)) == HANDSHAKE_REQUEST
        writer.write(HANDSHAKE_RESPONSE + frame(5, b"\x92\x01\x00")[:4])
        await writer.drain()
        writer.write(frame(5, b"\x92\x01\x00")[4:] + frame(6, b"\x92\x80\x00"))
        await writer.drain()
        request = await reader.readexactly(14)
        assert request == bytes.fromhex("0a00000055aa0500035264000d0a")
        status_requested.set()
        await reader.read()
        writer.close()
        await writer.wait_closed()

    async def on_connect() -> None:
        connected.set()

    async def on_disconnect() -> None:
        disconnected.set()

    async def on_frame(value: TCP3rdFrame) -> None:
        await received.put(value)

    server = await asyncio.start_server(handler, "127.0.0.1", unused_tcp_port)
    transport = TCP3rdStatusTransport(
        "127.0.0.1",
        port=unused_tcp_port,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_frame=on_frame,
    )
    try:
        await transport.start()
        await transport.start()
        await asyncio.wait_for(connected.wait(), 1)
        assert transport.connected
        assert await asyncio.wait_for(received.get(), 1) == TCP3rdFrame(5, b"\x92\x01\x00")
        assert await asyncio.wait_for(received.get(), 1) == TCP3rdFrame(6, b"\x92\x80\x00")
        await transport.request_status(5)
        await asyncio.wait_for(status_requested.wait(), 1)
    finally:
        await transport.stop()
        server.close()
        await server.wait_closed()
    assert disconnected.is_set()


async def test_client_preserves_unverified_relay_bank_without_publishing_state() -> None:
    transport = FakeTransport()
    client = SchideronClient("unused", transport=transport, command_timeout=0.1)
    await client.connect()
    await client._on_relay_connect()
    await client._on_relay_frame(TCP3rdFrame(5, b"\x92\x00\x00"))

    assert client.relay_status_connected
    assert not client.lighting
    baseline = client.relay_banks[5]
    assert baseline.opcode == 0x92
    assert baseline.data == b"\x00\x00"
    await client._on_relay_frame(TCP3rdFrame(5, b"\x92\x01\x00"))
    changed = client.relay_banks[5]
    assert changed.data == b"\x01\x00"
    assert changed.generation > baseline.generation

    await client._on_relay_disconnect()
    assert not client.relay_status_connected


async def test_client_ignores_unknown_tcp3rd_payload() -> None:
    client = SchideronClient("unused", transport=FakeTransport())
    await client._on_relay_frame(TCP3rdFrame(1, b"\x52\x01\x02"))
    assert not client.lighting


async def test_client_decodes_tcp3rd_conditioner_status(
    conditioner_status_payload,
) -> None:
    transport = FakeTransport()
    client = SchideronClient("unused", transport=transport)
    await client.connect()
    await transport.publish([conditioner_status_payload])
    await client._on_relay_frame(TCP3rdFrame(1, bytes.fromhex("5200000000010104000f010f01")))
    status = next(iter(client.conditioners.values()))
    assert status.power.name == "OFF"
    assert status.mode.name == "COOL"
    assert status.fan_speed.name == "AUTO"
    assert status.target_temperature == 27
    assert status.current_temperature == 27.1
    assert status.raw["TCP3rd"] == "5200000000010104000f010f01"


async def test_client_decodes_tcp3rd_heating_status(heating_status_payload) -> None:
    transport = FakeTransport()
    client = SchideronClient("unused", transport=transport)
    await client.connect()
    await transport.publish([heating_status_payload])
    await client._on_relay_frame(TCP3rdFrame(17, bytes.fromhex("520000000002000000f000e700")))
    status = next(iter(client.heatings.values()))
    assert status.power.name == "ON"
    assert status.authoritative
    assert status.source.value == "tcp3rd"
    assert status.target_temperature == 24
    assert status.current_temperature == 23.1
    assert status.raw["TCP3rd"] == "520000000002000000f000e700"

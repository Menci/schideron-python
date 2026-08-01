from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

_LOGGER = logging.getLogger(__name__)

HANDSHAKE_REQUEST = bytes.fromhex("55aa00000280010d0a")
HANDSHAKE_RESPONSE = bytes.fromhex("55aa00000280020d0a")
HEADER = b"\x55\xaa"
TERMINATOR = b"\x0d\x0a"
MIN_HEADER_LENGTH = 5
HVAC_OPCODE = 0x52
HVAC_PAYLOAD_LENGTH = 13
RELAY_OPCODE = 0x92
RELAY_PAYLOAD_LENGTH = 3


@dataclass(frozen=True, slots=True)
class TCP3rdFrame:
    device_id: int
    payload: bytes


class TCP3rdFrameParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> tuple[TCP3rdFrame, ...]:
        self._buffer.extend(data)
        frames: list[TCP3rdFrame] = []
        while True:
            header_index = self._buffer.find(HEADER)
            if header_index < 0:
                self._buffer[:] = self._buffer[-1:] if self._buffer.endswith(b"\x55") else b""
                break
            if header_index:
                del self._buffer[:header_index]
            if len(self._buffer) < MIN_HEADER_LENGTH:
                break
            payload_length = self._buffer[4]
            frame_length = payload_length + 7
            if len(self._buffer) < frame_length:
                break
            if self._buffer[frame_length - 2 : frame_length] != TERMINATOR:
                del self._buffer[0]
                continue
            device_id = int.from_bytes(self._buffer[2:4], "big")
            payload = bytes(self._buffer[5 : 5 + payload_length])
            frames.append(TCP3rdFrame(device_id, payload))
            del self._buffer[:frame_length]
        return tuple(frames)


LifecycleHandler = Callable[[], Awaitable[None]]
FrameHandler = Callable[[TCP3rdFrame], Awaitable[None]]


class TCP3rdStatusTransport:
    def __init__(
        self,
        host: str,
        *,
        port: int = 7776,
        on_connect: LifecycleHandler,
        on_disconnect: LifecycleHandler,
        on_frame: FrameHandler,
    ) -> None:
        parsed = urlsplit(host if "://" in host else f"//{host}")
        if not parsed.hostname:
            raise ValueError("host must contain a hostname or IP address")
        self._host = parsed.hostname
        self._port = port
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_frame = on_frame
        self._supervisor: asyncio.Task[None] | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._writer_lock = asyncio.Lock()
        self._connected = False
        self._closing = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            return
        self._closing = False
        self._supervisor = asyncio.create_task(self._run(), name="schideron-tcp3rd")

    async def stop(self) -> None:
        self._closing = True
        supervisor = self._supervisor
        self._supervisor = None
        if supervisor is not None:
            supervisor.cancel()
            with suppress(asyncio.CancelledError):
                await supervisor
        await self._close_writer()
        if self._connected:
            await self._mark_disconnected()

    async def request_status(self, device_id: int) -> None:
        writer = self._writer
        if not self._connected or writer is None:
            return
        payload = b"\x52\x64\x00"
        frame = (
            HEADER + device_id.to_bytes(2, "little") + bytes([len(payload)]) + payload + TERMINATOR
        )
        wire = len(frame).to_bytes(4, "little") + frame
        async with self._writer_lock:
            writer.write(wire)
            await writer.drain()

    async def _run(self) -> None:
        delay = 1.0
        while not self._closing:
            try:
                await self._run_connection()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError, TimeoutError):
                _LOGGER.debug("TCP3rd status connection failed", exc_info=True)
            finally:
                await self._close_writer()
                if self._connected:
                    await self._mark_disconnected()
            if self._closing:
                return
            await asyncio.sleep(delay * random.uniform(0.75, 1.25))
            delay = min(delay * 2, 30.0)

    async def _run_connection(self) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=5,
        )
        self._writer = writer
        writer.write(HANDSHAKE_REQUEST)
        await writer.drain()
        parser = TCP3rdFrameParser()
        handshake_complete = False
        async with asyncio.timeout(2):
            while not handshake_complete:
                data = await reader.read(4096)
                if not data:
                    raise ConnectionError("TCP3rd closed during handshake")
                for frame in parser.feed(data):
                    if frame.device_id == 0 and frame.payload == b"\x80\x02":
                        handshake_complete = True
                    elif handshake_complete:
                        await self._on_frame(frame)
        await self._mark_connected()
        while data := await reader.read(4096):
            for frame in parser.feed(data):
                if frame.device_id or frame.payload != b"\x80\x02":
                    await self._on_frame(frame)

    async def _close_writer(self) -> None:
        writer = self._writer
        self._writer = None
        if writer is not None:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def _mark_connected(self) -> None:
        self._connected = True
        await self._on_connect()

    async def _mark_disconnected(self) -> None:
        self._connected = False
        await self._on_disconnect()

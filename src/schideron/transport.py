from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .constants import DEFAULT_PORT, DEFAULT_SOCKETIO_PATH, SEND_COMMAND, UPDATE_STATUS
from .exceptions import ConnectionClosedError, ProtocolError
from .models import JsonValue

_LOGGER = logging.getLogger(__name__)
_MIN_EVENT_ITEMS = 2
_RECONNECT_DELAY = 1.0
_RECONNECT_DELAY_MAX = 30.0

LifecycleHandler = Callable[[], Awaitable[None]]
StatusHandler = Callable[[object], Awaitable[None]]


class Transport(Protocol):
    @property
    def connected(self) -> bool: ...

    def set_handlers(
        self,
        *,
        on_connect: LifecycleHandler,
        on_disconnect: LifecycleHandler,
        on_status: StatusHandler,
    ) -> None: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_command(self, command: Mapping[str, JsonValue]) -> None: ...

    async def send_text(self, payload: str) -> None: ...


def _gateway_url(host: str, port: int, socketio_path: str) -> str:
    parsed = urlsplit(host if "://" in host else f"//{host}")
    if not parsed.hostname:
        raise ValueError("host must contain a hostname or IP address")
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    effective_port = parsed.port or port
    path = f"/{socketio_path.strip('/')}/"
    return urlunsplit(
        (scheme, f"{parsed.hostname}:{effective_port}", path, "transport=websocket&EIO=4", "")
    )


class SocketIOTransport:
    """Transport for the gateway's legacy Socket.IO-shaped protocol.

    Firmware V2.91 sends a non-standard ``40[\"connect\",{}]`` namespace
    packet. A conforming Socket.IO client rejects its array payload, so this
    class delegates RFC 6455 to aiohttp and handles only the observed Engine.IO
    heartbeat and event envelope.
    """

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_PORT,
        socketio_path: str = DEFAULT_SOCKETIO_PATH,
        connect_timeout: float = 10,
        ready_on_websocket_open: bool = False,
    ) -> None:
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        self._url = _gateway_url(host, port, socketio_path)
        self._connect_timeout = connect_timeout
        self._ready_on_websocket_open = ready_on_websocket_open
        self._on_connect: LifecycleHandler | None = None
        self._on_disconnect: LifecycleHandler | None = None
        self._on_status: StatusHandler | None = None
        self._session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._connected_event = asyncio.Event()
        self._connected = False
        self._closing = False
        self._ping_interval = 5.0
        self._ping_timeout = 44.0
        self._last_pong = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    def set_handlers(
        self,
        *,
        on_connect: LifecycleHandler,
        on_disconnect: LifecycleHandler,
        on_status: StatusHandler,
    ) -> None:
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_status = on_status

    async def connect(self) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            await self._wait_for_connection()
            return
        self._closing = False
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, connect=self._connect_timeout)
        )
        self._supervisor = asyncio.create_task(self._run(), name="schideron-transport")
        try:
            await self._wait_for_connection()
        except BaseException:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        self._closing = True
        supervisor = self._supervisor
        self._supervisor = None
        websocket = self._websocket
        self._websocket = None
        if websocket is not None and not websocket.closed:
            await websocket.close(code=aiohttp.WSCloseCode.GOING_AWAY)
        if supervisor is not None:
            supervisor.cancel()
            with suppress(asyncio.CancelledError):
                await supervisor
        if self._connected:
            await self._mark_disconnected()
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def send_command(self, command: Mapping[str, JsonValue]) -> None:
        payload = json.dumps([SEND_COMMAND, dict(command)], separators=(",", ":"))
        await self.send_text(f"42{payload}")

    async def send_text(self, payload: str) -> None:
        websocket = self._websocket
        if not self.connected or websocket is None or websocket.closed:
            raise ConnectionClosedError("gateway is not connected")
        try:
            await websocket.send_str(payload)
        except (ConnectionError, RuntimeError) as error:
            raise ConnectionClosedError("gateway connection closed while sending") from error

    async def _wait_for_connection(self) -> None:
        try:
            async with asyncio.timeout(self._connect_timeout):
                await self._connected_event.wait()
        except TimeoutError as error:
            raise ConnectionClosedError("gateway did not complete the handshake") from error

    async def _run(self) -> None:
        delay = _RECONNECT_DELAY
        while not self._closing:
            try:
                await self._connect_once()
                delay = _RECONNECT_DELAY
                await self._read_messages()
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, ConnectionClosedError, OSError, ProtocolError):
                _LOGGER.exception("gateway transport failed")
            finally:
                if self._connected:
                    await self._mark_disconnected()
                websocket = self._websocket
                self._websocket = None
                if websocket is not None and not websocket.closed:
                    await websocket.close()
            if self._closing:
                break
            jittered_delay = delay * random.uniform(0.75, 1.25)
            await asyncio.sleep(jittered_delay)
            delay = min(delay * 2, _RECONNECT_DELAY_MAX)

    async def _connect_once(self) -> None:
        if self._session is None:
            raise ConnectionClosedError("transport session is closed")
        self._websocket = await self._session.ws_connect(
            self._url,
            autoping=True,
            heartbeat=None,
            max_msg_size=2**20,
        )
        if self._ready_on_websocket_open:
            await self._mark_connected()

    async def _read_messages(self) -> None:
        websocket = self._websocket
        if websocket is None:
            raise ConnectionClosedError("gateway websocket is unavailable")
        heartbeat = asyncio.create_task(self._heartbeat(), name="schideron-heartbeat")
        try:
            async for message in websocket:
                if message.type is aiohttp.WSMsgType.TEXT:
                    await self._handle_text(message.data)
                elif message.type is aiohttp.WSMsgType.ERROR:
                    error = websocket.exception()
                    if error is not None:
                        raise error
                    raise ConnectionClosedError("gateway websocket failed")
                elif message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                }:
                    return
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self) -> None:
        await self._connected_event.wait()
        loop = asyncio.get_running_loop()
        self._last_pong = loop.time()
        interval = self._ping_interval * 0.9
        while self.connected:
            await asyncio.sleep(interval)
            websocket = self._websocket
            if websocket is None or websocket.closed:
                return
            if loop.time() - self._last_pong >= self._ping_timeout:
                await websocket.close(code=aiohttp.WSCloseCode.GOING_AWAY)
                return
            await websocket.send_str("2")

    async def _handle_text(self, message: str) -> None:
        if message == "2":
            websocket = self._websocket
            if websocket is not None:
                await websocket.send_str("3")
            return
        if message == "3":
            self._last_pong = asyncio.get_running_loop().time()
            return
        if message.startswith("0"):
            self._parse_open_packet(message[1:])
            return
        if message.startswith("40"):
            await self._mark_connected()
            return
        if message.startswith("42"):
            await self._handle_event(message[2:])
            return
        if message == "1":
            return
        _LOGGER.debug("ignored unsupported gateway packet type")

    def _parse_open_packet(self, payload: str) -> None:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ProtocolError("invalid Engine.IO open packet") from error
        if not isinstance(value, dict) or not isinstance(value.get("sid"), str):
            raise ProtocolError("Engine.IO open packet has no session ID")
        ping_interval = value.get("pingInterval")
        ping_timeout = value.get("pingTimeout")
        if not isinstance(ping_interval, (int, float)) or ping_interval <= 0:
            raise ProtocolError("Engine.IO open packet has no valid pingInterval")
        if not isinstance(ping_timeout, (int, float)) or ping_timeout <= 0:
            raise ProtocolError("Engine.IO open packet has no valid pingTimeout")
        self._ping_interval = ping_interval / 1000
        self._ping_timeout = ping_timeout / 1000

    async def _handle_event(self, payload: str) -> None:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ProtocolError("invalid Socket.IO event packet") from error
        if (
            not isinstance(value, list)
            or len(value) < _MIN_EVENT_ITEMS
            or not isinstance(value[0], str)
        ):
            raise ProtocolError("Socket.IO event packet has an invalid shape")
        if value[0] == UPDATE_STATUS and self._on_status is not None:
            await self._on_status(value[1])

    async def _mark_connected(self) -> None:
        if self._connected:
            return
        self._connected = True
        self._connected_event.set()
        if self._on_connect is not None:
            await self._on_connect()

    async def _mark_disconnected(self) -> None:
        self._connected = False
        self._connected_event.clear()
        if self._on_disconnect is not None:
            await self._on_disconnect()

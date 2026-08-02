from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Self, TypeVar

from .commands import (
    conditioner_extension,
    conditioner_mode,
    conditioner_off,
    conditioner_on,
    conditioner_speed,
    conditioner_temperature,
    heating_extension,
    heating_off,
    heating_on,
    heating_temperature,
    light_off,
    light_on,
)
from .constants import (
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    HeatingPower,
    HeatingStatusSource,
)
from .exceptions import (
    CommandOutcomeUnknownError,
    CommandQueueFullError,
    CommandTimeoutError,
    ConnectionClosedError,
    InvalidCommandError,
    ProtocolError,
)
from .models import (
    Conditioner,
    ConditionerKey,
    ConditionerStatus,
    DeviceStatus,
    Extension,
    Heating,
    HeatingCommandResult,
    HeatingKey,
    HeatingStatus,
    JsonValue,
    LightingChannel,
    LightingCommandResult,
    LightingKey,
    LightingStatus,
    RelayBankStatus,
    UnknownStatus,
)
from .protocol import parse_update_status
from .tcp3rd import (
    HVAC_OPCODE,
    HVAC_PAYLOAD_LENGTH,
    RELAY_OPCODE,
    RELAY_PAYLOAD_LENGTH,
    TCP3rdFrame,
    TCP3rdStatusTransport,
)
from .transport import SocketIOTransport, Transport

_LOGGER = logging.getLogger(__name__)

StatusCallback = Callable[[DeviceStatus], Awaitable[None] | None]
StatusT = TypeVar("StatusT", ConditionerStatus, HeatingStatus, LightingStatus)
HvacStatusT = TypeVar("HvacStatusT", ConditionerStatus, HeatingStatus)


class SchideronClient:
    def __init__(
        self,
        host: str,
        *,
        port: int = 3001,
        command_timeout: float = 45,
        stale_after: float = 30,
        relay_stale_after: float = 60,
        max_pending_commands: int = 32,
        transport: Transport | None = None,
        status_port: int = 7776,
        fresh_command_connections: bool = True,
    ) -> None:
        if command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        if stale_after <= 0:
            raise ValueError("stale_after must be positive")
        if relay_stale_after <= 0:
            raise ValueError("relay_stale_after must be positive")
        if max_pending_commands <= 0:
            raise ValueError("max_pending_commands must be positive")
        self._transport = transport or SocketIOTransport(host, port=port)
        self._command_endpoint = (
            (host, port) if transport is None and fresh_command_connections else None
        )
        self._status_transport = (
            TCP3rdStatusTransport(
                host,
                port=status_port,
                on_connect=self._on_relay_connect,
                on_disconnect=self._on_relay_disconnect,
                on_frame=self._on_relay_frame,
            )
            if transport is None
            else None
        )
        self._transport.set_handlers(
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            on_status=self._on_status,
        )
        self._command_timeout = command_timeout
        self._stale_after = timedelta(seconds=stale_after)
        self._relay_stale_after = timedelta(seconds=relay_stale_after)
        self._connected = False
        self._relay_connected = False
        self._connection_epoch = 0
        self._epoch_started_version = 0
        self._version = 0
        self._conditioners: dict[ConditionerKey, ConditionerStatus] = {}
        self._heatings: dict[HeatingKey, HeatingStatus] = {}
        self._lighting: dict[LightingKey, LightingStatus] = {}
        self._relay_banks: dict[int, RelayBankStatus] = {}
        self._relay_generation = 0
        self._unknown: deque[UnknownStatus] = deque(maxlen=100)
        self._history: deque[DeviceStatus] = deque(maxlen=512)
        self._callbacks: list[StatusCallback] = []
        self._ready = asyncio.Event()
        self._state_changed = asyncio.Condition()
        self._command_lock = asyncio.Lock()
        self._pending_guard = asyncio.Lock()
        self._pending_commands = 0
        self._max_pending_commands = max_pending_commands

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()

    @property
    def connected(self) -> bool:
        return self._connected and self._transport.connected

    @property
    def relay_status_connected(self) -> bool:
        return self._relay_connected

    @property
    def conditioners(self) -> Mapping[ConditionerKey, ConditionerStatus]:
        return MappingProxyType(self._conditioners.copy())

    @property
    def heatings(self) -> Mapping[HeatingKey, HeatingStatus]:
        return MappingProxyType(self._heatings.copy())

    @property
    def lighting(self) -> Mapping[LightingKey, LightingStatus]:
        return MappingProxyType(self._lighting.copy())

    @property
    def relay_banks(self) -> Mapping[int, RelayBankStatus]:
        return MappingProxyType(self._relay_banks.copy())

    @property
    def unknown_statuses(self) -> tuple[UnknownStatus, ...]:
        return tuple(self._unknown)

    async def connect(self) -> None:
        await self._transport.connect()
        if self._status_transport is not None:
            await self._status_transport.start()

    async def disconnect(self) -> None:
        if self._status_transport is not None:
            await self._status_transport.stop()
        await self._transport.disconnect()

    async def wait_until_ready(self, timeout: float = 30) -> None:
        try:
            async with asyncio.timeout(timeout):
                await self._ready.wait()
        except TimeoutError as error:
            raise CommandTimeoutError("gateway did not publish device status") from error

    def subscribe(self, callback: StatusCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            self._callbacks.remove(callback)

        return unsubscribe

    def is_stale(self, status: DeviceStatus, *, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        stale_after = (
            self._relay_stale_after if isinstance(status, LightingStatus) else self._stale_after
        )
        return current_time - status.received_at > stale_after

    def is_available(self, status: DeviceStatus, *, now: datetime | None = None) -> bool:
        return (
            self.connected
            and status.version > self._epoch_started_version
            and not self.is_stale(status, now=now)
        )

    async def send_command(self, command: Mapping[str, JsonValue]) -> None:
        async with self._pending_command(), AsyncExitStack() as connection:
            async with self._command_lock:
                self._require_connection()
                await connection.enter_async_context(self._device_command_connection(command))
            await asyncio.sleep(2)

    async def get_pi_status(
        self,
        uid: str,
        *,
        language: str = "en",
        response_timeout: float = 2,
        quiet_period: float = 0.15,
    ) -> tuple[DeviceStatus, ...]:
        if not uid.startswith("schideron_"):
            raise InvalidCommandError("uid must be the full schideron_ discovery identifier")
        if not language:
            raise InvalidCommandError("language cannot be empty")
        if response_timeout <= 0:
            raise ValueError("response_timeout must be positive")
        if not 0 < quiet_period < response_timeout:
            raise ValueError("quiet_period must be positive and less than response_timeout")
        payload = json.dumps(["getPiStatus", uid, {"language": language}], separators=(",", ":"))
        async with self._pending_command():
            async with self._command_lock:
                self._require_connection()
                baseline_version = self._version
                connection_epoch = self._connection_epoch
                await self._transport.send_text(payload)
            return await self._collect_status_burst(
                after_version=baseline_version,
                connection_epoch=connection_epoch,
                response_timeout=response_timeout,
                quiet_period=quiet_period,
            )

    async def conditioner_on(self, conditioner: Conditioner) -> ConditionerStatus:
        return await self._set_conditioner(
            conditioner,
            conditioner_on(conditioner),
            lambda status: status.power is ConditionerPower.ON,
        )

    async def conditioner_off(self, conditioner: Conditioner) -> ConditionerStatus:
        return await self._set_conditioner(
            conditioner,
            conditioner_off(conditioner),
            lambda status: status.power is ConditionerPower.OFF,
        )

    async def set_conditioner_temperature(
        self,
        conditioner: Conditioner,
        temperature: int,
    ) -> ConditionerStatus:
        current = self._conditioners.get(conditioner.key)
        current_mode = current.mode if current is not None else None
        payload = conditioner_temperature(
            conditioner,
            temperature,
            current_mode=current_mode,
        )
        return await self._set_conditioner(
            conditioner,
            payload,
            lambda status: status.set_temperature == temperature * 10,
        )

    async def set_conditioner_mode(
        self,
        conditioner: Conditioner,
        mode: ConditionerMode,
    ) -> ConditionerStatus:
        mode = ConditionerMode(mode)
        return await self._set_conditioner(
            conditioner,
            conditioner_mode(conditioner, mode),
            lambda status: status.mode is mode,
        )

    async def set_conditioner_fan_speed(
        self,
        conditioner: Conditioner,
        speed: ConditionerFanSpeed,
    ) -> ConditionerStatus:
        speed = ConditionerFanSpeed(speed)
        return await self._set_conditioner(
            conditioner,
            conditioner_speed(conditioner, speed),
            lambda status: status.fan_speed is speed,
        )

    async def run_conditioner_extension(
        self,
        conditioner: Conditioner,
        extension: Extension,
    ) -> None:
        await self.send_command(conditioner_extension(conditioner, extension))

    async def heating_on(
        self,
        heating: Heating,
        *,
        confirm: bool = False,
    ) -> HeatingCommandResult:
        return await self._set_heating(
            heating,
            heating_on(heating),
            power=HeatingPower.ON,
            target_temperature=None,
            matches=lambda status: status.power is HeatingPower.ON,
            confirm=confirm,
        )

    async def heating_off(
        self,
        heating: Heating,
        *,
        confirm: bool = False,
    ) -> HeatingCommandResult:
        return await self._set_heating(
            heating,
            heating_off(heating),
            power=HeatingPower.OFF,
            target_temperature=None,
            matches=lambda status: status.power is HeatingPower.OFF,
            confirm=confirm,
        )

    async def set_heating_temperature(
        self,
        heating: Heating,
        temperature: int,
        *,
        confirm: bool = False,
    ) -> HeatingCommandResult:
        return await self._set_heating(
            heating,
            heating_temperature(heating, temperature),
            power=None,
            target_temperature=temperature,
            matches=lambda status: status.set_temperature == temperature * 10,
            confirm=confirm,
        )

    async def run_heating_extension(
        self,
        heating: Heating,
        extension: Extension,
    ) -> None:
        await self.send_command(heating_extension(heating, extension))

    async def lighting_on(
        self,
        channel: LightingChannel,
        *,
        confirm: bool = False,
    ) -> LightingCommandResult:
        return await self._set_lighting(
            channel,
            light_on(channel),
            is_on=True,
            confirm=confirm,
        )

    async def lighting_off(
        self,
        channel: LightingChannel,
        *,
        confirm: bool = False,
    ) -> LightingCommandResult:
        return await self._set_lighting(
            channel,
            light_off(channel),
            is_on=False,
            confirm=confirm,
        )

    async def _set_conditioner(
        self,
        conditioner: Conditioner,
        payload: Mapping[str, JsonValue],
        matches: Callable[[ConditionerStatus], bool],
    ) -> ConditionerStatus:
        return await self._set_hvac(
            get_status=lambda: self._conditioners.get(conditioner.key),
            device_id=conditioner.device_id,
            payload=payload,
            matches=matches,
        )

    async def _set_heating(
        self,
        heating: Heating,
        payload: Mapping[str, JsonValue],
        *,
        power: HeatingPower | None,
        target_temperature: int | None,
        matches: Callable[[HeatingStatus], bool],
        confirm: bool,
    ) -> HeatingCommandResult:
        async with self._pending_command(), AsyncExitStack() as connection:
            async with self._command_lock:
                self._require_connection()
                current = self._heatings.get(heating.key)
                sent_at = datetime.now(UTC)
                if (
                    confirm
                    and current is not None
                    and current.authoritative
                    and self.is_available(current)
                    and matches(current)
                ):
                    return HeatingCommandResult(
                        heating=heating,
                        power=power,
                        target_temperature=target_temperature,
                        confirmed=True,
                        status=current,
                        sent_at=sent_at,
                    )
                baseline = current.version if current is not None else self._version
                epoch = self._connection_epoch
                await connection.enter_async_context(self._device_command_connection(payload))
            if not confirm:
                return HeatingCommandResult(
                    heating=heating,
                    power=power,
                    target_temperature=target_temperature,
                    confirmed=False,
                    status=current,
                    sent_at=sent_at,
                )
            if self._status_transport is not None:
                await asyncio.sleep(0.5)
                await self._status_transport.request_status(heating.device_id)
            status = await self._wait_for_hvac(
                lambda: self._heatings.get(heating.key),
                after_version=baseline,
                connection_epoch=epoch,
                matches=lambda status: status.authoritative and matches(status),
            )
            return HeatingCommandResult(
                heating=heating,
                power=power,
                target_temperature=target_temperature,
                confirmed=True,
                status=status,
                sent_at=sent_at,
            )

    async def _set_hvac(
        self,
        *,
        get_status: Callable[[], HvacStatusT | None],
        device_id: int,
        payload: Mapping[str, JsonValue],
        matches: Callable[[HvacStatusT], bool],
    ) -> HvacStatusT:
        async with self._pending_command(), AsyncExitStack() as connection:
            async with self._command_lock:
                self._require_connection()
                current = get_status()
                if current is not None and self.is_available(current) and matches(current):
                    return current
                baseline = current.version if current is not None else self._version
                epoch = self._connection_epoch
                await connection.enter_async_context(self._device_command_connection(payload))
            if self._status_transport is not None:
                await asyncio.sleep(0.5)
                await self._status_transport.request_status(device_id)
            return await self._wait_for_hvac(
                get_status,
                after_version=baseline,
                connection_epoch=epoch,
                matches=matches,
            )

    async def _set_lighting(
        self,
        channel: LightingChannel,
        payload: Mapping[str, JsonValue],
        *,
        is_on: bool,
        confirm: bool,
    ) -> LightingCommandResult:
        async with self._pending_command(), AsyncExitStack() as connection:
            async with self._command_lock:
                self._require_connection()
                current = self._lighting.get(channel.key)
                sent_at = datetime.now(UTC)
                if current is not None and self.is_available(current) and current.is_on is is_on:
                    return LightingCommandResult(
                        channel=channel,
                        is_on=is_on,
                        confirmed=True,
                        status=current,
                        sent_at=sent_at,
                    )
                baseline = current.version if current is not None else self._version
                epoch = self._connection_epoch
                if not confirm:
                    await self._transport.send_command(payload)
                    return LightingCommandResult(
                        channel=channel,
                        is_on=is_on,
                        confirmed=False,
                        status=current,
                        sent_at=sent_at,
                    )
                await connection.enter_async_context(self._device_command_connection(payload))
            status = await self._wait_for_lighting(
                channel.key,
                after_version=baseline,
                connection_epoch=epoch,
                is_on=is_on,
            )
            return LightingCommandResult(
                channel=channel,
                is_on=is_on,
                confirmed=True,
                status=status,
                sent_at=sent_at,
            )

    async def _wait_for_hvac(
        self,
        get_status: Callable[[], HvacStatusT | None],
        *,
        after_version: int,
        connection_epoch: int,
        matches: Callable[[HvacStatusT], bool],
    ) -> HvacStatusT:
        def result() -> HvacStatusT | None:
            status = get_status()
            if status is not None and status.version > after_version and matches(status):
                return status
            return None

        return await self._wait_for_status(result, connection_epoch)

    async def _wait_for_lighting(
        self,
        key: LightingKey,
        *,
        after_version: int,
        connection_epoch: int,
        is_on: bool,
    ) -> LightingStatus:
        def result() -> LightingStatus | None:
            status = self._lighting.get(key)
            if status is not None and status.version > after_version and status.is_on is is_on:
                return status
            return None

        return await self._wait_for_status(result, connection_epoch)

    async def _wait_for_status(
        self,
        result: Callable[[], StatusT | None],
        connection_epoch: int,
    ) -> StatusT:
        try:
            async with asyncio.timeout(self._command_timeout):
                async with self._state_changed:
                    while (status := result()) is None:
                        if self._connection_epoch != connection_epoch or not self.connected:
                            raise CommandOutcomeUnknownError(
                                "gateway disconnected after command transmission"
                            )
                        await self._state_changed.wait()
                    return status
        except TimeoutError as error:
            raise CommandTimeoutError("gateway did not confirm the requested state") from error

    async def _collect_status_burst(
        self,
        *,
        after_version: int,
        connection_epoch: int,
        response_timeout: float,
        quiet_period: float,
    ) -> tuple[DeviceStatus, ...]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + response_timeout
        quiet_deadline: float | None = None
        latest_version = after_version
        async with self._state_changed:
            while True:
                statuses = tuple(
                    status for status in self._history if status.version > after_version
                )
                if statuses and statuses[-1].version > latest_version:
                    latest_version = statuses[-1].version
                    quiet_deadline = loop.time() + quiet_period
                now = loop.time()
                if statuses and quiet_deadline is not None and now >= quiet_deadline:
                    return statuses
                if now >= deadline:
                    if statuses:
                        return statuses
                    raise CommandTimeoutError("gateway did not return a status snapshot")
                if self._connection_epoch != connection_epoch or not self.connected:
                    raise ConnectionClosedError("gateway disconnected during status snapshot")
                wake_at = min(deadline, quiet_deadline or deadline)
                try:
                    async with asyncio.timeout(wake_at - now):
                        await self._state_changed.wait()
                except TimeoutError:
                    continue

    def _require_connection(self) -> None:
        if not self.connected:
            raise ConnectionClosedError("gateway is not connected")

    @asynccontextmanager
    async def _device_command_connection(
        self,
        command: Mapping[str, JsonValue],
    ) -> AsyncIterator[None]:
        if self._command_endpoint is None:
            await self._transport.send_command(command)
            yield
            return
        host, port = self._command_endpoint
        transport = SocketIOTransport(host, port=port, ready_on_websocket_open=True)

        async def no_op() -> None:
            return None

        async def ignore_status(_: object) -> None:
            return None

        transport.set_handlers(
            on_connect=no_op,
            on_disconnect=no_op,
            on_status=ignore_status,
        )
        await transport.connect()
        try:
            await transport.send_command(command)
            yield
        finally:
            await transport.disconnect()

    @asynccontextmanager
    async def _pending_command(self) -> AsyncIterator[None]:
        async with self._pending_guard:
            if self._pending_commands >= self._max_pending_commands:
                raise CommandQueueFullError("gateway command queue is full")
            self._pending_commands += 1
        try:
            yield
        finally:
            async with self._pending_guard:
                self._pending_commands -= 1

    async def _on_connect(self) -> None:
        async with self._state_changed:
            self._connected = True
            self._connection_epoch += 1
            self._epoch_started_version = self._version
            self._state_changed.notify_all()

    async def _on_disconnect(self) -> None:
        async with self._state_changed:
            self._connected = False
            self._connection_epoch += 1
            self._ready.clear()
            self._state_changed.notify_all()

    async def _on_relay_connect(self) -> None:
        async with self._state_changed:
            self._relay_connected = True
            self._state_changed.notify_all()

    async def _on_relay_disconnect(self) -> None:
        async with self._state_changed:
            self._relay_connected = False
            self._state_changed.notify_all()

    async def _on_relay_frame(self, frame: TCP3rdFrame) -> None:
        if len(frame.payload) == HVAC_PAYLOAD_LENGTH and frame.payload[0] == HVAC_OPCODE:
            heating = tuple(
                status for key, status in self._heatings.items() if key.device_id == frame.device_id
            )
            conditioners = tuple(
                status
                for key, status in self._conditioners.items()
                if key.device_id == frame.device_id
            )
            if len(heating) + len(conditioners) != 1:
                return
            if heating:
                await self._on_heating_status_frame(frame, heating[0])
            else:
                await self._on_conditioner_status_frame(frame, conditioners[0])
            return
        if len(frame.payload) != RELAY_PAYLOAD_LENGTH or frame.payload[0] != RELAY_OPCODE:
            return
        received_at = datetime.now(UTC)
        async with self._state_changed:
            self._relay_generation += 1
            self._relay_banks[frame.device_id] = RelayBankStatus(
                device_id=frame.device_id,
                opcode=frame.payload[0],
                data=frame.payload[1:],
                received_at=received_at,
                generation=self._relay_generation,
            )
            self._state_changed.notify_all()

    async def _on_conditioner_status_frame(
        self,
        frame: TCP3rdFrame,
        current: ConditionerStatus,
    ) -> None:
        try:
            power = ConditionerPower(frame.payload[5])
            mode = ConditionerMode(frame.payload[6])
            fan_speed = ConditionerFanSpeed(frame.payload[7])
        except ValueError:
            return
        raw_set_temperature = int.from_bytes(frame.payload[9:11], "little")
        room_temperature = int.from_bytes(frame.payload[11:13], "little")
        received_at = datetime.now(UTC)
        async with self._state_changed:
            self._version += 1
            status = replace(
                current,
                power=power,
                mode=mode,
                fan_speed=fan_speed,
                set_temperature=(raw_set_temperature // 10) * 10,
                room_temperature=room_temperature,
                temperature_type=frame.payload[8],
                received_at=received_at,
                version=self._version,
                raw={
                    **current.raw,
                    "TCP3rd": frame.payload.hex(),
                },
            )
            self._history.append(status)
            self._conditioners[status.key] = status
            self._state_changed.notify_all()
        self._publish(status)

    async def _on_heating_status_frame(
        self,
        frame: TCP3rdFrame,
        current: HeatingStatus,
    ) -> None:
        try:
            power = HeatingPower(frame.payload[5])
        except ValueError:
            return
        raw_set_temperature = int.from_bytes(frame.payload[9:11], "little")
        raw_room_temperature = int.from_bytes(frame.payload[11:13], "little")
        received_at = datetime.now(UTC)
        async with self._state_changed:
            self._version += 1
            status = replace(
                current,
                power=power,
                set_temperature=(raw_set_temperature // 10) * 10 if raw_set_temperature else None,
                room_temperature=raw_room_temperature or None,
                temperature_type=frame.payload[8],
                received_at=received_at,
                version=self._version,
                source=HeatingStatusSource.TCP3RD,
                raw={
                    **current.raw,
                    "TCP3rd": frame.payload.hex(),
                },
            )
            self._history.append(status)
            self._heatings[status.key] = status
            self._state_changed.notify_all()
        self._publish(status)

    async def _on_status(self, payload: object) -> None:
        received_at = datetime.now(UTC)
        try:
            statuses = parse_update_status(
                payload,
                received_at=received_at,
                first_version=self._version + 1,
            )
        except ProtocolError:
            _LOGGER.exception("gateway published an invalid updateStatus payload")
            return
        async with self._state_changed:
            for status in statuses:
                self._version = status.version
                self._history.append(status)
                if isinstance(status, ConditionerStatus):
                    self._conditioners[status.key] = status
                elif isinstance(status, HeatingStatus):
                    self._heatings[status.key] = status
                elif isinstance(status, LightingStatus):
                    self._lighting[status.key] = status
                else:
                    self._unknown.append(status)
            if statuses:
                self._ready.set()
            self._state_changed.notify_all()
        for status in statuses:
            self._publish(status)

    def _publish(self, status: DeviceStatus) -> None:
        for callback in tuple(self._callbacks):
            try:
                result = callback(status)
            except Exception:
                _LOGGER.exception("status subscriber raised an exception")
                continue
            if inspect.isawaitable(result):
                task = asyncio.ensure_future(result)
                task.add_done_callback(self._subscriber_done)

    @staticmethod
    def _subscriber_done(task: asyncio.Future[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            _LOGGER.error(
                "async status subscriber raised an exception",
                exc_info=(type(error), error, error.__traceback__),
            )

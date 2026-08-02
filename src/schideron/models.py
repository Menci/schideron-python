from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

from .constants import (
    MAX_DEVICE_ID,
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    HeatingPower,
    HeatingStatusSource,
)

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ConditionerKey:
    device_name: int
    device_id: int
    pb: int
    serial_port: str | None


@dataclass(frozen=True, slots=True)
class HeatingKey:
    device_name: int
    device_id: int
    pb: int
    serial_port: str | None


@dataclass(frozen=True, slots=True)
class LightingKey:
    device_id: int
    channel: int


@dataclass(frozen=True, slots=True)
class Conditioner:
    device_id: int
    device_name: int = 1
    sync_type: int = 2
    pb: int = 0
    serial_port: str | None = None
    min_temperature: int = 17
    max_temperature: int = 28
    mode_flag: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.device_id <= MAX_DEVICE_ID:
            raise ValueError(f"device_id must be between 1 and {MAX_DEVICE_ID}")
        if self.device_name < 1:
            raise ValueError("device_name must be positive")
        if self.sync_type < 0:
            raise ValueError("sync_type cannot be negative")
        if self.pb < 0:
            raise ValueError("pb cannot be negative")
        if self.min_temperature > self.max_temperature:
            raise ValueError("min_temperature cannot exceed max_temperature")

    @property
    def key(self) -> ConditionerKey:
        return ConditionerKey(self.device_name, self.device_id, self.pb, self.serial_port)

    @classmethod
    def from_status(
        cls,
        status: ConditionerStatus,
        *,
        sync_type: int = 2,
        min_temperature: int = 17,
        max_temperature: int = 28,
        mode_flag: bool = False,
    ) -> Self:
        return cls(
            device_id=status.key.device_id,
            device_name=status.key.device_name,
            sync_type=sync_type,
            pb=status.key.pb,
            serial_port=status.key.serial_port,
            min_temperature=min_temperature,
            max_temperature=max_temperature,
            mode_flag=mode_flag,
        )


@dataclass(frozen=True, slots=True)
class Heating:
    device_id: int
    device_name: int = 1
    sync_type: int = 2
    pb: int = 0
    serial_port: str | None = None
    min_temperature: int = 5
    max_temperature: int = 35

    def __post_init__(self) -> None:
        if not 1 <= self.device_id <= MAX_DEVICE_ID:
            raise ValueError(f"device_id must be between 1 and {MAX_DEVICE_ID}")
        if self.device_name < 1:
            raise ValueError("device_name must be positive")
        if self.sync_type < 0:
            raise ValueError("sync_type cannot be negative")
        if self.pb < 0:
            raise ValueError("pb cannot be negative")
        if self.min_temperature > self.max_temperature:
            raise ValueError("min_temperature cannot exceed max_temperature")

    @property
    def key(self) -> HeatingKey:
        return HeatingKey(self.device_name, self.device_id, self.pb, self.serial_port)

    @classmethod
    def from_status(
        cls,
        status: HeatingStatus,
        *,
        sync_type: int = 2,
        min_temperature: int = 5,
        max_temperature: int = 35,
    ) -> Self:
        return cls(
            device_id=status.key.device_id,
            device_name=status.key.device_name,
            sync_type=sync_type,
            pb=status.key.pb,
            serial_port=status.key.serial_port,
            min_temperature=min_temperature,
            max_temperature=max_temperature,
        )


@dataclass(frozen=True, slots=True)
class LightingChannel:
    device_id: int
    channel: int
    sync_type: int = 2

    def __post_init__(self) -> None:
        if self.device_id < 1:
            raise ValueError("device_id must be positive")
        if self.channel < 0:
            raise ValueError("channel cannot be negative")
        if self.sync_type < 0:
            raise ValueError("sync_type cannot be negative")

    @property
    def key(self) -> LightingKey:
        return LightingKey(self.device_id, self.channel)


@dataclass(frozen=True, slots=True)
class Extension:
    extension_id: int
    name: str | None = None

    def __post_init__(self) -> None:
        if self.extension_id < 0:
            raise ValueError("extension_id cannot be negative")


@dataclass(frozen=True, slots=True)
class ConditionerStatus:
    key: ConditionerKey
    power: ConditionerPower
    mode: ConditionerMode
    fan_speed: ConditionerFanSpeed
    set_temperature: int
    room_temperature: int | None
    outside_temperature: int | None
    temperature_type: int | None
    set_humidity: int | None
    room_humidity: int | None
    room_pm: int | None
    room_co2: int | None
    definition: str
    product_model: str | None
    brand: str | None
    category: str | None
    received_at: datetime
    version: int
    raw: dict[str, Any]

    @property
    def target_temperature(self) -> float:
        return self.set_temperature / 10

    @property
    def current_temperature(self) -> float | None:
        if self.room_temperature is None:
            return None
        return self.room_temperature / 10


@dataclass(frozen=True, slots=True)
class HeatingStatus:
    key: HeatingKey
    power: HeatingPower
    set_temperature: int | None
    room_temperature: int | None
    temperature_type: int | None
    definition: str
    product_model: str | None
    brand: str | None
    category: str | None
    received_at: datetime
    version: int
    source: HeatingStatusSource
    raw: dict[str, Any]

    @property
    def authoritative(self) -> bool:
        return self.source is HeatingStatusSource.TCP3RD

    @property
    def target_temperature(self) -> float | None:
        if self.set_temperature is None:
            return None
        return self.set_temperature / 10

    @property
    def current_temperature(self) -> float | None:
        if self.room_temperature is None:
            return None
        return self.room_temperature / 10


@dataclass(frozen=True, slots=True)
class LightingStatus:
    key: LightingKey
    is_on: bool
    type: int | None
    definition: str
    product_model: str | None
    brand: str | None
    category: str | None
    received_at: datetime
    version: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UnknownStatus:
    definition: str | None
    received_at: datetime
    version: int
    raw: dict[str, Any]


type DeviceStatus = ConditionerStatus | HeatingStatus | LightingStatus | UnknownStatus


@dataclass(frozen=True, slots=True)
class GatewayInfo:
    host: str
    port: int
    uid: str | None
    raw_response: str


@dataclass(frozen=True, slots=True)
class LightingCommandResult:
    channel: LightingChannel
    is_on: bool
    confirmed: bool
    status: LightingStatus | None
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class HeatingCommandResult:
    heating: Heating
    power: HeatingPower | None
    target_temperature: int | None
    confirmed: bool
    status: HeatingStatus | None
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class RelayBankStatus:
    device_id: int
    opcode: int
    data: bytes
    received_at: datetime
    generation: int

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from .constants import (
    DEFINITION_CONDITIONER,
    DEFINITION_LIGHT,
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    HeatingPower,
    HeatingStatusSource,
)
from .exceptions import ProtocolError
from .models import (
    ConditionerKey,
    ConditionerStatus,
    DeviceStatus,
    HeatingKey,
    HeatingStatus,
    LightingKey,
    LightingStatus,
    UnknownStatus,
)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ProtocolError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ProtocolError(f"{field} must be an integer")
    try:
        return int(value)
    except ValueError as error:
        raise ProtocolError(f"{field} must be an integer") from error


def _optional_integer(data: Mapping[str, object], field: str) -> int | None:
    if field not in data or data[field] is None:
        return None
    return _integer(data[field], field)


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"{field} must be a string")
    return value


def _optional_nonzero_integer(data: Mapping[str, object], field: str) -> int | None:
    value = _optional_integer(data, field)
    return value if value else None


def _is_floor_heating(data: Mapping[str, object]) -> bool:
    product_model = _optional_string(data, "product_model")
    if product_model is None:
        return False
    normalized = "".join(character for character in product_model.casefold() if character.isalnum())
    return "floorheating" in normalized


def _conditioner_status(
    data: Mapping[str, object],
    *,
    received_at: datetime,
    version: int,
) -> ConditionerStatus:
    try:
        power = ConditionerPower(_integer(data.get("state"), "state"))
        mode = ConditionerMode(_integer(data.get("mode"), "mode"))
        fan_speed = ConditionerFanSpeed(_integer(data.get("fanspeed"), "fanspeed"))
    except ValueError as error:
        raise ProtocolError("conditioner status contains an unknown enum value") from error

    key = ConditionerKey(
        device_name=_integer(data.get("device_name"), "device_name"),
        device_id=_integer(data.get("device_id"), "device_id"),
        pb=_integer(data.get("PB"), "PB"),
        serial_port=_optional_string(data, "interface"),
    )
    return ConditionerStatus(
        key=key,
        power=power,
        mode=mode,
        fan_speed=fan_speed,
        set_temperature=_integer(data.get("set_temperature"), "set_temperature"),
        room_temperature=_optional_integer(data, "room_temperature"),
        outside_temperature=_optional_integer(data, "outside_temperature"),
        temperature_type=_optional_integer(data, "temperature_type"),
        set_humidity=_optional_integer(data, "set_humidity"),
        room_humidity=_optional_integer(data, "room_humidity"),
        room_pm=_optional_integer(data, "PM2.5"),
        room_co2=_optional_integer(data, "room_co2"),
        definition=DEFINITION_CONDITIONER,
        product_model=_optional_string(data, "product_model"),
        brand=_optional_string(data, "brand"),
        category=_optional_string(data, "category"),
        received_at=received_at,
        version=version,
        raw=dict(data),
    )


def _heating_status(
    data: Mapping[str, object],
    *,
    received_at: datetime,
    version: int,
) -> HeatingStatus:
    try:
        power = HeatingPower(_integer(data.get("state"), "state"))
    except ValueError as error:
        raise ProtocolError("heating status contains an unknown power value") from error

    return HeatingStatus(
        key=HeatingKey(
            device_name=_integer(data.get("device_name"), "device_name"),
            device_id=_integer(data.get("device_id"), "device_id"),
            pb=_integer(data.get("PB"), "PB"),
            serial_port=_optional_string(data, "interface"),
        ),
        power=power,
        set_temperature=_optional_nonzero_integer(data, "set_temperature"),
        room_temperature=_optional_nonzero_integer(data, "room_temperature"),
        temperature_type=_optional_integer(data, "temperature_type"),
        definition=DEFINITION_CONDITIONER,
        product_model=_optional_string(data, "product_model"),
        brand=_optional_string(data, "brand"),
        category=_optional_string(data, "category"),
        received_at=received_at,
        version=version,
        source=HeatingStatusSource.CACHED_SNAPSHOT,
        raw=dict(data),
    )


def _lighting_status(
    data: Mapping[str, object],
    *,
    received_at: datetime,
    version: int,
) -> LightingStatus:
    status = _integer(data.get("status"), "status")
    if status not in (0, 1):
        raise ProtocolError("lighting status must be 0 or 1")
    return LightingStatus(
        key=LightingKey(
            device_id=_integer(data.get("device_id"), "device_id"),
            channel=_integer(data.get("channel"), "channel"),
        ),
        is_on=status == 1,
        type=_optional_integer(data, "type"),
        definition=DEFINITION_LIGHT,
        product_model=_optional_string(data, "product_model"),
        brand=_optional_string(data, "brand"),
        category=_optional_string(data, "category"),
        received_at=received_at,
        version=version,
        raw=dict(data),
    )


def _is_supported_conditioner(data: Mapping[str, object]) -> bool:
    required_fields = ("state", "mode", "fanspeed", "set_temperature")
    if any(field not in data for field in required_fields):
        return False
    return (
        _integer(data["state"], "state") in set(ConditionerPower)
        and _integer(data["mode"], "mode") in set(ConditionerMode)
        and _integer(data["fanspeed"], "fanspeed") in set(ConditionerFanSpeed)
    )


def parse_status(
    value: object,
    *,
    received_at: datetime,
    version: int,
) -> DeviceStatus:
    if not isinstance(value, Mapping):
        raise ProtocolError("status entry must be an object")
    data = dict(value)
    definition = _optional_string(data, "definition")
    if definition == DEFINITION_CONDITIONER and _is_floor_heating(data):
        return _heating_status(data, received_at=received_at, version=version)
    if definition == DEFINITION_CONDITIONER and _is_supported_conditioner(data):
        return _conditioner_status(data, received_at=received_at, version=version)
    if definition == DEFINITION_LIGHT:
        return _lighting_status(data, received_at=received_at, version=version)
    return UnknownStatus(
        definition=definition,
        received_at=received_at,
        version=version,
        raw=data,
    )


def parse_update_status(
    payload: object,
    *,
    received_at: datetime,
    first_version: int,
) -> tuple[DeviceStatus, ...]:
    if isinstance(payload, (str, bytes, bytearray)) or not isinstance(payload, Sequence):
        raise ProtocolError("updateStatus payload must be an array")
    statuses: list[DeviceStatus] = []
    light_metadata: dict[str, object] | None = None
    for item in payload:
        if not isinstance(item, Mapping):
            raise ProtocolError("status entry must be an object")
        data = dict(item)
        definition = _optional_string(data, "definition")
        is_light_row = all(field in data for field in ("device_id", "channel", "status"))
        if definition == DEFINITION_LIGHT and not is_light_row:
            light_metadata = data
            continue
        if is_light_row and (
            definition == DEFINITION_LIGHT
            or light_metadata is not None
            or _optional_integer(data, "type") == 1
        ):
            combined = dict(light_metadata or {})
            combined.update(data)
            combined["definition"] = DEFINITION_LIGHT
            status: DeviceStatus = _lighting_status(
                combined,
                received_at=received_at,
                version=first_version + len(statuses),
            )
        else:
            status = parse_status(
                data,
                received_at=received_at,
                version=first_version + len(statuses),
            )
        statuses.append(status)
    return tuple(statuses)

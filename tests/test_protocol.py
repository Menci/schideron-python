from datetime import UTC, datetime

import pytest

from schideron import (
    Conditioner,
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    Heating,
    HeatingPower,
    HeatingStatusSource,
    ProtocolError,
)
from schideron.models import (
    ConditionerStatus,
    HeatingStatus,
    LightingKey,
    LightingStatus,
    UnknownStatus,
)
from schideron.protocol import parse_status, parse_update_status

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def test_parse_conditioner_status(conditioner_status_payload) -> None:
    status = parse_status(conditioner_status_payload, received_at=NOW, version=7)
    assert isinstance(status, ConditionerStatus)
    assert status.key.device_id == 1
    assert status.key.pb == 1
    assert status.key.serial_port == "USB3"
    assert status.power is ConditionerPower.ON
    assert status.mode is ConditionerMode.COOL
    assert status.fan_speed is ConditionerFanSpeed.AUTO
    assert status.target_temperature == 27
    assert status.current_temperature == 28
    assert status.received_at is NOW
    assert status.version == 7
    assert Conditioner.from_status(status) == Conditioner(
        device_id=1,
        device_name=1,
        sync_type=2,
        pb=1,
        serial_port="USB3",
    )


def test_parse_floor_heating_status(heating_status_payload) -> None:
    status = parse_status(heating_status_payload, received_at=NOW, version=8)
    assert isinstance(status, HeatingStatus)
    assert status.key.device_id == 17
    assert status.key.pb == 17
    assert status.key.serial_port == "USB1"
    assert status.power is HeatingPower.OFF
    assert status.source is HeatingStatusSource.CACHED_SNAPSHOT
    assert not status.authoritative
    assert status.target_temperature is None
    assert status.current_temperature is None
    assert Heating.from_status(status) == Heating(
        device_id=17,
        device_name=1,
        sync_type=2,
        pb=17,
        serial_port="USB1",
    )

    heating_status_payload["state"] = "2"
    heating_status_payload["set_temperature"] = "240"
    heating_status_payload["room_temperature"] = "231"
    updated = parse_status(heating_status_payload, received_at=NOW, version=9)
    assert isinstance(updated, HeatingStatus)
    assert updated.power is HeatingPower.ON
    assert updated.target_temperature == 24
    assert updated.current_temperature == 23.1


def test_parse_lighting_status() -> None:
    status = parse_status(
        {
            "definition": "lightControl",
            "device_id": "5",
            "channel": "2",
            "status": "1",
            "type": 1,
            "product_model": "SDR-RL-C08",
        },
        received_at=NOW,
        version=8,
    )
    assert isinstance(status, LightingStatus)
    assert status.key.device_id == 5
    assert status.key.channel == 2
    assert status.is_on


def test_parse_lighting_header_and_channel_rows() -> None:
    statuses = parse_update_status(
        [
            {
                "definition": "lightControl",
                "product_model": "SDR-RL-C08",
                "brand": "Schideron",
                "category": "Lighting",
                "interface": "S-Net",
            },
            {"device_id": "5", "channel": "0", "status": "1", "type": 1},
            {"device_id": "5", "channel": "1", "status": "0", "type": 1},
        ],
        received_at=NOW,
        first_version=30,
    )
    assert len(statuses) == 2
    first, second = statuses
    assert isinstance(first, LightingStatus)
    assert isinstance(second, LightingStatus)
    assert first.key == LightingKey(5, 0)
    assert first.product_model == "SDR-RL-C08"
    assert first.is_on
    assert not second.is_on
    assert [status.version for status in statuses] == [30, 31]


def test_parse_bare_type_one_lighting_row() -> None:
    (status,) = parse_update_status(
        [{"device_id": "6", "channel": "2", "status": "1", "type": 1}],
        received_at=NOW,
        first_version=40,
    )
    assert isinstance(status, LightingStatus)
    assert status.key.device_id == 6
    assert status.key.channel == 2


def test_parse_unknown_status_preserves_payload() -> None:
    payload = {"definition": "curtainControl", "device_id": "9"}
    status = parse_status(payload, received_at=NOW, version=9)
    assert isinstance(status, UnknownStatus)
    assert status.definition == "curtainControl"
    assert status.raw == payload


def test_parse_update_status_assigns_monotonic_versions(conditioner_status_payload) -> None:
    result = parse_update_status(
        [conditioner_status_payload, {"definition": "unknown"}],
        received_at=NOW,
        first_version=20,
    )
    assert [status.version for status in result] == [20, 21]


@pytest.mark.parametrize(
    "payload",
    [
        "not-an-array",
        {},
        ["not-an-object"],
    ],
)
def test_parse_update_status_rejects_invalid_shapes(payload) -> None:
    with pytest.raises(ProtocolError):
        parse_update_status(payload, received_at=NOW, first_version=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("device_id", "invalid"),
        ("device_id", "0"),
        ("device_id", "65536"),
    ],
)
def test_parse_conditioner_status_rejects_invalid_fields(
    conditioner_status_payload,
    field,
    value,
) -> None:
    conditioner_status_payload[field] = value
    with pytest.raises(ProtocolError):
        parse_status(conditioner_status_payload, received_at=NOW, version=1)


@pytest.mark.parametrize("device_id", ["0", "65536"])
def test_parse_heating_status_rejects_out_of_range_device_id(
    heating_status_payload,
    device_id,
) -> None:
    heating_status_payload["device_id"] = device_id
    with pytest.raises(ProtocolError):
        parse_status(heating_status_payload, received_at=NOW, version=1)


@pytest.mark.parametrize(("field", "value"), [("state", 0), ("mode", 0), ("fanspeed", 0)])
def test_parse_unsupported_aircon_control_as_unknown(
    conditioner_status_payload,
    field,
    value,
) -> None:
    conditioner_status_payload[field] = value
    status = parse_status(conditioner_status_payload, received_at=NOW, version=1)
    assert isinstance(status, UnknownStatus)

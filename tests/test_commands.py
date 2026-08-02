import pytest

from schideron import (
    Conditioner,
    ConditionerFanSpeed,
    ConditionerMode,
    Extension,
    Heating,
    InvalidCommandError,
    LightingChannel,
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


@pytest.fixture
def conditioner() -> Conditioner:
    return Conditioner(
        device_id=3,
        device_name=1,
        sync_type=2,
        pb=3,
        serial_port="USB3",
    )


@pytest.fixture
def heating() -> Heating:
    return Heating(
        device_id=17,
        device_name=1,
        sync_type=2,
        pb=17,
        serial_port="USB1",
    )


def test_conditioner_power_commands_copy_java_shape(conditioner: Conditioner) -> None:
    common = {
        "device_name": 1,
        "device_id": 3,
        "sync_type": 2,
        "ac_action": "onoff",
        "action": "acdirectcontrol",
        "definition": "airconPowerControl",
        "PB": 3,
        "interface": "USB3",
    }
    assert conditioner_off(conditioner) == {**common, "cmd": 1}
    assert conditioner_on(conditioner) == {**common, "cmd": 2}


def test_conditioner_temperature_and_mode_flag(conditioner: Conditioner) -> None:
    assert conditioner_temperature(conditioner, 25) == {
        "device_name": 1,
        "device_id": 3,
        "sync_type": 2,
        "cmd": 25,
        "ac_action": "setTemp",
        "action": "acdirectcontrol",
        "definition": "airconTempControl",
        "PB": 3,
        "interface": "USB3",
    }

    mode_coupled = Conditioner(device_id=3, pb=3, serial_port="USB3", mode_flag=True)
    command = conditioner_temperature(
        mode_coupled,
        25,
        current_mode=ConditionerMode.COOL,
    )
    assert command["mode"] == ConditionerMode.COOL


def test_conditioner_temperature_rejects_invalid_values(conditioner: Conditioner) -> None:
    with pytest.raises(InvalidCommandError):
        conditioner_temperature(conditioner, 16)
    with pytest.raises(InvalidCommandError):
        conditioner_temperature(
            Conditioner(device_id=1, mode_flag=True),
            25,
        )


def test_conditioner_mode_fan_and_extension(conditioner: Conditioner) -> None:
    assert conditioner_mode(conditioner, ConditionerMode.FAN) == {
        "device_name": 1,
        "device_id": 3,
        "sync_type": 2,
        "cmd": 3,
        "ac_action": "changeMode",
        "action": "acdirectcontrol",
        "definition": "airconModeControl",
        "PB": 3,
        "interface": "USB3",
    }
    assert conditioner_speed(conditioner, ConditionerFanSpeed.AUTO)["cmd"] == 4
    assert conditioner_extension(conditioner, Extension(7, "swing")) == {
        "device_name": 1,
        "device_id": 3,
        "sync_type": 2,
        "cmd": 7,
        "ac_action": "extensionCommand",
        "action": "acdirectcontrol",
        "definition": "airconExtensionControl",
        "PB": 3,
        "interface": "USB3",
    }


def test_heating_commands_copy_java_shape(heating: Heating) -> None:
    common = {
        "device_name": 1,
        "device_id": 17,
        "sync_type": 2,
        "action": "acdirectcontrol",
        "PB": 17,
        "interface": "USB1",
    }
    assert heating_off(heating) == {
        **common,
        "cmd": 1,
        "ac_action": "onoff",
        "definition": "heatingPowerControl",
    }
    assert heating_on(heating) == {
        **common,
        "cmd": 2,
        "ac_action": "onoff",
        "definition": "heatingPowerControl",
    }
    assert heating_temperature(heating, 24) == {
        **common,
        "cmd": 24,
        "ac_action": "setTemp",
        "definition": "heatingTempControl",
    }
    assert heating_extension(heating, Extension(3, "eco")) == {
        **common,
        "cmd": 3,
        "ac_action": "extensionCommand",
        "definition": "heatingExtensionControl",
    }


def test_heating_temperature_rejects_invalid_values(heating: Heating) -> None:
    with pytest.raises(InvalidCommandError):
        heating_temperature(heating, 4)
    with pytest.raises(InvalidCommandError):
        heating_temperature(heating, 36)


def test_lighting_commands_copy_java_shape() -> None:
    channel = LightingChannel(device_id=5, channel=6, sync_type=2)
    common = {
        "device_id": 5,
        "channel": 6,
        "sync_type": 2,
        "action": "directcontrol",
        "definition": "lightControl",
    }
    assert light_off(channel) == {**common, "cmd": "off"}
    assert light_on(channel) == {**common, "cmd": "on"}


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: Conditioner(device_id=0), "device_id"),
        (lambda: Conditioner(device_id=65536), "device_id"),
        (lambda: Conditioner(device_id=1, min_temperature=29, max_temperature=28), "min"),
        (lambda: Heating(device_id=0), "device_id"),
        (lambda: Heating(device_id=65536), "device_id"),
        (lambda: Heating(device_id=17, min_temperature=36, max_temperature=35), "min"),
        (lambda: LightingChannel(device_id=0, channel=0), "device_id"),
        (lambda: LightingChannel(device_id=1, channel=-1), "channel"),
        (lambda: Extension(-1), "extension_id"),
    ],
)
def test_models_reject_invalid_addresses(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()

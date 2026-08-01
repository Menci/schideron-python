from __future__ import annotations

from .constants import (
    ACTION_AC_DIRECT_CONTROL,
    ACTION_DIRECT_CONTROL,
    DEFINITION_CONDITIONER_EXTENSION,
    DEFINITION_CONDITIONER_FAN,
    DEFINITION_CONDITIONER_MODE,
    DEFINITION_CONDITIONER_POWER,
    DEFINITION_CONDITIONER_TEMP,
    DEFINITION_HEATING_EXTENSION,
    DEFINITION_HEATING_POWER,
    DEFINITION_HEATING_TEMP,
    DEFINITION_LIGHT,
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    HeatingPower,
    LightingCommand,
)
from .exceptions import InvalidCommandError
from .models import Conditioner, Extension, Heating, JsonObject, LightingChannel


def _hvac_command(
    device: Conditioner | Heating,
    command: int,
    ac_action: str,
    definition: str,
) -> JsonObject:
    payload: JsonObject = {
        "device_name": device.device_name,
        "device_id": device.device_id,
        "sync_type": device.sync_type,
        "cmd": command,
        "ac_action": ac_action,
        "action": ACTION_AC_DIRECT_CONTROL,
        "definition": definition,
        "PB": device.pb,
    }
    if device.serial_port:
        payload["interface"] = device.serial_port
    return payload


def conditioner_off(conditioner: Conditioner) -> JsonObject:
    return _hvac_command(
        conditioner,
        ConditionerPower.OFF,
        "onoff",
        DEFINITION_CONDITIONER_POWER,
    )


def conditioner_on(conditioner: Conditioner) -> JsonObject:
    return _hvac_command(
        conditioner,
        ConditionerPower.ON,
        "onoff",
        DEFINITION_CONDITIONER_POWER,
    )


def conditioner_mode(conditioner: Conditioner, mode: ConditionerMode) -> JsonObject:
    return _hvac_command(
        conditioner,
        mode,
        "changeMode",
        DEFINITION_CONDITIONER_MODE,
    )


def conditioner_speed(conditioner: Conditioner, speed: ConditionerFanSpeed) -> JsonObject:
    return _hvac_command(
        conditioner,
        speed,
        "setFanSpeed",
        DEFINITION_CONDITIONER_FAN,
    )


def conditioner_temperature(
    conditioner: Conditioner,
    temperature: int,
    *,
    current_mode: ConditionerMode | None = None,
) -> JsonObject:
    if not conditioner.min_temperature <= temperature <= conditioner.max_temperature:
        message = (
            f"temperature {temperature} is outside "
            f"{conditioner.min_temperature}..{conditioner.max_temperature}"
        )
        raise InvalidCommandError(message)
    payload = _hvac_command(
        conditioner,
        temperature,
        "setTemp",
        DEFINITION_CONDITIONER_TEMP,
    )
    if conditioner.mode_flag:
        if current_mode is None:
            raise InvalidCommandError("current mode is required when mode_flag is enabled")
        payload["mode"] = current_mode
    return payload


def conditioner_extension(conditioner: Conditioner, extension: Extension) -> JsonObject:
    return _hvac_command(
        conditioner,
        extension.extension_id,
        "extensionCommand",
        DEFINITION_CONDITIONER_EXTENSION,
    )


def heating_off(heating: Heating) -> JsonObject:
    return _hvac_command(
        heating,
        HeatingPower.OFF,
        "onoff",
        DEFINITION_HEATING_POWER,
    )


def heating_on(heating: Heating) -> JsonObject:
    return _hvac_command(
        heating,
        HeatingPower.ON,
        "onoff",
        DEFINITION_HEATING_POWER,
    )


def heating_temperature(heating: Heating, temperature: int) -> JsonObject:
    if not heating.min_temperature <= temperature <= heating.max_temperature:
        message = (
            f"temperature {temperature} is outside "
            f"{heating.min_temperature}..{heating.max_temperature}"
        )
        raise InvalidCommandError(message)
    return _hvac_command(
        heating,
        temperature,
        "setTemp",
        DEFINITION_HEATING_TEMP,
    )


def heating_extension(heating: Heating, extension: Extension) -> JsonObject:
    return _hvac_command(
        heating,
        extension.extension_id,
        "extensionCommand",
        DEFINITION_HEATING_EXTENSION,
    )


def lighting_command(channel: LightingChannel, command: LightingCommand) -> JsonObject:
    return {
        "device_id": channel.device_id,
        "channel": channel.channel,
        "cmd": command,
        "sync_type": channel.sync_type,
        "action": ACTION_DIRECT_CONTROL,
        "definition": DEFINITION_LIGHT,
    }


def light_off(channel: LightingChannel) -> JsonObject:
    return lighting_command(channel, LightingCommand.OFF)


def light_on(channel: LightingChannel) -> JsonObject:
    return lighting_command(channel, LightingCommand.ON)

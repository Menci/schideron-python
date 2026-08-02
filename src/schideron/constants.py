from enum import IntEnum, StrEnum

ACTION_AC_DIRECT_CONTROL = "acdirectcontrol"
ACTION_DIRECT_CONTROL = "directcontrol"

DEFINITION_CONDITIONER = "airconControl"
DEFINITION_CONDITIONER_FAN = "airconFanControl"
DEFINITION_CONDITIONER_MODE = "airconModeControl"
DEFINITION_CONDITIONER_POWER = "airconPowerControl"
DEFINITION_CONDITIONER_TEMP = "airconTempControl"
DEFINITION_CONDITIONER_EXTENSION = "airconExtensionControl"
DEFINITION_HEATING_POWER = "heatingPowerControl"
DEFINITION_HEATING_TEMP = "heatingTempControl"
DEFINITION_HEATING_EXTENSION = "heatingExtensionControl"
DEFINITION_LIGHT = "lightControl"

SEND_COMMAND = "sendCommand"
UPDATE_STATUS = "updateStatus"

DEFAULT_PORT = 3001
DEFAULT_SOCKETIO_PATH = "socket.io"
DISCOVERY_MESSAGE = b"discover node"
DISCOVERY_PORT = 33333


class ConditionerPower(IntEnum):
    OFF = 1
    ON = 2


class ConditionerMode(IntEnum):
    COOL = 1
    HEAT = 2
    FAN = 3
    DEHUMIDIFICATION = 4


class ConditionerFanSpeed(IntEnum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    AUTO = 4


class HeatingPower(IntEnum):
    OFF = 1
    ON = 2


class HeatingStatusSource(StrEnum):
    CACHED_SNAPSHOT = "cached_snapshot"
    TCP3RD = "tcp3rd"


class LightingCommand(StrEnum):
    OFF = "off"
    ON = "on"

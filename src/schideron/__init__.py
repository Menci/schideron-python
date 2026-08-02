from importlib.metadata import PackageNotFoundError, version

from .client import SchideronClient
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
    lighting_command,
)
from .constants import (
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    HeatingPower,
    HeatingStatusSource,
    LightingCommand,
)
from .discovery import discover_gateways, parse_discovery_response
from .exceptions import (
    CommandOutcomeUnknownError,
    CommandQueueFullError,
    CommandTimeoutError,
    ConnectionClosedError,
    InvalidCommandError,
    ProtocolError,
    SchideronError,
)
from .models import (
    Conditioner,
    ConditionerStatus,
    Extension,
    GatewayInfo,
    Heating,
    HeatingCommandResult,
    HeatingStatus,
    LightingChannel,
    LightingCommandResult,
    LightingStatus,
    RelayBankStatus,
    UnknownStatus,
)

try:
    __version__ = version("schideron")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "CommandOutcomeUnknownError",
    "CommandQueueFullError",
    "CommandTimeoutError",
    "Conditioner",
    "ConditionerFanSpeed",
    "ConditionerMode",
    "ConditionerPower",
    "ConditionerStatus",
    "ConnectionClosedError",
    "Extension",
    "GatewayInfo",
    "Heating",
    "HeatingCommandResult",
    "HeatingPower",
    "HeatingStatus",
    "HeatingStatusSource",
    "InvalidCommandError",
    "LightingChannel",
    "LightingCommand",
    "LightingCommandResult",
    "LightingStatus",
    "ProtocolError",
    "RelayBankStatus",
    "SchideronClient",
    "SchideronError",
    "UnknownStatus",
    "__version__",
    "conditioner_extension",
    "conditioner_mode",
    "conditioner_off",
    "conditioner_on",
    "conditioner_speed",
    "conditioner_temperature",
    "discover_gateways",
    "heating_extension",
    "heating_off",
    "heating_on",
    "heating_temperature",
    "light_off",
    "light_on",
    "lighting_command",
    "parse_discovery_response",
]

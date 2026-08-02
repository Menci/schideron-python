class SchideronError(Exception):
    pass


class ConnectionClosedError(SchideronError):
    """The gateway connection is not available."""


class CommandTimeoutError(SchideronError):
    """No matching status update arrived before the command deadline."""


class CommandOutcomeUnknownError(SchideronError):
    """The connection was lost after a command may have been transmitted."""


class CommandQueueFullError(SchideronError):
    """The bounded command queue cannot accept another operation."""


class ProtocolError(SchideronError):
    """A gateway message violates the known protocol shape."""


class InvalidCommandError(SchideronError, ValueError):
    """A command cannot be represented for the target device."""

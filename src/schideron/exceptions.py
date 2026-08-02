class SchideronError(Exception):
    pass


class ConnectionClosedError(SchideronError):
    pass


class CommandTimeoutError(SchideronError):
    pass


class CommandOutcomeUnknownError(SchideronError):
    pass


class CommandQueueFullError(SchideronError):
    pass


class ProtocolError(SchideronError):
    pass


class InvalidCommandError(SchideronError, ValueError):
    pass

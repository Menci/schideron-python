# Contributing

## Development environment

The project uses Python 3.12 or newer and uv:

```console
uv sync --all-groups
```

Run every local quality gate before submitting changes:

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=schideron --cov-report=term-missing
uv build
```

## Protocol changes

Keep the wire constants and numeric mappings aligned with the UControl APK and
gateway firmware. Add a sanitized fixture and a fake-gateway test for every
new message shape. Do not commit APKs, firmware images, credentials, gateway
UIDs, private addresses, or captures containing installation metadata.

The gateway protocol has no command transaction ID. New control methods must
serialize writes and define whether they return confirmed, unconfirmed, or
unknown outcome. A successful WebSocket write alone is never confirmation.

## Hardware validation

Hardware tests are opt-in and must not run as part of the normal test suite.
Record the complete initial state before writing, use bounded safe values, and
restore every changed field in a `finally` block. Relay writes require physical
observation when the installation does not publish relay status.


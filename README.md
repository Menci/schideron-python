# schideron

`schideron` is an unofficial async Python SDK for controlling Schideron
UControl gateways over the local network. It supports gateway discovery,
air conditioners, floor heating, relay commands, and status telemetry.

## Usage

Install the package:

```console
uv add schideron
```

Discover and connect to a gateway:

```python
import asyncio

from schideron import SchideronClient, discover_gateways


async def main() -> None:
    gateway = (await discover_gateways())[0]
    async with SchideronClient(gateway.host, port=gateway.port) as client:
        await client.wait_until_ready()
        print(client.conditioners)


asyncio.run(main())
```

See [the protocol reference](docs/protocol.md) for device support and command
confirmation semantics.

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict

from schideron import SchideronClient, discover_gateways


async def monitor(host: str | None) -> None:
    if host is None:
        gateways = await discover_gateways()
        if len(gateways) != 1:
            raise RuntimeError(f"expected one gateway, discovered {len(gateways)}")
        host = gateways[0].host

    async with SchideronClient(host) as client:
        client.subscribe(lambda status: print(asdict(status), flush=True))
        await client.wait_until_ready()
        await asyncio.Event().wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Schideron gateway status")
    parser.add_argument("--host", help="gateway hostname or IP; omit to use UDP discovery")
    arguments = parser.parse_args()
    asyncio.run(monitor(arguments.host))


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from schideron import (
    CommandOutcomeUnknownError,
    CommandQueueFullError,
    CommandTimeoutError,
    Conditioner,
    ConditionerFanSpeed,
    ConditionerMode,
    ConditionerPower,
    ConnectionClosedError,
    Heating,
    HeatingPower,
    LightingChannel,
    SchideronClient,
)
from schideron.models import DeviceStatus, JsonValue
from schideron.tcp3rd import TCP3rdFrame
from schideron.transport import LifecycleHandler, StatusHandler


class FakeTransport:
    def __init__(self) -> None:
        self.connected = False
        self.commands: asyncio.Queue[dict[str, JsonValue]] = asyncio.Queue()
        self.texts: asyncio.Queue[str] = asyncio.Queue()
        self.on_connect: LifecycleHandler | None = None
        self.on_disconnect: LifecycleHandler | None = None
        self.on_status: StatusHandler | None = None

    def set_handlers(
        self,
        *,
        on_connect: LifecycleHandler,
        on_disconnect: LifecycleHandler,
        on_status: StatusHandler,
    ) -> None:
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_status = on_status

    async def connect(self) -> None:
        self.connected = True
        assert self.on_connect is not None
        await self.on_connect()

    async def disconnect(self) -> None:
        self.connected = False
        assert self.on_disconnect is not None
        await self.on_disconnect()

    async def send_command(self, command: Mapping[str, JsonValue]) -> None:
        if not self.connected:
            raise ConnectionClosedError
        await self.commands.put(dict(command))

    async def send_text(self, payload: str) -> None:
        if not self.connected:
            raise ConnectionClosedError
        await self.texts.put(payload)

    async def publish(self, payload: object) -> None:
        assert self.on_status is not None
        await self.on_status(payload)


@pytest.fixture
def conditioner() -> Conditioner:
    return Conditioner(device_id=1, device_name=1, pb=1, serial_port="USB3")


@pytest.fixture
def heating() -> Heating:
    return Heating(device_id=101, device_name=7, pb=101, serial_port="MODBUS_A")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport: FakeTransport) -> SchideronClient:
    return SchideronClient(
        "unused",
        transport=transport,
        command_timeout=0.05,
        stale_after=30,
    )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"command_timeout": 0}, "command_timeout"),
        ({"stale_after": 0}, "stale_after"),
        ({"relay_stale_after": 0}, "relay_stale_after"),
        ({"max_pending_commands": 0}, "max_pending_commands"),
    ],
)
def test_client_constructor_validation(options: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SchideronClient("unused", **options)


async def test_connect_and_receive_status(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner_status_payload,
) -> None:
    await client.connect()
    await transport.publish([conditioner_status_payload])
    await client.wait_until_ready(timeout=0.1)
    status = next(iter(client.conditioners.values()))
    assert client.connected
    assert status.power is ConditionerPower.ON


async def test_get_pi_status_sends_apk_bare_frame_and_collects_burst(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner_status_payload,
) -> None:
    await client.connect()
    pending = asyncio.create_task(
        client.get_pi_status(
            "schideron_test-gateway",
            response_timeout=0.2,
            quiet_period=0.01,
        )
    )
    payload = await transport.texts.get()
    assert payload == '["getPiStatus","schideron_test-gateway",{"language":"en"}]'
    await transport.publish([conditioner_status_payload])
    statuses = await pending
    assert len(statuses) == 1
    assert statuses[0].version == 1


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"uid": "invalid"}, "uid"),
        ({"uid": "schideron_test", "language": ""}, "language"),
        ({"uid": "schideron_test", "response_timeout": 0}, "response_timeout"),
        ({"uid": "schideron_test", "quiet_period": 0}, "quiet_period"),
        (
            {"uid": "schideron_test", "response_timeout": 1, "quiet_period": 1},
            "quiet_period",
        ),
    ],
)
async def test_get_pi_status_validates_arguments(
    client: SchideronClient,
    options: dict[str, object],
    message: str,
) -> None:
    await client.connect()
    with pytest.raises(ValueError, match=message):
        await client.get_pi_status(**options)


async def test_conditioner_command_waits_for_fresh_confirmation(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    baseline = deepcopy(conditioner_status_payload)
    baseline["state"] = "1"
    await client.connect()
    await transport.publish([baseline])

    pending = asyncio.create_task(client.conditioner_on(conditioner))
    command = await transport.commands.get()
    assert command["cmd"] == 2
    assert not pending.done()

    await transport.publish([baseline])
    assert not pending.done()
    await transport.publish([conditioner_status_payload])
    status = await pending
    assert status.power is ConditionerPower.ON


async def test_conditioner_confirmation_does_not_block_lighting_transmission(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    baseline = deepcopy(conditioner_status_payload)
    baseline["state"] = "1"
    await client.connect()
    await transport.publish([baseline])

    conditioner_pending = asyncio.create_task(client.conditioner_on(conditioner))
    assert (await transport.commands.get())["cmd"] == 2

    lighting_pending = asyncio.create_task(client.lighting_on(LightingChannel(5, 0)))
    assert (await asyncio.wait_for(transport.commands.get(), timeout=0.01))["cmd"] == "on"
    assert not conditioner_pending.done()
    assert not (await lighting_pending).confirmed

    await transport.publish([conditioner_status_payload])
    assert (await conditioner_pending).power is ConditionerPower.ON


async def test_conditioner_command_is_idempotent(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    await client.connect()
    await transport.publish([conditioner_status_payload])
    status = await client.conditioner_on(conditioner)
    assert status.power is ConditionerPower.ON
    assert transport.commands.empty()


async def test_reconnect_requires_fresh_state_before_idempotent_success(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    await client.connect()
    await transport.publish([conditioner_status_payload])
    await transport.disconnect()
    await transport.connect()

    pending = asyncio.create_task(client.conditioner_on(conditioner))
    assert (await transport.commands.get())["cmd"] == 2
    await transport.publish([conditioner_status_payload])
    assert (await pending).power is ConditionerPower.ON


async def test_reconnect_requires_fresh_lighting_state_before_idempotent_success(
    client: SchideronClient,
    transport: FakeTransport,
) -> None:
    status = {
        "definition": "lightControl",
        "device_id": "5",
        "channel": "0",
        "status": "1",
    }
    await client.connect()
    await transport.publish([status])
    await transport.disconnect()
    await transport.connect()

    pending = asyncio.create_task(client.lighting_on(LightingChannel(5, 0)))
    assert (await transport.commands.get())["cmd"] == "on"
    assert not (await pending).confirmed


async def test_temperature_mode_and_fan_commands(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    await client.connect()
    await transport.publish([conditioner_status_payload])

    async def execute(call, field: str, value: str):
        pending = asyncio.create_task(call)
        await transport.commands.get()
        updated = deepcopy(conditioner_status_payload)
        updated[field] = value
        await transport.publish([updated])
        return await pending

    temperature = await execute(
        client.set_conditioner_temperature(conditioner, 26),
        "set_temperature",
        "260",
    )
    assert temperature.target_temperature == 26

    mode = await execute(
        client.set_conditioner_mode(conditioner, ConditionerMode.FAN),
        "mode",
        "3",
    )
    assert mode.mode is ConditionerMode.FAN

    fan = await execute(
        client.set_conditioner_fan_speed(conditioner, ConditionerFanSpeed.LOW),
        "fanspeed",
        "3",
    )
    assert fan.fan_speed is ConditionerFanSpeed.LOW


async def test_heating_commands_wait_for_fresh_confirmation(
    client: SchideronClient,
    transport: FakeTransport,
    heating: Heating,
    heating_status_payload,
) -> None:
    await client.connect()
    await transport.publish([heating_status_payload])
    status = next(iter(client.heatings.values()))
    assert status.power is HeatingPower.OFF

    power_pending = asyncio.create_task(client.heating_on(heating, confirm=True))
    assert (await transport.commands.get())["definition"] == "heatingPowerControl"
    powered = deepcopy(heating_status_payload)
    powered["state"] = "2"
    await transport.publish([powered])
    assert not power_pending.done()
    await client._on_relay_frame(TCP3rdFrame(101, bytes.fromhex("52000000000200000000000000")))
    assert (await power_pending).power is HeatingPower.ON

    temperature_pending = asyncio.create_task(
        client.set_heating_temperature(heating, 24, confirm=True)
    )
    command = await transport.commands.get()
    assert command["definition"] == "heatingTempControl"
    assert command["cmd"] == 24
    warmed = deepcopy(powered)
    warmed["set_temperature"] = "240"
    warmed["room_temperature"] = "231"
    await transport.publish([warmed])
    assert not temperature_pending.done()
    await client._on_relay_frame(TCP3rdFrame(101, bytes.fromhex("520000000002000000f000e700")))
    temperature = await temperature_pending
    assert temperature.target_temperature == 24
    assert temperature.status is not None
    assert temperature.status.current_temperature == 23.1


async def test_heating_returns_unconfirmed_receipt_by_default(
    client: SchideronClient,
    transport: FakeTransport,
    heating: Heating,
    heating_status_payload,
) -> None:
    await client.connect()
    await transport.publish([heating_status_payload])
    result = await client.heating_on(heating)
    assert not result.confirmed
    assert result.power is HeatingPower.ON
    assert result.target_temperature is None
    assert result.status is not None
    assert (await transport.commands.get())["definition"] == "heatingPowerControl"

    off_result = await client.heating_off(heating)
    assert not off_result.confirmed
    assert off_result.power is HeatingPower.OFF
    off_command = await transport.commands.get()
    assert off_command["definition"] == "heatingPowerControl"
    assert off_command["cmd"] == 1


async def test_command_timeout(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    baseline = deepcopy(conditioner_status_payload)
    baseline["state"] = "1"
    await client.connect()
    await transport.publish([baseline])
    with pytest.raises(CommandTimeoutError):
        await client.conditioner_on(conditioner)


async def test_disconnect_after_send_has_unknown_outcome(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    baseline = deepcopy(conditioner_status_payload)
    baseline["state"] = "1"
    await client.connect()
    await transport.publish([baseline])
    pending = asyncio.create_task(client.conditioner_on(conditioner))
    await transport.commands.get()
    await transport.disconnect()
    with pytest.raises(CommandOutcomeUnknownError):
        await pending


async def test_lighting_returns_unconfirmed_receipt(
    client: SchideronClient,
    transport: FakeTransport,
) -> None:
    await client.connect()
    channel = LightingChannel(5, 0)
    result = await client.lighting_on(channel)
    assert result.is_on
    assert not result.confirmed
    assert result.status is None
    assert (await transport.commands.get())["cmd"] == "on"


async def test_lighting_can_wait_for_confirmation(
    client: SchideronClient,
    transport: FakeTransport,
) -> None:
    await client.connect()
    channel = LightingChannel(5, 0)
    pending = asyncio.create_task(client.lighting_on(channel, confirm=True))
    await transport.commands.get()
    await transport.publish(
        [
            {
                "definition": "lightControl",
                "device_id": "5",
                "channel": "0",
                "status": "1",
            }
        ]
    )
    result = await pending
    assert result.confirmed
    assert result.status is not None


async def test_subscribers_receive_updates(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner_status_payload,
) -> None:
    received: list[DeviceStatus] = []

    async def callback(status: DeviceStatus) -> None:
        received.append(status)

    unsubscribe = client.subscribe(callback)
    await client.connect()
    await transport.publish([conditioner_status_payload])
    await asyncio.sleep(0)
    assert len(received) == 1
    unsubscribe()


async def test_staleness(
    client: SchideronClient,
    transport: FakeTransport,
    conditioner_status_payload,
) -> None:
    await client.connect()
    await transport.publish([conditioner_status_payload])
    status = next(iter(client.conditioners.values()))
    assert not client.is_stale(status, now=status.received_at + timedelta(seconds=29))
    assert client.is_stale(status, now=status.received_at + timedelta(seconds=31))
    assert client.is_available(status, now=status.received_at + timedelta(seconds=29))
    assert not client.is_available(status, now=status.received_at + timedelta(seconds=31))


async def test_command_queue_is_bounded(
    transport: FakeTransport,
    conditioner: Conditioner,
    conditioner_status_payload,
) -> None:
    client = SchideronClient(
        "unused",
        transport=transport,
        command_timeout=1,
        max_pending_commands=1,
    )
    baseline = deepcopy(conditioner_status_payload)
    baseline["state"] = "1"
    await client.connect()
    await transport.publish([baseline])
    pending = asyncio.create_task(client.conditioner_on(conditioner))
    await transport.commands.get()
    with pytest.raises(CommandQueueFullError):
        await client.send_command({"definition": "test"})
    await transport.publish([conditioner_status_payload])
    await pending


async def test_commands_require_connection(
    client: SchideronClient,
    conditioner: Conditioner,
) -> None:
    with pytest.raises(ConnectionClosedError):
        await client.conditioner_on(conditioner)


def test_context_timestamp_is_utc() -> None:
    assert datetime.now(UTC).utcoffset() == timedelta(0)

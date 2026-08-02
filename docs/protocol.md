# Schideron UControl local protocol

This reference records behavior verified against gateway firmware V2.91 and the
UControl Android APK.

“S-Net” has a narrower, official meaning than the local gateway API:
Schideron's [SDR-RL-C08/10 product page](https://www.schideron.com/en/products/62.html)
calls S-Net the dedicated bus and protocol used by that relay family. UControl
WebSocket messages and TCP3rd frames are gateway-facing protocols and are not
themselves identified as S-Net.

## Layers and ports

```text
Application / SDK
  -> UDP 33333: gateway discovery
  -> TCP 3001: UControl WebSocket commands and cached snapshots
  -> TCP 7776: TCP3rd binary status bridge and targeted reads
  -> smart-core interface queues
  -> installation transports: S-Net, Modbus RTU, RS-485, and others
```

## UDP discovery

Send ASCII `discover node` to UDP port 33333. A verified response is:

```text
<host>:<port>_schideron_<gateway-uuid>
```

The complete UID is required by `getPiStatus`.

## Port 3001 WebSocket

```text
ws://<gateway>:3001/socket.io/?transport=websocket&EIO=4
```

Observed packets:

- `0{...}`: Engine.IO open metadata and heartbeat timings;
- `40["connect",{}]`: vendor connection packet;
- client `2`, gateway `3`: heartbeat;
- `42["event",payload]`: event packet;
- `1`: close.

The `40` array payload is rejected by conforming modern Socket.IO clients. The
SDK therefore delegates RFC 6455 to aiohttp and implements the observed
Engine.IO-shaped envelope itself.

### Cached snapshot

The snapshot request is bare WebSocket text, without the `42` prefix:

```json
["getPiStatus","schideron_<gateway-uuid>",{"language":"en"}]
```

It makes firmware serialize saved state; it does not read the downstream bus.
Responses are a short burst of `42["updateStatus", ...]` events with no
terminator, so the SDK completes a snapshot after a bounded quiet period.

### Commands

Commands use this envelope:

```text
42["sendCommand",{...}]
```

There is no generic downstream acknowledgement. The gateway can echo a
`sendCommand` object, but the APK treats that echo as optimistic UI input and
handles authoritative device state through a separate status event.

## Conditioner protocol

Conditioner operations:

| Operation | `ac_action` | `definition` | `cmd` |
| --- | --- | --- | --- |
| power off/on | `onoff` | `airconPowerControl` | `1` / `2` |
| temperature | `setTemp` | `airconTempControl` | integer Celsius |
| mode | `changeMode` | `airconModeControl` | `1..4` |
| fan | `setFanSpeed` | `airconFanControl` | `1..4` |
| extension | `extensionCommand` | `airconExtensionControl` | configured ID |

Modes are cool `1`, heat `2`, fan `3`, and dehumidification `4`. Fan values are
high `1`, medium `2`, low `3`, and automatic `4`. Conditioner state uses off
`1` and on `2`; temperatures are tenths of a degree in status messages.

## Floor-heating protocol

The verified device reports the following sanitized shape. IDs and interface
names are synthetic while preserving field relationships:

```json
{
  "definition": "airconControl",
  "product_model": "HaiLin-FloorHeating-MODBUS-RTU",
  "brand": "海林自控",
  "device_id": "101",
  "device_name": "7",
  "state": "1",
  "set_temperature": "0",
  "room_temperature": "0",
  "PB": "101",
  "interface": "MODBUS_A"
}
```

The shared `airconControl` definition is insufficient for classification. The
SDK normalizes `product_model` and recognizes the `FloorHeating` marker before
trying conditioner enums. Placeholder mode and fan values are zero and are not
floor-heating capabilities.

Native floor-heating state and commands follow the APK's `Heating` and
`UHeating` definitions:

- state `1` is off and `2` is on;
- set and room temperatures are tenths of a degree in status;
- zero temperature is unavailable;
- the default target range is 5–35°C;
- command target temperatures are integer Celsius.

Power command:

```json
{
  "device_name": 7,
  "device_id": 101,
  "sync_type": 2,
  "cmd": 2,
  "ac_action": "onoff",
  "action": "acdirectcontrol",
  "definition": "heatingPowerControl",
  "PB": 101,
  "interface": "MODBUS_A"
}
```

Temperature replaces `cmd` with the integer target, uses `setTemp`, and uses
definition `heatingTempControl`. Extensions use `extensionCommand` and
`heatingExtensionControl`.

Firmware routes the logical `device_id` as `ctlrid` and `device_name` as the
port/Modbus address. The typed heating record is therefore the APK command
target. This proves the gateway routing path but does not prove that the
installed downstream controller accepts or executes a command.

Associated `CHVAC-THC-01` panel records on a separate interface reported state
values that did not match their PB-linked HVAC devices. These values cannot be
treated as physical device state, and an equal PB does not make a panel record
a wire-level alias.

The heating device currently appears only in saved snapshots as off with zero
temperatures. Passive 3001 and 7776 captures and targeted TCP3rd reads produced
no heating or associated-panel response. The SDK marks snapshot-derived
heating status as `cached_snapshot`; it is useful for discovery and routing
only. A TCP3rd `0x52` frame for the heating device is the only currently
modelled authoritative heating source.
Heating writes return unconfirmed receipts by default, and cached snapshots
cannot satisfy strict confirmation or clear an optimistic UI value.

## Relay protocol

Relay command example:

```json
{
  "device_id": 301,
  "channel": 2,
  "cmd": "on",
  "sync_type": 2,
  "action": "directcontrol",
  "definition": "lightControl"
}
```

## Command scheduling inside the gateway

The WebSocket parser turns a request into an internal command, appends it to a
request buffer, and queues the physical interface worker. The parse path has no
sleep or gateway power cooldown.

The interface worker queue is unbounded FIFO: it has no deduplication,
replacement, priority, or cancellation. RS-485 workers also apply the
configured `sndcmd_interval` around a physical write. Queue backlog and this
spacing lie between WebSocket receipt and the downstream transaction. The
verified runtime interval is unavailable, and no downstream result is returned
to the WebSocket client.

Applications should debounce rapid controls and reconcile only their latest
intent. Sending every intermediate UI value and an extra status request after
each one increases the same FIFO backlog.

## Port 7776 TCP3rd

Connect and send the unprefixed handshake:

```text
55 aa 00 00 02 80 01 0d 0a
```

The gateway acknowledges:

```text
55 aa 00 00 02 80 02 0d 0a
```

Server frames have no outer length prefix:

```text
55 aa | device_id:u16be | payload_len:u8 | payload | 0d 0a
```

The stream can split or concatenate frames. Invalid data is resynchronized at
the next `55 aa` header after length and CRLF validation.

### Targeted HVAC read

The only identified targeted read uses a four-byte little-endian outer length,
a little-endian request device ID, and payload `52 64 00`:

```text
frame = 55 aa | device_id:u16le | 03 | 52 64 00 | 0d 0a
wire  = frame_length:u32le | frame
```

Firmware translates it to `ctlrid=N&logic=get_status`. It shares the downstream
interface FIFO, so it is not an immediate status acknowledgement. One live
conditioner response took about 4.5 seconds; other captures landed on the
ordinary periodic cadence. The heating device and associated panel did not
respond.

HVAC response payloads are 13 bytes and begin with opcode `0x52`:

| Offset | Meaning |
| --- | --- |
| `0` | opcode `0x52` |
| `5` | power |
| `6` | mode, when supported |
| `7` | fan, when supported |
| `8` | temperature type |
| `9..10` | target temperature, `u16le` tenths |
| `11..12` | room temperature, `u16le` tenths |

The SDK decodes a `0x52` frame as heating when a typed heating record with the
same device ID exists; otherwise it uses conditioner semantics.

### Raw relay bank

Observed relay-like payloads are:

```text
92 | mask:u8 | reserved:u8
```

The verified installation emits relay-controller frames periodically.
Controlled OFF/ON operations did not alter the reported mask, so these frames
expose a stale controller cache. The SDK preserves the bytes and generation as
`RelayBankStatus`; it does not create `LightingStatus` or confirm commands.

Stale cache is not an S-Net hardware limitation. Official relay documentation
says every channel uploads status, and the APK subscribes to live lighting
updates. MarsWindow calls bus-wide relay auto-communication enable/disable
frames, but their exact bytes remain in an unavailable vendor `protocol.dll`.

## Reliability rules

- Keep the persistent 3001 status connection separate from command connections.
- Keep TCP3rd connected so any `0x52` response can be consumed immediately.
- Serialize physical writes and coalesce obsolete UI intent before transmission.
- Confirm conditioner changes only from newer matching telemetry.
- Confirm floor heating only from a matching TCP3rd frame; cached snapshots are
  discovery data.
- Treat floor-heating and relay writes as unconfirmed when no live status source
  exists.
- Treat targeted reads as queued work, not acknowledgements.
- Limit relay entities to explicit installation mappings.
- Do not scan unknown writable device or extension IDs.

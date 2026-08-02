# Compatibility

## Verified environment

| Property | Result |
| --- | --- |
| Gateway firmware | V2.91 |
| Vendor application | UControl Android APK |
| Discovery | UDP 33333 |
| Command and cached snapshot | TCP 3001 WebSocket |
| Binary status bridge | TCP 7776 TCP3rd |
| Relay family downstream protocol | S-Net |
| Conditioner and floor-heating transport | Modbus RTU |
| Heartbeat | client `2`, gateway `3` |
| Authentication | none observed locally |
| TLS | unavailable |

S-Net is the official dedicated bus/protocol name for the SDR-RL-C08/10 relay
family. It does not name the UControl WebSocket or TCP3rd protocol exposed by the
gateway.

## Conditioner verification

Live round-trips cover power, whole-degree target temperature, cool/fan modes,
and low/automatic fan speed on device 1. Each test restored the complete
initial state. Heat and dehumidification depend on the downstream equipment's
capabilities.

The gateway publishes physical conditioner status on an observed roughly
10.6-second cycle. TCP3rd targeted reads and `0x52` decoding are verified, with
one live response at about 4.5 seconds. A targeted read is queued on the same
physical interface, is not an acknowledgement, and has not consistently beaten
the periodic cycle.

The SDK serializes only connection setup and wire transmission; it releases the
global write lock before telemetry confirmation. One slow conditioner therefore
does not block relay or other HVAC transmissions. Applications must still
coalesce rapid UI input because every transmitted intermediate value and status
read remains in the gateway's unbounded physical-interface FIFO.

## Floor-heating verification

The cached snapshot contains one typed floor-heating device:

| Property | Value |
| --- | --- |
| Device ID | 17 |
| Device name / Modbus address | 1 |
| PB | 17 |
| Interface | USB1 |
| Product model | `HaiLin-FloorHeating-MODBUS-RTU` |
| Brand | 海林自控 |
| Cached power | off (`1`), not authoritative |
| Cached target/current temperature | unavailable (`0`) |

APK and firmware analysis verify the gateway command schema, integer target
temperature, state `1/2`, tenths-degree status, and a 5–35°C default range. The
physical execution of device 17 power and temperature writes has not been
verified. No live device 17 status appeared in passive 3001/TCP3rd captures or
targeted TCP3rd reads, so the default SDK result is explicitly unconfirmed and
strict confirmation accepts only a matching TCP3rd frame.

Four `CHVAC-THC-01` records at logical IDs 20–23 are Com2 panel nodes. Node 20
shares PB 17, but its cached state changed between `2` and `1` with zero
temperatures. Nodes 21–23 reported state `0` while PB-linked conditioners 1–3
were on. These panel rows are not valid telemetry proxies for their PB-linked
devices, and Com2 node 20 does not proxy USB1 device 17.

## Relay verification

Ten configured channels across relay device IDs 5 and 6 were physically
verified for command execution. Port 3001 command transmission is reliable and
fast on the tested LAN.

TCP3rd emits opcode `0x92` banks for IDs 5 and 6, but controlled OFF/ON tests
left their masks unchanged. Those frames are retained only as raw diagnostic
data. Current relay state, channel count, names, and rooms must not be inferred
from them.

Official relay documentation and the APK both support live channel feedback, so
the stale bank is installation integration or configuration behavior. The exact
S-Net auto-communication enable/disable frames remain unavailable.

## Unverified variants

- firmware other than V2.91;
- floor-heating models without `FloorHeating` in `product_model`;
- installations with live floor-heating status confirmation;
- gateways with working S-Net relay feedback;
- alternative TCP3rd opcodes or longer relay masks;
- authenticated or TLS-enabled gateways;
- cloud control;
- extensions, dimmers, RGB lights, curtains, and other UControl device families.

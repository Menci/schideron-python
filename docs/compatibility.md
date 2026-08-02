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

The identifiers below are synthetic while preserving the observed field
relationships. The cached snapshot contains one typed floor-heating device:

| Property | Value |
| --- | --- |
| Device ID | 101 |
| Device name / Modbus address | 7 |
| PB | 101 |
| Interface | `MODBUS_A` |
| Product model | `HaiLin-FloorHeating-MODBUS-RTU` |
| Brand | 海林自控 |
| Cached power | off (`1`), not authoritative |
| Cached target/current temperature | unavailable (`0`) |

APK and firmware analysis verify the gateway command schema, integer target
temperature, state `1/2`, tenths-degree status, and a 5–35°C default range. The
physical execution of floor-heating power and temperature writes has not been
verified. No live heating status appeared in passive 3001/TCP3rd captures or
targeted TCP3rd reads, so the default SDK result is explicitly unconfirmed and
strict confirmation accepts only a matching TCP3rd frame.

Associated `CHVAC-THC-01` panel records on a separate interface reported state
values that did not match their PB-linked HVAC devices. These panel rows are
not valid telemetry proxies for the linked devices, and an equal PB does not
make a panel record a wire-level alias.

## Relay verification

Multiple configured relay channels were physically verified for command
execution. Port 3001 command transmission is reliable and fast on the tested
LAN.

TCP3rd emits opcode `0x92` banks for the relay controllers, but controlled
OFF/ON tests left their masks unchanged. Those frames are retained only as raw
diagnostic data. Current relay state, channel count, names, and rooms must not
be inferred from them.

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

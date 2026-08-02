# Changelog

All notable changes are documented here.

## Unreleased

- Added UDP gateway and UID discovery.
- Added the legacy Engine.IO-shaped port 3001 transport, active heartbeat,
  reconnect, and APK-compatible cached `getPiStatus` snapshots.
- Added conditioner power, temperature, mode, fan, and extension commands with
  newer-telemetry confirmation.
- Added typed floor-heating discovery, state, exact APK command payloads,
  unconfirmed receipts, optional strict confirmation, and TCP3rd decoding.
- Distinguished cached floor-heating discovery snapshots from authoritative
  TCP3rd telemetry so stale cache cannot confirm commands or overwrite
  optimistic state.
- Added fresh HVAC command connections and best-effort TCP3rd targeted status
  reads after confirmed writes.
- Limited the global command lock to connection setup and wire transmission so
  slow telemetry confirmation no longer blocks unrelated commands.
- Added TCP3rd handshake, framing, resynchronization, reconnect, conditioner
  `0x52` decoding, and raw relay-bank preservation.
- Added unconfirmed relay command receipts; `0x92` banks are not authoritative
  relay state because live commands did not change them.
- Added pushed subscriptions, independent connection health, stale-state
  tracking, bounded in-flight commands, strict typing, and protocol fault tests.

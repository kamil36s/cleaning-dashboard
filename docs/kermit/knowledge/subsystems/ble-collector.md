# BLE collector

## Identity and verification

- Stable ID: `ble-collector`; separate `scripts/scan_ble.py` process, reviewed 2026-10-02 at revision `67931c3`.
- Its source still embeds fixed local device MAC addresses and a location-specific sensor ID. It remains **excluded** from Kermit's positive admission; this reviewed pack, `PROJECT_MAP.md`, safe launcher metadata and synthetic tests describe its contract. Kermit never runs or controls it.

## Lifecycle and outputs

`start-dev.cmd` launches `node scripts/dev-service.js scale` in the normal local dashboard startup. `dev-service.js` maps that name to the Python collector and supervises its streams; it does not automatically restart a stopped scale process. The collector itself uses Bleak scanning: zero `--seconds` means continuous operation in 65-second scanner sessions; a nonzero duration runs one session. Session start/scan failure waits five seconds then the continuous loop retries; stop failures also wait five seconds. Cancellation propagates. This retry loop does not guarantee adapter recovery, packets, or fresh cache. The server and Sensors UI do not start it. Kermit service is independent.

When BLE reconnect fails, the collector logs the scanner exception, waits five seconds, and retries another session in continuous mode. Existing latest snapshots can remain stale while no valid advertisement arrives.

For the scale address, the callback appends **raw BLE advertisement evidence** (device/address, RSSI, service/manufacturer payload hex) to private `data/scale/scale_raw.jsonl`. It decodes supported scale service payloads, accepts stable realistic weight only, and applies a 15-second save cooldown. Accepted normalized measurements are appended to `data/scale/scale_measurements.csv` and `.jsonl`; `data/scale/latest.json` and `signal.json` are replaceable snapshots. Raw evidence is not canonical normalized weight history. The `/api/weight/*` readers belong to `server.py` and use these stored roles; see `weight-steps.md`.

For the environmental address, the callback parses unencrypted BTHome v2 payloads. Missing temperature/humidity or a duplicate consecutive payload is ignored. A valid normalized reading replaces `data/sensor/latest.json`; history appends at most once per monotonic minute to `data/sensor/readings.jsonl`. `temp_c` is Celsius to 0.01, `hum_pct` percent to 0.01, optional battery fields are percent/millivolts, and timestamp is server-local naive ISO. The latest snapshot includes device/signal metadata; history uses normalized field names `temperature_c` and `humidity_percent`. The environmental raw payload is held in memory for deduplication, not persisted as a separate raw sensor archive by this path. Server `/api/sensor/*` reads these files; the page/widget only render them.

Tests in `tests/test_scan_ble.py` cover packet decode, invalid/duplicate sensor frames, stable weight acceptance and fake writes; they do not prove recovery on real radio hardware. Collector output and raw evidence may contain private device IDs and health/environment readings. All `data/scale/*`, `data/sensor/*`, raw packets, logs and backups are excluded from static admission. A scan failure may leave a stale latest file; missing packets are unknown, not zero. See BC4-01 in `GAPS_AND_CONFLICTS.md`.

| Admitted source | Checked marker |
| --- | --- |
| `scripts/dev-service.js` | `scale: { label: 'SCALE'` |

# Sensors

## Identity and verification

- Stable ID: `sensors`; `sensors.html`, dashboard `data-widget="sensors"`, and GET `/api/sensor/latest` and `/api/sensor/history`. Reviewed 2026-10-02 at revision `67931c3`.
- Kermit has no live temperature or humidity reader. The Sensors page and widget display data; neither starts the BLE collector.

## Storage roles and source flow

`scripts/scan_ble.py` separately receives environmental BLE advertisements and decodes valid unencrypted BTHome v2 temperature/humidity payloads. It rejects absent/invalid fields and identical consecutive payloads. A successful normalized reading contains server-local naive `timestamp`, local sensor ID, temperature Celsius, humidity percent, optional battery percentage/millivolts, and signal/source metadata. `handle_sensor_reading` atomically replaces `data/sensor/latest.json` for **every accepted reading** and appends normalized `data/sensor/readings.jsonl` at most once per monotonic minute. JSONL is the retained **canonical sensor history**; latest is a replaceable **snapshot/cache**, not complete history. Raw advertisement bytes are input evidence, not normalized measurements and not a Sensors store. Unlike scale packets, environmental raw bytes are not separately appended by this collector.

`server.py::read_sensor_latest` returns `{ok:false}` when latest is absent/corrupt and otherwise returns the snapshot plus `age_seconds` calculated at read time. `read_sensor_history` reads JSONL, skips malformed rows/timestamps, and selects a server-local rolling hour window (default 24, minimum 0.1), exact local calendar day or local month. Missing history yields `[]`; file errors also yield `[]`, so an empty response alone cannot prove a measured zero or no past readings. Sensor writes are collector-owned; these API routes only read.

`js/sensors-page.js` fetches latest and selected history every minute and on controls, with `cache:'no-store'`; the browser selects local day/month boundaries. It normalizes timestamps/numeric fields, merges a latest point for the selected range if its timestamp is absent from history, plots temperature/humidity and computes min/mean/max from finite points. It displays Celsius to one decimal, Fahrenheit as `C × 9/5 + 32`, humidity rounded to whole percent, sample count, battery and last reading. It marks latest `LIVE` through 150 seconds, stale afterward, or no signal if age is missing. This rendering merge is not a write to history. `js/widget-sensors.js` polls latest every 30 seconds and history initially/every fifth tick; it marks no signal/stale similarly and renders a 24-hour sparkline. A failed latest request marks no signal; unavailable history leaves chart data absent. A cached latest value may outlive collection, and the displayed range may use a point that has not yet been appended to JSONL.

Collector timestamps are server-local without offset. Server history filtering uses naive server-local datetimes; the browser parses them using its own local timezone. Browser date selection and server-local filtering may differ when hosts/zones differ, and DST transitions have no explicit disambiguation. `age_seconds` and UI freshness are observations of a cache timestamp, not a guarantee of live BLE connectivity. Tests: `tests/test_sensor_api.py`, `tests/sensors-page.test.js`, `tests/widget-sensors.test.js`, `tests/test_scan_ble.py` use temporary files/fakes.

## Privacy and checked references

`data/sensor/readings.jsonl`, `data/sensor/latest.json`, raw advertisements, logs and backups are private runtime material and excluded. The collector source embeds device addresses and remains excluded. The page/widget have a fixed local sensor/location label; they were reviewed for display behavior but conservatively excluded from static admission. This pack and shared `server.py` supply bounded metadata. See SE4-01 and SE4-02 in `GAPS_AND_CONFLICTS.md`.

| Admitted source | Checked marker |
| --- | --- |
| `server.py` | `def read_sensor_latest` |
| `server.py` | `def read_sensor_history` |

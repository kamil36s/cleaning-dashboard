# COLMI ring

## Identity and verification

- Stable ID: `ring`; `ring.html`, `js/ring-app.js`, `js/ring-api.js`, and central `/api/ring/*`. Reviewed 2026-10-03 against B5 source.
- Kermit has no authorized reader for the current ring, measurements, diagnostics or paired device identity.

## Ownership and flow

`js/ring-api.js` calls central state, capabilities, diagnostics, history, scan, connect, disconnect, sync and presence routes. `js/ring-app.js` renders connect/status, latest readings, history, charts and diagnostic states. `server.py` delegates to `RingCollector`, `RingPhoneBridge` and `RingStore`; UI polling does not itself own BLE collection. Phone bridge POST `/api/ring/phone/status` and `/ingest` use the central API's token/origin boundary and bounded request bodies.

`ring_collector.py::RingCollector` owns BLE discovery, selected-device reconnect, scheduled history sync and live collection while the central API runs. Its supervisor backs off from 5 to 300 seconds on missing device or failures. When the phone bridge reports active collection, direct BLE is suspended to avoid competing collectors. Partial dataset errors are logged by sync rather than being silently converted into full success. `ring_protocol.py` parses device packets; `ring_wear.py::RingWearDetector` gates questionable off-wrist measurements. `ring_phone_bridge.py::RingPhoneBridge` validates timestamps, ranges and batches before writing normalized observations.

`ring_store.py::RingStore` owns WAL-mode `data/ring.sqlite`: device selection and metadata, sync status, packet/event diagnostics, heart rate, smartwatch reference, SpO2, activity, HRV and sleep. `history` and `overview` are reads of that store; `heart_rate_archive` is a bounded source for the separate history page. Device packet captures and phone uploads are source evidence; normalized tables are application state. The ring is a fallback for heart-rate-history minutes occupied by no watch sample, while Sleep has separate per-night watch/ring selection. Ring pages do not make medical diagnoses.

## Recovery, privacy and evidence

The selected device survives central API restarts in SQLite, but the BLE connection does not; the collector supervisor reconnects when available. Missing hardware, Bluetooth permission, stale readings or partial protocol support can leave a blank or incomplete view. No static pack proves a real device is connected. Private ring SQLite, mock database, packet dumps, logs and user measurement exports are excluded. Focused tests: `tests/test_ring.py`, `tests/test_health_connect_history.py`, `tests/heart-rate-history.test.js`.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `ring_collector.py` | `async def _supervisor` |
| `ring_store.py` | `def heart_rate_archive` |
| `ring_phone_bridge.py` | `def ingest` |
| `js/ring-api.js` | `export const ringApi` |

# Heart-rate history

## Identity and verification

- Stable ID: `heart-rate-history`; `heart-rate-history.html`, `js/heart-rate-history.js`, central GET `/api/live-workout/heart-rate-history`, and runtime SSE. Reviewed 2026-10-03 against B5 source.
- This is a static description. Kermit cannot read the user's heart-rate history, current BPM or device state.

## Sources and precedence

`live_workout_store.py::archive_heart_rates` appends accepted smartwatch transmissions to the independent `heart_rate_telemetry` table in `data/live-workout.sqlite`; both legacy port-8000 and runtime port-8766 ingest reach this archive. It persists independently of workout lifecycle and cancellation. `ring_store.py::heart_rate_archive` reads selected-ring measurements and Health Connect smartwatch-reference records from `data/ring.sqlite`. `server.py::merge_heart_rate_archive_sources` merges these at read time: archive smartwatch samples occupy their minute; a valid Health Connect watch reference fills an unoccupied minute; a valid ring sample fills only a minute with no watch source. Ring BPM is accepted in 30–220, watch reference in 30–240. The central endpoint clamps requested result limit to 1–100000 and returns `samples` plus per-source counts. Runtime `:8766` has a smartwatch-only history endpoint, so using it alone omits ring fallback.

`js/heart-rate-history.js` selects a browser-local day window and fetches the merged central archive while loading workout history/session windows directly from the runtime. It subscribes to runtime SSE for live telemetry, periodically reconciles with persisted archive, replaces matching transient samples and reapplies smartwatch-per-minute precedence. `filterUnwornHeartRateSamples` and chart analysis remove suspected off-wrist/flatline segments from presentation; they do not delete the canonical archive. The page groups ring-only phases, shows daily/workout summaries and caps raw table display at 1000 rows. If workout-state loading fails, the page retains daily data without workout windows; if the central archive fails, the history load shows an error while an existing SSE view may continue.

## Boundaries and evidence

UTC epoch timestamps are stored/queried; `localDayRange` uses the browser's local day for selection. A minute-priority merge can hide simultaneous ring samples even if the devices disagree. Presentation filtering can make visible counts differ from stored counts. Neither a missing sample nor a disconnected stream means zero BPM. `data/live-workout.sqlite`, `data/ring.sqlite`, Health Connect snapshots and all raw user measurements stay outside Kermit's static index. Relevant tests: `tests/test_health_connect_history.py`, `tests/test_training_runtime.py`, `tests/heart-rate-history.test.js`.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `live_workout_store.py` | `def heart_rate_history` |
| `ring_store.py` | `def heart_rate_archive` |
| `js/heart-rate-history.js` | `export function applySmartwatchPriority` |
| `server.py` | `def merge_heart_rate_archive_sources` |

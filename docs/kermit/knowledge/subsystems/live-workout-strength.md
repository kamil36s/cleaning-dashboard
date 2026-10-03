# Live Workout and Strength

## Identity and verification

- Stable ID: `live-workout-strength`; `live-workout.html`, dashboard `data-widget="live-workout"`, independent `/api/live-workout/*` runtime and central `/api/strength/*`. Reviewed 2026-10-03 against B5 source.
- Kermit describes static contracts. It has no authorized reader for an active session, personal training history, heart-rate samples, plans, or strength records.

## Ownership and flow

`index.html::data-widget="live-workout"` loads `js/widget-live-workout.js` through the dashboard loader; `live-workout.html` uses `js/live-workout-page.js`. `js/live-workout-runtime-api.js::liveWorkoutRuntimeBase` resolves a direct port-8766 URL (with browser override `liveWorkout.runtimeBase.v1`). Current workout surfaces read the plan, session, latest telemetry, history and SSE there. Browser `localStorage` session, plan and profile values are UI mirrors/preferences, not the active-session authority. `docs/training-runtime.md` describes the operational boundary.

`training_runtime.py::TrainingRuntime` and `TrainingHandler` own session start/control/checkpoint/finish/cancel, telemetry, SSE and history. `live_workout_store.py::LiveWorkoutStore` owns WAL-mode `data/live-workout.sqlite`: one active session, clock anchors, samples, progress checkpoints, strength-in-progress summary, sensor events, journey commits and an outbox for virtual-walk step delivery. The clock is reconstructed from persisted anchors after runtime restart. Idempotent request IDs avoid duplicate starts; repeated finish returns the finished session. Accepted telemetry is separately archived in `heart_rate_telemetry`, including outside a workout; cancelling removes session-specific samples, not that archive. The central `server.py` still exposes legacy live-workout handlers for older clients, but current browser lifecycle requests use the runtime.

`strength_store.py::StrengthStore` owns separate canonical `data/strength.sqlite` and the central `/api/strength/*` dashboard, exercises, history, equipment, settings, sessions, sets and recovery routes. `js/strength-api.js` is the browser adapter. A completed set needs reps or duration, a known exercise and matching technique variant. Set ID retries return the existing result. Warmup or rejected-technique sets do not earn quality-set credit; records are comparable only for the same exercise, technique and load identity, and pain-stop sets are excluded. The weekly scoreboard counts quality sets within its week window, computes `toMinimum=max(0, minimum-count)`, `toTarget=max(0,target-count)` and caps progress at `1.25`. Recovery flags use recent 24/48-hour quality sets, near-failure RIR and reported soreness; these are app guidance, not medical conclusions.

## Recovery, privacy and evidence

The browser rehydrates `GET /api/live-workout/session` on load/reconnect. SSE loss causes reconnect and persisted latest-sample reads. A central API/Vite outage leaves runtime clock and telemetry running; a runtime outage stops ingestion until restart, then accepted SQLite state is recovered. Virtual-walk step events remain in the durable outbox until central delivery succeeds. Direct telemetry ingest can use a configured token for LAN devices; origin/local-client checks belong to `training_runtime.py::TrainingHandler._authorize`. See `docs/training-runtime.md` and `tests/test_training_runtime.py::test_session_survives_dashboard_restarts_reconnect_and_runtime_recovery`.

Excluded: personal `data/live-workout.sqlite`, `data/strength.sqlite`, plan JSON/settings, raw sensor data, postcards and runtime logs. Focused implementation tests are `tests/test_training_runtime.py`, `tests/test_live_workout.py`, `tests/test_strength_store.py`; browser behavior is covered by matching Live Workout and Strength tests. The pack does not certify device telemetry availability or a current workout.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `training_runtime.py` | `class TrainingRuntime` |
| `live_workout_store.py` | `def start_dashboard_session` |
| `strength_store.py` | `def save_set` |
| `js/live-workout-runtime-api.js` | `function liveWorkoutRuntimeBase` |

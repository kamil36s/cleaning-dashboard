# Independent Training Runtime

## Ownership boundary

`training_runtime.py` is the operational owner of every active Live Workout session. It runs as a separate local process on port `8766`; `server.py` and Vite may stop or restart without stopping it. The browser uses `js/live-workout-runtime-api.js` to call the runtime directly for session lifecycle, plan/history reads, latest telemetry and SSE.

The canonical store remains `data/live-workout.sqlite`. No historical workout migration or destructive rewrite is performed. The runtime enables SQLite WAL, foreign keys, a 10-second busy timeout and normal synchronous mode. Existing `/api/live-workout/*` handlers in `server.py` remain temporarily for compatibility with older clients, but current workout UIs do not use them for live lifecycle ownership.

## Durable live state

The runtime persists:

- one stable `dashboard-…` session ID from start through finish;
- status, start/transition anchors and runtime-derived elapsed time;
- HR samples and aggregate HR/zone values on every accepted telemetry post;
- cardio progress, calories, interval progress, virtual-walk values and cadence through browser checkpoints approximately every two seconds;
- the full in-progress strength state plus its compact summary;
- a durable outbox event for virtual-walk steps, retried against the dashboard API after dashboard outages.
- Santiago journey distance in the same SQLite database, with one unique commit per finalized indoor-cycling or virtual-walk session.
- CSC measurement and connection-state events plus two-second distance checkpoints in `live_workout_sensor_samples`. They are available at `GET /api/live-workout/history/<session-id>/sensors` for diagnosing lost Magene signals and distance freezes.

The journey endpoint is `GET /api/live-workout/journey/santiago`. Its static route/checkpoint architecture, distance model, idempotency transaction, validation, regeneration, and development reset procedure are documented in `docs/santiago-journey.md`.

`localStorage` remains a fast UI mirror, not the authority. A page load/reopen calls `GET /api/live-workout/session`; SSE reconnect also triggers rehydration. The runtime serves the last accepted telemetry from SQLite after its own restart. Duplicate starts with the same `request_id` return the same session, concurrent starts are serialized, and duplicate finish requests return the already-finished session.

## Process lifecycle

- `./start-training-runtime.ps1` starts only the independent runtime (hidden process) and waits for its health endpoint.
- `./start-dashboard.ps1` starts only the ordinary dashboard stack. It never stops the runtime.
- `./start-all.ps1` starts/ensures the runtime, then starts the dashboard.
- `start-dev.cmd` uses the safe default: it ensures the runtime is already running, then freely replaces/restarts only dashboard, network, scale and Vite processes. Its shutdown cleanup deliberately does not match or stop `training_runtime.py` or port `8766`.

Equivalent npm commands are `npm run training:runtime`, `npm run dashboard:only`, and `npm run dashboard:all`.

To expose telemetry ingest to a watch on the LAN, set `TRAINING_RUNTIME_HOST=0.0.0.0`, configure `DASHBOARD_LIVE_WORKOUT_TOKEN`, restart the runtime, and point the watch/sender at:

`http://<PC-LAN-IP>:8766/api/live-workout/telemetry`

The legacy watch URL on port `8000` remains supported and writes to the same SQLite store, so existing live-HR senders continue to feed the active workout. Port `8766` is preferred because it keeps accepting BPM while the central dashboard API is restarting or unavailable. Do not configure one watch to send the same sample to both ports.

Every accepted smartwatch transmission is also written to the independent `heart_rate_telemetry` archive used by the HR History page. This archive is separate from `live_workout_samples`: pausing, finishing or cancelling a workout does not remove its archived HR transmissions. Cancelling removes the workout and its session-specific samples only. The central history endpoint continues to merge this smartwatch archive with the COLMI fallback; both the legacy `:8000` ingest and the runtime `:8766` ingest write into the same smartwatch archive.

Local simulation uses:

`python scripts/simulate_live_workout.py`

## Magene CSC and fullscreen

Magene cadence/speed sensors are connected by the browser through Web Bluetooth; they are independent of smartwatch HR ingest and the runtime process. The picker allows all nearby Bluetooth devices because some Magene models do not advertise the CSC service until after GATT connection. Wake the sensor by rotating the crank or wheel, then select the Magene device. Service access is still restricted to the standard CSC service (`0x1816`).

A sensor is remembered only after the CSC service, measurement characteristic and notifications have all connected. Cancelling the picker, selecting a non-CSC device, a timeout, or a failed initial handshake returns the UI to `disconnected` and does not start an endless reconnect loop. Automatic reconnect is reserved for a sensor that had connected successfully and was subsequently lost. Sensor state never disables the fullscreen control; fullscreen can be entered after a failed or cancelled sensor attempt.

Reconnect uses the browser's `getDevices()` permission list for the same page origin, then retries a lost GATT connection with bounded backoff. A different origin, revoked permission, or a browser without `getDevices()` requires selecting the sensor again with **POŁĄCZ CSC**; `requestDevice()` cannot open its picker automatically. The Focus HUD has a collapsible **Diagnostyka połączenia Magene CSC** log with the latest 30 connection events and errors. **WYBIERZ PONOWNIE** during retry opens the picker in one click. The sensor also checks for a lost GATT connection when the page becomes visible or the inactivity timer expires, in case the browser misses the disconnect event.

## Failure behavior

- Dashboard/Vite restart or outage: runtime clock, ingest, SQLite writes and SSE service continue.
- Browser refresh/navigation: the same active session is queried and rehydrated; no new start is issued.
- SSE loss: browser reconnects automatically, polls the persisted latest sample, then rehydrates session state.
- Runtime crash: accepted samples/checkpoints survive. On restart the unfinished session remains active and the clock is reconstructed from its persisted anchor. Samples cannot be collected while the runtime process itself is down.
- Dashboard unavailable when a virtual walk finishes: its step event stays pending in the SQLite outbox and is retried after port `8000` returns.

## Development rule

Unrelated dashboard work may restart `server.py` and Vite. Do not attach `training_runtime.py` to the central API supervisor, do not add port `8766` to ordinary dashboard cleanup, and do not move active-session authority back into browser-only state or `server.py`. Changes to `training_runtime.py`, `live_workout_store.py`, the runtime API adapter, or the runtime startup script should not be deployed during a real active session unless the runtime itself is intentionally restarted.

# Kraków → Santiago Journey

## CORE JOURNEY — COMPLETE

Live Workout has a compact, persistent Journey panel driven by the same `distance_km` stored with the workout. It displays committed plus current-ride distance, total progress, the last checkpoint, the next physical checkpoint with country context, distance to that checkpoint, and a progress bar.

Checkpoint crossings use brief, non-blocking notifications and queue when several are crossed in one update. Reaching Santiago produces a simple 100% completed state. Finishing indoor cycling commits distance exactly once in SQLite; refresh only restores preview distance.

The 365-row checkpoint table is hidden during normal use and is available only with `?journeyDebug=1`. Existing standalone QA and maintenance tooling remain available without appearing in the workout UI.

## ROUTE/DATA — FROZEN

Accepted production state:

```text
365 checkpoint identities
361 main-route checkpoints
4 variant checkpoints
route distance: 4294.18 km
start: Kraków
finish: Santiago de Compostela
```

The accepted production assets are `data/journeys/santiago/checkpoints.json`, `data/journeys/santiago/route.geojson`, and `data/journeys/santiago/route-meta.json`. Checkpoint ordering, route geometry, route distance, variant handling, geocoding, and the authoritative source dataset are frozen unless a reproducible runtime bug requires a correction.

## Architecture

- Dataset: `data/journeys/santiago/checkpoints-source.json` (365 authoritative identities with stable `id` / `originalIndex`) and generated runtime-ordered `checkpoints.json`.
- Order review: `data/journeys/santiago/checkpoint-order-review.json` and `docs/santiago-checkpoint-order-review.md`.
- Route: `data/journeys/santiago/route.geojson` plus `route-meta.json`; browser copies live in `public/data/journeys/santiago/`.
- Journey engines: `santiago_journey.py` and `js/santiago-journey.js`.
- Distance source: `js/live-workout-distance.js`.
- Persistence/idempotency: journey tables and finish transaction in `live_workout_store.py`.
- Runtime API: `training_runtime.py`, `/api/live-workout/journey/santiago`.
- Live UI/crossing detection: `js/widget-live-workout.js` and `styles.css`.
- Image handling: optional cached `imageUrl` metadata in generated checkpoints; missing images never block workout/journey logic.

Existing route-audit scripts, caches, validation reports, and QA pages remain maintenance infrastructure. They are not part of normal Live Workout use.

## Current limitations

- Cadence-only distance is a documented virtual model (`0.004 km/revolution`), not wheel odometry.
- Missing checkpoint images do not affect journey or workout operation.
- Journey commits currently apply to finalized dashboard indoor-cycling sessions; historical/imported sessions are not retroactively added.

## OPTIONAL FUTURE ENHANCEMENTS

These ideas are optional and are not required for the completed core journey:

- Cached, attributed checkpoint photos where already available.
- A Journey Journal.
- An optional interactive route map.
- Optional compact/full presentation modes and further accessibility polish.
- Optional country milestones or other gamification.

No additional Santiago engineering work is the automatic next task.

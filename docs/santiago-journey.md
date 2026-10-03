# Kraków → Santiago journey

## Runtime architecture

The authoritative set of 365 checkpoint identities is stored at `data/journeys/santiago/checkpoints-source.json`. Every identity has a stable `id` and `originalIndex` preserving the supplied 1–365 order. The generated runtime dataset is `data/journeys/santiago/checkpoints.json`; its `index` / `journeyIndex` follows the accepted geographic order in `checkpoint-order-review.json` and it adds coordinates, route distance, association metadata, the snapped route vertex, and route offset. The static bicycle line is `route.geojson`, with precomputed per-vertex cumulative kilometers in `route-meta.json`. Compact runtime assets are mirrored under `public/data/journeys/santiago/` for Vite/build delivery.

`scripts/enrich_santiago_checkpoints.py` performs the build-time pipeline:

```text
365 authoritative identities with stable id and originalIndex
→ Wikipedia/Nominatim coordinate enrichment with a local cache
→ reviewed runtime order and alternative-branch associations
→ BRouter trekking route (OSRM bicycle fallback), cached in route-parts/
→ 25 m route simplification
→ main-route checkpoint snapping and variant association
→ routeDistanceKm and cumulative route metadata
```

No geocoding or routing request runs in the dashboard. `geocode-cache.json` and `route-parts/` make regeneration repeatable. Technical aliases disambiguate labels without renaming checkpoint identities. Failures leave an explicit non-zero script exit.

Regenerate from existing caches without network access:

```powershell
python scripts/enrich_santiago_checkpoints.py --offline
```

Run a fresh/updated network enrichment by omitting `--offline`. Generate or inspect the order proposal first with `python scripts/review_santiago_checkpoint_order.py`.

## Source order, journey order, and variants

The September 2026 order audit accepted five strong-confidence corrections: the Rhine valley near Balzers, the mixed Bidache/Orthez approaches, the mixed Route Napoléon/Valcarlos approaches, the Via Trajana branch at Calzadilla de los Hermanillos, and the reversed local order on the Samos branch. The route changed from **4,409.19 km** to **4,294.18 km**.

Orthez, Sauveterre-de-Béarn, Valcarlos, and Calzadilla de los Hermanillos remain among the 365 identities as `variantCheckpoint: true`. Each shares the route distance of an explicit nearby main-route association. It remains visible in debug data and can be marked reached when that distance is crossed, but it is excluded from physical geometry and from previous/next main-destination lookup. Main-route checkpoint distances remain strictly increasing; the complete journey order is non-decreasing because a variant may share its association distance.

## Journey calculation

`santiago_journey.py` is the server-side route/checkpoint engine. `js/santiago-journey.js` is the browser equivalent used by the Live Workout panel. Both use binary search over precomputed cumulative route distance. Position is linearly interpolated between the two surrounding geographic vertices and clamped to the route endpoints. Checkpoint lookup and multi-checkpoint crossing detection also use sorted cumulative distance.

The browser loads route assets once and reuses the in-memory engine; it does not parse GeoJSON on every render. If the journey API or assets fail, the panel shows `Podróż niedostępna` and the workout continues normally.

## Live Workout distance

`js/live-workout-distance.js` is the single distance source for workout storage and journey movement. A positive fresh CSC/telemetry speed measurement wins. When positive RPM arrives alongside a conflicting `0 km/h` field, cadence wins so the zero field cannot freeze a moving ride. The `cadence_virtual_distance_v1` model uses `0.004 km` per crank revolution (80 RPM = 19.2 km/h). When the watch supplies fresh BPM but no speed or cadence, `heart_rate_virtual_distance_v1` provides an explicit fallback: below 50% HRmax it records 0 km/h, at 50% HRmax it starts at 8 km/h, and it scales linearly to 30 km/h at HRmax. An explicit 0 RPM with no positive speed still wins over BPM and records no movement. `distance_km` is included in the same two-second runtime checkpoint, local refresh mirror, session history record, and finish request.

A CSC sensor that stops sending measurements remains stale even after its display changes to 0 RPM, so fresh BPM can take over distance calculation. Virtual Walk uses its credited steps at 0.75 m per step for Santiago distance; only steps earned in the walk's target HR zone count. The walk's live distance is previewed and committed by the same session mechanism as cycling.

The current session remains preview-only:

```text
live journey = committed journey + active session distance_km
```

Refresh restores the active `distance_km` from the runtime/local mirror but never commits it.

## Persistence and idempotency

The existing `data/live-workout.sqlite` owns both tables:

- `journey_progress`: journey/route ID, committed distance, update timestamp;
- `journey_session_commits`: one row per journey/session, protected by primary key `(journey_id, session_id)`.

`LiveWorkoutStore.control_dashboard_session()` finishes an indoor-cycling or virtual-walk workout and inserts its journey commit in the same `BEGIN IMMEDIATE` SQLite transaction. Only a newly inserted session key increments progress. Duplicate finish delivery returns the completed session and cannot add distance twice.

`GET http://127.0.0.1:8766/api/live-workout/journey/santiago` returns persistent progress, active preview distance, interpolated position, and adjacent checkpoints. Add `?checkpoints=1` for the complete debug list.

## Journey page and postcards

The `Podróż` tab in `live-workout.html` renders route statistics, an interactive Leaflet/OpenStreetMap map from the local GeoJSON, and all 365 postcard slots. Every checkpoint name and route distance remains visible as the travel plan. Before its route distance is reached, the locked card deliberately contains no postcard image or image URL; only the artwork is the surprise.

Postcard images are private runtime files under `data/journeys/santiago/postcards/` and are not committed to Git. `journey_postcards.py` accepts JPEG, PNG, and WebP images up to 12 MB, validates their signatures, and keeps an atomic manifest. The runtime exposes listing, upload, and image endpoints under `/api/live-workout/journey/postcards`. Images may be prepared for any checkpoint in advance, but locked cards render only sealed-state metadata: no image element or image URL is inserted into the page until the checkpoint is reached. Re-uploading replaces the existing image for that checkpoint.

When the live distance crosses a checkpoint that has an uploaded image, the Focus HUD shows the postcard for 10 seconds. A checkpoint without an image keeps the compact checkpoint notification.

## Validation

Run:

```powershell
python scripts/validate_santiago_dataset.py
npm run test:run -- tests/santiago-journey.test.js
npm run test:run -- tests/live-workout-journey-page.test.js
python -m unittest tests.test_santiago_journey tests.test_journey_postcards
```

The validator treats identity count, unique stable IDs, original/runtime indexes, main-route monotonicity, variant associations, coordinates, excessive main-route offset, and endpoint mismatch as errors. Missing images and unusual/tiny gaps are warnings.

## Route geometry QA

The route is audited as 360 main-route checkpoint-to-checkpoint legs; four variants do not create physical legs:

```powershell
python scripts/audit_santiago_route.py
python scripts/verify_santiago_route_tags.py
python scripts/audit_santiago_route.py
```

The first command writes `data/journeys/santiago/route-qa.json`, its public map copy, and
`docs/santiago-route-qa.md`. The optional network verification re-queries only legs flagged for
ratio, length, intersection, fallback, backtracking, corridor deviation, or border-detour concerns
and caches road/ferry tag summaries in `route-road-tags.json`. The final audit merges those results.

Open `santiago-route-qa.html` through the Vite development server to inspect the route, numbered
checkpoints, and flagged legs. This page is developer tooling and is not loaded by Live Workout.

The September 2026 audit corrected checkpoint #84's technical coordinate without altering its name,
index, or sequence. The original Wikipedia municipality point was on the ski slope south of St. Anton;
the replacement uses the official town-hall location and keeps the bicycle line on the paved Arlberg
road corridor. Only cached route part `070-093.geojson` was regenerated. Details and exact before/after
leg distances are preserved in `route-corrections.json` and `docs/santiago-route-qa.md`.

The later order audit is documented separately in `docs/santiago-checkpoint-order-review.md`. The full proposal,
including every baseline retrace decision and all old/new neighbors, is in `checkpoint-order-review.json`.

Committed progress is stored as kilometres, not a percentage or checkpoint index. Rebuilding the route does not
rewrite `committed_distance_km`; only its resulting percentage, interpolated position, and future milestones change.

## Development reset

There is deliberately no production reset button. Stop the training runtime, back up `data/live-workout.sqlite`, then use SQLite explicitly:

```sql
BEGIN IMMEDIATE;
DELETE FROM journey_session_commits WHERE journey_id = 'krakow-santiago';
UPDATE journey_progress
SET committed_distance_km = 0, updated_at = unixepoch('subsec') * 1000
WHERE journey_id = 'krakow-santiago';
COMMIT;
```

Restart the training runtime afterward. Resetting does not delete workout history.

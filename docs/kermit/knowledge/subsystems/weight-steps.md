# Weight and steps

## Identity and verification

- Stable ID: `weight-steps`; current `data-widget="weight-cut"` implementation, reviewed 2026-10-01 on dirty `main`. L0: `PROJECT_MAP.md` Weight/steps widget, telemetry API and storage rows.
- This is implementation knowledge. Kermit has no scale, step, Health Connect, or other private runtime reader and cannot report a person's measurements.

## Purpose and boundaries

The dashboard displays scale history, weight statistics and goals alongside daily steps. `server.py` owns the local API and normalization; `scripts/scan_ble.py` collects scale advertisements; the Android steps-sync companion uploads Health Connect snapshots and automatic steps. Diet reads weight/steps as context but does not own them. Sleep reads Health Connect sleep snapshots but does not ingest them. There is no generic Kermit health tool.

## Frontend and API

| Surface or route | Current owner and behavior |
| --- | --- |
| `index.html` `data-widget="weight-cut"` | `js/widget-weight-cut.js` loads combined `/api/weight/dashboard-summary`, additional weight/steps routes, live latest/signal and Health Connect latest, and renders charts and browser-only goals. It polls latest weight every 2.5 s and steps every 60 s. |
| GET `/api/weight/latest`, `/signal`, `/history`, `/events`, `/stats`, `/dashboard-summary` | `server.py::Handler.do_GET` calls `read_latest_weight_measurement`, `read_scale_signal`, `read_weight_history`, `read_weight_events`, `read_weight_stats`, and `read_weight_dashboard_summary`. The combined response is a read model, not another store. |
| POST `/api/weight/events/delete` | `delete_weight_event` removes a selected normalized event and rewrites affected history/cache files. Kermit cannot call it. |
| GET `/api/steps/history`, `/events`, `/exclusions`, `/stream` | `read_steps_history` supplies calendar-day rows; `read_steps_events` returns stored events; exclusions identify dashboard-started Live Workout intervals; stream broadcasts changes. |
| POST `/api/steps/events/upsert`, `/delete` | `upsert_steps_event` and `delete_steps_event` edit `steps.json`, preserving automatic/virtual components when deleting manual steps. |
| GET `/api/health-connect/latest`, `/history`; POST `/api/health-connect/snapshot` | `read_health_latest` returns the replaceable latest snapshot; `read_health_sleep_history` selects sleep snapshots from history; `write_health_snapshot` appends upload history and replaces latest. None writes normalized scale history. |

`js/widget-weight-cut.js` stores tile/goal/MA target presentation choices under `weightCut.tiles.v1`, `weightCut.goals.v1`, and `weightCut.maTarget.v1`; these are not measured weight history. The card is registered by the dashboard loader and may be hidden by dashboard settings. Failed API reads leave unavailable/previous display state rather than proving zero measurements.

## Persistence and source of truth

| Artifact | Role and owner |
| --- | --- |
| `data/scale/scale_measurements.jsonl` | **Canonical normalized scale history** appended by `scripts/scan_ble.py::handle_measurement`; stable, realistic measurements only. `scale_measurements.csv` is a parallel normalized legacy/fallback history used when JSONL is absent or empty in selected readers. Both remain private. |
| `data/scale/scale_raw.jsonl` | **Raw BLE advertisement evidence**, before stable/realistic filtering. Raw packet bytes are not normalized measurements. |
| `data/scale/latest.json`, `signal.json` | **Cache/latest snapshots**, replaced by the collector; `signal.json` can reflect signal without a valid new weight. `read_latest_weight_measurement` can fall back to normalized history if latest is idle/invalid. Neither file is complete canonical history. |
| `data/scale/steps.json` | **Canonical local step-day state**: manual and automatic candidate counts, `normal_mode`, automatic capture/exclusion metadata, and virtual walk sessions. A missing day is different from a recorded zero. |
| `data/health-connect/snapshots.jsonl`, `latest.json` | **Private external ingest history and replaceable latest cache** from Android snapshots. This is Health Connect payload history, not scale history or proof of current device sync. |
| Browser `weightCut.*` keys | **Presentation targets/preferences and local fallback state**. Default goal/starting values are hardcoded in the widget and do not turn into canonical measurements. |
| Derived API stats, chart series and report TXT | **Read-time metrics/presentation output**, not persisted measurement authority. `js/daily-report.js` labels filled weight and missing step days. |

Backups/imports are private recovery or source evidence; none is Kermit-admitted. No scale or Health Connect row has been read for this review.

## Data flow and calculations

1. `scripts/scan_ble.py` decodes Mi Scale service payloads, keeps raw advertisement evidence separately, and appends normalized CSV/JSONL only for stable, realistic weight after a save cooldown. It replaces latest/signal snapshots. Server validation accepts 30–300 kg; invalid/idle latest readings fall back to the latest valid history event. `tests/test_scan_ble.py` and `tests/test_weight_validation.py` cover the boundary.
2. `server.py::parse_weight_history_row` retains valid timestamp/weight and sets `day` from the first ten timestamp characters. `read_weight_events` sorts newest first and deduplicates on timestamp, weight rounded to 0.001 kg, type and raw hex. `read_weight_history` averages all valid readings per day and rounds API daily means to 0.01 kg. With `fill=1`, internal gaps are linearly interpolated; outside gaps carry the nearest known value, with `filled=true`, `count=0`, null timestamps. Missing history with no anchor stays absent.
3. `read_weight_stats` uses actual normalized events. Daily points average same-day readings; 7/14/30-day moving averages average **observed daily points within the window**, not seven guaranteed dates. Seven/30-day changes use exact daily mean or interpolation only when both neighboring measured days exist; missing endpoints yield null. Weekly rate is change/days × 7; status is down below -0.2 kg/week, up above +0.2, otherwise stable. Output weights/changes/rates are rounded to 0.01 kg. The hardcoded 2026-05-01 comparison is a current widget-specific metric, not a universal start date.
4. `js/weight-ma-stats.js::calculateMa7Stats` implements a **separate browser MA7**: daily means, linear interpolation between first and last observed day, then seven consecutive daily values. It returns null until a full window exists. It compares current MA7 to yesterday, seven and fourteen days earlier; `dailyDeficitKcal = -(MA7 - MA7 seven days ago) × 7500 / 7`, `distanceToGoalKg = current MA7 - browser goal`, and forecast extrapolates the last 14-day MA7 slope only when negative. These are estimates, not stored observations (`tests/weight-ma-stats.test.js`).
5. `server.py::compose_steps_event` chooses either manual or Health Connect automatic normal steps according to `normal_mode`, then **adds** virtual-walk session steps. It never sums manual and automatic normal candidates. `upsert_steps_event` defaults to manual mode when existing manual steps are positive; automatic updates during active dashboard workouts or without required exclusion coverage are ignored. `read_steps_history` fills absent days with `steps=0` and `filled=true`; consumers must preserve that flag rather than call missing telemetry a measured zero.
6. `js/widget-weight-cut.js` calculates walking energy for display as `round(steps × 0.00075 km/step × weightKg × 0.53 kcal/kg/km)` with a hardcoded fallback weight if needed. Daily/weekly step charts are browser summaries; weekly period averages use nonfilled positive day rows, so missing/zero days do not form equal evidence. `js/daily-report.js` emits “no data” for filled step rows.

## Date, source precedence and failure

Collector timestamps use server-local `datetime.now().isoformat()` without UTC offset; weight grouping slices that timestamp, while the widget's `todayIso()` uses browser-local calendar dates. Step keys are ISO calendar dates from client input or Android `LocalDate` in the device's system zone. `read_steps_history` defaults its end to server-local `date.today()`. Live Workout exclusion intervals use configurable `DASHBOARD_TIMEZONE`/`TZ`, default Europe/Warsaw. Android Health Connect snapshots carry device-zone day and window, while `write_health_snapshot` stamps server-local naive `received_at`; freshness is not implied by a cached latest file. These scoped clocks can disagree at midnight or across zones.

Automatic step updates preserve manual candidates, but counted normal mode determines precedence; virtual walks remain an additive, separately identified source. Duplicate raw advertisements are filtered before normal history; server event deduplication is an additional read rule. CSV fallback can diverge from JSONL after legacy edits; no automatic reconciliation is established. No Health Connect snapshot writes `scale_measurements.jsonl`.

## Jobs, privacy and evidence

BLE collection and Android WorkManager are external processes. The server does not autonomously restart them. Kermit admits only reviewed static metadata. `scripts/scan_ble.py` contains fixed device addresses, and `js/widget-weight-cut.js`/`js/weight-ma-stats.js` contain hardcoded personal weight/goal literals, so those sources were reviewed for contract only and **excluded** from positive admission. `data/scale/*`, `data/health-connect/*`, backups, logs, raw advertisements and user exports are excluded. Shared admitted `server.py` is route metadata only; it grants no runtime access.

Focused evidence: `tests/test_weight_validation.py`, `tests/test_scan_ble.py`, `tests/weight-ma-stats.test.js`, `tests/test_health_connect_history.py`, and `tests/test_server_startup.py::StepsSourceAggregationTests`. The latter verifies idempotent virtual sessions, manual/automatic precedence, deletion, and workout exclusion with temporary step files; it is reviewed but not separately admitted because it also spans unrelated domains. Gaps: W4-01 to W4-03 in `GAPS_AND_CONFLICTS.md`.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `server.py` | `def compose_steps_event` |
| `server.py` | `def read_weight_stats` |
| `js/daily-report.js` | `export async function generateCombinedDailyReport` |

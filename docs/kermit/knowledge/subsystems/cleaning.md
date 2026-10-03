# Cleaning

## Identity and verification

- Stable subsystem ID: `cleaning`; display: Cleaning; domain: household tasks.
- Status: **verified current implementation**, reviewed 2026-09-30 against the dirty working tree on `main`. L0: `PROJECT_MAP.md` pages, widgets, backend, and persistence.
- Scope includes `cleaning.html`, dashboard `index.html::data-widget="cleaning"`, and `/api/cleaning/*`. It does not make Kermit a task editor.

## Purpose and boundaries

Cleaning owns apartment-specific recurring tasks, completion actions, undo/history, and cleaning settings. The Python `CleaningStore` is authoritative for task and action state. The page and card call the API through `js/cleaning-api.js`; `js/cleaning-dependencies.js` adds browser presentation dependencies. A pending shopping Todo for a mop can mark matching Cleaning tasks `blocked` in the frontend; it does not alter canonical Cleaning rows. Dashboard loader/order/visibility, phone-cleaning goal refresh, and cross-feature weekly insights are separate owners. A user can mutate Cleaning through its application UI; Kermit only explains the static implementation.

## Frontend

| Surface | Entry/identifier | Controller, store, API client | Loading, empty, error, review/stale behavior |
| --- | --- | --- | --- |
| Full page | `cleaning.html` | `js/main.js`, `js/render.js`, `js/cleaning-history.js`, `js/cleaning-api.js` | Fetches selected apartment and task/history data; API errors are surfaced by the request wrapper. |
| Dashboard card | `index.html::data-widget="cleaning"` | `js/widget-cleaning.js`, `js/cleaning-api.js` | Lazy-loaded by `js/dashboard-widget-loader.js`; the card is a second presentation of the same store. |

- User actions: create/update/soft-delete tasks; mark done; undo or soft-delete an action; edit settings. `js/cleaning-api.js` sends the corresponding POST/PATCH/DELETE calls. Read operations use GET.
- Browser-only state: `cleaning.action-history.v1` mirrors recent actions; `cleaning.forecastRampStart.v1:<apartment>` anchors the forecast ramp; `cleaningDashboard.dailyGoalTarget.v2` snapshots the widget target and `cleaningDashboard.dailyUnlock.v1` tracks manual unlock. These are presentation/forecast state, not the canonical task ledger. Old `data/settings/cleaning*.json` files are migration/recovery material, not the active store.
- Compact/hidden behavior: the card participates in dashboard visibility and lazy loading; no page or widget identifier is sent to Kermit.

## Backend and API

| Method + route | Handler and service | Request/response owner; validation/limits | Read or mutation |
| --- | --- | --- | --- |
| GET `/api/cleaning/state`, `/api/cleaning/tasks`, `/api/cleaning/history`, `/api/cleaning/settings` | `server.py` GET handlers -> `CleaningStore` | Apartment query is required for state/tasks/history; store validates apartment, filters and history range/offset. | Read |
| POST `/api/cleaning/tasks`, `/api/cleaning/tasks/{id}/done`, `/api/cleaning/history/undo`, `/api/cleaning/settings` | `server.py` POST handlers -> `CleaningStore` | JSON bodies; store validates task/apartment/source and settings. | Mutation |
| PATCH `/api/cleaning/tasks/{id}` | `server.py` PATCH handler -> `CleaningStore.update_task` | Task field validation and bounded body. | Mutation |
| DELETE `/api/cleaning/tasks/{id}`, `/api/cleaning/history/actions/{id}` | `server.py` DELETE handlers -> `CleaningStore` | Soft deletion or action reversal, with task history reconciliation. | Mutation |

The API service does not use a generic ORM. `CleaningError` carries status/code to the HTTP handler. `js/cleaning-api.js::requestJson` rejects non-OK and `ok:false` responses. Cleaning has no external provider in its normal runtime path. The optional cleaning AI tips action belongs to a separate bounded UI/proxy path and does not define store facts.

`server.py::authorize_api_request` is the central origin gate: mutation methods call it with `require_origin=True`; a local client, allowed/host Origin or Referer, or a valid dashboard bearer token on the listed Cleaning write routes can satisfy it. Cleaning GET routes do not require Origin. This application authorization is not available to Kermit.

## Persistence and source of truth

| Artifact/entity | Owner | Role | Schema/migration/version and retention |
| --- | --- | --- | --- |
| `data/cleaning.sqlite`: `apartments`, `tasks`, `cleaning_actions`, `cleaning_settings` | `CleaningStore._initialize` | **Canonical** task/settings/action state | SQLite WAL; task soft-delete uses `is_active`; action reversal uses `reverted_at`; apartment/legacy-row uniqueness and action indexes are defined in code. |
| Old Cleaning JSON and Google rows | import scripts / migration path | **Migration input / legacy** | Not read as the active task ledger. |
| Browser-derived task dependencies and UI state | frontend modules | **Cache / browser-only presentation** | Recomputed or replaced from API reads; not an authoritative completion history. |

No separate generated canonical state, raw runtime archive, or backup is part of the reviewed interactive flow. Backups, if present, are recovery copies and excluded from Kermit admission.

## Data flow

1. A page/card GET identifies an apartment; `CleaningStore._require_apartment` validates it and `get_tasks` reads only active tasks, with optional room/category/status/due/supply filters.
2. `_task_payload` transforms stored `last_done` and positive `freq` into Warsaw-calendar days since completion, next due days, overdue flag, and status. Missing completion is overdue.
3. `mark_done` validates source and active task, inserts a `cleaning_actions` row with previous `last_done`, then updates the task in one write transaction. Invalid/inactive tasks are rejected; there is no silent completion.
4. `revert_last_action` allows only the latest non-reverted action for a task and restores previous `last_done`. `remove_action` marks an action reverted and recomputes `last_done` when it removed the latest action.
5. `get_history` excludes reverted actions and groups remaining actions into Warsaw date buckets. The dashboard/page render the resulting task and KPI snapshots.
6. `js/cleaning-api.js::getTasks` applies `js/cleaning-dependencies.js::resolveCleaningDependencies` after the API response. A pending mop-shopping Todo can mark a matching mop-floor Cleaning task `blocked`; `js/cleaning-history.js::normalizeForecastTask` excludes blocked tasks from the widget forecast. `js/widget-cleaning.js` listens for Todo-store changes and refreshes this derived status. This dependency changes display/planning, not SQLite task status.

## Metrics and calculations

| Metric | Meaning, inputs, filter/group/window/date semantics | Exact formula/rule and units/format/null handling | Version, owner, focused test |
| --- | --- | --- | --- |
| `daysSince`, `nextDueIn`, `status` | One active task, current and last-done Warsaw dates, frequency in days | `daysSince=max(0, calendar-date difference)` or null; `nextDueIn=max(0, ceil(freq-daysSince))`; overdue if missing last-done or `daysSince>freq`; `DEAD` if overdue by >7 days, otherwise `OVERDUE`; `DUE` at zero next due; `COMING` at ratio >=0.92; else `FRESH`. | `CleaningStore._task_payload`; `tests/test_cleaning_store.py` |
| State KPIs | All active tasks of one apartment | `dueToday` counts non-overdue tasks with zero next-due; `overdue` counts overdue; `total` is task count; `avgDelay` is one-decimal mean of positive `(daysSince-freq)` among overdue tasks with a completion, else 0. | `CleaningStore.get_state`; `tests/test_cleaning_store.py` |
| History totals | Non-reverted actions in week/month/year/all window | `total=len(actions)`; `activeDays` counts Warsaw dates with at least one action; bounded windows emit zero-filled daily series. | `CleaningStore.get_history`; `tests/cleaning-history.test.js`, `tests/test_cleaning_store.py` |

`count_actions_for_day` has a separate configurable 06:00 Warsaw rollover for the phone-cleaning goal; it must not be conflated with `get_state.doneToday` or history counts. This is a cross-feature semantic distinction, not a second ledger.

## Phone goal day boundary

`CleaningStore.count_actions_for_day` counts non-reverted actions from **06:00 Warsaw time to the next 06:00** by default. `get_history` uses Warsaw calendar-midnight boundaries. `get_state.doneToday` starts at Warsaw midnight but computes the end as **24 elapsed UTC hours later**, which can differ from the next Warsaw midnight during a daylight-saving transition. These are different metrics over the same canonical `cleaning_actions` table.

## Dashboard goal and rhythm metrics

`js/cleaning-history.js::buildCleaningForecastSeries` schedules non-blocked routine and overdue tasks subject to daily capacity. Capacity starts at 3, ramps by `floor((dayOffset+1)/2)` when overdue backlog exists, and caps at 10; a recovery day caps at 1. `js/widget-cleaning.js::getTodayGoalTarget` takes the forecast count plus completions outside the current plan, bounded by capacity. `getStableTodayGoalTarget` restores a same-day version-2 target from `cleaningDashboard.dailyGoalTarget.v2` or computes and clamps it to 0–10; after the first completed action it reconstructs that first-action target to avoid moving the goal. A recovery day forces target 1.

`updateGoalState` sets `todayDone` to today's action items, marks complete when target >0 and done >= target, and displays `round(100*done/target)` clamped 0–100. The seven-day total sums seven daily counts; weekly average is `round((total/7)*10)/10`. The dashboard lock is a separate optional presentation gate driven by goal completion/manual unlock, not a Cleaning database permission. The widget's 06:00 day and local snapshot are distinct from `CleaningStore.get_state` KPIs.

## Jobs and workers

No Cleaning-owned background queue or worker is required for ordinary task operations. Synchronous SQLite transactions own completion and undo. The optional tips request and phone-goal refresh are separate adjunct flows; neither changes Cleaning's canonical action semantics. Recovery after browser reload is an API read of the canonical store.

## Integrations

The current Cleaning task store needs no external provider. Legacy Google import is a one-time migration, and optional tips use a configured proxy with a bounded visible-task payload. These are not live providers for `CleaningStore.get_state`.

## Dependencies, failure and recovery

- Upstream: central `server.py`, local SQLite, and the Todo store for the optional mop dependency. Downstream: Cleaning page/card, phone-cleaning goal, weekly insights, and Timeline activity composition.
- API or store failure becomes a rejected `requestJson` call; the UI cannot infer a successful write from a failed response. Soft-deleted tasks and reverted actions remain distinguishable in the database.
- The task status and KPIs depend on the current Warsaw date and are recalculated on reads. Source fingerprints describe code revision, not the current household state.

## Privacy and security

Task names, notes, history, apartment IDs and runtime database rows are personal data. Kermit's Phase 8 index admits only reviewed documentation and selected source/test metadata, never `data/cleaning.sqlite`, old JSON records, Google exports, or AI-tip payloads. No Kermit model tool or runtime data adapter is introduced.

## Tests and evidence

| Contract | Current test | Limit |
| --- | --- | --- |
| Canonical task/action state, undo and status | `tests/test_cleaning_store.py` | No guarantee about a live household DB. |
| Widget and history display | `tests/widget-cleaning.test.js`, `tests/cleaning-history.test.js`, `tests/cleaning-logic.test.js` | Browser tests use fixtures, not live service availability. |

- **Verified implementation sources:** `cleaning_store.py::CleaningStore._initialize,_task_payload,get_state,get_history,mark_done,revert_last_action,remove_action,count_actions_for_day`; `server.py::GET/POST/PATCH/DELETE /api/cleaning/*`; `js/cleaning-api.js::requestJson,markDone,getTasks`; `js/cleaning-history.js::buildCleaningForecastSeries,getCleaningForecastDailyCapacity`; `js/cleaning-dependencies.js::resolveCleaningDependencies` (reviewed but intentionally not source-admitted because of its embedded Todo identity); `js/widget-cleaning.js::getTodayGoalTarget,getStableTodayGoalTarget,updateGoalState`; `index.html::data-widget="cleaning"`.
- **Documented current contracts:** `PROJECT_MAP.md` Cleaning rows. **Historical/proposed:** legacy import sources only; no proposed feature was used as current evidence.
- **Conflicts:** None established in the reviewed core flow. **Known gap:** the 06:00 goal boundary versus midnight dashboard/history boundary needs explicit wording in cross-feature answers.
- **Verification metadata:** source and focused test review 2026-09-30 on dirty `main`; no private runtime data read.

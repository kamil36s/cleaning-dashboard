# Habits App

## Identity and verification

- Stable ID: `habits-app`; current, reviewed 2026-09-30 on dirty `main` against `index.html::data-widget="habits-app"`, the lazy loader, Habits API, stores and focused tests. L0: `PROJECT_MAP.md` Habits rows.
- Scope: modern habit definitions and check-ins, synchronization, reminders, and supplement catalog/regimen state. Kermit describes static implementation only and cannot inspect user rows or perform actions.

## Purpose and boundaries

`data/habits.sqlite` is the **canonical current Habits App state**. It is not authority for every habits-themed widget: the legacy timeline uses exported Loop Habit history and the summary can show either a generated fallback or a modern live preview. Self-care tasks use Cleaning and Timeline, not this store. Never regenerate `data/habits.sqlite` from a legacy view or treat a notification claim as completion.

## Frontend and API

| Surface or route | Owner and behavior |
| --- | --- |
| `data-widget="habits-app"` | `js/widget-habits-app.js` loads an API snapshot, applies queued browser preview mutations, polls cursor changes, renders current habits and reminders. It publishes `habits-app:data-updated` for the summary. Offline errors leave a visible sync state. |
| GET `/api/habits/health`, `/api/habits/snapshot` | `server.py` calls `HabitsStore.health,snapshot`; snapshot accepts optional date range and returns habits, entries, cursor, reminder groups/settings/states. |
| POST `/api/habits/sync` | `HabitsStore.sync` accepts schema version 1, device ID, cursor, and at most 500 mutations; returns acknowledgements, conflicts and changes. Server body bound is 5 MiB. |
| POST `/api/habits/reminders/settings`, `/api/habits/reminders/action` | Save settings and claim/snooze/dismiss/satisfy reminder occurrences; bounded API bodies. |
| GET `/api/habits/supplements`; POST `/api/habits/supplements/{slots,regimen,product,claim}` | `SupplementsStore` reads dated catalog/regimen/slot state and mutates those records or claims a due slot. |

`js/habits-app-api.js` is the browser transport. Central `server.py::authorize_api_request` checks Host/Origin/Referer for writes; the browser UI has no Kermit mutation bridge. `js/widget-habits-app.js` owns browser notification display. There is no Habits-owned durable notification worker.

## Persistence and source of truth

| Entity or artifact | Owner and role |
| --- | --- |
| `data/habits.sqlite`: `habits`, `entries` | **Canonical user state**. Definitions have category, schedule, target, archive and revision. Dated check-ins are unique by `(habit_id,date)` with `DONE`, `MISSED`, `SKIPPED` and optional `takenAt`. Schema version 1; SQLite WAL. |
| `changes`, `processed_mutations` | **Canonical sync metadata**. Cursor orders changes; mutation ID records allow idempotent replay. Base revision mismatch yields a conflict and server state wins in current UI. |
| `reminder_time_groups`, `reminder_settings`, `reminder_occurrences` | **Canonical configuration / notification execution state**, separate from habit completion. Occurrence key deduplicates claims and persists snooze/dismiss/satisfied status. |
| `supplement_catalog`, `supplement_products`, `supplement_regimens`, `supplement_slots`, `supplement_slot_claims` | **Canonical supplement definition and dated product/regimen history**, slot times and day/slot claim deduplication in the same SQLite DB. A slot claim is a reminder claim, not a regimen edit or intake entry. |
| Browser preview mutation queue and live snapshot | **Local pending sync metadata / display cache**; current UI overlays it until acknowledgement and refresh. The browser mirror is not durable server authority. |
| Legacy Loop Habit exports and `public/data/habits.json` | **Migration input / generated view**. Can be rebuilt from their original imports, but cannot reconstruct all current definitions, revisions, reminder and regimen history. |

`HabitsStore.initialize` creates the schema and seeds from a legacy input only if the canonical habit table is empty. This one-time seed is not continuous synchronization. It does not make the input canonical. No backup or archive is admitted to Kermit.

## Data flow and calculations

1. Snapshot reads canonical rows; the UI converts them into browser models and overlays pending preview mutations. Mutations carry unique IDs and base revisions; `sync` transaction acknowledges repeats, records accepted changes and reports revision conflicts.
2. `js/habits-app-model.js::resolvedValue` chooses the latest pending mutation for the same habit/date before the canonical entry; missing returns null. `isHabitComplete`: binary value > 0; numeric finite value > 0 and at least target. Missing or nonfinite is incomplete.
3. `summarizeHabitsForDashboard` filters archived habits and counts active, complete and incomplete today; an unrecorded day is displayed as `MISSED` by this summary, not persisted as a `MISSED` entry. `habitMetrics` counts complete days within a bounded window and consecutive streaks; `habitPeriodSummary` averages only recorded finite values and returns null average when none. These are browser calculations, not stored aggregate rows (`tests/habits-app-model.test.js`).
4. `js/habits-reminder-schedule.js` interprets daily, selected weekdays, interval days with anchor, and custom schedules. It combines time groups and custom HH:MM times, removes duplicate times, and generates `habitId|localDate|sourceKey` occurrence IDs. Weekdays are Monday=0. Invalid/missing schedule settings are rejected by validation.
5. `js/habits-reminder-execution.js::ReminderExecutionService.tick` runs in the browser. It tests due occurrences, normally within a five-minute grace; a persisted snooze can be retried later, including across midnight. It asks the server to claim before displaying a notification. Browser closed or notification failure is not a durable retry guarantee; server claim can exist without delivery. A notification, claim, or snooze never records a habit completion (`tests/habits-reminder-execution.test.js`).
6. `SupplementsStore.snapshot` evaluates dated product/regimen periods and weekday masks for a requested day, defaulting to server-local `date.today()`. `change_product` closes prior dated intervals and creates new history; `save_regimen` uses effective dates. `claim_slot` inserts at most one `(local_date,slot)` claim only when a due untaken item exists. Supplement `TAKEN` check-ins belong to canonical entries, not the slot claim (`tests/test_supplements_store.py`).

## Date, failure and recovery semantics

Browser `localDateKey` and reminder `occurrenceDateTime` use the browser's local clock/timezone; UTC arithmetic shifts calendar keys without changing their intended local day. `HabitsStore` stores date strings and UTC server timestamps; its legacy seed maps imported timestamps to UTC dates. Supplement default day uses the server's local date. There is no single timezone rule shared by all components. A stale/offline UI retries its pending queue on later synchronization; conflicting revisions are reconciled from server snapshot. Restart reopens WAL-backed state; missed browser notification windows are not replayed as a durable job.

## Privacy, evidence and review

Names, health-related routines, supplement products, reminder payloads, runtime DB rows and exported histories are private. `habits_store.py`, `supplements_store.py`, `js/habits-app-model.js`, `js/habits-app-api.js`, and `js/widget-habits-app.js` contain hardcoded product or medication names; they were reviewed for contracts but deliberately **not admitted** to Kermit's static index. No runtime DB, notification payload or import is admitted.

Checked tests: `tests/test_habits_store.py`, `tests/test_supplements_store.py`, `tests/habits-app-model.test.js`, `tests/habits-app-api.test.js`, `tests/habits-reminder-schedule.test.js`, `tests/habits-reminder-execution.test.js`, `tests/widget-habits-app.test.js`. Static tests cannot prove live data freshness or browser notification delivery. Known date/retry limits are recorded in `GAPS_AND_CONFLICTS.md`.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `js/habits-reminder-schedule.js` | `export function getReminderOccurrences` |
| `js/habits-reminder-execution.js` | `export class ReminderExecutionService` |
| `server.py` | `/api/habits/sync` |

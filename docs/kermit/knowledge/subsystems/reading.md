# Reading

## Identity and verification

- Stable subsystem ID: `reading`; display: Reading; domain: book catalog and reading progress.
- Status: **verified current implementation**, reviewed 2026-09-30 on dirty `main`. L0: `PROJECT_MAP.md` pages, widgets, backend, persistence.
- Scope: `reading.html`, `index.html::data-widget="reading"`, `/api/reading/*`, and the active SQLite `ReadingStore`.

## Purpose and boundaries

Reading owns books, page progress, a daily reading log, settings, and derived progress/target summaries. `ReadingStore` in `reading_store.py` owns canonical book/log/settings state. Frontend modules own display, cover handling, browser view preferences, and synchronization mirrors. Synchrobook owns its own book/audio pipeline; Timeline and weekly insights consume Reading facts without owning them. Kermit only describes this static design.

## Frontend

| Surface | Entry/identifier | Controller, store, API client | Loading, empty, error, review/stale behavior |
| --- | --- | --- | --- |
| Full page | `reading.html` | `js/reading.js`, `js/reading-api.js`, `js/reading-books.js`, `js/reading-history.js`, `js/reading-settings-store.js` | Loads server state; local mirrors/guards help page transitions and fallback. Failed API calls reject through `readJson`. |
| Dashboard card | `index.html::data-widget="reading"` | `js/widget-reading.js`, `js/reading-api.js` | Lazy-loaded; refreshes state and renders selected book, due date, progress, targets, and summary. |

- User actions: add/update book, save page progress, replace history/settings, and local display preferences. The first four call mutating API operations.
- Browser-only state: `readingActiveMap.v1`, `readingOwnershipMap.v1`, `readingWidgetSelectedBook.v1`, `readingRemotePages.v1`, `readingSettingsUpdatedAt.v1`, and `readingDashboardSync.v1` are synchronization/view mirrors. `readingViewColumns.v1`, `readingCoverSize.v1`, and `readingPageSize.v1` are display preferences. Short recent-save guards in `js/reading-books.js` prevent a stale fetch from immediately masking a successful local update. None makes localStorage the canonical book/log database.
- The page and widget share API state but may have distinct presentation choices. Dashboard visibility/ordering is owned by shared dashboard code.

## Backend and API

| Method + route | Handler and service | Request/response owner; validation/limits | Read or mutation |
| --- | --- | --- | --- |
| GET `/api/reading/state`, `/api/reading/books`, `/api/reading/history`, `/api/reading/settings` | `server.py` GET -> `ReadingStore` | Store assembles current books, logs, settings and computed stats. | Read |
| POST `/api/reading/books`, `/api/reading/history`, `/api/reading/settings` | `server.py` POST -> `ReadingStore.create_book,replace_history,replace_settings` | Bounded JSON body; store validates book/history/settings shape. | Mutation |
| PATCH `/api/reading/books/{id}`, `/api/reading/books/{id}/progress` | `server.py` PATCH -> `ReadingStore.update_book,update_progress` | Progress is nonnegative and cannot exceed positive total pages; missing book returns 404. | Mutation |

`js/reading-api.js::request` centralizes JSON serialization and error decoding. Cover proxy/upload behavior is separate from the book/log store. There is no Reading-owned external model or background job in this core flow.

`server.py::authorize_api_request` gates mutations with `require_origin=True`; local clients and allowed/host Origin or Referer qualify, and a valid dashboard bearer token is recognized for PATCH book/progress paths. The POST create/history/settings paths do not have that Reading-specific token exception. Reading GET routes do not require Origin. This application authorization is not available to Kermit.

## Persistence and source of truth

| Artifact/entity | Owner | Role | Schema/migration/version and retention |
| --- | --- | --- | --- |
| `data/reading.sqlite`: `books`, `reading_logs`, `reading_settings` | `ReadingStore.initialize` | **Canonical** catalog, daily log, settings | Schema version 1 in `reading_settings`; WAL; `reading_logs` unique by `(day,book_key)` and book reference can become null. |
| Old Reading JSON/Google records | `ReadingStore.import_initial` and import scripts | **Migration input / legacy** | Not the current authoritative catalog or log. |
| Browser keys and cover artifacts | Reading frontend / cover handlers | **Browser-only view mirror / cache / generated media** | May be refreshed or rebuilt; separate from SQLite book and page counts. |

No separate raw archive or backup is required by the reviewed progress flow; any such files remain excluded from Kermit. Private cover files are not admitted.

## Data flow

1. `ReadingStore.initialize` creates schema, and `state` reads books, history-derived daily stats, and settings. Frontend page/widget load this snapshot via `fetchReadingState`.
2. `create_book`/`update_book` normalize identifiers, text, pages, source/return date and metadata before writing `books`. Invalid inputs are rejected with `ReadingError`.
3. `update_progress` validates page count and optional day, updates `books.pages_read`, and records history only for a positive increase when `recordHistory` is true. A decrease changes current progress but adds no negative log pages.
4. `_record_progress_row` uses `remote:{book_id}` and a unique day/book key. On repeated saves it preserves the first start page, takes the maximum current page, sets pages to `max(0,current-start)`, and increments save count. Thus repeated saves on one day are not naively summed.
5. `history` groups log rows by day, sums per-book and total pages, and exposes progress metadata. `replace_history` validates and replaces log rows; `state` derives the dashboard summary and target from current canonical records.

## Metrics and calculations

| Metric | Meaning, inputs, filter/group/window/date semantics | Exact formula/rule and units/format/null handling | Version, owner, focused test |
| --- | --- | --- | --- |
| Book progress | One book row | `pagesLeft=max(0,pagesTotal-pagesRead)`; `percent=round(100*pagesRead/pagesTotal)` and fractional `completedPct=pagesRead/pagesTotal` when total >0, else both 0. | `ReadingStore._row_to_book`; `tests/test_reading_store.py` |
| Daily average and streak | Daily totals from `reading_logs`; local `date.today()` | Average uses last `min(7, days since start)` days, rounded to whole pages; streak counts consecutive positive-total days backward from today and stops at first zero. `todayRead` is today's total, default 0. | `ReadingStore.daily_stats`; `tests/test_reading_store.py` |
| Library target | Active library-owned books with return date and positive remaining pages | For each eligible book: `ceil(remaining / max(1, returnDate-today in days))`; sum across books. `pagesLeftToday=max(0,target-todayRead)`. This is a daily page target, not a predicted completion date. | `ReadingStore._library_target,state`; `tests/test_reading_store.py` |
| State summary | Book list and daily stats | `booksActive` counts `remoteActive`; `pagesLeftAll` sums nonnegative remaining pages across all books; next return is earliest unfinished return date, or null. | `ReadingStore.state`; `tests/test_reading_store.py` |

The widget also computes a **display estimate** of overdue library fees from its own constant; it is not stored as a real library charge or sourced from the library provider. The exact fee policy is a UI assumption and must be labeled as such.

## Overdue fee estimate

`js/widget-reading.js::LIBRARY_OVERDUE_FEE_PER_ITEM_PER_DAY` is **0.35 zł per overdue day per library-owned book**. `getOverdueFee` returns zero for a nonnegative or nonfinite day count; `getTotalOverdueFee` sums only library books with return dates. The widget formats the result to two decimals and hides it at zero. This is a local display estimate: no reviewed source establishes a real lender charge or policy, and it does not mutate `data/reading.sqlite`.

## Jobs and workers

No Reading-owned durable queue or worker was found in the reviewed core flow. API writes are synchronous SQLite operations. A browser reload re-fetches canonical state. Synchrobook transcription/processing is a different subsystem.

## Integrations

Core book/log state is local. Historical Google-backed import and cover lookups/caches are adjacent paths, not live authority for current page counts. The dashboard card's return notification is a browser presentation side effect based on stored return dates; it does not write canonical Reading history.

## Dependencies, failure and recovery

- Upstream: central API and `data/reading.sqlite`; frontend settings/history mirrors and optional cover path. Downstream: Reading card/page, Timeline, weekly insights.
- `ReadingError` carries validation/not-found codes; `js/reading-api.js::readJson` rejects non-OK/`ok:false`. Local recent-save guards reduce stale-display races but do not replace server persistence.
- History replacement is destructive within the canonical log and must be distinguished from incremental page progress. Source review does not establish a conflict resolution protocol for simultaneous edits from multiple browsers.

## Privacy and security

Book titles, reading history, settings, raw imports and cover assets can reveal personal activity. Kermit admits selected code/test metadata and reviewed L1 prose only, never SQLite rows, legacy JSON records, cover media, or private import sources. No Kermit runtime adapter is added.

## Tests and evidence

| Contract | Current test | Limit |
| --- | --- | --- |
| Schema, progress, daily log, target, import | `tests/test_reading_store.py`, `tests/test_reading_api.py` | Fixed fixtures do not prove live DB freshness. |
| API adapter and page/widget behavior | `tests/reading-api.test.js`, `tests/reading-e2e.test.js` | Browser behavior depends on localStorage and network timing; no dedicated `widget-reading` test was found. |

- **Verified implementation sources:** `reading_store.py::ReadingStore.initialize,_row_to_book,update_progress,_record_progress_row,history,replace_history,daily_stats,_library_target,state`; `server.py::GET/POST/PATCH /api/reading/*`; `js/reading-api.js`; `js/reading-settings-store.js`; `js/reading-books.js`; `js/widget-reading.js`; `index.html::data-widget="reading"`.
- **Documented current contracts:** `PROJECT_MAP.md` Reading rows. **Historical/proposed:** old JSON/Google import paths only.
- **Conflicts:** None established in reviewed core flow. **Known gaps:** multi-browser write conflict semantics and whether the widget fee estimate matches any real lender policy remain unverified; see register.
- **Verification metadata:** source and focused test review 2026-09-30 on dirty `main`; no runtime database or private input read.

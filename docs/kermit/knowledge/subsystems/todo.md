# Todo board

## Identity and verification

- Stable subsystem ID: `todo`; display: Todo; domain: task and project planning.
- Status: **verified current implementation**, reviewed 2026-09-30 on dirty `main`. L0: `PROJECT_MAP.md` pages, widgets, settings API and persistence.
- Scope: `todo.html`, `index.html::data-widget="todo"`, `js/todo-store.js`, and generic `/api/settings/todo`.

## Purpose and boundaries

Todo owns tasks in `now`, `projects`, `ideas`, and `shopping` buckets, with dates, completion, project priorities, and subtasks. It is a JavaScript store with a file-backed setting, not a dedicated Python task repository. The generic settings API owns the file write; page and widget own presentation. Cleaning tasks, Google Tasks, and Timeline items are separate domains. The Cleaning frontend consults a pending mop-shopping Todo to mark matching Cleaning tasks blocked in its forecast, without changing either canonical store. Kermit can explain this ownership but cannot edit Todo state.

## Frontend

| Surface | Entry/identifier | Controller, store, API client | Loading, empty, error, review/stale behavior |
| --- | --- | --- | --- |
| Full board | `todo.html` | `js/todo.js`, `js/todo-store.js`, `js/file-settings.js` | Waits for `todoStoreReady`, renders buckets/projects and KPIs; browser mirror supports local fallback. |
| Dashboard card | `index.html::data-widget="todo"` | `js/widget-todo.js`, `js/todo-store.js` | Lazy-loaded; shows `now` and `shopping` lists, with recently completed items visible for a grace window. |

- User actions: add/edit/delete/toggle tasks and project subtasks, clear completed items, reorder projects, and export a local `.ics` reminder from the page. Store mutations call `saveTodos`; the ICS export is a browser download, not a backend write.
- Exact browser keys: `todo-items-v1` is a working mirror/fallback; `todo-deleted-seed-ids-v1` prevents deliberately removed seed projects from reappearing; `todo-expanded-projects-v1` stores page expansion only. In-memory `todosCache` is not a second authority.
- `BACKLOG_PROJECTS_SEED` can add absent seed projects unless their IDs were marked deleted. This is local seed behavior, not imported user history.

## Backend and API

| Method + route | Handler and service | Request/response owner; validation/limits | Read or mutation |
| --- | --- | --- | --- |
| GET `/api/settings/todo` | `server.py::read_settings_payload` | Allowlisted `todo` name; returns `{ok,name,data,storedPath}` from `data/settings/todo.json`. | Read |
| POST `/api/settings/todo` | `server.py::write_settings_payload` | Allowlisted name; writes JSON `data` via `rewrite_json_file`; frontend normalizes items. | Mutation |

`js/file-settings.js::loadFileBackedSetting` prefers a non-null server value, otherwise uses localStorage and may migrate it to the server. `saveFileBackedSetting` writes the local mirror immediately and starts an asynchronous server save whose rejection is swallowed. This provides offline/local fallback but a failed server write can leave browser and canonical file divergent; the UI does not get a durable success acknowledgment from this helper.

`server.py::authorize_api_request` gates the generic settings POST with `require_origin=True`; a local client or allowed/host Origin or Referer qualifies. The settings name is allowlisted by `normalize_settings_name`, so the route cannot choose an arbitrary file. The GET does not require Origin. Neither application route is callable by Kermit.

## Server save failure

If the Todo server POST fails, `js/file-settings.js::saveFileBackedSetting` keeps the updated `todo-items-v1` localStorage mirror and suppresses the error. The canonical `data/settings/todo.json` file may remain older. No durable retry queue or user-visible server-write confirmation is established.

## Persistence and source of truth

| Artifact/entity | Owner | Role | Schema/migration/version and retention |
| --- | --- | --- | --- |
| `data/settings/todo.json` | `server.py::write_settings_payload` | **Canonical file-backed** Todo array when the local API is available | Generic allowlisted JSON setting; no Todo-specific SQLite schema or migration. |
| `localStorage: todo-items-v1` | `js/todo-store.js` / `js/file-settings.js` | **Working mirror / offline fallback** | Normalized on read; may temporarily diverge after a failed asynchronous server save. |
| Seed projects and deleted-seed IDs | `js/todo-projects-backlog-seed.js`, `js/todo-store.js` | **Seed / browser-only control** | Seed is source code; deleted IDs are local browser state. |
| Expanded projects preference | `js/todo.js` | **Browser-only presentation** | `todo-expanded-projects-v1`. |

No Todo raw archive, generated dataset, database backup, or dedicated worker is part of this flow. The JSON file is private runtime state and is not admitted to Kermit.

## Data flow

1. Module initialization calls `hydrateTodosFromServer`; `loadFileBackedSetting` reads server JSON, falls back to `todo-items-v1`, optionally migrates that mirror, then normalizes items.
2. `normalizeItem` drops invalid/empty titles, validates bucket/priority/due date, and keeps project-only fields (`description`, `priority`, `order`, `subtasks`) only for the `projects` bucket. An invalid due date becomes null rather than an inferred day.
3. Store operations update an in-memory list, call `saveTodos`, write the browser mirror, fire an asynchronous settings POST, and emit `todo:store-changed` for page/widget refresh.
4. Project completion follows all subtasks when any exist; changing or toggling a subtask recomputes the parent done/completedAt state. A project without subtasks can be toggled directly.
5. `clearDone` removes completed items; deleting/clearing seed projects records their IDs locally to avoid reseeding. Sorting and KPI calculation occur in the browser from current items.

## Metrics and calculations

| Metric | Meaning, inputs, filter/group/window/date semantics | Exact formula/rule and units/format/null handling | Version, owner, focused test |
| --- | --- | --- | --- |
| Todo KPIs | All normalized items, current local calendar day | `total=items.length`, `done=count(done)`, `open=total-done`, `withDue=count(valid due)`, `overdue=count(open with due before startOfDay(today))`, `dueSoon=count(open with due in 0..3 days)` using rounded day difference. | `js/todo-store.js::getStats`; `tests/todo-store.test.js` |
| Recently completed | Done item with `completedAt`, else `updatedAt` | Visible in active list while `now-completedAt < 3*24h`; older completed items are archived from the active list, not deleted. | `isRecentlyCompletedTodo,isTodoActiveListVisible`; `tests/todo-store.test.js` |
| Sorting | Current list | `sortTodos`: open first, earlier due dates first, undated last, then creation time. `sortProjects`: priority P0..P4, then order, then creation time. | `sortTodos,sortProjects`; `tests/todo-store.test.js` |

No server-side Todo analytics cache exists. The widget computes bucket-specific counts from the shared array.

## Jobs and workers

No background worker, retry queue, or startup recovery contract exists for Todo. The browser performs best-effort asynchronous saves; startup hydration and local fallback are the recovery path. A failed save is not automatically retried by a durable queue.

## Integrations

No external provider is needed. The generic settings API is local. Calendar `.ics` export is a client-generated file and does not create a Google Calendar event.

## Dependencies, failure and recovery

- Upstream: generic settings handler, `data/settings/todo.json`, and browser localStorage. Downstream: Todo board/card and `timeline_activity.py::_todos`, which reads the canonical Todo JSON for completed-task activity without owning Todo writes. Timeline's full composition remains a later batch.
- If server GET fails or returns null, the local mirror is used. If server POST fails, the local mirror still changes and the helper suppresses the rejection. Different browsers can therefore show different state until a successful save/read resolves it; no multi-client conflict protocol was found.
- Project seed deletion relies on a browser-only key. Clearing that key could allow an absent seed project to reappear.

## Privacy and security

Task titles, descriptions, due dates, and project details can be personal. Kermit admits only selected source/test metadata and this pack, never `data/settings/todo.json` or localStorage contents. The generic settings route is part of the dashboard application, not a Kermit capability.

## Tests and evidence

| Contract | Current test | Limit |
| --- | --- | --- |
| Normalization, completion, date/KPI and seed rules | `tests/todo-store.test.js` | Does not prove persistence after a real server outage. |
| Board/card display and actions | `tests/todo-page.test.js`, `tests/widget-todo.test.js` | Fixture/browser behavior only. |

- **Verified implementation sources:** `js/todo-store.js::hydrateTodosFromServer,normalizeItem,saveTodos,updateTodo,toggleSubtask,getStats,sortTodos,isRecentlyCompletedTodo`; `js/file-settings.js::loadFileBackedSetting,saveFileBackedSetting`; `js/todo.js`; `js/widget-todo.js`; `server.py::normalize_settings_name,read_settings_payload,write_settings_payload`; `index.html::data-widget="todo"`.
- **Documented current contracts:** `PROJECT_MAP.md` Todo rows. **Historical/proposed:** seed project list is a source default, not existing user tasks.
- **Conflicts:** None established. **Known gap:** best-effort save has no durable retry or visible server-write failure; see register.
- **Verification metadata:** source and focused test review 2026-09-30 on dirty `main`; no runtime Todo JSON or browser private state read.

# Main dashboard infrastructure — reviewed L1 pack

## Identity and verification

- Stable subsystem ID: `dashboard`. Current implementation, reviewed 2026-09-30 on dirty `main` from source and focused tests.
- L0 locator: `PROJECT_MAP.md` High-Level Architecture and Main dashboard row.
- Scope: composition, registration, loading, order, visibility, sizing and headers; individual widget data models belong to their feature packs.

## Purpose and boundaries

`index.html` composes the main `.dash` surface. A dashboard widget is **ACTIVE WIDGET** when a direct `data-widget` child has a matching key in `widgetLoaders` in `js/dashboard-widget-loader.js`; the current intersection contains **34 distinct keys**. Registration does not mean immediate module execution. `data/widget-order.json` ships defaults with **13 registered keys hidden by default** and 21 shown by default. Such a key is **REGISTERED BUT HIDDEN**, and a persisted user choice can show it. An **INACTIVE MODULE** is a `widget-*.js` file without a current markup and loader registration; file existence and old fallback settings metadata do not activate it. A **STANDALONE PAGE** is a root page such as `todo.html` or `settings.html`; its page controller is independent of whether a related card is registered or visible. The 34 keys are inventory, not 34 validated feature packs.

## Frontend

| Surface | Entry and behavior | Failure behavior |
| --- | --- | --- |
| Main composition | `index.html` direct `.dash > [data-widget]`; `js/dashboard-widget-loader.js::startDashboard` reads config and applies initial layout. | Top-level startup errors are logged. |
| Module loading | `widgetLoaders`, `loadWidget`, `loadVisibleWidgets`, `waitForNetworkIdle` load visible priority cards first, wait at most 4.5 seconds for network quiet, then deferred cards. Habits support loads even if its card is hidden. | `Promise.allSettled` isolates failed imports; failed `loadWidget` promise is cached and logged, so that key is not automatically retried in the current page session. |
| Layout | `js/widget-order.js` sorts direct cards and applies visibility, spans and headers; `js/dashboard-widget-visibility.js::filterVisibleWidgetKeys` removes only explicit `false` keys from the load list. | A missing widget key has no loader. |
| Settings | `js/dashboard-settings.js::loadDashboardWidgetConfig,saveDashboardWidgetConfig` normalizes order, visible, layout, placement and headers. `js/settings.js` exposes the dashboard editor. | Server load falls back to local mirror/default. Save writes local mirror before a best-effort server POST. |

Changing dashboard settings emits `dashboard:widgets-changed`; the loader applies layout and imports newly visible keys. Column count is clamped to 2–4, header font to 13–22, and spans to `auto`, `1`, `2`, `3`, or `full`. These are UI layout values, not canonical widget data.

## Backend and API

`GET /api/settings/dashboard` and `POST /api/settings/dashboard` are served by `server.py`'s generic allowlisted settings handler. The server file `data/settings/dashboard.json` is the canonical dashboard preference when available. These routes are application capabilities; Kermit has no tool or permission to call the write route.

## Persistence and source of truth

| Artifact | Role |
| --- | --- |
| `data/widget-order.json` | Shipped default configuration; not user state and not admitted to Kermit. |
| `data/settings/dashboard.json` | Canonical server setting when the API is available; private runtime file, not admitted. |
| `dashboard.widget-settings.v1` | Browser localStorage mirror and offline fallback. A failed asynchronous POST can leave it ahead of the server. |
| `FALLBACK_DEFAULT_CONFIG` | Code fallback in `js/dashboard-settings.js` when shipped defaults are unavailable. |

The dashboard widget order setting is stored in canonical server JSON `data/settings/dashboard.json` when the API is available; `dashboard.widget-settings.v1` is its browser mirror and offline fallback.

No dashboard-wide SQLite store or background worker owns layout. Widget-specific persistence is outside this pack.

## Data flow, jobs and dependencies

Startup reads server preferences, otherwise mirror/defaults; layout is applied before visible imports. `widget-order.js`, the Settings controller, shortcuts and Habits support join priority imports; deferred imports follow a bounded network-idle wait. `js/widget-order.js` refreshes placement when settings change. Independent feature modules and their APIs may fail without a single failed import rejecting the whole load group. Vite serves the frontend and proxies central `/api` requests; feature-owned services can be independent.

## Metrics and calculations

The 34 registered and 13 default-hidden counts are current source inventory from markup, loader and shipped defaults, not analytics or coverage scores. Individual widget formulas remain with their owning feature packs.

## Privacy and security

The dashboard can invoke its normal APIs, including writes for user actions. Kermit only retrieves admitted static evidence about those APIs; it cannot mutate widget order, settings or runtime state. No `data/` user preference file is admitted.

## Tests and evidence

`tests/dashboard-settings.test.js`, `tests/widget-order.test.js` and `tests/settings-widget-headers.test.js` cover configuration and layout behavior. They do not prove every registered widget's own data path. Source review: `index.html`, `js/dashboard-widget-loader.js`, `js/dashboard-widget-visibility.js`, `js/widget-order.js`, `js/dashboard-settings.js`, `js/settings.js`, `server.py`.

## Checked implementation references

Each row is an exact current path and literal source marker for the read-only coverage check.

| Path | Marker |
| --- | --- |
| `index.html` | `data-widget="feelings"` |
| `js/dashboard-widget-loader.js` | `const widgetLoaders = {` |
| `js/dashboard-widget-visibility.js` | `filterVisibleWidgetKeys` |
| `js/widget-order.js` | `function applyOrder` |
| `js/dashboard-settings.js` | `loadDashboardWidgetConfig` |
| `js/settings.js` | `commitDashboardWidgetState` |
| `server.py` | `read_settings_payload` |

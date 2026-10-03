# Settings infrastructure — reviewed L1 pack

## Identity and verification

- Stable subsystem ID: `settings`. Current mixed persistence implementation, reviewed 2026-09-30 on dirty `main`.
- L0 locator: `PROJECT_MAP.md` Settings row. This pack covers settings plumbing, not every feature's settings semantics.

## Purpose and boundaries

`settings.html` is a **STANDALONE PAGE** with Status, dashboard layout, network devices, kitchen dashboard and Spotify screensaver sections. `js/settings.js` also provides the dashboard settings modal. These sections do not share one persistence model. The generic file-settings helper serves several feature clients, including Todo, but Todo's complete contract is in its own pack.

## Frontend

| Surface | Controller | Behavior |
| --- | --- | --- |
| Dashboard layout | `js/settings.js`, `js/dashboard-settings.js` | Order, visibility, columns, spans and header text normalized then saved; some modal changes wait for Save and Close, header text saves on edit. |
| Generic file setting | `js/file-settings.js::loadFileBackedSetting,saveFileBackedSetting` | Fetch server first, then local mirror, then caller default. Browser saves mirror first and fires an asynchronous POST whose rejection is suppressed. |
| Status tab | `js/settings-runtime-status.js` | Reads `/api/dashboard/runtime-status`; informational, no service lifecycle control. |
| Network notifications | `js/network-notification-settings.js` | `networkWidgetStatusNotificationsEnabled` is a **BROWSER-ONLY PREFERENCE** with no generic settings POST. |
| Network devices, kitchen, Spotify | `js/settings.js` and feature-specific API clients | Their API/state contracts are feature-owned, not instances of one generic settings file. |

## Backend and API

`server.py::normalize_settings_name` accepts a lowercase name matching `[a-z0-9][a-z0-9_-]{0,63}` only if it is in the allowlist `bills`, `dashboard`, `live-workout-plan`, `todo`, `reading`, `reading-history`, `cleaning`, `events`, `network`, or starts with `cleaning-history-`. `GET /api/settings/<name>` calls `read_settings_payload` and returns `ok`, `name`, `data`, `storedPath`; unknown names return 404. `POST /api/settings/<name>` calls `write_settings_payload`; invalid names return 400. The POST is an application write route subject to the central request authorization checks. The helper serializes `{data: value}` and uses keepalive only for bodies at most 60 KiB. The generic POST path parses JSON and has some route-specific size checks; do not infer a universal settings payload size limit from the helper's keepalive threshold.

## Persistence and source of truth

| Role | Example and exact meaning |
| --- | --- |
| **CANONICAL SERVER SETTING** | Allowlisted `data/settings/<name>.json`, for example `dashboard.json` or `todo.json`, when the server is available. The server file is private runtime state and is not admitted to Kermit. |
| **DEFAULT** | `data/widget-order.json` and `FALLBACK_DEFAULT_CONFIG` seed dashboard layout; defaults are not user changes. |
| **LOCAL MIRROR** | `dashboard.widget-settings.v1` and caller-provided `storageKey` in `js/file-settings.js` cache the last local/server value. |
| **OFFLINE FALLBACK** | If the server GET fails or returns null, a local mirror is used; if absent, the caller's default is normalized. |
| **BROWSER-ONLY PREFERENCE** | `networkWidgetStatusNotificationsEnabled` in localStorage has no server counterpart in this setting flow. |

Server success overwrites the local mirror. A local-only value may be migrated by a best-effort POST. A failed save can leave the mirror ahead of canonical server state; there is no durable retry or multi-browser conflict resolution in this helper. `localhost:3000` and non-HTTP contexts skip its server fetch path. Clearing localStorage can discard browser-only preferences and offline mirrors. The Settings UI cannot treat all feature settings as SQLite or all localStorage values as canonical.

## Jobs, integration and failure

No generic settings background worker exists. The runtime Status section reads status only; Network Monitor and Spotify use their own API/integration paths. Errors in generic fetch fall back to local/default; generic save errors are swallowed, so a visible local edit does not prove persistence on disk.

## Privacy and security

The allowlist limits generic file names and the API authorization controls remote writes. Browser localStorage is local state, not a private database reader for Kermit. Kermit has no application write tool and never indexes runtime settings JSON.

## Tests and evidence

`tests/dashboard-settings.test.js`, `tests/file-settings.test.js`, `tests/network-notification-settings.test.js`, `tests/settings-runtime-status.test.js`, and `tests/settings-widget-headers.test.js` provide focused browser contracts. Source review: `settings.html`, `js/settings.js`, `js/dashboard-settings.js`, `js/file-settings.js`, `js/network-notification-settings.js`, `js/settings-runtime-status.js`, `server.py`.

## Checked implementation references

| Path | Marker |
| --- | --- |
| `settings.html` | `data-settings-section-link="dashboard-layout"` |
| `js/settings.js` | `commitDashboardWidgetState` |
| `js/dashboard-settings.js` | `DASHBOARD_WIDGET_STORAGE_KEY` |
| `js/file-settings.js` | `loadFileBackedSetting` |
| `js/network-notification-settings.js` | `networkWidgetStatusNotificationsEnabled` |
| `js/settings-runtime-status.js` | `/api/dashboard/runtime-status` |
| `server.py` | `def normalize_settings_name` |

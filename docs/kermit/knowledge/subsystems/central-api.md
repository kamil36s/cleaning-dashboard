# Central API and static security — reviewed L1 pack

## Identity and verification

- Stable subsystem ID: `central-api`. Current implementation, reviewed 2026-09-30 on dirty `main` with targeted route and security-symbol inspection.
- L0 locator: `PROJECT_MAP.md` High-Level Architecture and Backend API Domains.

## Purpose and boundaries

`server.py::DashboardHTTPServer` extends `ThreadingHTTPServer`; `Handler` extends `SimpleHTTPRequestHandler` and dispatches GET, POST, PATCH and DELETE by explicit path checks. It owns the central API/static server, usually port 8000. It composes feature-specific stores and services; the presence of a route does not transfer canonical storage ownership into `server.py`. Current route inventory across central, training and network implementations has **43 distinct `/api/<domain>` prefixes**, but this shared pack validates the boundary, not 43 feature domains.

## Frontend and process ownership

`vite.config.js` proxies browser `/api` calls to `127.0.0.1:8000` with `changeOrigin: false` and has additional static-path denial rules. Vite is the frontend development server; central `server.py` owns its API and file serving. `training_runtime.py` on 8766 owns active Live Workout clock, telemetry, checkpoints and SSE; restarting central `server.py` does not stop that separate workout process. `run_network_monitor.py` / `network_monitor/api.py` on 8765 owns network scanning/API. Kermit on 8767 owns only its read-only chat and static knowledge access. `scripts/scan_ble.py` is a separate BLE collector. Port/service ownership is specific: 8000 central API, 8766 Live Workout, 8765 Network Monitor, 8767 Kermit. This is ownership context, not validation of those later feature packs.

## API authorization and input boundary

`Handler.authorize_api_request` applies origin/host checks to API requests. A browser Origin may be accepted when explicitly allowed or same as request Host; an allowed/same-host Referer is a fallback. Local loopback clients are permitted by this check. Remote companion/device paths have separate token rules, including phone tracker, feelings, habits, finance companion and Live Workout telemetry; those exceptions must not be described as ordinary anonymous writes. Mutating handlers require origin where applicable; GET does not uniformly require one. Route handlers validate their own payloads and limits, rather than one global schema. Some routes require a valid Content-Length and some enforce explicit body-size caps. The generic settings POST parses JSON, returns 400 for malformed JSON or invalid allowlisted names, and writes only normalized settings paths. Do not equate the browser helper's 60 KiB keepalive threshold with a universal server request cap.

## Static privacy boundary

`server.py::is_protected_static_path,authorize_static_request` reject private static paths with 404. Rules cover runtime/private data, raw imports, finance SQLite and sidecars, finance receipt/import areas, budget backups, language/reference paths, selected settings and denied suffixes/segments. Vite adds its own denial plugin for finance, language and phone/source areas; API proxying does not turn a private path into ordinary static content. Secrets, OAuth state, runtime databases, user imports and backups are outside Kermit's positive admission. An explicit feature API may serve authorized derived data; static denial does not imply all feature APIs are unavailable.

## Persistence, data flow and failure

The central server has no single canonical application database. Feature stores own SQLite/JSON state, while static files are served only after path policy. Browser requests flow through Vite's proxy in development or directly to the central server where configured. If the central API is unavailable, its dependent widgets/settings can fail or use feature-specific fallback; independent workout, network and Kermit processes have separate lifecycles. No central restart command should be inferred as a safe restart of those processes.

## Privacy, read-only guarantee and tests

Kermit may explain approved static source evidence but has no tool for `server.py` write APIs, arbitrary filesystem browsing, SQL, or user runtime data. `tests/vite-finance-privacy.test.js` checks Vite denial; central security tests are feature-specific. This pack does not claim uniform security behavior across all 43 route domains.

## Checked implementation references

| Path | Marker |
| --- | --- |
| `server.py` | `class DashboardHTTPServer` |
| `server.py` | `def authorize_api_request` |
| `server.py` | `def is_protected_static_path` |
| `server.py` | `def normalize_settings_name` |
| `vite.config.js` | `changeOrigin: false` |
| `training_runtime.py` | `8766` |
| `network_monitor/api.py` | `/api/network` |
| `PROJECT_MAP.md` | `scripts/scan_ble.py` |

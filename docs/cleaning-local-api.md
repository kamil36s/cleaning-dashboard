# Cleaning local API

The cleaning dashboard uses `data/cleaning.sqlite` through `cleaning_store.py`. Google Apps Script is only a source for the one-time import and is not used by the running UI.

## Initial import

```powershell
npm run cleaning:import -- --dry-run
npm run cleaning:import
```

The importer downloads both legacy apartments, caches the source payloads as `data/settings/cleaning-tasks-<apartment>.json`, imports every `cleaning-history-*.json` file, prints SHA-256 checksums and record counts, and runs `PRAGMA integrity_check`. A pre-existing target database is backed up under `data/backups/` before a real import. Use `--offline` to import from the cached task payloads.

## REST endpoints

- `GET /api/cleaning/state?apartment=<id>`
- `GET /api/cleaning/tasks?apartment=<id>`
- `POST /api/cleaning/tasks`
- `PATCH /api/cleaning/tasks/<id>`
- `POST /api/cleaning/tasks/<id>/done`
- `DELETE /api/cleaning/tasks/<id>` (soft delete; action history stays in SQLite)
- `GET /api/cleaning/history?apartment=<id>&range=<week|month|year>&offset=<int>`
- `POST /api/cleaning/history/undo`
- `DELETE /api/cleaning/history/actions/<action_id>?apartment=<id>` (ukrywa tylko wskazany wpis audytowo i przelicza `lastDone` zadania, gdy potrzeba)
- `GET /api/cleaning/settings`
- `POST /api/cleaning/settings`

Writes from the dashboard use same-origin protection. A future Android client can use `Authorization: Bearer <DASHBOARD_WRITE_TOKEN>` or `X-Dashboard-Token` on write requests. Mark-done accepts `source: "android"`.

## Restart

Stop the running local server, then run `python server.py` (or the existing `npm run dev:all` launcher). Vite alone serves the frontend but the local Python server must be running for `/api/cleaning/*`.

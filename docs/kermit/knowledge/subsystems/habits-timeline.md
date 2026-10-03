# Habits Timeline

## Identity and verification

- Stable ID: `habits-timeline`; active `index.html::data-widget="habits-timeline"`, hidden in shipped defaults; reviewed 2026-09-30 on dirty `main` against loader, timeline renderer/uploader, legacy builder and server routes.
- Purpose: visualize historical Loop Habit points and allow a legacy DB upload. It is not the modern Habits App store or its sync history.

## Source and generated-view flow

`scripts/build-habits.py` reads selected Loop Habit DB and CSV exports (defaults under `data/raw/db` and `data/raw/csv`), normalizes points, resolves duplicate/conflicting inputs and writes `data/habit-data.json`, `js/habit-data.js`, conflicts and `data/report.*`. Its CSV timezone defaults to Europe/Warsaw; DB timestamps are imported as recorded. Running it is a deliberate import/build action, not dashboard startup. The generated `js/habit-data.js` assigns `window.HABIT_DB` and contains actual personal point history. It can be rebuilt from retained imports, subject to the builder's normalization/conflict policy. These outputs must never be used to regenerate the modern canonical `data/habits.sqlite` blindly.

The lazy loader imports generated data, `js/habit-timelines.js` and `js/habit-upload.js` when the widget loads. The renderer turns point arrays into day-indexed binary/numeric series, selectable pills, tiles and canvas plots. Its day range uses fixed 86,400,000-ms steps and ISO dates; that is the legacy chart's calendar calculation, not the modern reminder schedule. The renderer contains hardcoded medication filters and is excluded from Kermit's index.

`js/habit-upload.js` accepts only `.db` files up to 64 MiB, base64-encodes the browser-selected file, POSTs `/api/habits/upload-db`, then reloads after success. The server validates the upload and calls `import_habit_db_from_payload`, which runs the legacy build path; uploaded data is private. A failed upload leaves the old generated view in place. `TimelineActivity._habits` in `timeline_activity.py` separately reads `data/habit-data.json` and emits private positive-value activity events; it does not read `habits.sqlite`. This is a Timeline consumer of legacy history, not Timeline ownership of current Habits records.

## Persistence, security and recovery

Raw Loop Habit DB/CSV files are **private import inputs**. `data/habit-data.json`, `js/habit-data.js`, generated report/conflicts and browser `window.HABIT_DB` are **generated views**; `public/data/habits.json` is another generated summary. They can be rebuilt only if original imports and build assumptions survive. `data/habits.sqlite` is the separate **canonical modern store** and must be preserved. The upload is an explicit mutating API under central Host/Origin controls; Kermit cannot call it or inspect any imported row. The generated JS is browser-visible when this widget loads, a privacy exposure of the legacy design; Kermit still excludes it.

Reviewed tests include `tests/test_timeline_activity.py`, `tests/timeline-activity-model.test.js`, and Habits feature tests. These do not establish that legacy imported points exactly match modern check-ins. `js/habit-timelines.js` and `js/habit-data.js` are excluded due to personal names/history. No private raw DB/CSV, report or generated JSON is admitted.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `scripts/build-habits.py` | `def build_dataset` |
| `js/habit-upload.js` | `/api/habits/upload-db` |
| `timeline_activity.py` | `def _habits` |
| `index.html` | `data-widget="habits-timeline"` |

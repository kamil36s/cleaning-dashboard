# Cleaning Dashboard analytical context

This directory is a compact, data-only view of a personal dashboard. The dashboard tracks task workload, cleaning cadence, habits, body/activity observations, workouts, reading, local events, AI quota usage, and room environment readings.

`manifest.json` is the machine-readable index. Current normalized exports are in `snapshots/current/`; deterministic cross-dataset signal candidates are in `summaries/`; JSON Schemas are in `schemas/`. `history/` is reserved for future point-in-time exports and currently contains documentation only.

# ACCESS BOUNDARY

This directory is the complete context available to Antigravity.

Antigravity must reason only from information exposed here.

The parent repository and application source code are intentionally outside its workspace.

Do not require access to parent directories.

Do not assume undocumented data exists.

Do not request or modify application source code.

Treat calculated metrics supplied here as authoritative unless explicitly instructed otherwise.

## How to read the data

- An **observation** is a measured or recorded value, such as a weight, step count, completed workout, reading log, or sensor sample.
- A **calculated fact** is produced deterministically from observations, such as a 7-day average, previous-period delta, overdue count, streak, or trend label.
- An **interpretation** explains why one or more facts may matter. It must be grounded in exported facts and clearly separated from them.
- A **recommendation** proposes an action. It must follow from an interpretation, respect uncertainty, and never invent missing context.

Missing, `null`, or `unknown` values mean the exporter did not have enough clean data. Never fill them by guessing.

## Time and units

- `generated_at` and source freshness timestamps are ISO 8601 UTC timestamps ending in `Z`.
- Calendar dates use `YYYY-MM-DD` and are interpreted in `Europe/Warsaw` unless a dataset says otherwise.
- Rolling windows include the `as_of` date unless a dataset supplies a separate comparison-window end. “Previous 7 days” is the immediately preceding non-overlapping seven-day window. Step comparisons end on the latest complete calendar day so a partial current day does not bias the average.
- Weight is kilograms (`kg`), duration is minutes, energy is kilocalories (`kcal`), heart rate is beats per minute (`bpm`), temperature is degrees Celsius, humidity/quota values are percentages, and steps/pages/sets/sessions are counts.
- `source_freshness` is a file modification timestamp, not necessarily the time of the latest observation. Use dataset-specific dates such as `observed_at` or `latest_weight_date` when present.

## Available datasets

### Tasks

`snapshots/current/tasks.json` contains counts, completion rate, open items by bucket, overdue count, and due-soon facts. Due records use opaque IDs. Task titles and free text are intentionally omitted.

### Cleaning

`snapshots/current/cleaning.json` contains active/overdue/never-completed counts and cadence-derived overdue records. Locations are irreversibly aliased; addresses, task names, articles, and notes are omitted. `days_overdue` is calculated from `last_completed + frequency_days`.

### Habits

`snapshots/current/habits.json` compares positive days in the current and previous seven-day windows and provides a current consecutive-day streak. Habit names are retained because they are required to interpret the metric; descriptions, questions, reminders, and entry notes are omitted. For binary habits a positive day is `DONE`; for numeric habits it is a recorded value greater than zero. A positive day is not necessarily the same as meeting a target.

### Body and activity

`snapshots/current/body-activity.json` contains one compact daily record for the most recent 30 observed dates, plus 7-day/previous-7-day comparisons and a 30-day weight baseline. Raw BLE packets and device identifiers are excluded. `ma7`/`ma30` mean arithmetic averages across available observations in the window; missing days are not imputed.

### Training

`snapshots/current/training.json` contains finished workout totals for the current and previous seven-day windows, recent workout summaries, and strength session/set aggregates. Raw heart-rate samples and exercise notes are excluded. `training_load` is a dashboard-supplied calculated value and is not re-derived here.

### Reading

`snapshots/current/reading.json` contains active book progress and recent page totals. Titles/authors are retained because they define the tracked items; other metadata and free text are omitted. Page comparisons use reading-log dates.

### Events

`snapshots/current/events.json` contains timing, type, source, and workday flags for local dashboard events from seven days ago through 60 days ahead. Titles and external calendar account data are omitted. `days_from_today` is negative for past events.

### AI usage

`snapshots/current/ai-usage.json` contains the newest quota snapshot per provider/group and a recent session count. It contains no prompts, response content, credentials, tokens, cookies, or authentication material.

### Environment

`snapshots/current/environment.json` contains the latest room temperature/humidity/battery observation and 24-hour min/mean/max metrics. MAC addresses, signal identifiers, and raw packets are excluded.

### Deterministic summary

`summaries/current.json` collects source freshness and candidate threshold/trend/comparison signals. These are calculated facts for prioritization, not prose conclusions or recommendations.

## Relationships

- Tasks, cleaning, habits, reading, and events share the same local calendar convention, so recent-period comparisons can be related by date.
- Body/activity and training can be compared over identical seven-day windows. Correlation is not causation; do not claim a workout caused a body or activity change.
- Environment timestamps are observation-time facts and may be compared with other time-based data only when windows overlap.
- AI usage is operational capacity data. It should not be treated as a measure of productivity or quality.

The exporter intentionally does not include journals, voice notes, OCR images, network/device logs, detailed media histories, external calendar caches, raw health telemetry, or database files.

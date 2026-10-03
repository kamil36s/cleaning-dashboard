# Phone Telemetry Architecture Note

## Current dashboard findings

- Stack: Vite + vanilla JavaScript ES modules + static `index.html` + shared `styles.css`.
- Widget pattern: each dashboard card lives in `index.html` and is powered by a dedicated module in `js/`.
- Widget ordering and visibility are controlled by `data/widget-order.json` and `js/widget-order.js`.
- Existing local file import pattern already exists for habits in `js/habit-upload.js`, but that flow posts a database file to the Python backend. Phone telemetry should start with direct client-side JSON import because the exported Android files are already structured.

## Why the Android app should be separate

The current repository is a web dashboard. It cannot call Android-only APIs such as:

- `UsageStatsManager`
- `UsageEvents`
- `NotificationListenerService`
- `WorkManager`
- `MediaStore`

Those APIs require a native Android project, Android permissions, a device, and Android Studio. Keeping the collector separate is the correct architecture because:

- the Android app owns data collection and permission handling
- the dashboard stays simple and reads exported files only
- the schema becomes the contract between the two parts
- debugging is easier because collection problems and visualization problems are isolated

## Export format

Phase 1 uses versioned JSON exports with one logical export object per file:

- `schemaVersion`: schema contract version, starting at `1.0.0`
- `exportKind`: fixed discriminator, `phoneTelemetryExport`
- `exportedAt`: ISO timestamp for when the file was written
- `timezone`: IANA timezone string from the phone
- `device`: metadata about the source phone and app build
- `privacy`: export privacy settings, especially notification text handling
- `appUsageSessions`: foreground app sessions reconstructed from usage events
- `phoneSessions`: unlock-to-lock sessions
- `notificationEvents`: notification-derived communication events
- `dailyAggregates`: precomputed daily summaries for fast ingestion and cross-checking

This format is explicit, diffable, and easy to inspect by hand.

## Dashboard ingestion flow

Phase 1 ingestion is file-based:

1. user exports JSON files from Android
2. user imports one or more JSON files in the dashboard
3. client-side parser validates `exportKind` and `schemaVersion`
4. parser normalizes and merges records across imported files
5. pure analytics utilities calculate metrics for the selected day
6. widget renders overview metrics, charts, and lists

This keeps the first version offline and easy to reason about.

## Phase split

### Phase 1

- versioned schema
- mock JSON exports
- client-side parser and validation
- reusable analytics utilities
- dashboard widget with local JSON import
- Android architecture docs and starter Kotlin files

### Later phases

- better notification privacy controls
- stronger Android foreground/background session reconstruction
- import persistence and richer merge conflict handling
- optional automatic sync to a watched folder or small backend
- notification-to-app-open correlation refinement

## Proposed feature structure

```text
docs/
  phone-telemetry/
    architecture.md
    schema.md
  phone-telemetry-android/
    README.md
    dependencies.md
    implementation-notes.md
    app/
      src/main/manifests/AndroidManifest.snippet.xml
      src/main/java/com/cleaningdashboard/phonetelemetry/
        MainActivity.kt
        permissions/UsageAccessHelper.kt
        notifications/NotificationCaptureService.kt
        data/UsageRepository.kt
        data/local/TelemetryEntities.kt
        data/local/TelemetryDao.kt
        data/local/TelemetryDatabase.kt
        export/DailyExportFileModel.kt
        export/ExportSerializer.kt
        export/MediaStoreExportWriter.kt
        export/ExportWorker.kt

data/
  phone-telemetry/
    mock-export-2026-03-12.json
    mock-export-2026-03-13.json
    mock-export-2026-03-14.json
    mock-bundle.json

js/
  phone-telemetry/
    schema.js
    parser.js
    analytics.js
    formatters.js
    phone-telemetry.types.d.ts
  widget-phone-telemetry.js

tests/
  phone-telemetry-parser.test.js
  phone-telemetry-analytics.test.js
```

## Concrete implementation plan

1. Lock the JSON schema and document each record type.
2. Create realistic mock exports so the dashboard UI can be built before the Android collector exists.
3. Build pure parser and analytics utilities and cover them with Vitest.
4. Add a new `Phone Telemetry` card to `index.html`, then wire import, date selection, empty/error states, and charts.
5. Add Android planning files and Kotlin starter code in `docs/phone-telemetry-android/`.
6. Validate with tests and a production build.

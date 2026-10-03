# Phone Telemetry Android Starter

This folder is a planning and starter-code scaffold for a separate Android Studio project.

It is intentionally not wired into the web dashboard build. The dashboard repo is the consumer of exported telemetry files. The Android app is the producer.

## Goal

Build a native Android collector that:

- reads app usage and session history from `UsageStatsManager` and `UsageEvents`
- captures notification-based communication events through `NotificationListenerService`
- stores raw local records in Room
- exports one structured JSON file per day through `WorkManager`
- writes exports to user-visible storage using `MediaStore`

## Why Room was chosen

Phase 1 uses Room instead of direct NDJSON writes because the collector has to handle:

- repeated background inserts
- deduplication across multiple sync passes
- joins across app sessions, phone sessions, and notifications
- export retries after a failed write
- future privacy re-export without recollecting device data

JSON files are still the export format, but Room is the local capture layer.

## Suggested package structure

```text
com.cleaningdashboard.phonetelemetry
  MainActivity.kt
  permissions/
    UsageAccessHelper.kt
  notifications/
    NotificationCaptureService.kt
  data/
    UsageRepository.kt
    local/
      TelemetryEntities.kt
      TelemetryDao.kt
      TelemetryDatabase.kt
  export/
    DailyExportFileModel.kt
    ExportSerializer.kt
    MediaStoreExportWriter.kt
    ExportWorker.kt
```

## Core flow

1. `MainActivity` shows permission status and launch buttons for special-access settings.
2. `UsageRepository` queries usage events for a target day and stores reconstructed sessions.
3. `NotificationCaptureService` receives posted notifications and stores message-like metadata.
4. `ExportWorker` runs daily, loads yesterday's records from Room, serializes them, and writes a JSON export file.
5. The user imports those files into the web dashboard.

## Important Android realities

- `PACKAGE_USAGE_STATS` is a special access, not a normal runtime permission.
- Notification listener access is granted in system settings, not through the usual runtime permission dialog.
- Different apps expose different notification metadata. Conversation IDs and sender names are best-effort fields.
- Exact foreground/background reconstruction is approximate and should be treated as "best possible from Android APIs", not perfect truth.

## First Android Studio steps

1. Create a new Android Studio project for package `com.cleaningdashboard.phonetelemetry`.
2. Add the dependencies listed in `dependencies.md`.
3. Copy the Kotlin starter files into the Android project.
4. Add the manifest snippet from `app/src/main/manifests/AndroidManifest.snippet.xml`.
5. Run on a real Android device and manually grant usage access and notification listener access.

# Phone Telemetry Schema

This schema is designed for daily Android exports that the dashboard can merge later.

## Top-level export object

```json
{
  "exportKind": "phoneTelemetryExport",
  "schemaVersion": "1.0.0",
  "exportedAt": "2026-03-14T00:05:00+01:00",
  "timezone": "Europe/Warsaw",
  "device": {
    "deviceId": "pixel7-demo",
    "deviceLabel": "Pixel 7",
    "manufacturer": "Google",
    "model": "Pixel 7",
    "sdkInt": 34,
    "osVersion": "14",
    "appVersionName": "0.1.0",
    "appVersionCode": 1
  },
  "privacy": {
    "storeNotificationText": true,
    "notificationTextMode": "raw"
  },
  "dayRange": {
    "startDay": "2026-03-14",
    "endDay": "2026-03-14"
  },
  "appUsageSessions": [],
  "phoneSessions": [],
  "notificationEvents": [],
  "dailyAggregates": []
}
```

## `appUsageSessions`

Foreground app sessions reconstructed from `UsageEvents`.

```json
{
  "id": "app-20260314-001",
  "day": "2026-03-14",
  "appPackage": "com.whatsapp",
  "appLabel": "WhatsApp",
  "sessionStart": "2026-03-14T06:52:00+01:00",
  "sessionEnd": "2026-03-14T06:58:00+01:00",
  "durationSeconds": 360,
  "category": "messaging",
  "unlockSessionId": "unlock-20260314-001"
}
```

## `phoneSessions`

Unlock-to-lock screen sessions.

```json
{
  "id": "unlock-20260314-001",
  "day": "2026-03-14",
  "screenUnlockTime": "2026-03-14T06:52:00+01:00",
  "screenLockTime": "2026-03-14T07:06:00+01:00",
  "durationSeconds": 840
}
```

## `notificationEvents`

Notification-derived communication events collected from `NotificationListenerService`.

```json
{
  "id": "notif-20260314-001",
  "day": "2026-03-14",
  "timestamp": "2026-03-14T07:18:12+01:00",
  "sourceAppPackage": "com.whatsapp",
  "sourceAppLabel": "WhatsApp",
  "senderOrThreadTitle": "Alex",
  "conversationId": "wa:alex",
  "previewAvailable": true,
  "messageCount": 1,
  "isGroup": false,
  "eventSource": "notification",
  "messageLike": true,
  "rawTitle": "Alex",
  "rawText": "Leaving in 10 minutes"
}
```

Notes:

- `messageLike` is the Android app's best heuristic for "this notification behaves like a message".
- `senderOrThreadTitle` and `conversationId` are nullable because not all apps expose them.
- When privacy mode disables text storage, `rawTitle` and `rawText` should be `null`.

## `dailyAggregates`

Precomputed daily rollups for fast loading and cross-checking.

```json
{
  "day": "2026-03-14",
  "totalPhoneMinutes": 165,
  "unlockCount": 28,
  "notificationCount": 92,
  "messageLikeNotificationCount": 34,
  "appSwitchCount": 57,
  "nightUsageMinutes": 21,
  "topApps": [
    {
      "appPackage": "com.whatsapp",
      "appLabel": "WhatsApp",
      "durationSeconds": 2460,
      "sessionCount": 7
    }
  ],
  "topContactsOrThreads": [
    {
      "label": "Alex",
      "conversationId": "wa:alex",
      "messageLikeCount": 8,
      "sourceAppPackage": "com.whatsapp",
      "sourceAppLabel": "WhatsApp"
    }
  ]
}
```

## Privacy modes

`privacy.notificationTextMode` is intentionally explicit:

- `raw`: keep `rawTitle` and `rawText`
- `redacted`: keep metadata but store redacted text later
- `disabled`: store only structural metadata and set raw text fields to `null`

Phase 1 keeps the schema ready for privacy settings even if the Android app starts with `raw`.

## Mock files

For local development, use:

- `data/phone-telemetry/mock-export-2026-03-12.json`
- `data/phone-telemetry/mock-export-2026-03-13.json`
- `data/phone-telemetry/mock-export-2026-03-14.json`
- `data/phone-telemetry/mock-bundle.json`

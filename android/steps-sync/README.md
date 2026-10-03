# Cleaning Dashboard Steps Sync

Minimal Android app that reads today's Health Connect data and posts it to the dashboard.

It sends:

- steps to `/api/steps/events/upsert`, which feeds the reduction widget chart
- a full Health Connect snapshot to `/api/health-connect/snapshot`

The snapshot currently includes steps, active calories, distance, elevation gained, speed samples, exercise sessions, exercise route status/data when available, sleep sessions/stages, heart rate samples, and oxygen saturation samples.

Default config in the app:

- Dashboard URL: `http://192.168.0.136:8000`
- Token: `Steps2137!`

Both can be edited on the first screen.

## Build

```powershell
.\build-debug.cmd
```

Debug APK:

```text
app\build\outputs\apk\debug\app-debug.apk
```

## Install over USB

1. Enable Developer options on the phone.
2. Enable USB debugging.
3. Connect the phone and accept the RSA prompt.
4. Run:

```powershell
.\install-debug.cmd
```

## First run

1. Tap `Grant Health Connect access`.
2. Allow the requested Health Connect data types.
3. Tap `Sync now`.
4. Tap `Enable 15-minute background sync`.

The dashboard server must be running with:

```powershell
$env:DASHBOARD_STEPS_WRITE_TOKEN="Steps2137!"
$env:DASHBOARD_HOST="0.0.0.0"
py server.py
```

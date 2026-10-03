# Health Connect Steps Sync

This is the phone-side bridge for:

```text
Xiaomi Watch 2 / Mi Fitness -> Health Connect on phone -> cleaning-dashboard steps API
```

The dashboard already stores steps in `data/scale/steps.json` and the reduction widget reads them through:

- `GET /api/steps/history`
- `GET /api/steps/events`
- `POST /api/steps/events/upsert`

## Dashboard setup

Set a write token before starting `server.py`:

```powershell
$env:DASHBOARD_STEPS_WRITE_TOKEN="change-me-long-random-token"
py server.py
```

The phone posts:

```http
POST http://PC-LAN-IP:8000/api/steps/events/upsert
Authorization: Bearer change-me-long-random-token
Content-Type: application/json

{
  "day": "2026-05-15",
  "steps": 12345,
  "source": "health-connect"
}
```

Quick LAN test from another device:

```bash
curl -X POST "http://PC-LAN-IP:8000/api/steps/events/upsert" \
  -H "Authorization: Bearer change-me-long-random-token" \
  -H "Content-Type: application/json" \
  -d '{"day":"2026-05-15","steps":12345,"source":"health-connect"}'
```

## Android app shape

Use a tiny native Android app, not Google Fit:

1. Ask for Health Connect `READ_STEPS`.
2. Aggregate today's `StepsRecord.COUNT_TOTAL`.
3. POST it to the dashboard every 15-60 minutes with WorkManager.
4. Keep manual entry in the widget as fallback.

Files in this folder are copyable starters for an Android Studio project.

## Phone settings checklist

1. Install/open Health Connect on the phone.
2. In Mi Fitness, enable writing steps to Health Connect if the option exists.
3. In Health Connect, grant the sync app read access to Steps.
4. Make sure the phone can reach the dashboard machine on LAN, e.g. `http://192.168.x.x:8000`.

If Mi Fitness does not write steps into Health Connect, the fallback is a small Wear OS app later. We do not need that first.

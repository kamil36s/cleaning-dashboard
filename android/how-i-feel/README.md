# How I Feel Android

Native, local-first companion for the dashboard's How I Feel feature. The phone reads the
canonical emotion catalog and history from the PC and writes check-ins directly to the same
`data/feelings.sqlite` database. Failed writes are retained in an app-private queue and retried
the next time the app connects. The server URL is stored privately and the bearer token is
encrypted with Android Keystore.

## PC configuration

Start the dashboard API on the LAN and configure a dedicated token before starting `server.py`:

```powershell
$env:DASHBOARD_HOST = "0.0.0.0"
$env:DASHBOARD_FEELINGS_TOKEN = "use-a-long-random-secret"
python server.py
```

In the Android app enter `http://<PC-LAN-IP>:8000` and the same token. A dedicated
`DASHBOARD_FEELINGS_TOKEN` is preferred; the existing `DASHBOARD_HABITS_TOKEN` and general
`DASHBOARD_WRITE_TOKEN` are also accepted so the current Habits phone setup can be reused.

## Build and install

```powershell
.\build-debug.cmd
.\install-debug.cmd
```

APK: `app\build\outputs\apk\debug\app-debug.apk`

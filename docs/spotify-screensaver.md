# Spotify Screensaver

This project includes a Windows-friendly pseudo-screensaver:

- `spotify-dashboard-server.js` serves the dashboard and `GET /api/screensaver-status`.
- `spotify-screensaver.html` is available at `/spotify-screensaver`.
- `spotify-screensaver.ahk` watches Windows idle time and opens Chrome kiosk mode.

## Configuration

Set these values in your shell, `.env`, or `.env.development`.

```bat
set PORT=4173
set DASHBOARD_URL=http://localhost:4173
set SPOTIFY_CLIENT_ID=your-client-id
set SPOTIFY_CLIENT_SECRET=your-client-secret
set SPOTIFY_REDIRECT_URI=http://localhost:4173/api/spotify/oauth/callback
```

`PORT` and `DASHBOARD_URL` can be any available local port and matching URL.
Add the exact `SPOTIFY_REDIRECT_URI` value to the Spotify app's Redirect URIs in the Spotify Developer Dashboard.

If you use the existing Python API server from `start-dev.cmd`, use this redirect URI instead:

```bat
set SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/api/spotify/oauth/callback
```

The first manual visit to the screensaver opens Spotify authorization and stores the returned refresh token in `data/spotify/state.json`.
Playback controls require the `user-modify-playback-state` scope. If you connected Spotify before this was added, reconnect Spotify from Settings -> Spotify screensaver.

The watcher can also be configured with environment variables:

```bat
set IDLE_MINUTES=3
set CHECK_INTERVAL_MS=5000
set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
set CHROME_PROFILE_DIR=C:\Users\kamil\AppData\Local\SpotifyScreensaverChrome
```

Idle timing can also be changed from Dashboard Settings -> Spotify screensaver. The AutoHotkey watcher reads `/api/screensaver-config` on each check, so changes apply without editing the `.ahk` file.

## Run

Start the dashboard:

```bat
npm run start:dashboard
```

Then open:

```text
%DASHBOARD_URL%/spotify-screensaver
```

Start the idle watcher:

```bat
start-spotify-screensaver-watcher.bat
```

Or start both:

```bat
start-dashboard-and-watcher.bat
```

## Spotify Behavior

`GET /api/screensaver-status` returns `shouldShow: true` only when Spotify is authenticated and a track is actively playing. Paused playback, no active device, authentication failure, dashboard downtime, or Spotify API errors all result in `shouldShow: false`.

For the automatic AutoHotkey watcher, point `DASHBOARD_URL` at the server that serves both `/api/screensaver-status` and `/spotify-screensaver`. With the Python API server this is usually:

```bat
set DASHBOARD_URL=http://127.0.0.1:8000
```

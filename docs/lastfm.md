# Last.fm integration

The dashboard keeps Last.fm credentials in the ignored `.env.development` file and listening data in the ignored `data/lastfm.sqlite` database. The shared secret never reaches browser code. Read-only `user.getRecentTracks` synchronization only needs `LASTFM_API_KEY` and `LASTFM_USERNAME`.

## Initial import

Use the CSV export; the multi-page JSON export can contain overlapping pages when scrobbles arrive during export.

```powershell
python scripts/import_lastfm.py "C:\path\to\recenttracks.csv"
```

The import is idempotent. It preserves the complete raw scrobble history and builds album/artist summaries plus exact day/week/month/year charts. Local database size is not treated as an API request or cache limit.

## Synchronization

While `server.py` is running, it checks `user.getRecentTracks` every 30 minutes by default. The minimum accepted interval is 15 minutes. Configure it with:

```dotenv
LASTFM_SYNC_INTERVAL_MINUTES=30
```

The request starts six hours before the newest stored scrobble, then relies on the database uniqueness constraint to remove overlap. A manual refresh is available with `POST /api/lastfm/sync`; status is available at `GET /api/lastfm/status`.

Album widgets send their visible artist/album pairs to `POST /api/lastfm/match`. The Great Timeline receives precomputed Last.fm charts through its existing activity endpoint and switches automatically between day, week, month and year as the user zooms.

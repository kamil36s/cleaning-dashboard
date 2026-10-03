# Cinema City widget data sources

The dashboard widget uses the official Cinema City quickbook feed through the local
`GET /api/cinema-city/repertoire` endpoint as its primary source of truth. The backend
caches the result for 10 minutes and returns only future, non-sold-out screenings for
Cinema City Galeria Kazimierz (`cinemaId` 1076 by default).

If that feed is temporarily unavailable, the widget falls back to the existing Google
Calendar sync. It reads dashboard events from `GET /api/events` with local JSON disabled
and keeps only events from the Google Calendar named `Cinema City Galeria Kazimierz`
whose description contains `AUTO_CINEMA_CITY`.

The feed configuration can be overridden with `CINEMA_CITY_REPERTOIRE_API_ROOT`,
`CINEMA_CITY_CINEMA_ID`, `CINEMA_CITY_REPERTOIRE_DAYS`, and
`CINEMA_CITY_REPERTOIRE_CACHE_SECONDS`.

## Monthly stats from Google Sheets

The monthly Unlimited summary is isolated in `js/cinema-city-stats-adapter.js` and reads:

- endpoint: `GET /api/cinema-city/monthly-stats`
- spreadsheet: `1WqWJEOCg8qC-l2S7CA4Dwog3nQ18tCAlbFf_4d5aoog`
- sheet tab: `Filters`
- range: `A:Z`

The backend counts non-empty watched-movie cells in `D2:D` and reads `E2` as the total average ticket price (`pricePerFilm`). `E2` is expected to contain the spreadsheet formula for the lifetime/total average, for example:

```text
=IFERROR(((DATEDIF(DATE(2026, 5, 21), TODAY(), "m") + 1) * 50.99) / COUNTA(D2:D), 0)
```

To use this endpoint, the same Google OAuth setup used by Calendar must also have:

- Google Sheets API enabled in Google Cloud
- OAuth scope: `https://www.googleapis.com/auth/spreadsheets.readonly`
- a fresh reconnect through `/api/google-calendar/auth/start`

If the sheet layout changes, override these env vars before starting the backend:

- `CINEMA_CITY_SHEET_ID`
- `CINEMA_CITY_SHEET_NAME`
- `CINEMA_CITY_SHEET_RANGE`
- `CINEMA_CITY_WATCHED_START_CELL` (defaults to `D2`)
- `CINEMA_CITY_AVERAGE_CELL` (defaults to `E2`)

Keep this adapter read-only. It should not fetch Cinema City repertory data.

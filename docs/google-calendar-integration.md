# Google Calendar integration

This dashboard is prepared for Google Calendar two-way sync.

## What is already wired

- `GET /api/events`
  - returns local `data/events.json`
  - adds cached Google Calendar events when connected
  - runs incremental Google sync by default with `sync=1`

- `GET /api/google-calendar/status`
  - checks config, connection, calendars, sync cache, and token state

- `GET /api/google-calendar/calendars`
  - returns the Google Calendar list used by the widget calendar filter

- `GET /api/google-calendar/auth/start`
  - starts OAuth and redirects to Google

- `GET /api/google-calendar/oauth/callback`
  - receives the OAuth code
  - stores access/refresh token in `data/google-calendar/state.json`
  - runs initial sync

- `POST /api/google-calendar/sync`
  - body: `{ "force": false }`
  - runs manual sync

- `POST /api/events/google/upsert`
  - creates or updates a Google Calendar all-day event from the dashboard event model
  - safety rule: only existing Google Calendar events and `payday` events can be written to Google
  - local JSON/widget events are read-only toward Google until this guard is intentionally changed

- `POST /api/events/google/delete`
  - deletes a Google Calendar event by `calendarId` + `eventId`

Token/cache files live in `data/google-calendar/`. This directory is gitignored and blocked from static serving by `server.py`.

## Google Cloud setup

1. Go to Google Cloud Console.
2. Create/select a project.
3. Enable **Google Calendar API**.
4. Configure OAuth consent screen.
   - For personal/local use, Testing mode is fine.
   - Add your Google account as a test user.
5. Create OAuth Client ID.
   - Application type: **Web application**
   - Authorized redirect URI:

```text
http://127.0.0.1:8000/api/google-calendar/oauth/callback
```

6. In `.env.development`, fill:

```text
GOOGLE_CALENDAR_CLIENT_ID=...
GOOGLE_CALENDAR_CLIENT_SECRET=...
GOOGLE_CALENDAR_REDIRECT_URI=http://127.0.0.1:8000/api/google-calendar/oauth/callback
GOOGLE_CALENDAR_IDS=auto
```

7. Restart `start-dev.cmd`.
8. Open:

```text
http://127.0.0.1:8000/api/google-calendar/auth/start
```

9. Approve access. When the success page appears, refresh the dashboard.

## Recommended calendar setup

For clean two-way sync, create a separate Google Calendar named something like:

```text
Dashboard Important Dates
```

Then put its calendar ID in:

```text
GOOGLE_CALENDAR_IDS=your_calendar_id@group.calendar.google.com
```

Using `primary` also works, but a dedicated calendar keeps dashboard-created events separate from regular meetings.
Use `GOOGLE_CALENDAR_IDS=auto` to import all calendars available in the Google Calendar list.
This requires both scopes:

```text
https://www.googleapis.com/auth/calendar.events
https://www.googleapis.com/auth/calendar.calendarlist.readonly
```

If you previously connected with only `calendar.events`, reconnect via:

```text
http://127.0.0.1:8000/api/google-calendar/auth/start
```

## Current sync policy

The initial direction is:

```text
Google Calendar -> widget
```

The widget does **not** automatically migrate local JSON events to Google Calendar.

Writes back to Google are intentionally restricted:

- allowed: edit an event that originally came from Google Calendar
- allowed: create/update payday events
- blocked: local public holidays
- blocked: local trips/concerts
- blocked: local deadlines
- blocked: local custom events

This keeps testing safe while importing real calendar data into the widget first.

## Dashboard event metadata in Google

The integration stores dashboard-only fields in:

```text
extendedProperties.private
```

Current fields:

- `dashboardType`
- `dashboardEventId`
- `isDayOff`
- `isShortDay`
- `actionNeeded`
- `actionStatus`

This lets Google events round-trip into the same internal widget format.

## Local dev behavior

The widget first tries:

```text
./api/events?sync=1
```

With Vite, `/api` is proxied to:

```text
http://127.0.0.1:8000
```

If the backend is down or Google is not configured, it falls back to:

```text
./data/events.json
```

## Live updates

Current implementation uses incremental sync with Google `syncToken`.

For local dev, this is the right first step. True push requires a public HTTPS webhook URL, because Google Calendar push notifications call your server. That can be added later with:

- `events.watch`
- `/api/google-calendar/webhook`
- periodic channel renewal

Even with push, Google sends only "something changed", so the backend still performs incremental sync after receiving the notification.

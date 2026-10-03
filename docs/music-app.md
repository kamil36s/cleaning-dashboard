# Muzyka — architecture and imports

`music.html` is a dashboard-native client for the canonical Music catalog. The
browser talks to `/api/music/*` in the existing Python server. Persistent state
lives in `data/music.sqlite`; saved source files are copied to the ignored
`data/music-imports/` directory by SHA-256. This follows the repository's
module-per-database convention and keeps the three older projects independent.

## Data model

The schema is initialized idempotently by `MusicStore.initialize()` and recorded
in `music_schema_migrations`. Artists, releases, release credits, tracks,
genres, genre relations, descriptors and external IDs are relational. Chart
definitions, immutable source snapshots and ranking entries are separate.
The visible genre tree is sourced from RYM imports. Migration 4 removes genres
that metadata providers had inserted into that tree; their observed tags remain
available in metadata values.
Personal ratings, rankings and generic lists are also separate concepts.

Changing source observations are stored in `music_source_records` and
`music_release_metric_snapshots`, linked to a traceable import batch. The schema
also reserves indexed mappings for the existing Last.fm scrobble IDs. Actual
history remains authoritative in the existing `data/lastfm.sqlite`.

## Import flow

1. The user selects a locally saved RYM HTML file. No RYM page is requested.
2. `RYMPageDetector` identifies a genre index, chart or release page from DOM
   structure and semantic URLs.
3. The matching parser returns a normalized DTO without database writes.
4. `MusicStore.preview_import()` preserves the source, stages every row and
   assigns `EXACT_MATCH`, `LEGACY_MATCH`, `LIKELY_MATCH`, `AMBIGUOUS`, `NEW` or
   `ERROR`.
5. The Imports screen lets the user create, accept a candidate or skip a row.
6. Commit runs in one SQLite transaction. A failure rolls back releases,
   relations and the ranking snapshot together.

Saved RYM collection pages also contain personal half-star ratings and rating
dates. They use the same staging flow, but never create chart snapshots or
community rating metrics. The importer links releases by RYM ID first and
keeps existing Music or legacy personal ratings when they conflict. The source
rating remains in the archived import row and the conflict is reported.

For a numbered offline collection, run `python -m scripts.import_rym_collection
<folder> --dry-run`, review ambiguous rows, then run it without `--dry-run`.
The command validates every page, backs up the Music SQLite database, imports
the HTML locally and attaches saved WebP thumbnails where no local cover exists.
The JSON report is written under `data/music-imports/`.

The artist ranking groups effective personal ratings by primary artist and
includes only releases with type `Album`. It counts each album once per artist,
includes collaborations for each credited artist, and lets the reader set a
minimum number of rated albums. Weighted score uses the same BM365 prior:
`(artist rating sum + 3 * global average album rating) / (artist album count + 3)`.
The user can sort by weighted or arithmetic average.
Library filters can show rated and unrated releases independently and select
an exact release year, a decade or an inclusive year range. The artist ranking
uses the same year selection and recalculates its global album average for the
selected period.
The library defaults to descending effective personal rating and can also sort
by RYM community average, release year, artist or title. Missing ratings sort
last. The listened filter reads only the separate status from linked legacy
projects; an imported RYM personal rating does not set that status.

The same file hash points back to its existing batch. Another capture of the
same chart creates a new snapshot while reusing releases. Release pages enrich
the release first created by a chart because the RYM ID/URL is resolved before
text matching.

## Matching

Matching priority is exact external ID/normalized RYM URL, exact known legacy
mapping, normalized artist + title + compatible year/type, and finally fuzzy
candidates. Fuzzy candidates are always marked ambiguous and are never merged
silently. Original strings remain in source DTOs.

## Protected legacy boundary

`music_legacy_adapters.py` only calls the public read methods of Black Metal
365, Brutal Assault 2027 and Top 100 RYM Polish BM. It provides compact project
summaries and conservative match candidates. The Music commit may write a
`music_legacy_links` mapping, but it never changes legacy rows, schemas, routes,
ratings or UI.

## Last.fm

Music reuses `LASTFM_STORE`, its environment configuration, sync loop and
cached SQLite data. `music_history()` adds a paginated read model and optional
server-side now-playing lookup. No key reaches frontend JavaScript and no second
Last.fm database is created.

## Adding another source

Add a side-effect-free parser that returns the existing release/genre DTO
shape, register it in a structural detector, and stage its output through
`MusicStore.preview_import()`. Add source-specific external IDs and observations
instead of source columns on canonical release identity.

## Automatic metadata enrichment

`music_enrichment.py` runs one daemon worker inside `server.py` after the normal
Music startup sync. It adds at most 50 new releases to `music_enrichment_jobs`
at a time. Missing covers get priority; the rest of the catalog is backfilled
gradually. The Import screen shows queue and coverage counts and can enqueue
another batch. Opening an album does not call external providers. The existing
single cover button now queues that release. Set `MUSIC_ENRICHMENT_ENABLED=false`
to stop external enrichment while retaining all catalog functionality.

Migration 3 only adds `music_metadata_values`, `music_metadata_checks`,
`music_provider_payloads`, `music_enrichment_jobs` and `music_artwork_cache`.
Provider values, source IDs, confidence, timestamps and negative checks stay
separate from user ratings and imported source snapshots. Album fields are
filled only when empty. Small covers are replaced when a verified larger image
is available.
Small existing covers (under 300 pixels on either side) are queued once for a
larger replacement. Manual and already adequate artwork stays in place.
Downloads are deduplicated by SHA-256 under `covers/music-*`; the database stores
the local path and original source. JSON responses are cached locally. A found
check is kept for ten years, a missing result for 90 days, and a transient error
for one day. Manual requeue does not discard this cache.

Matching requires one exact MusicBrainz release-group title and artist credit,
with the first release year within one year when available. Ambiguous candidates
are marked unresolved; they never become canonical IDs. An existing MusicBrainz
release-group ID takes precedence. Discogs, TheAudioDB and Apple cover lookups
also require exact artist and album titles. The fallback order is per field:

| Field | Source order |
| --- | --- |
| Cover | Cover Art Archive release group, Cover Art Archive release, Discogs, TheAudioDB, Apple |
| Date/year | MusicBrainz release group and release, Discogs edition/date or master/year, Apple date |
| Type, genre | MusicBrainz release group; Discogs genre observation |
| Label, catalog number, barcode, format | MusicBrainz release, Discogs main edition |
| Country | MusicBrainz release |
| Track list and credits | MusicBrainz release, Discogs main edition |
| Artist photo | Wikimedia Commons through MusicBrainz→Wikidata ID, TheAudioDB |
| Artist facts and links | MusicBrainz, then Wikidata |
| Album description | TheAudioDB when configured |

Discogs needs `MUSIC_DISCOGS_TOKEN`; TheAudioDB needs `MUSIC_AUDIODB_KEY`.
Both are skipped when unset. MusicBrainz, Cover Art Archive, Wikidata,
Wikimedia Commons and Apple need no key. Set `MUSIC_METADATA_USER_AGENT` with a
real contact address before bulk backfill. Each provider has a separate serial
request interval, a timeout, up to two retries with exponential delay and
`Retry-After` support, and a five-minute cooldown after repeated failures.
Intervals and timeouts can be increased with `MUSIC_<PROVIDER>_INTERVAL` and
`MUSIC_<PROVIDER>_TIMEOUT`; providers can be disabled individually with
`MUSIC_<PROVIDER>_ENABLED=false`.

`GET /api/music/enrichment/status` reports coverage, queue state and provider
state. `POST /api/music/enrichment/queue` with `{ "limit": 50 }` schedules a
batch; `{ "releaseId": 123 }` schedules one release. Runtime API errors and
unresolved matches are visible in the status response. The backup created before
the first migration is `data/music.sqlite.pre-enrichment-20260929.bak`.


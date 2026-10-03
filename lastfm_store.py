from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


WARSAW = ZoneInfo("Europe/Warsaw")
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
MIN_SYNC_INTERVAL_SECONDS = 15 * 60
DEFAULT_SYNC_INTERVAL_SECONDS = 30 * 60
EDITION_WORDS = r"remaster(?:ed)?|deluxe|expanded|anniversary|bonus|reissue|special\s+edition"
EDITION_SUFFIX_RE = re.compile(
    rf"\s*(?:[-–—:]\s*)?(?:\([^)]*(?:{EDITION_WORDS})[^)]*\)|"
    rf"\[[^]]*(?:{EDITION_WORDS})[^]]*\]|(?:{EDITION_WORDS}).*)\s*$",
    re.IGNORECASE,
)


class LastFmError(RuntimeError):
    pass


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def normalize_name(value, *, album=False):
    text = str(value or "").strip().casefold().translate(str.maketrans({
        "ł": "l", "ø": "o", "đ": "d", "ð": "d", "þ": "th", "æ": "ae", "œ": "oe",
    }))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ").replace("’", "'")
    if album:
        previous = None
        while previous != text:
            previous = text
            text = EDITION_SUFFIX_RE.sub("", text).strip()
    normalized = " ".join("".join(char if char.isalnum() else " " for char in text).split())
    if normalized or not text:
        return normalized
    return "symbol:" + ",".join(f"{ord(char):x}" for char in text if not char.isspace())


def _period_keys(uts):
    local = datetime.fromtimestamp(int(uts), WARSAW)
    day = local.date()
    week = day - timedelta(days=day.weekday())
    return day.isoformat(), week.isoformat(), day.strftime("%Y-%m"), str(day.year)


class LastFmStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "data" / "lastfm.sqlite"
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._sync_thread = None

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scrobbles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uts INTEGER NOT NULL,
                    local_day TEXT NOT NULL,
                    local_week TEXT NOT NULL,
                    local_month TEXT NOT NULL,
                    local_year TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    artist_key TEXT NOT NULL,
                    album TEXT NOT NULL DEFAULT '',
                    album_key TEXT NOT NULL DEFAULT '',
                    track TEXT NOT NULL,
                    track_key TEXT NOT NULL,
                    UNIQUE (uts, artist_key, album_key, track_key)
                );
                CREATE INDEX IF NOT EXISTS idx_lastfm_day ON scrobbles(local_day);
                DROP INDEX IF EXISTS idx_lastfm_uts;
                DROP INDEX IF EXISTS idx_lastfm_artist;
                DROP INDEX IF EXISTS idx_lastfm_album;
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS period_charts (
                    granularity TEXT NOT NULL,
                    period TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (granularity, period)
                );
                CREATE TABLE IF NOT EXISTS artist_stats (
                    artist_key TEXT PRIMARY KEY,
                    artist TEXT NOT NULL,
                    scrobbles INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS album_stats (
                    artist_key TEXT NOT NULL,
                    album_key TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT NOT NULL,
                    scrobbles INTEGER NOT NULL,
                    unique_tracks INTEGER NOT NULL,
                    first_uts INTEGER NOT NULL,
                    last_uts INTEGER NOT NULL,
                    last_track TEXT NOT NULL,
                    PRIMARY KEY (artist_key, album_key)
                );
                CREATE TABLE IF NOT EXISTS album_tracks (
                    artist_key TEXT NOT NULL,
                    album_key TEXT NOT NULL,
                    track_key TEXT NOT NULL,
                    PRIMARY KEY (artist_key, album_key, track_key)
                );
                CREATE TABLE IF NOT EXISTS media_cache (
                    artist_key TEXT NOT NULL,
                    album_key TEXT NOT NULL,
                    image_url TEXT,
                    checked_at INTEGER NOT NULL,
                    PRIMARY KEY (artist_key, album_key)
                );
                """
            )

    @staticmethod
    def _clean_row(row):
        try:
            uts = int(row.get("uts") or row.get("date", {}).get("uts"))
        except (TypeError, ValueError, AttributeError):
            return None
        artist_value = row.get("artist")
        album_value = row.get("album")
        if isinstance(artist_value, dict):
            artist = artist_value.get("#text") or artist_value.get("name") or ""
        else:
            artist = artist_value or ""
        if isinstance(album_value, dict):
            album = album_value.get("#text") or ""
        else:
            album = album_value or ""
        track = row.get("track") or row.get("name") or ""
        if not str(artist).strip() or not str(track).strip():
            return None
        local_day, local_week, local_month, local_year = _period_keys(uts)
        return (
            uts, local_day, local_week, local_month, local_year,
            str(artist).strip(), normalize_name(artist),
            str(album).strip(), normalize_name(album, album=True),
            str(track).strip(), normalize_name(track),
        )

    @staticmethod
    def _insert_sql():
        return """
            INSERT OR IGNORE INTO scrobbles (
                uts, local_day, local_week, local_month, local_year,
                artist, artist_key, album, album_key, track, track_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

    def import_csv(self, source_path):
        source = Path(source_path)
        if not source.exists():
            raise LastFmError(f"Last.fm CSV does not exist: {source}")
        self.initialize()
        processed = inserted = skipped = 0
        started = time.monotonic()
        with self._lock, self._connect() as connection, source.open("r", encoding="utf-8-sig", newline="") as handle:
            batch = []
            for row in csv.DictReader(handle):
                processed += 1
                cleaned = self._clean_row(row)
                if cleaned is None:
                    skipped += 1
                    continue
                batch.append(cleaned)
                if len(batch) >= 5000:
                    before = connection.total_changes
                    connection.executemany(self._insert_sql(), batch)
                    inserted += connection.total_changes - before
                    batch.clear()
            if batch:
                before = connection.total_changes
                connection.executemany(self._insert_sql(), batch)
                inserted += connection.total_changes - before
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('last_import_file', ?)",
                (source.name,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('last_import_at', ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
        self.rebuild_summaries()
        self.rebuild_period_charts()
        with self._connect() as connection:
            connection.execute("VACUUM")
        return {
            "ok": True,
            "file": source.name,
            "processed": processed,
            "inserted": inserted,
            "duplicates": processed - inserted - skipped,
            "skipped": skipped,
            "seconds": round(time.monotonic() - started, 2),
            "status": self.status(),
        }

    def _metadata(self, connection):
        return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}

    def status(self):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(scrobbles), 0) AS total, MIN(first_uts) AS first_uts, "
                "MAX(last_uts) AS last_uts FROM album_stats"
            ).fetchone()
            days = int(connection.execute(
                "SELECT COUNT(*) FROM period_charts WHERE granularity = 'day'"
            ).fetchone()[0])
            metadata = self._metadata(connection)
        configured = bool(os.environ.get("LASTFM_API_KEY", "").strip() and self.username)
        return {
            "configured": configured,
            "username": self.username,
            "totalScrobbles": int(row["total"] or 0),
            "days": days,
            "firstScrobbleAt": self._iso_timestamp(row["first_uts"]),
            "lastScrobbleAt": self._iso_timestamp(row["last_uts"]),
            "lastSyncAt": metadata.get("last_sync_at"),
            "lastSyncError": metadata.get("last_sync_error"),
            "lastImportAt": metadata.get("last_import_at"),
            "lastImportFile": metadata.get("last_import_file"),
            "syncIntervalMinutes": self.sync_interval_seconds // 60,
        }

    def music_history(self, *, period="all", limit=30, offset=0, include_live=False):
        """Small paginated read model used by the Music hub.

        It deliberately reads the existing Last.fm cache instead of creating a
        second scrobble store or exposing the API key to the browser.
        """
        self.initialize()
        period = str(period or "all").lower()
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        local_now = datetime.now(WARSAW)
        filters = {
            "today": ("local_day = ?", local_now.date().isoformat()),
            "week": ("local_week = ?", (local_now.date() - timedelta(days=local_now.weekday())).isoformat()),
            "month": ("local_month = ?", local_now.strftime("%Y-%m")),
            "year": ("local_year = ?", str(local_now.year)),
            "all": ("1=1", None),
        }
        if period not in filters:
            raise LastFmError("Invalid Last.fm history period")
        clause, value = filters[period]
        params = (value,) if value is not None else ()
        with self._connect() as connection:
            totals = connection.execute(
                f"SELECT COUNT(*) AS scrobbles,COUNT(DISTINCT artist_key) AS artists,"
                f"COUNT(DISTINCT CASE WHEN album_key<>'' THEN artist_key||char(0)||album_key END) AS albums,"
                f"COUNT(DISTINCT artist_key||char(0)||track_key) AS tracks FROM scrobbles WHERE {clause}",
                params,
            ).fetchone()
            rows = connection.execute(
                f"SELECT id,uts,artist,album,track FROM scrobbles WHERE {clause} ORDER BY uts DESC,id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            top_artists = connection.execute(
                f"SELECT artist,artist_key,COUNT(*) AS scrobbles FROM scrobbles WHERE {clause} GROUP BY artist_key ORDER BY scrobbles DESC LIMIT 5",
                params,
            ).fetchall()
            top_albums = connection.execute(
                f"SELECT artist,album,COUNT(*) AS scrobbles FROM scrobbles WHERE {clause} AND album_key<>'' "
                "GROUP BY artist_key,album_key ORDER BY scrobbles DESC LIMIT 5",
                params,
            ).fetchall()
            top_artist_albums = {}
            for artist_row in top_artists:
                representative = connection.execute(
                    f"SELECT album FROM scrobbles WHERE {clause} AND artist_key=? AND album_key<>'' "
                    "GROUP BY album_key ORDER BY COUNT(*) DESC,MAX(uts) DESC LIMIT 1",
                    (*params, artist_row["artist_key"]),
                ).fetchone()
                if representative:
                    top_artist_albums[artist_row["artist_key"]] = representative["album"]
        payload = {
            "ok": True,
            "period": period,
            "status": self.status(),
            "stats": {key: int(totals[key] or 0) for key in ("scrobbles", "artists", "albums", "tracks")},
            "rows": [
                {
                    **dict(row),
                    "playedAt": self._iso_timestamp(row["uts"]),
                }
                for row in rows
            ],
            "topArtists": [dict(row) for row in top_artists],
            "topAlbums": [dict(row) for row in top_albums],
            "limit": limit,
            "offset": offset,
        }
        if payload["status"]["configured"]:
            for album in payload["topAlbums"]:
                try:
                    album["cover"] = self._album_info_image(album.get("artist"), album.get("album"))
                except LastFmError:
                    album["cover"] = None
            artist_images = {
                normalize_name(album.get("artist")): album.get("cover")
                for album in payload["topAlbums"] if album.get("cover")
            }
            for artist in payload["topArtists"]:
                artist_key = artist.pop("artist_key", normalize_name(artist.get("artist")))
                artist["image"] = artist_images.get(artist_key)
                if not artist["image"] and top_artist_albums.get(artist_key):
                    try:
                        artist["image"] = self._album_info_image(artist.get("artist"), top_artist_albums[artist_key])
                    except LastFmError:
                        pass
        if include_live and payload["status"]["configured"]:
            try:
                recent = self._api_page(from_uts=max(0, int(time.time()) - 24 * 60 * 60), page=1)
                recent_tracks = (recent.get("recenttracks") or {}).get("track", [])
                recent_media = {}
                for item in recent_tracks:
                    artist_value = item.get("artist") or {}
                    album_value = item.get("album") or {}
                    artist_name = artist_value.get("#text") or artist_value.get("name") or "" if isinstance(artist_value, dict) else artist_value
                    album_name = album_value.get("#text") or "" if isinstance(album_value, dict) else album_value
                    images = item.get("image") or []
                    image = next((entry.get("#text") for entry in reversed(images) if entry.get("#text")), None)
                    if artist_name and album_name and image:
                        recent_media[(normalize_name(artist_name), normalize_name(album_name, album=True))] = image
                for row in payload["rows"]:
                    row["cover"] = recent_media.get((normalize_name(row.get("artist")), normalize_name(row.get("album"), album=True)))
                now_playing = next(
                    (row for row in recent_tracks if (row.get("@attr") or {}).get("nowplaying")),
                    None,
                )
                if now_playing:
                    artist = now_playing.get("artist") or {}
                    album = now_playing.get("album") or {}
                    images = now_playing.get("image") or []
                    payload["nowPlaying"] = {
                        "artist": artist.get("#text") or artist.get("name") or "",
                        "album": album.get("#text") or "",
                        "track": now_playing.get("name") or "",
                        "url": now_playing.get("url"),
                        "image": next((item.get("#text") for item in reversed(images) if item.get("#text")), None),
                    }
            except Exception as exc:
                payload["liveError"] = str(exc)
        return payload

    @property
    def username(self):
        return os.environ.get("LASTFM_USERNAME", "mart3s").strip() or "mart3s"

    @property
    def sync_interval_seconds(self):
        try:
            requested = int(os.environ.get("LASTFM_SYNC_INTERVAL_MINUTES", "30")) * 60
        except ValueError:
            requested = DEFAULT_SYNC_INTERVAL_SECONDS
        return max(MIN_SYNC_INTERVAL_SECONDS, requested)

    @staticmethod
    def _iso_timestamp(uts):
        return datetime.fromtimestamp(int(uts), timezone.utc).isoformat(timespec="seconds") if uts else None

    def _api_page(self, *, from_uts, page):
        api_key = os.environ.get("LASTFM_API_KEY", "").strip()
        if not api_key:
            raise LastFmError("LASTFM_API_KEY is not configured")
        query = urllib.parse.urlencode({
            "method": "user.getrecenttracks",
            "user": self.username,
            "api_key": api_key,
            "format": "json",
            "limit": 200,
            "extended": 1,
            "from": max(0, int(from_uts)),
            "page": max(1, int(page)),
        })
        request = urllib.request.Request(
            f"{LASTFM_API_URL}?{query}",
            headers={"Accept": "application/json", "User-Agent": "personal-dashboard/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise LastFmError(f"Last.fm request failed: {exc}") from exc
        if payload.get("error"):
            raise LastFmError(f"Last.fm error {payload.get('error')}: {payload.get('message', 'unknown error')}")
        return payload

    def _album_info_image(self, artist, album):
        artist = str(artist or "").strip()
        album = str(album or "").strip()
        if not artist or not album:
            return None
        artist_key = normalize_name(artist)
        album_key = normalize_name(album, album=True)
        now = int(time.time())
        with self._connect() as connection:
            cached = connection.execute(
                "SELECT image_url,checked_at FROM media_cache WHERE artist_key=? AND album_key=?",
                (artist_key, album_key),
            ).fetchone()
            if cached and int(cached["checked_at"]) >= now - 30 * 24 * 60 * 60:
                return cached["image_url"] or None

        api_key = os.environ.get("LASTFM_API_KEY", "").strip()
        if not api_key:
            return None
        query = urllib.parse.urlencode({
            "method": "album.getInfo",
            "artist": artist,
            "album": album,
            "autocorrect": 1,
            "api_key": api_key,
            "format": "json",
        })
        request = urllib.request.Request(
            f"{LASTFM_API_URL}?{query}",
            headers={"Accept": "application/json", "User-Agent": "personal-dashboard/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                info = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise LastFmError(f"Last.fm album info failed: {exc}") from exc
        images = (info.get("album") or {}).get("image") or []
        image = next((item.get("#text") for item in reversed(images) if item.get("#text")), None)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO media_cache(artist_key,album_key,image_url,checked_at) VALUES(?,?,?,?) "
                "ON CONFLICT(artist_key,album_key) DO UPDATE SET image_url=excluded.image_url,checked_at=excluded.checked_at",
                (artist_key, album_key, image, now),
            )
        return image

    def sync(self, *, force=False):
        if not self._sync_lock.acquire(blocking=False):
            return {"ok": True, "skipped": True, "reason": "sync_in_progress", "status": self.status()}
        try:
            self.initialize()
            with self._connect() as connection:
                metadata = self._metadata(connection)
                last_uts = int(connection.execute("SELECT COALESCE(MAX(last_uts), 0) FROM album_stats").fetchone()[0])
            last_sync_at = metadata.get("last_sync_at")
            if not force and last_sync_at:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
                    if age.total_seconds() < self.sync_interval_seconds:
                        return {"ok": True, "skipped": True, "reason": "fresh_cache", "status": self.status()}
                except ValueError:
                    pass

            from_uts = max(0, last_uts - 6 * 60 * 60)
            page = 1
            inserted = processed = 0
            while True:
                payload = self._api_page(from_uts=from_uts, page=page)
                recent = payload.get("recenttracks") or {}
                tracks = recent.get("track") or []
                cleaned = [self._clean_row(row) for row in tracks if not (row.get("@attr") or {}).get("nowplaying")]
                cleaned = [row for row in cleaned if row is not None]
                processed += len(cleaned)
                with self._lock, self._connect() as connection:
                    before = connection.total_changes
                    connection.executemany(self._insert_sql(), cleaned)
                    inserted += connection.total_changes - before
                attrs = recent.get("@attr") or {}
                total_pages = max(1, int(attrs.get("totalPages") or 1))
                if page >= total_pages:
                    break
                page += 1
                time.sleep(0.25)

            synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with self._connect() as connection:
                connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('last_sync_at', ?)", (synced_at,))
                connection.execute("DELETE FROM metadata WHERE key = 'last_sync_error'")
            if inserted:
                self.apply_incremental_updates(last_uts)
            return {"ok": True, "processed": processed, "inserted": inserted, "pages": page, "status": self.status()}
        except Exception as exc:
            with self._connect() as connection:
                connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('last_sync_error', ?)", (str(exc)[:500],))
            raise
        finally:
            self._sync_lock.release()

    def start_auto_sync(self, logger=None):
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._stop_event.clear()

        def worker():
            while not self._stop_event.wait(5):
                try:
                    result = self.sync()
                    if logger and not result.get("skipped"):
                        logger(f"Last.fm sync: +{result.get('inserted', 0)} scrobbles", tag="lastfm", level="success")
                except Exception as exc:
                    if logger:
                        logger(f"Last.fm sync failed: {exc}", tag="lastfm", level="warn")
                if self._stop_event.wait(self.sync_interval_seconds):
                    break

        self._sync_thread = threading.Thread(target=worker, name="lastfm-sync", daemon=True)
        self._sync_thread.start()

    def stop_auto_sync(self):
        self._stop_event.set()
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=3)

    def match_albums(self, albums):
        self.initialize()
        results = []
        with self._connect() as connection:
            for item in (albums or [])[:1000]:
                artist = str((item or {}).get("artist") or "").strip()
                album = str((item or {}).get("album") or "").strip()
                artist_key = normalize_name(artist)
                album_key = normalize_name(album, album=True)
                album_row = connection.execute(
                    "SELECT scrobbles AS plays, unique_tracks, first_uts, last_uts, last_track "
                    "FROM album_stats WHERE artist_key = ? AND album_key = ?",
                    (artist_key, album_key),
                ).fetchone()
                artist_row = connection.execute(
                    "SELECT scrobbles AS plays FROM artist_stats WHERE artist_key = ?",
                    (artist_key,),
                ).fetchone()
                plays = int(album_row["plays"] or 0) if album_row else 0
                last_track = album_row["last_track"] if album_row else None
                results.append({
                    "artist": artist,
                    "album": album,
                    "key": f"{artist_key}\0{album_key}",
                    "matched": plays > 0,
                    "albumScrobbles": plays,
                    "artistScrobbles": int(artist_row["plays"] or 0) if artist_row else 0,
                    "uniqueTracks": int(album_row["unique_tracks"] or 0) if album_row else 0,
                    "firstScrobbleAt": self._iso_timestamp(album_row["first_uts"] if album_row else None),
                    "lastScrobbleAt": self._iso_timestamp(album_row["last_uts"] if album_row else None),
                    "lastTrack": last_track,
                    "lastTrackUrl": (
                        f"https://www.last.fm/music/{urllib.parse.quote_plus(artist)}/_/{urllib.parse.quote_plus(last_track)}"
                        if last_track else None
                    ),
                    "lastfmUrl": f"https://www.last.fm/music/{urllib.parse.quote_plus(artist)}/{urllib.parse.quote_plus(album)}",
                })
        return {"username": self.username, "albums": results, "status": self.status()}

    @staticmethod
    def _period_label(granularity, key):
        if granularity == "day":
            return key
        if granularity == "week":
            return f"Week of {key}"
        if granularity == "month":
            return key
        return key

    def _period_charts(self, connection, start, end, granularity):
        column = {"day": "local_day", "week": "local_week", "month": "local_month", "year": "local_year"}[granularity]
        base_params = (start, end)
        totals = {
            row["period"]: dict(row)
            for row in connection.execute(
                f"SELECT {column} AS period, COUNT(*) AS scrobbles, COUNT(DISTINCT artist_key) AS unique_artists "
                "FROM scrobbles WHERE local_day BETWEEN ? AND ? GROUP BY period ORDER BY period",
                base_params,
            )
        }

        def top_rows(entity_columns, key_columns):
            selected = ", ".join(entity_columns)
            grouped = ", ".join([column, *key_columns])
            query = f"""
                WITH counts AS (
                    SELECT {column} AS period, {selected}, COUNT(*) AS plays, MAX(uts) AS latest_uts,
                           ROW_NUMBER() OVER (
                               PARTITION BY {column}
                               ORDER BY COUNT(*) DESC, MAX(uts) DESC, {', '.join(key_columns)}
                           ) AS rank
                    FROM scrobbles
                    WHERE local_day BETWEEN ? AND ?
                    GROUP BY {grouped}
                )
                SELECT * FROM counts WHERE rank = 1 ORDER BY period
            """
            return {row["period"]: dict(row) for row in connection.execute(query, base_params)}

        artists = top_rows(["artist", "artist_key"], ["artist_key"])
        albums = top_rows(["artist", "artist_key", "album", "album_key"], ["artist_key", "album_key"])
        tracks = top_rows(["artist", "artist_key", "track", "track_key"], ["artist_key", "track_key"])
        events = []
        for period, total in totals.items():
            artist = artists.get(period) or {}
            album = albums.get(period) or {}
            track = tracks.get(period) or {}
            events.append({
                "period": period,
                "granularity": granularity,
                "label": self._period_label(granularity, period),
                "scrobbles": int(total.get("scrobbles") or 0),
                "uniqueArtists": int(total.get("unique_artists") or 0),
                "topArtist": {"name": artist.get("artist"), "scrobbles": int(artist.get("plays") or 0)},
                "topAlbum": {"artist": album.get("artist"), "name": album.get("album"), "scrobbles": int(album.get("plays") or 0)},
                "topTrack": {"artist": track.get("artist"), "name": track.get("track"), "scrobbles": int(track.get("plays") or 0)},
            })
        return events

    @staticmethod
    def _period_bounds(granularity, period):
        if granularity == "day":
            first = datetime.strptime(period, "%Y-%m-%d").date()
            return first, first
        if granularity == "week":
            first = datetime.strptime(period, "%Y-%m-%d").date()
            return first, first + timedelta(days=6)
        if granularity == "month":
            first = datetime.strptime(f"{period}-01", "%Y-%m-%d").date()
            following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            return first, following - timedelta(days=1)
        first = date(int(period), 1, 1)
        return first, date(int(period), 12, 31)

    def rebuild_period_charts(self):
        self.initialize()
        with self._lock, self._connect() as connection:
            bounds = connection.execute("SELECT MIN(local_day), MAX(local_day) FROM scrobbles").fetchone()
            connection.execute("DELETE FROM period_charts")
            if not bounds[0] or not bounds[1]:
                return 0
            rows = [
                row
                for granularity in ("day", "week", "month", "year")
                for row in self._period_charts(connection, bounds[0], bounds[1], granularity)
            ]
            connection.executemany(
                "INSERT INTO period_charts(granularity, period, payload_json) VALUES (?, ?, ?)",
                ((row["granularity"], row["period"], json.dumps(row, ensure_ascii=False, separators=(",", ":"))) for row in rows),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('charts_updated_at', ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
        return len(rows)

    def rebuild_summaries(self):
        self.initialize()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM artist_stats")
            connection.execute("DELETE FROM album_stats")
            connection.execute("DELETE FROM album_tracks")
            connection.execute(
                """
                INSERT INTO album_tracks(artist_key, album_key, track_key)
                SELECT DISTINCT artist_key, album_key, track_key FROM scrobbles
                """
            )
            connection.execute(
                """
                INSERT INTO artist_stats(artist_key, artist, scrobbles)
                SELECT artist_key, artist, COUNT(*)
                FROM scrobbles
                GROUP BY artist_key
                """
            )
            connection.execute(
                """
                WITH album_counts AS (
                    SELECT artist_key, album_key, artist, album, COUNT(*) AS scrobbles,
                           COUNT(DISTINCT track_key) AS unique_tracks,
                           MIN(uts) AS first_uts, MAX(uts) AS last_uts
                    FROM scrobbles
                    GROUP BY artist_key, album_key
                ), latest AS (
                    SELECT artist_key, album_key, track,
                           ROW_NUMBER() OVER (
                               PARTITION BY artist_key, album_key
                               ORDER BY uts DESC, id DESC
                           ) AS rank
                    FROM scrobbles
                )
                INSERT INTO album_stats(
                    artist_key, album_key, artist, album, scrobbles,
                    unique_tracks, first_uts, last_uts, last_track
                )
                SELECT counts.artist_key, counts.album_key, counts.artist, counts.album,
                       counts.scrobbles, counts.unique_tracks, counts.first_uts,
                       counts.last_uts, latest.track
                FROM album_counts counts
                JOIN latest ON latest.artist_key = counts.artist_key
                           AND latest.album_key = counts.album_key
                           AND latest.rank = 1
                """
            )

    def apply_incremental_updates(self, previous_last_uts):
        with self._lock, self._connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM scrobbles WHERE uts > ? ORDER BY uts",
                (int(previous_last_uts or 0),),
            )]
            if not rows:
                return 0

            artist_groups = {}
            album_groups = {}
            for row in rows:
                artist = artist_groups.setdefault(row["artist_key"], {"artist": row["artist"], "count": 0})
                artist["artist"] = row["artist"]
                artist["count"] += 1
                album_key = (row["artist_key"], row["album_key"])
                album = album_groups.setdefault(album_key, {
                    "artist": row["artist"], "album": row["album"], "count": 0,
                    "first": row["uts"], "last": row["uts"], "last_track": row["track"], "new_tracks": 0,
                })
                album["count"] += 1
                album["first"] = min(album["first"], row["uts"])
                if row["uts"] >= album["last"]:
                    album["last"] = row["uts"]
                    album["last_track"] = row["track"]
                before = connection.total_changes
                connection.execute(
                    "INSERT OR IGNORE INTO album_tracks(artist_key, album_key, track_key) VALUES (?, ?, ?)",
                    (row["artist_key"], row["album_key"], row["track_key"]),
                )
                album["new_tracks"] += connection.total_changes - before

            connection.executemany(
                """
                INSERT INTO artist_stats(artist_key, artist, scrobbles) VALUES (?, ?, ?)
                ON CONFLICT(artist_key) DO UPDATE SET
                    artist = excluded.artist,
                    scrobbles = artist_stats.scrobbles + excluded.scrobbles
                """,
                ((key, value["artist"], value["count"]) for key, value in artist_groups.items()),
            )
            connection.executemany(
                """
                INSERT INTO album_stats(
                    artist_key, album_key, artist, album, scrobbles,
                    unique_tracks, first_uts, last_uts, last_track
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artist_key, album_key) DO UPDATE SET
                    artist = excluded.artist,
                    album = excluded.album,
                    scrobbles = album_stats.scrobbles + excluded.scrobbles,
                    unique_tracks = album_stats.unique_tracks + excluded.unique_tracks,
                    first_uts = MIN(album_stats.first_uts, excluded.first_uts),
                    last_track = CASE WHEN excluded.last_uts >= album_stats.last_uts THEN excluded.last_track ELSE album_stats.last_track END,
                    last_uts = MAX(album_stats.last_uts, excluded.last_uts)
                """,
                ((artist_key, album_key, value["artist"], value["album"], value["count"],
                  value["new_tracks"], value["first"], value["last"], value["last_track"])
                 for (artist_key, album_key), value in album_groups.items()),
            )

            affected = {
                "day": {row["local_day"] for row in rows},
                "week": {row["local_week"] for row in rows},
                "month": {row["local_month"] for row in rows},
                "year": {row["local_year"] for row in rows},
            }
            for granularity, periods in affected.items():
                for period in periods:
                    first, last = self._period_bounds(granularity, period)
                    chart = next((item for item in self._period_charts(
                        connection, first.isoformat(), last.isoformat(), granularity
                    ) if item["period"] == period), None)
                    if chart:
                        connection.execute(
                            "INSERT OR REPLACE INTO period_charts(granularity, period, payload_json) VALUES (?, ?, ?)",
                            (granularity, period, json.dumps(chart, ensure_ascii=False, separators=(",", ":"))),
                        )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('charts_updated_at', ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
        return len(rows)

    def timeline_charts(self, start, end):
        self.initialize()
        with self._connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM period_charts").fetchone()[0])
        if not count and self.status()["totalScrobbles"]:
            self.rebuild_period_charts()
        with self._connect() as connection:
            rows = [json.loads(row[0]) for row in connection.execute(
                "SELECT payload_json FROM period_charts ORDER BY granularity, period"
            )]
        return [
            row for row in rows
            if self._period_bounds(row["granularity"], row["period"])[0] <= end
            and self._period_bounds(row["granularity"], row["period"])[1] >= start
        ]


LASTFM_STORE = LastFmStore(Path(__file__).resolve().parent)

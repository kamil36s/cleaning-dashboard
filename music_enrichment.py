"""Conservative, local-first metadata enrichment for the Music catalog.

Provider results are observations. Existing catalog values always win.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from music_importers import normalize_text
from music_store import utc_now


LOG = logging.getLogger("music.enrichment")
MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
QID = re.compile(r"^Q[1-9][0-9]*$")
ALLOWED_IMAGE_HOSTS = (
    "coverartarchive.org", "archive.org", "discogs.com", "wikimedia.org",
    "theaudiodb.com", "mzstatic.com",
)


def enabled(name):
    return os.environ.get(f"MUSIC_{name.upper()}_ENABLED", "1").lower() not in {"0", "false", "no"}


class ProviderUnavailable(RuntimeError):
    pass


class ProviderScheduler:
    """One lock and cooldown per provider; HTTP 404 is a cacheable absence."""

    DEFAULTS = {
        "musicbrainz": (1.15, 15), "cover_art_archive": (1.0, 20),
        "discogs": (1.2, 15), "theaudiodb": (1.2, 15),
        "apple": (1.0, 12), "wikidata": (1.2, 15), "wikimedia": (1.2, 20),
    }

    def __init__(self, opener=None, sleep=None, clock=None):
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self._locks = {key: threading.Lock() for key in self.DEFAULTS}
        self._next = {key: 0.0 for key in self.DEFAULTS}
        self._failures = {key: 0 for key in self.DEFAULTS}
        self._minute = {key: [] for key in self.DEFAULTS}

    def request(self, provider, url, *, image=False, headers=None):
        if not enabled(provider):
            raise ProviderUnavailable(f"{provider} disabled")
        interval, timeout = self.DEFAULTS[provider]
        interval = max(interval, float(os.environ.get(f"MUSIC_{provider.upper()}_INTERVAL", interval)))
        timeout = max(2, min(float(os.environ.get(f"MUSIC_{provider.upper()}_TIMEOUT", timeout)), 60))
        user_agent = os.environ.get("MUSIC_METADATA_USER_AGENT", "CleaningDashboard-Music/1.0 (local personal catalog)")
        request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "image/*" if image else "application/json", **(headers or {})})
        with self._locks[provider]:
            for attempt in range(3):
                now = self.clock()
                self._minute[provider] = [stamp for stamp in self._minute[provider] if now - stamp < 60]
                per_minute = max(1, min(int(os.environ.get(f"MUSIC_{provider.upper()}_MAX_PER_MINUTE", int(60 / interval))), 60))
                if len(self._minute[provider]) >= per_minute:
                    self._next[provider] = max(self._next[provider], self._minute[provider][0] + 60)
                wait = self._next[provider] - self.clock()
                if wait > 0:
                    self.sleep(wait)
                self._next[provider] = self.clock() + interval
                self._minute[provider].append(self.clock())
                try:
                    with self.opener(request, timeout=timeout) as response:
                        final_url = response.geturl()
                        if image and not self._allowed_image_url(final_url):
                            raise ValueError("Image redirect outside known provider hosts")
                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                        max_bytes = 8 * 1024 * 1024 if image else 2 * 1024 * 1024
                        raw = response.read(max_bytes + 1)
                        if len(raw) > max_bytes:
                            raise ValueError("Provider response too large")
                        if image:
                            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                                raise ValueError("Unsupported image content type")
                            result = (raw, content_type, final_url)
                        else:
                            result = json.loads(raw.decode("utf-8"))
                        self._failures[provider] = 0
                        if provider == "discogs" and response.headers.get("X-Discogs-Ratelimit-Remaining") == "0":
                            self._next[provider] = max(self._next[provider], self.clock() + 60)
                        return result
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        return None
                    retry = exc.code in {429, 500, 502, 503, 504}
                    if not retry:
                        raise
                    delay = self._retry_delay(exc.headers.get("Retry-After"), attempt)
                    self._next[provider] = max(self._next[provider], self.clock() + delay)
                    LOG.warning("provider=%s status=%s retry=%s", provider, exc.code, attempt + 1)
                except (urllib.error.URLError, TimeoutError):
                    self._next[provider] = max(self._next[provider], self.clock() + self._retry_delay(None, attempt))
                if attempt == 2:
                    self._failures[provider] += 1
                    if self._failures[provider] >= 3:
                        self._next[provider] = max(self._next[provider], self.clock() + 300)
                    raise ProviderUnavailable(f"{provider} temporarily unavailable")

    @staticmethod
    def _retry_delay(header, attempt):
        try:
            return max(1, min(float(header), 120))
        except (TypeError, ValueError):
            if header:
                try:
                    seconds = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
                    return max(1, min(seconds, 120))
                except (TypeError, ValueError):
                    pass
            return min(2 ** attempt + random.random(), 30)

    @staticmethod
    def _allowed_image_url(url):
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_IMAGE_HOSTS)


def image_size(data, mime):
    if mime == "image/png" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if mime == "image/webp" and len(data) >= 30 and data[12:16] == b"VP8X":
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    if mime == "image/webp" and len(data) >= 30 and data[12:16] == b"VP8 ":
        return int.from_bytes(data[26:28], "little") & 0x3fff, int.from_bytes(data[28:30], "little") & 0x3fff
    if mime == "image/webp" and len(data) >= 25 and data[12:16] == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
    if mime == "image/jpeg" and data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xff:
                break
            marker = data[index + 1]
            length = int.from_bytes(data[index + 2:index + 4], "big")
            if marker in {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb}:
                return int.from_bytes(data[index + 7:index + 9], "big"), int.from_bytes(data[index + 5:index + 7], "big")
            if length < 2:
                break
            index += length + 2
    return None, None


def without_scores(value):
    """Provider response cache never persists ratings, reviews or ranking scores."""
    if isinstance(value, dict):
        return {key: without_scores(item) for key, item in value.items()
                if not any(word in key.lower() for word in ("rating", "review", "score", "community"))}
    if isinstance(value, list):
        return [without_scores(item) for item in value]
    return value


class MetadataProvider:
    name = "base"

    def __init__(self, scheduler):
        self.scheduler = scheduler


class MusicBrainzProvider(MetadataProvider):
    name = "musicbrainz"
    base = "https://musicbrainz.org/ws/2"

    def search_release_group(self, artist, title):
        clean = lambda value: re.sub(r'[^\w\s\-]', ' ', str(value or '')).strip()
        query = f'releasegroup:"{clean(title)}" AND artist:"{clean(artist)}"'
        return self.scheduler.request(self.name, f"{self.base}/release-group/?{urllib.parse.urlencode({'query': query, 'limit': 8, 'fmt': 'json'})}") or {}

    def release_group(self, mbid):
        return self.scheduler.request(self.name, f"{self.base}/release-group/{mbid}?inc=artist-credits+genres+tags+url-rels&fmt=json") or {}

    def releases(self, mbid):
        return self.scheduler.request(self.name, f"{self.base}/release/?{urllib.parse.urlencode({'release-group': mbid, 'limit': 10, 'fmt': 'json'})}") or {}

    def release(self, mbid):
        return self.scheduler.request(self.name, f"{self.base}/release/{mbid}?inc=recordings+artist-credits+labels+media+isrcs+artist-rels+recording-level-rels+work-rels+work-level-rels&fmt=json") or {}

    def artist(self, mbid):
        return self.scheduler.request(self.name, f"{self.base}/artist/{mbid}?inc=url-rels+genres+aliases&fmt=json") or {}


class CoverArtArchiveProvider(MetadataProvider):
    name = "cover_art_archive"

    def artwork(self, mbid, *, group=True):
        kind = "release-group" if group else "release"
        return self.scheduler.request(self.name, f"https://coverartarchive.org/{kind}/{mbid}/front-500", image=True)


class DiscogsProvider(MetadataProvider):
    name = "discogs"

    @staticmethod
    def _headers():
        return {"Authorization": f"Discogs token={os.environ['MUSIC_DISCOGS_TOKEN']}"}

    def album(self, artist, title):
        token = os.environ.get("MUSIC_DISCOGS_TOKEN", "").strip()
        if not token:
            raise ProviderUnavailable("Discogs token missing")
        params = urllib.parse.urlencode({"artist": artist, "release_title": title, "type": "master", "per_page": 5})
        data = self.scheduler.request(self.name, f"https://api.discogs.com/database/search?{params}", headers=self._headers()) or {}
        for row in data.get("results") or []:
            parts = str(row.get("title") or "").split(" - ", 1)
            if len(parts) == 2 and normalize_text(parts[0]) == normalize_text(artist) and normalize_text(parts[1]) == normalize_text(title):
                return row
        return None

    def master(self, master_id):
        return self.scheduler.request(self.name, f"https://api.discogs.com/masters/{int(master_id)}", headers=self._headers()) or {}

    def release(self, release_id):
        return self.scheduler.request(self.name, f"https://api.discogs.com/releases/{int(release_id)}", headers=self._headers()) or {}


class TheAudioDBProvider(MetadataProvider):
    name = "theaudiodb"

    def album(self, artist, title):
        key = os.environ.get("MUSIC_AUDIODB_KEY", "").strip()
        if not key:
            raise ProviderUnavailable("TheAudioDB key missing")
        params = urllib.parse.urlencode({"s": artist, "a": title})
        data = self.scheduler.request(self.name, f"https://www.theaudiodb.com/api/v1/json/{key}/searchalbum.php?{params}") or {}
        for row in data.get("album") or []:
            if normalize_text(row.get("strArtist")) == normalize_text(artist) and normalize_text(row.get("strAlbum")) == normalize_text(title):
                return row
        return None

    def artist(self, name):
        key = os.environ.get("MUSIC_AUDIODB_KEY", "").strip()
        if not key:
            raise ProviderUnavailable("TheAudioDB key missing")
        data = self.scheduler.request(self.name, f"https://www.theaudiodb.com/api/v1/json/{key}/search.php?{urllib.parse.urlencode({'s': name})}") or {}
        for row in data.get("artists") or []:
            if normalize_text(row.get("strArtist")) == normalize_text(name):
                return row
        return None


class AppleProvider(MetadataProvider):
    name = "apple"

    def album(self, artist, title):
        params = urllib.parse.urlencode({"term": f"{artist} {title}", "entity": "album", "limit": 10})
        data = self.scheduler.request(self.name, f"https://itunes.apple.com/search?{params}") or {}
        for row in data.get("results") or []:
            if normalize_text(row.get("artistName")) == normalize_text(artist) and normalize_text(row.get("collectionName")) == normalize_text(title):
                return row
        return None


class WikidataProvider(MetadataProvider):
    name = "wikidata"

    def artist(self, qid):
        data = self.scheduler.request(self.name, f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json") or {}
        return (data.get("entities") or {}).get(qid) or {}


class WikimediaProvider(MetadataProvider):
    name = "wikimedia"

    def image_url(self, filename):
        params = urllib.parse.urlencode({"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 600, "titles": "File:" + filename, "format": "json"})
        data = self.scheduler.request(self.name, f"https://commons.wikimedia.org/w/api.php?{params}") or {}
        for page in (data.get("query") or {}).get("pages", {}).values():
            for info in page.get("imageinfo") or []:
                return info.get("thumburl") or info.get("url")
        return None


class MusicEnrichment:
    """Single local worker. Each field has independent provenance and checks."""

    def __init__(self, store, scheduler=None):
        self.store = store
        self.scheduler = scheduler or ProviderScheduler()
        self.mb = MusicBrainzProvider(self.scheduler)
        self.caa = CoverArtArchiveProvider(self.scheduler)
        self.discogs = DiscogsProvider(self.scheduler)
        self.audiodb = TheAudioDBProvider(self.scheduler)
        self.apple = AppleProvider(self.scheduler)
        self.wikidata = WikidataProvider(self.scheduler)
        self.wikimedia = WikimediaProvider(self.scheduler)
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if not enabled("enrichment") or self._thread and self._thread.is_alive():
            return
        self.store.initialize()
        with self.store._connect() as db:
            db.execute("UPDATE music_enrichment_jobs SET status='pending',updated_at=? WHERE status='running'", (utc_now(),))
        self._thread = threading.Thread(target=self._loop, name="music-enrichment", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.enqueue_missing(50)
                if not self.run_next():
                    self._stop.wait(60)
            except Exception:
                LOG.exception("Music enrichment worker failed")
                self._stop.wait(30)

    def enqueue(self, release_id, *, priority=0, retry=False):
        self.store.initialize()
        with self.store._connect() as db:
            if not db.execute("SELECT 1 FROM music_releases WHERE id=?", (release_id,)).fetchone():
                raise ValueError("Album nie istnieje")
            db.execute("INSERT OR IGNORE INTO music_enrichment_jobs(release_id,priority,status,updated_at) VALUES(?,?,'pending',?)", (release_id, priority, utc_now()))
            if retry:
                db.execute("UPDATE music_enrichment_jobs SET status='pending',priority=?,updated_at=? WHERE release_id=?", (priority, utc_now(), release_id))
        return {"ok": True, "releaseId": release_id, "status": "pending"}

    def prioritize_artist_photos(self, names):
        """Move one album per artist with no photo to the front of the existing worker queue."""
        if not enabled('enrichment'):
            return 0
        self.store.initialize()
        queued = 0
        with self.store._connect() as db:
            for name in list(names)[:20]:
                key = normalize_text(name)
                row = db.execute("""SELECT r.id,j.status,j.attempts FROM music_artists a
                    JOIN music_release_artists ra ON ra.artist_id=a.id
                    JOIN music_releases r ON r.id=ra.release_id
                    LEFT JOIN music_enrichment_jobs j ON j.release_id=r.id
                    WHERE a.normalized_name=? AND NOT EXISTS (
                      SELECT 1 FROM music_metadata_values m WHERE m.entity_type='artist'
                      AND m.entity_id=a.id AND m.field_name='image_url')
                    AND (j.release_id IS NULL OR j.status='pending' OR (j.status='done' AND j.attempts<2))
                    ORDER BY CASE WHEN j.status='pending' THEN 0 ELSE 1 END,r.id LIMIT 1""", (key,)).fetchone()
                if not row:
                    continue
                db.execute("INSERT OR IGNORE INTO music_enrichment_jobs(release_id,priority,status,updated_at) VALUES(?,-2,'pending',?)",
                           (row['id'], utc_now()))
                db.execute("UPDATE music_enrichment_jobs SET status='pending',priority=-2,updated_at=? WHERE release_id=?",
                           (utc_now(), row['id']))
                queued += 1
        return queued

    def prioritize_visible_covers(self, releases):
        """Fetch better art for small covers currently visible in the library."""
        if not enabled('enrichment'):
            return 0
        queued = 0
        with self.store._connect() as db:
            for position, release in enumerate(list(releases)[:100]):
                if not self._needs_better_cover(release):
                    continue
                release_id = int(release['id'])
                job = db.execute('SELECT status,attempts FROM music_enrichment_jobs WHERE release_id=?', (release_id,)).fetchone()
                if job and (job['status'] in {'running', 'error'} or job['status'] in {'done', 'unresolved'} and job['attempts'] >= 2):
                    continue
                priority = -100 + position
                db.execute("INSERT OR IGNORE INTO music_enrichment_jobs(release_id,priority,status,updated_at) VALUES(?,?,'pending',?)",
                           (release_id, priority, utc_now()))
                db.execute("UPDATE music_enrichment_jobs SET status='pending',priority=?,updated_at=? WHERE release_id=?",
                           (priority, utc_now(), release_id))
                queued += 1
        return queued

    def enqueue_missing(self, limit=50):
        self.store.initialize()
        limit = max(1, min(int(limit), 200))
        with self.store._connect() as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
            db.execute("UPDATE music_enrichment_jobs SET status='pending',updated_at=? WHERE status='error' AND attempts<3 AND updated_at<?",
                       (utc_now(), cutoff))
            upgrades = 0
            candidates = db.execute("""SELECT r.id,r.cover_local,r.cover_remote,j.status,j.attempts
                FROM music_releases r JOIN music_enrichment_jobs j ON j.release_id=r.id
                WHERE j.status IN ('pending','done') AND COALESCE(r.cover_local,'')<>''
                ORDER BY r.id""")
            for candidate in candidates:
                if upgrades >= limit:
                    break
                if candidate['status'] == 'done' and candidate['attempts'] >= 2:
                    continue
                if self._needs_better_cover(candidate):
                    db.execute("UPDATE music_enrichment_jobs SET status='pending',priority=0,updated_at=? WHERE release_id=?",
                               (utc_now(), candidate['id']))
                    upgrades += 1
            rows = db.execute("""SELECT r.id, CASE WHEN COALESCE(r.cover_local,'')='' AND COALESCE(r.cover_remote,'')='' THEN 0 ELSE 1 END priority
                FROM music_releases r LEFT JOIN music_enrichment_jobs j ON j.release_id=r.id
                WHERE j.release_id IS NULL ORDER BY priority,r.id LIMIT ?""", (limit,)).fetchall()
            db.executemany("INSERT OR IGNORE INTO music_enrichment_jobs(release_id,priority,status,updated_at) VALUES(?,?,'pending',?)",
                           [(row["id"], row["priority"], utc_now()) for row in rows])
        return len(rows) + upgrades

    def status(self):
        self.store.initialize()
        with self.store._connect() as db:
            counts = {row["status"]: row["n"] for row in db.execute("SELECT status,count(*) n FROM music_enrichment_jobs GROUP BY status")}
            total = db.execute("SELECT count(*) FROM music_releases").fetchone()[0]
            covers = db.execute("SELECT count(*) FROM music_releases WHERE COALESCE(cover_local,'')<>'' OR COALESCE(cover_remote,'')<>''").fetchone()[0]
            identified = db.execute("SELECT count(*) FROM music_external_ids WHERE entity_type='release' AND source='musicbrainz' AND external_type='release_group_id'").fetchone()[0]
            artist_images = db.execute("SELECT count(*) FROM music_metadata_values WHERE entity_type='artist' AND field_name='image_url'").fetchone()[0]
            errors = db.execute("SELECT count(*) FROM music_metadata_checks WHERE status='error'").fetchone()[0]
            unresolved = [dict(row) for row in db.execute("""SELECT j.release_id,r.artist_credit,r.title,j.match_method,j.error_text
                FROM music_enrichment_jobs j JOIN music_releases r ON r.id=j.release_id
                WHERE j.status IN ('unresolved','error') ORDER BY j.updated_at DESC LIMIT 10""")]
        providers = {name: "disabled" if not enabled(name) else "cooldown" if self.scheduler._next[name] > self.scheduler.clock() + self.scheduler.DEFAULTS[name][0] else "ok" for name in self.scheduler.DEFAULTS}
        if enabled("discogs") and not os.environ.get("MUSIC_DISCOGS_TOKEN"):
            providers["discogs"] = "needs_key"
        if enabled("theaudiodb") and not os.environ.get("MUSIC_AUDIODB_KEY"):
            providers["theaudiodb"] = "needs_key"
        return {"ok": True, "enabled": enabled("enrichment"), "total": total, "identified": identified,
                "covers": covers, "missingCovers": total - covers, "artistImages": artist_images,
                "jobs": counts, "apiErrors": errors, "providers": providers, "unresolvedSample": unresolved}

    def run_next(self):
        if not enabled("enrichment"):
            return None
        self.store.initialize()
        with self.store._connect() as db:
            row = db.execute("SELECT release_id FROM music_enrichment_jobs WHERE status='pending' ORDER BY priority,updated_at,release_id LIMIT 1").fetchone()
            if not row:
                return None
            release_id = row["release_id"]
            db.execute("UPDATE music_enrichment_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE release_id=?", (utc_now(), release_id))
        try:
            result = self.process_release(release_id)
            status = "error" if result.get("errors") else "unresolved" if result["match"] == "uncertain" else "done"
            error = "provider_failed" if status == "error" else None
        except Exception as exc:
            LOG.exception("Music enrichment release=%s failed", release_id)
            result = {"releaseId": release_id, "error": str(exc)}
            status, error = "error", str(exc)[:300]
        with self.store._connect() as db:
            db.execute("UPDATE music_enrichment_jobs SET status=?,match_method=?,match_confidence=?,error_text=?,updated_at=? WHERE release_id=?",
                       (status, result.get("method"), result.get("confidence"), error, utc_now(), release_id))
        return result

    def _checked(self, db, entity_type, entity_id, field, provider):
        row = db.execute("SELECT status,checked_at FROM music_metadata_checks WHERE entity_type=? AND entity_id=? AND field_name=? AND provider=?",
                         (entity_type, entity_id, field, provider)).fetchone()
        if not row:
            return False
        ttl = 3650 if row["status"] == "found" else 90 if row["status"] == "not_found" else 1
        try:
            return datetime.fromisoformat(row["checked_at"]) > datetime.now(timezone.utc) - timedelta(days=ttl)
        except ValueError:
            return False

    def _check(self, db, entity_type, entity_id, field, provider, status, error=None):
        db.execute("""INSERT INTO music_metadata_checks(entity_type,entity_id,field_name,provider,status,checked_at,error_text)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(entity_type,entity_id,field_name,provider) DO UPDATE SET
            status=excluded.status,checked_at=excluded.checked_at,error_text=excluded.error_text""",
            (entity_type, entity_id, field, provider, status, utc_now(), str(error)[:300] if error else None))

    def _value(self, db, entity_type, entity_id, field, value, provider, provider_id=None, confidence=1):
        if value is None or value == "" or value == []:
            self._check(db, entity_type, entity_id, field, provider, "not_found")
            return False
        db.execute("""INSERT INTO music_metadata_values(entity_type,entity_id,field_name,provider,provider_entity_id,value_json,confidence,fetched_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(entity_type,entity_id,field_name,provider) DO UPDATE SET
            provider_entity_id=excluded.provider_entity_id,value_json=excluded.value_json,confidence=excluded.confidence,fetched_at=excluded.fetched_at""",
            (entity_type, entity_id, field, provider, provider_id, json.dumps(value, ensure_ascii=False), confidence, utc_now()))
        self._check(db, entity_type, entity_id, field, provider, "found")
        if entity_type == "release" and field in {"release_date", "release_year", "label", "catalog_number", "description"}:
            db.execute(f"UPDATE music_releases SET {field}=?,updated_at=? WHERE id=? AND COALESCE({field},'')=''",
                       (value, utc_now(), entity_id))
        return True

    def _cover_dimensions(self, source):
        source = str(source or '')
        if not source or source.startswith(('http:', 'https:', 'data:')):
            return None, None
        path = (self.store.root / source.lstrip('/')).resolve()
        if not path.is_relative_to(self.store.root.resolve()) or not path.is_file():
            return None, None
        mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}.get(path.suffix.lower())
        if not mime:
            return None, None
        with path.open('rb') as image:
            return image_size(image.read(65536), mime)

    def _needs_better_cover(self, cover):
        if not cover['cover_local'] and not cover['cover_remote']:
            return True
        width, height = self._cover_dimensions(cover['cover_local'] or cover['cover_remote'])
        return width is not None and height is not None and min(width, height) < 300

    @staticmethod
    def _external(db, entity_type, entity_id, provider, kind, value):
        if value:
            db.execute("INSERT OR IGNORE INTO music_external_ids(entity_type,entity_id,source,external_type,external_value,created_at) VALUES(?,?,?,?,?,?)",
                       (entity_type, entity_id, provider, kind, str(value), utc_now()))

    def _cover(self, db, entity_type, entity_id, provider, source_url, raw=None):
        if not source_url or not self.scheduler._allowed_image_url(source_url):
            return False
        existing = db.execute("SELECT local_path,width,height FROM music_artwork_cache WHERE source_url=?", (source_url,)).fetchone()
        if existing and (self.store.root / existing["local_path"].lstrip("/")).is_file():
            local = existing["local_path"]
            width, height = existing['width'], existing['height']
        else:
            try:
                data, mime, _ = raw or self.scheduler.request(provider, source_url, image=True)
            except TypeError:
                return False
            if not data or (mime == "image/jpeg" and not data.startswith(b"\xff\xd8")) or (mime == "image/png" and not data.startswith(b"\x89PNG")) or (mime == "image/webp" and data[8:12] != b"WEBP"):
                return False
            digest = hashlib.sha256(data).hexdigest()
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
            local = f"/covers/music-{digest}.{ext}"
            path = self.store.root / local.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(data)
            width, height = image_size(data, mime)
            db.execute("INSERT OR IGNORE INTO music_artwork_cache(sha256,provider,source_url,local_path,mime_type,width,height,artwork_type,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (digest, provider, source_url, local, mime, width, height, "front" if entity_type == "release" else "artist", utc_now()))
        if entity_type == 'release':
            if width and height and min(width, height) < 300:
                return False
            current = db.execute('SELECT cover_local,cover_remote FROM music_releases WHERE id=?', (entity_id,)).fetchone()
            old_width, old_height = self._cover_dimensions(current['cover_local'] or current['cover_remote'])
            if current['cover_local'] or current['cover_remote']:
                if not width or not height or min(width, height) < 300 or (old_width and old_height and min(width, height) <= min(old_width, old_height)):
                    return False
        self._value(db, entity_type, entity_id, "cover_url" if entity_type == "release" else "image_url", local, provider, source_url)
        if entity_type == "release":
            db.execute("UPDATE music_releases SET cover_local=?,updated_at=? WHERE id=?",
                       (local, utc_now(), entity_id))
        return True

    @staticmethod
    def _artist_credit(group):
        return "".join(part if isinstance(part, str) else (part.get("name") or (part.get("artist") or {}).get("name", "")) + part.get("joinphrase", "")
                       for part in group.get("artist-credit") or [])

    @staticmethod
    def _claim(entity, prop):
        for statement in (entity.get("claims") or {}).get(prop) or []:
            value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
            if isinstance(value, dict):
                return value.get("id")
            if isinstance(value, str):
                return value
        return None

    def _try(self, db, entity_type, entity_id, field, provider, callback):
        if self._checked(db, entity_type, entity_id, field, provider):
            LOG.debug("provider=%s entity=%s:%s field=%s cache=hit", provider, entity_type, entity_id, field)
            cached = db.execute("SELECT payload_json FROM music_provider_payloads WHERE entity_type=? AND entity_id=? AND action=? AND provider=?",
                                (entity_type, entity_id, field, provider)).fetchone()
            return json.loads(cached["payload_json"]) if cached else None
        db.commit()  # Never hold a SQLite write lock during an external request.
        try:
            result = callback()
            self._check(db, entity_type, entity_id, field, provider, "found" if result else "not_found")
            if result and not isinstance(result, tuple):
                try:
                    encoded = json.dumps(without_scores(result), ensure_ascii=False)
                except TypeError:
                    encoded = None
                if encoded and len(encoded) <= 2 * 1024 * 1024:
                    db.execute("""INSERT INTO music_provider_payloads(entity_type,entity_id,action,provider,payload_json,fetched_at)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(entity_type,entity_id,action,provider) DO UPDATE SET
                        payload_json=excluded.payload_json,fetched_at=excluded.fetched_at""",
                        (entity_type, entity_id, field, provider, encoded, utc_now()))
            LOG.info("provider=%s entity=%s:%s field=%s result=%s", provider, entity_type, entity_id, field, "found" if result else "missing")
            return result
        except (ProviderUnavailable, urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as exc:
            self._check(db, entity_type, entity_id, field, provider, "error", exc)
            LOG.warning("provider=%s entity=%s:%s field=%s error=%s", provider, entity_type, entity_id, field, type(exc).__name__)
            return None

    def _identify(self, db, release):
        release_id = release["id"]
        known = db.execute("SELECT external_value FROM music_external_ids WHERE entity_type='release' AND entity_id=? AND source='musicbrainz' AND external_type='release_group_id'", (release_id,)).fetchone()
        if known and MBID.fullmatch(known["external_value"]):
            return known["external_value"], "existing_id", 1.0
        payload = self._try(db, "release", release_id, "release_group_id", "musicbrainz",
                            lambda: self.mb.search_release_group(release["artist_credit"], release["title"]))
        if not payload:
            return None, "none", 0.0
        exact = []
        for row in payload.get("release-groups") or []:
            title_ok = normalize_text(row.get("title")) == normalize_text(release["title"])
            artist_ok = normalize_text(self._artist_credit(row)) == normalize_text(release["artist_credit"])
            date = str(row.get("first-release-date") or "")
            year_ok = not release["release_year"] or not date[:4].isdigit() or abs(int(date[:4]) - int(release["release_year"])) <= 1
            if title_ok and artist_ok and year_ok and MBID.fullmatch(str(row.get("id") or "")):
                exact.append(row)
        if len(exact) != 1:
            return None, "uncertain" if payload.get("release-groups") else "none", 0.0
        group = exact[0]
        mbid = group["id"]
        self._external(db, "release", release_id, "musicbrainz", "release_group_id", mbid)
        return mbid, "exact_artist_title_year", 0.98

    def _apply_group(self, db, release_id, group):
        mbid = group.get("id")
        self._value(db, "release", release_id, "canonical_title", group.get("title"), "musicbrainz", mbid)
        self._value(db, "release", release_id, "primary_artist", self._artist_credit(group), "musicbrainz", mbid)
        date = group.get("first-release-date")
        self._value(db, "release", release_id, "release_date", date, "musicbrainz", mbid)
        self._value(db, "release", release_id, "release_year", int(date[:4]) if date and date[:4].isdigit() else None, "musicbrainz", mbid)
        self._value(db, "release", release_id, "primary_type", group.get("primary-type"), "musicbrainz", mbid)
        self._value(db, "release", release_id, "secondary_types", group.get("secondary-types"), "musicbrainz", mbid)
        genres = [row.get("name") for row in group.get("genres") or [] if row.get("name")]
        self._value(db, "release", release_id, "genres", genres, "musicbrainz", mbid)
        self._value(db, "release", release_id, "tags", [row.get("name") for row in group.get("tags") or [] if row.get("name")], "musicbrainz", mbid)

    def _apply_release(self, db, release_id, item):
        mbid = item.get("id")
        self._external(db, "release", release_id, "musicbrainz", "release_id", mbid)
        for field, value in (("release_title", item.get("title")), ("release_date", item.get("date")), ("country", item.get("country")),
                             ("barcode", item.get("barcode")), ("status", item.get("status")),
                             ("packaging", item.get("packaging")),
                             ("language", (item.get("text-representation") or {}).get("language")),
                             ("script", (item.get("text-representation") or {}).get("script"))):
            self._value(db, "release", release_id, field, value, "musicbrainz", mbid)
        date = str(item.get("date") or "")
        self._value(db, "release", release_id, "release_year", int(date[:4]) if date[:4].isdigit() else None, "musicbrainz", mbid)
        label_info = (item.get("label-info") or [{}])[0]
        self._value(db, "release", release_id, "label", (label_info.get("label") or {}).get("name"), "musicbrainz", mbid)
        self._value(db, "release", release_id, "catalog_number", label_info.get("catalog-number"), "musicbrainz", mbid)
        media = item.get("media") or []
        self._value(db, "release", release_id, "media_count", len(media) if media else None, "musicbrainz", mbid)
        self._value(db, "release", release_id, "formats", [medium.get("format") for medium in media if medium.get("format")], "musicbrainz", mbid)
        if not db.execute("SELECT 1 FROM music_tracks WHERE release_id=?", (release_id,)).fetchone():
            for disc, medium in enumerate(media, 1):
                for track in medium.get("tracks") or []:
                    title = track.get("title") or (track.get("recording") or {}).get("title")
                    if not title:
                        continue
                    position = str(track.get("number") or track.get("position") or "")
                    length = track.get("length")
                    db.execute("INSERT OR IGNORE INTO music_tracks(release_id,position,disc_number,title,normalized_title,duration_seconds,source) VALUES(?,?,?,?,?,?,'MusicBrainz')",
                               (release_id, position, disc, title, normalize_text(title), round(length / 1000) if isinstance(length, (int, float)) else None))
        for medium in media:
            for track in medium.get("tracks") or []:
                recording = track.get("recording") or {}
                title = track.get("title") or recording.get("title")
                position = str(track.get("number") or track.get("position") or "")
                local_track = db.execute("SELECT id FROM music_tracks WHERE release_id=? AND position=? AND normalized_title=?",
                                         (release_id, position, normalize_text(title))).fetchone()
                if local_track and recording.get("id"):
                    self._value(db, "track", local_track["id"], "recording_id", recording["id"], "musicbrainz", recording["id"])
                    self._value(db, "track", local_track["id"], "isrcs", recording.get("isrcs"), "musicbrainz", recording["id"])
                for relation in recording.get("relations") or []:
                    self._credit_relation(db, release_id, relation)
                    work = relation.get("work") or {}
                    if local_track and work.get("id"):
                        self._value(db, "track", local_track["id"], "work_id", work["id"], "musicbrainz", work["id"])
                        self._value(db, "track", local_track["id"], "iswcs", work.get("iswcs"), "musicbrainz", work["id"])
                    for work_relation in work.get("relations") or []:
                        self._credit_relation(db, release_id, work_relation)
        for relation in item.get("relations") or []:
            self._credit_relation(db, release_id, relation)

    @staticmethod
    def _credit_relation(db, release_id, relation):
        artist = relation.get("artist") or {}
        role = relation.get("type")
        name = artist.get("name")
        if name and role:
            db.execute("INSERT OR IGNORE INTO music_release_credits(release_id,person_name,normalized_person_name,role,source) VALUES(?,?,?,?,?)",
                       (release_id, name, normalize_text(name), role, "MusicBrainz"))

    def _artist(self, db, release_id, group):
        for credit in group.get("artist-credit") or []:
            if not isinstance(credit, dict):
                continue
            mb_artist = credit.get("artist") or {}
            mbid = mb_artist.get("id")
            name = mb_artist.get("name")
            if not mbid or not MBID.fullmatch(mbid) or not name:
                continue
            artist_row = db.execute("SELECT a.id FROM music_release_artists ra JOIN music_artists a ON a.id=ra.artist_id WHERE ra.release_id=? AND a.normalized_name=?", (release_id, normalize_text(name))).fetchone()
            if not artist_row:
                continue
            artist_id = artist_row["id"]
            self._external(db, "artist", artist_id, "musicbrainz", "artist_id", mbid)
            details = self._try(db, "artist", artist_id, "facts", "musicbrainz", lambda: self.mb.artist(mbid))
            if details:
                for field, value in (("canonical_name", details.get("name")), ("country", details.get("country")), ("area", (details.get("area") or {}).get("name")),
                                     ("artist_type", details.get("type")), ("sort_name", details.get("sort-name")),
                                     ("aliases", [alias.get("name") for alias in details.get("aliases") or [] if alias.get("name")]),
                                     ("begin_date", (details.get("life-span") or {}).get("begin")),
                                     ("end_date", (details.get("life-span") or {}).get("end")),
                                     ("disambiguation", details.get("disambiguation"))):
                    self._value(db, "artist", artist_id, field, value, "musicbrainz", mbid)
                qid = None
                external_links = []
                for relation in details.get("relations") or []:
                    url = (relation.get("url") or {}).get("resource", "")
                    if url.startswith(("http://", "https://")):
                        external_links.append({"type": relation.get("type"), "url": url})
                    candidate = url.rstrip("/").split("/")[-1]
                    if "wikidata.org" in url and QID.fullmatch(candidate):
                        qid = candidate
                    if relation.get("type") == "official homepage":
                        self._value(db, "artist", artist_id, "official_website", url, "musicbrainz", mbid)
                self._value(db, "artist", artist_id, "external_links", external_links, "musicbrainz", mbid)
                if qid:
                    self._external(db, "artist", artist_id, "wikidata", "entity_id", qid)
            else:
                qid_row = db.execute("SELECT external_value FROM music_external_ids WHERE entity_type='artist' AND entity_id=? AND source='wikidata'", (artist_id,)).fetchone()
                qid = qid_row["external_value"] if qid_row else None
            has_image = db.execute("SELECT 1 FROM music_metadata_values WHERE entity_type='artist' AND entity_id=? AND field_name='image_url'", (artist_id,)).fetchone()
            if has_image:
                continue
            if qid:
                entity = self._try(db, "artist", artist_id, "wikidata_entity", "wikidata", lambda: self.wikidata.artist(qid))
                if entity:
                    filename = self._claim(entity, "P18")
                    self._value(db, "artist", artist_id, "wikidata_id", qid, "wikidata", qid)
                    description = (entity.get("descriptions") or {}).get("en", {}).get("value")
                    self._value(db, "artist", artist_id, "factual_description", description, "wikidata", qid)
                    self._value(db, "artist", artist_id, "official_website", self._claim(entity, "P856"), "wikidata", qid)
                    country = self._claim(entity, "P17")
                    if country:
                        self._value(db, "artist", artist_id, "country_id", country, "wikidata", qid)
                    if filename:
                        url = self._try(db, "artist", artist_id, "image_source_url", "wikimedia", lambda: self.wikimedia.image_url(filename))
                        if url:
                            self._try(db, "artist", artist_id, "image_file", "wikimedia", lambda: self._cover(db, "artist", artist_id, "wikimedia", url))
            if os.environ.get("MUSIC_AUDIODB_KEY") and not db.execute("SELECT 1 FROM music_metadata_values WHERE entity_type='artist' AND entity_id=? AND field_name='image_url'", (artist_id,)).fetchone():
                fallback = self._try(db, "artist", artist_id, "artist_lookup", "theaudiodb", lambda: self.audiodb.artist(name))
                if fallback:
                    image = fallback.get("strArtistThumb") or fallback.get("strArtistCutout")
                    if image:
                        self._try(db, "artist", artist_id, "image_url", "theaudiodb", lambda: self._cover(db, "artist", artist_id, "theaudiodb", image))

    def process_release(self, release_id):
        """Enrich one release without replacing existing catalog or user values."""
        self.store.initialize()
        with self.store._connect() as db:
            release = db.execute("SELECT * FROM music_releases WHERE id=?", (release_id,)).fetchone()
            if not release:
                raise ValueError("Album nie istnieje")
            title, artist = release["title"], release["artist_credit"]
            group_id, method, confidence = self._identify(db, release)
            group = {}
            exact_release_id = None
            if group_id:
                group = self._try(db, "release", release_id, "release_group", "musicbrainz", lambda: self.mb.release_group(group_id)) or {}
                if group:
                    self._apply_group(db, release_id, group)
                    self._artist(db, release_id, group)
                # One exact release supplies edition fields and track listing.
                needs_edition = (any(not release[key] for key in ("label", "catalog_number", "release_date"))
                                 or self._needs_better_cover(release)
                                 or not db.execute("SELECT 1 FROM music_tracks WHERE release_id=?", (release_id,)).fetchone()
                                 or not db.execute("SELECT 1 FROM music_release_credits WHERE release_id=?", (release_id,)).fetchone())
                if needs_edition:
                    browse = self._try(db, "release", release_id, "release_candidates", "musicbrainz", lambda: self.mb.releases(group_id)) or {}
                    candidates = [row for row in browse.get("releases") or [] if normalize_text(row.get("title")) == normalize_text(title) and MBID.fullmatch(str(row.get("id") or ""))]
                    candidates.sort(key=lambda row: (row.get("status") != "Official", not row.get("date"), row.get("date") or "9999"))
                    if candidates:
                        exact_release_id = candidates[0]["id"]
                        details = self._try(db, "release", release_id, "edition", "musicbrainz", lambda: self.mb.release(exact_release_id))
                        if details:
                            self._apply_release(db, release_id, details)
            cover = db.execute("SELECT cover_local,cover_remote FROM music_releases WHERE id=?", (release_id,)).fetchone()
            if self._needs_better_cover(cover):
                for mbid, kind in ((group_id, "group"), (exact_release_id, "release")):
                    if not mbid:
                        continue
                    field = f"cover_{kind}"
                    raw = self._try(db, "release", release_id, field, "cover_art_archive",
                                    lambda mbid=mbid, kind=kind: self.caa.artwork(mbid, group=kind == "group"))
                    if raw:
                        url = f"https://coverartarchive.org/{'release-group' if kind == 'group' else 'release'}/{mbid}/front-500"
                        if self._cover(db, "release", release_id, "cover_art_archive", url, raw):
                            break
            cover = db.execute("SELECT cover_local,cover_remote FROM music_releases WHERE id=?", (release_id,)).fetchone()
            needs_cover = self._needs_better_cover(cover)
            current = db.execute("SELECT release_date,label,catalog_number FROM music_releases WHERE id=?", (release_id,)).fetchone()
            needs_facts = (len(str(current["release_date"] or "")) <= 4 or not current["label"] or not current["catalog_number"]
                           or not db.execute("SELECT 1 FROM music_tracks WHERE release_id=?", (release_id,)).fetchone()
                           or not db.execute("SELECT 1 FROM music_release_credits WHERE release_id=?", (release_id,)).fetchone())
            if (needs_cover or needs_facts) and os.environ.get("MUSIC_DISCOGS_TOKEN"):
                discogs = self._try(db, "release", release_id, "discogs_album", "discogs", lambda: self.discogs.album(artist, title))
                if discogs:
                    self._external(db, "release", release_id, "discogs", "master_id", discogs.get("id"))
                    year = discogs.get("year")
                    self._value(db, "release", release_id, "release_year", year if isinstance(year, int) and year > 0 else None, "discogs", str(discogs.get("id")))
                    self._value(db, "release", release_id, "formats", discogs.get("format"), "discogs", str(discogs.get("id")))
                    self._value(db, "release", release_id, "genres", discogs.get("genre"), "discogs", str(discogs.get("id")))
                    if needs_cover and discogs.get("cover_image"):
                        self._try(db, "release", release_id, "cover_url", "discogs",
                                  lambda: self._cover(db, "release", release_id, "discogs", discogs["cover_image"]))
                    edition_fields = db.execute("SELECT release_date,label,catalog_number FROM music_releases WHERE id=?", (release_id,)).fetchone()
                    needs_edition = (len(str(edition_fields["release_date"] or "")) <= 4 or not edition_fields["label"]
                                     or not edition_fields["catalog_number"]
                                     or not db.execute("SELECT 1 FROM music_tracks WHERE release_id=?", (release_id,)).fetchone()
                                     or not db.execute("SELECT 1 FROM music_release_credits WHERE release_id=?", (release_id,)).fetchone())
                    if needs_edition and discogs.get("id"):
                        master = self._try(db, "release", release_id, "discogs_master", "discogs", lambda: self.discogs.master(discogs["id"])) or {}
                        edition_id = master.get("main_release")
                        if edition_id:
                            edition = self._try(db, "release", release_id, "discogs_edition", "discogs", lambda: self.discogs.release(edition_id)) or {}
                            if edition:
                                self._external(db, "release", release_id, "discogs", "release_id", edition_id)
                                self._value(db, "release", release_id, "release_date", str(edition.get("released") or "")[:10], "discogs", str(edition_id))
                                label = (edition.get("labels") or [{}])[0]
                                self._value(db, "release", release_id, "label", label.get("name"), "discogs", str(edition_id))
                                self._value(db, "release", release_id, "catalog_number", label.get("catno"), "discogs", str(edition_id))
                                self._value(db, "release", release_id, "barcode", next((row.get("value") for row in edition.get("identifiers") or [] if row.get("type") == "Barcode"), None), "discogs", str(edition_id))
                                self._value(db, "release", release_id, "formats", [row.get("name") for row in edition.get("formats") or [] if row.get("name")], "discogs", str(edition_id))
                                if not db.execute("SELECT 1 FROM music_tracks WHERE release_id=?", (release_id,)).fetchone():
                                    for track in edition.get("tracklist") or []:
                                        title_value = track.get("title")
                                        if title_value:
                                            db.execute("INSERT OR IGNORE INTO music_tracks(release_id,position,title,normalized_title,source) VALUES(?,?,?,?,?)",
                                                       (release_id, str(track.get("position") or ""), title_value, normalize_text(title_value), "Discogs"))
                                for credit in edition.get("extraartists") or []:
                                    name = credit.get("name")
                                    role = credit.get("role")
                                    if name and role:
                                        db.execute("INSERT OR IGNORE INTO music_release_credits(release_id,person_name,normalized_person_name,role,source) VALUES(?,?,?,?,?)",
                                                   (release_id, name, normalize_text(name), role, "Discogs"))
                                current_cover = db.execute("SELECT cover_local,cover_remote FROM music_releases WHERE id=?", (release_id,)).fetchone()
                                if self._needs_better_cover(current_cover):
                                    image = next((row.get("uri") or row.get("uri150") for row in edition.get("images") or [] if row.get("type") == "primary"), None)
                                    if image:
                                        self._try(db, "release", release_id, "edition_cover_url", "discogs",
                                                  lambda: self._cover(db, "release", release_id, "discogs", image))
            cover = db.execute("SELECT cover_local,cover_remote FROM music_releases WHERE id=?", (release_id,)).fetchone()
            needs_cover = self._needs_better_cover(cover)
            needs_description = not db.execute("SELECT description FROM music_releases WHERE id=?", (release_id,)).fetchone()[0]
            if (needs_cover or needs_description) and os.environ.get("MUSIC_AUDIODB_KEY"):
                audiodb = self._try(db, "release", release_id, "audiodb_album", "theaudiodb", lambda: self.audiodb.album(artist, title))
                if audiodb:
                    self._external(db, "release", release_id, "theaudiodb", "album_id", audiodb.get("idAlbum"))
                    self._value(db, "release", release_id, "description", audiodb.get("strDescriptionEN"), "theaudiodb", audiodb.get("idAlbum"))
                    if needs_cover:
                        image = audiodb.get("strAlbumThumbHQ") or audiodb.get("strAlbumThumb")
                        if image:
                            self._try(db, "release", release_id, "cover_url", "theaudiodb",
                                      lambda: self._cover(db, "release", release_id, "theaudiodb", image))
            cover = db.execute("SELECT cover_local,cover_remote FROM music_releases WHERE id=?", (release_id,)).fetchone()
            needs_cover = self._needs_better_cover(cover)
            current_date = db.execute("SELECT release_date FROM music_releases WHERE id=?", (release_id,)).fetchone()[0]
            full_date = db.execute("SELECT 1 FROM music_metadata_values WHERE entity_type='release' AND entity_id=? AND field_name='release_date' AND length(value_json)>6 LIMIT 1", (release_id,)).fetchone()
            needs_date = len(str(current_date or "")) <= 4 and not full_date
            if needs_cover or needs_date:
                apple = self._try(db, "release", release_id, "apple_album", "apple", lambda: self.apple.album(artist, title))
                if apple:
                    self._external(db, "release", release_id, "apple", "collection_id", apple.get("collectionId"))
                    apple_date = str(apple.get("releaseDate") or "")[:10]
                    self._value(db, "release", release_id, "release_date", apple_date, "apple", str(apple.get("collectionId")))
                    self._value(db, "release", release_id, "release_year", int(apple_date[:4]) if apple_date[:4].isdigit() else None, "apple", str(apple.get("collectionId")))
                    image = (apple.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
                    if needs_cover and image:
                        self._try(db, "release", release_id, "cover_url", "apple",
                                  lambda: self._cover(db, "release", release_id, "apple", image))
            updated = db.execute("SELECT cover_local,cover_remote FROM music_releases WHERE id=?", (release_id,)).fetchone()
            errors = db.execute("SELECT count(*) FROM music_metadata_checks WHERE entity_type='release' AND entity_id=? AND status='error'", (release_id,)).fetchone()[0]
            return {"ok": True, "releaseId": release_id, "match": method, "method": method,
                    "confidence": confidence, "cover": bool(updated["cover_local"] or updated["cover_remote"]), "errors": errors}

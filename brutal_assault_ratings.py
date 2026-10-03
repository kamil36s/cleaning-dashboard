import itertools
import json
import queue
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import re


MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_SITE = "https://musicbrainz.org/release-group"


def _identity(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(str.maketrans({
        "ł": "l", "đ": "d", "ð": "d", "þ": "th",
        "æ": "ae", "œ": "oe", "ø": "o",
    }))
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _candidate_artist(candidate):
    credits = candidate.get("artist-credit") or []
    return " ".join(str(item.get("name") or "") for item in credits).strip()


def choose_release_group(results, artist, album):
    target_artist = _identity(artist)
    target_album = _identity(album)
    if not target_artist or not target_album:
        return None

    exact = [
        item for item in results or []
        if _identity(item.get("title")) == target_album
        and _identity(_candidate_artist(item)) == target_artist
    ]
    if exact:
        return max(exact, key=lambda item: int(item.get("score") or 0))

    strong = [
        item for item in results or []
        if int(item.get("score") or 0) >= 90
        and _identity(item.get("title")) == target_album
    ]
    return max(strong, key=lambda item: int(item.get("score") or 0)) if strong else None


class MusicBrainzRatingProvider:
    def __init__(self, *, min_delay=1.1, opener=None):
        self.min_delay = float(min_delay)
        self.opener = opener
        self._lock = threading.Lock()
        self._last_call = 0.0

    def _get_json(self, url):
        with self._lock:
            wait = self.min_delay - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "cleaning-dashboard/1.0 (local personal dashboard)",
                },
            )
            if self.opener:
                response = self.opener(request)
            else:
                response = urllib.request.urlopen(request, timeout=20)
            with response:
                return json.load(response)

    def lookup(self, artist, album):
        query = f'artist:"{artist}" AND releasegroup:"{album}"'
        params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 5})
        search = self._get_json(f"{MUSICBRAINZ_API}/release-group/?{params}")
        match = choose_release_group(search.get("release-groups") or [], artist, album)
        if not match or not match.get("id"):
            return {"rating": None, "votes": 0, "source": "MusicBrainz", "url": None}

        release_group_id = match["id"]
        details = self._get_json(
            f"{MUSICBRAINZ_API}/release-group/{release_group_id}?inc=ratings&fmt=json"
        )
        rating = details.get("rating") or {}
        value = rating.get("value")
        votes = int(rating.get("votes-count") or 0)
        return {
            "rating": float(value) if value is not None and votes > 0 else None,
            "votes": votes,
            "source": "MusicBrainz",
            "url": f"{MUSICBRAINZ_SITE}/{release_group_id}",
        }


class BrutalAssaultRatingEnricher:
    def __init__(self, store, *, provider=None, logger=None):
        self.store = store
        self.provider = provider or MusicBrainzRatingProvider()
        self.logger = logger
        self._queue = queue.PriorityQueue()
        self._queued = set()
        self._lock = threading.Lock()
        self._counter = itertools.count()
        self._worker = None

    def _log(self, message):
        if self.logger:
            self.logger(message)

    def _ensure_worker(self):
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run,
                name="ba2027-musicbrainz-ratings",
                daemon=True,
            )
            self._worker.start()

    @staticmethod
    def _interleave_by_artist(rows):
        groups = {}
        order = []
        for row in sorted(rows, key=lambda item: (item.get("date") or "", item.get("rowId") or 0)):
            key = _identity(row.get("artist"))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)
        result = []
        while groups:
            for key in list(order):
                albums = groups.get(key)
                if not albums:
                    groups.pop(key, None)
                    order.remove(key)
                    continue
                result.append(albums.pop(0))
        return result

    def schedule(self, rows, *, priority=10, force=False):
        candidates = [
            row for row in rows or []
            if row.get("rowId") is not None
            and not row.get("rymRating")
            and (force or not row.get("communityCheckedAt"))
        ]
        for row in self._interleave_by_artist(candidates):
            album_id = int(row["rowId"])
            with self._lock:
                if album_id in self._queued:
                    continue
                self._queued.add(album_id)
                self._queue.put((int(priority), next(self._counter), album_id))
        if candidates:
            self._ensure_worker()
        return self.pending_count()

    def pending_count(self):
        with self._lock:
            return len(self._queued)

    def _run(self):
        while True:
            _, _, album_id = self._queue.get()
            try:
                album = self.store.get(album_id)
                if album and not album.get("rymRating"):
                    result = self.provider.lookup(album.get("artist"), album.get("album"))
                    self.store.update_community_rating(album_id, **result)
            except Exception as exc:
                self._log(f"MusicBrainz rating failed for album {album_id}: {exc}")
            finally:
                with self._lock:
                    self._queued.discard(album_id)
                self._queue.task_done()

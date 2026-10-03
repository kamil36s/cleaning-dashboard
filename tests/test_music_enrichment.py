import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from music_enrichment import MusicEnrichment, ProviderScheduler, without_scores
from music_store import MusicStore, utc_now


GROUP = "11111111-1111-4111-8111-111111111111"
ARTIST = "22222222-2222-4222-8222-222222222222"


class FakeScheduler:
    DEFAULTS = ProviderScheduler.DEFAULTS

    def __init__(self, *, groups=None, cover=True):
        self.groups = groups if groups is not None else [{
            "id": GROUP, "title": "Example", "first-release-date": "2020-01-02",
            "artist-credit": [{"name": "Artist", "artist": {"id": ARTIST, "name": "Artist"}}],
        }]
        self.cover = cover
        self.calls = []
        self._next = {name: 0 for name in self.DEFAULTS}

    def clock(self):
        return 0

    _allowed_image_url = staticmethod(ProviderScheduler._allowed_image_url)

    def request(self, provider, url, *, image=False, headers=None):
        self.calls.append((provider, url))
        if image and provider != "cover_art_archive":
            return b"\xff\xd8image", "image/jpeg", url
        if "/release-group/?" in url:
            return {"release-groups": self.groups}
        if "/release-group/" in url and provider == "musicbrainz":
            return {**self.groups[0], "primary-type": "EP", "genres": [{"name": "Rock"}]}
        if "/release/?" in url:
            return {"releases": []}
        if "/artist/" in url:
            return {"id": ARTIST, "country": "PL", "relations": []}
        if provider == "cover_art_archive":
            return (b"\xff\xd8image", "image/jpeg", url) if self.cover else None
        if provider == "discogs":
            return {"results": [{"id": 7, "title": "Artist - Example", "cover_image": "https://i.discogs.com/image.jpg", "year": 2020}]}
        if provider == "apple":
            return {"results": []}
        if provider == "theaudiodb":
            return {"album": None, "artists": None}
        return {}


class MusicEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MusicStore(Path(self.temp.name))
        self.store.initialize()
        with self.store._connect() as db:
            self.release_id = db.execute("""INSERT INTO music_releases(title,normalized_title,artist_credit,normalized_artist_credit,
                release_type,release_year,created_at,updated_at) VALUES('Example','example','Artist','artist','Album',2020,?,?)""",
                (utc_now(), utc_now())).lastrowid
            artist_id = self.store._artist_id(db, "Artist")
            db.execute("INSERT INTO music_release_artists(release_id,artist_id) VALUES(?,?)", (self.release_id, artist_id))

    def test_additive_migration_and_missing_list_excludes_rating(self):
        self.store.initialize()
        missing = self.store.missing_metadata({"field": "rym_rating"})
        self.assertEqual(missing["total"], 0)
        self.assertNotIn("rym_rating", missing["labels"])
        with self.store._connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM music_schema_migrations WHERE version=3").fetchone()[0], 1)

    def test_musicbrainz_artist_credit_keeps_join_phrase(self):
        credit = [{'name': 'Alice Coltrane', 'joinphrase': ' featuring '}, {'name': 'Pharoah Sanders'}]
        self.assertEqual(MusicEnrichment._artist_credit({'artist-credit': credit}),
                         'Alice Coltrane featuring Pharoah Sanders')

    def test_full_date_fallback_does_not_replace_year_only_source(self):
        engine = MusicEnrichment(self.store, FakeScheduler())
        with self.store._connect() as db:
            db.execute("UPDATE music_releases SET release_date='2020' WHERE id=?", (self.release_id,))
            engine._value(db, "release", self.release_id, "release_date", "2020-05-09", "apple", "123")
        release = self.store.release_detail(self.release_id)["release"]
        self.assertEqual(release["release_date"], "2020")
        self.assertEqual(release["effective_release_date"], "2020-05-09")
        self.assertEqual(self.store.missing_metadata({"field": "date"})["total"], 0)

    def test_exact_match_local_cover_and_existing_data(self):
        fake = FakeScheduler()
        engine = MusicEnrichment(self.store, fake)
        with self.store._connect() as db:
            db.execute("UPDATE music_releases SET release_date='2020-12-25' WHERE id=?", (self.release_id,))
        engine.enqueue(self.release_id)
        result = engine.run_next()
        self.assertTrue(result["cover"])
        release = self.store.release_detail(self.release_id)["release"]
        self.assertEqual(release["release_date"], "2020-12-25")
        self.assertEqual(release["metadata"]["primary_type"], "EP")
        self.assertTrue((self.store.root / release["cover_local"].lstrip("/")).is_file())
        self.assertEqual(engine.status()["jobs"]["done"], 1)
        calls = len(fake.calls)
        engine.process_release(self.release_id)
        self.assertEqual(len(fake.calls), calls)
        with self.store._connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM music_artwork_cache").fetchone()[0], 1)

    def test_small_existing_cover_is_replaced_by_larger_provider_art(self):
        class LargeCoverScheduler(FakeScheduler):
            def request(self, provider, url, *, image=False, headers=None):
                if provider == 'cover_art_archive' and image:
                    return b'\x89PNG\r\n\x1a\n' + bytes(8) + (500).to_bytes(4, 'big') * 2, 'image/png', url
                return super().request(provider, url, image=image, headers=headers)

        small = self.store.root / 'covers' / 'small.png'
        small.parent.mkdir(parents=True, exist_ok=True)
        small.write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(8) + (96).to_bytes(4, 'big') * 2)
        with self.store._connect() as db:
            db.execute("UPDATE music_releases SET cover_local='/covers/small.png' WHERE id=?", (self.release_id,))
        engine = MusicEnrichment(self.store, LargeCoverScheduler())
        engine.process_release(self.release_id)
        release = self.store.release_detail(self.release_id)['release']
        self.assertNotEqual(release['cover_local'], '/covers/small.png')
        self.assertEqual(engine._cover_dimensions(release['cover_local']), (500, 500))
        legacy = self.store.root / 'covers' / (self.store._cover_slug('Artist', 'Example') + '.png')
        legacy.write_bytes(small.read_bytes())
        self.store.sync_local_covers()
        self.assertEqual(self.store.release_detail(self.release_id)['release']['cover_local'], release['cover_local'])

    def test_provider_genres_do_not_enter_canonical_genre_tree(self):
        engine = MusicEnrichment(self.store, FakeScheduler())
        engine.process_release(self.release_id)
        self.assertEqual(self.store.genre_tree()['total'], 0)

    def test_genre_cleanup_migration_preserves_rym_genres(self):
        with self.store._connect() as db:
            db.execute('DELETE FROM music_schema_migrations WHERE version=4')
            for source, name in [('MusicBrainz', 'rock'), ('RYM', 'Rock')]:
                db.execute("""INSERT INTO music_genres(name,normalized_name,source,created_at,updated_at)
                    VALUES(?,?,?,?,?)""", (name, name.lower(), source, utc_now(), utc_now()))
        self.store.initialize()
        self.assertEqual([(row['source'], row['name']) for row in self.store.genre_tree()['genres']], [('RYM', 'Rock')])

    def test_missing_artist_photo_prioritizes_one_existing_album(self):
        engine = MusicEnrichment(self.store, FakeScheduler())
        self.assertEqual(engine.prioritize_artist_photos(['Artist']), 1)
        with self.store._connect() as db:
            job = db.execute('SELECT status,priority FROM music_enrichment_jobs WHERE release_id=?', (self.release_id,)).fetchone()
        self.assertEqual((job['status'], job['priority']), ('pending', -2))

    def test_visible_small_cover_is_queued_before_background_backfill(self):
        small = self.store.root / 'covers' / 'small.png'
        small.parent.mkdir(parents=True, exist_ok=True)
        small.write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(8) + (96).to_bytes(4, 'big') * 2)
        with self.store._connect() as db:
            db.execute("UPDATE music_releases SET cover_local='/covers/small.png' WHERE id=?", (self.release_id,))
        engine = MusicEnrichment(self.store, FakeScheduler())
        self.assertEqual(engine.prioritize_visible_covers([{'id': self.release_id, 'cover_local': '/covers/small.png', 'cover_remote': None}]), 1)
        with self.store._connect() as db:
            job = db.execute('SELECT status,priority FROM music_enrichment_jobs WHERE release_id=?', (self.release_id,)).fetchone()
        self.assertEqual((job['status'], job['priority']), ('pending', -100))

    def test_uncertain_match_never_writes_mbid(self):
        group = FakeScheduler().groups[0]
        fake = FakeScheduler(groups=[group, {**group, "id": "33333333-3333-4333-8333-333333333333"}], cover=False)
        engine = MusicEnrichment(self.store, fake)
        with patch.dict("os.environ", {"MUSIC_DISCOGS_TOKEN": "", "MUSIC_AUDIODB_KEY": ""}):
            engine.enqueue(self.release_id)
            result = engine.run_next()
        self.assertEqual(result["match"], "uncertain")
        self.assertEqual(engine.status()["jobs"]["unresolved"], 1)
        with self.store._connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM music_external_ids WHERE source='musicbrainz'").fetchone()[0], 0)

    def test_negative_cache_and_discogs_cover_fallback(self):
        fake = FakeScheduler(cover=False)
        engine = MusicEnrichment(self.store, fake)
        with patch.dict("os.environ", {"MUSIC_DISCOGS_TOKEN": "test-token", "MUSIC_AUDIODB_KEY": ""}):
            first = engine.process_release(self.release_id)
            self.assertTrue(first["cover"])
            count = sum(provider == "cover_art_archive" for provider, _ in fake.calls)
            engine.process_release(self.release_id)
        self.assertEqual(sum(provider == "cover_art_archive" for provider, _ in fake.calls), count)
        self.assertFalse(any(provider == "apple" for provider, _ in fake.calls))

    def test_recording_work_credit_and_tracks_are_idempotent(self):
        engine = MusicEnrichment(self.store, FakeScheduler())
        edition = {"id": "44444444-4444-4444-8444-444444444444", "media": [{"format": "CD", "tracks": [{
            "number": "1", "title": "Song", "length": 100000,
            "recording": {"id": "55555555-5555-4555-8555-555555555555", "relations": [{"work": {
                "id": "66666666-6666-4666-8666-666666666666",
                "relations": [{"type": "composer", "artist": {"name": "Composer"}}],
            }}]},
        }]}]}
        with self.store._connect() as db:
            engine._apply_release(db, self.release_id, edition)
            engine._apply_release(db, self.release_id, edition)
        release = self.store.release_detail(self.release_id)["release"]
        self.assertEqual([track["title"] for track in release["tracks"]], ["Song"])
        self.assertEqual([(credit["person_name"], credit["role"]) for credit in release["credits"]], [("Composer", "composer")])

    def test_worker_can_be_disabled_without_affecting_catalog(self):
        engine = MusicEnrichment(self.store, FakeScheduler())
        engine.enqueue(self.release_id)
        with patch.dict("os.environ", {"MUSIC_ENRICHMENT_ENABLED": "false"}):
            self.assertIsNone(engine.run_next())
            self.assertFalse(engine.status()["enabled"])
            self.assertEqual(self.store.release_detail(self.release_id)["release"]["title"], "Example")


class Response:
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _):
        return json.dumps({"ok": True}).encode()

    def geturl(self):
        return "https://musicbrainz.org/ws/2/test"


class SchedulerTests(unittest.TestCase):
    def test_provider_cache_strips_ratings(self):
        self.assertEqual(without_scores({"title": "Album", "community": {"rating": 4}, "tracks": [{"title": "Song", "score": 90}]}),
                         {"title": "Album", "tracks": [{"title": "Song"}]})

    def test_rate_limit_and_retry_after(self):
        current = [0.0]
        sleeps = []
        attempts = [0]

        def sleep(seconds):
            sleeps.append(seconds)
            current[0] += seconds

        def opener(_request, timeout):
            attempts[0] += 1
            if attempts[0] == 1:
                raise urllib.error.HTTPError("url", 429, "slow down", {"Retry-After": "3"}, io.BytesIO())
            return Response()

        scheduler = ProviderScheduler(opener=opener, sleep=sleep, clock=lambda: current[0])
        self.assertEqual(scheduler.request("musicbrainz", "https://musicbrainz.org/ws/2/test"), {"ok": True})
        scheduler.request("musicbrainz", "https://musicbrainz.org/ws/2/test")
        self.assertEqual(attempts[0], 3)
        self.assertGreaterEqual(sleeps[0], 3)
        self.assertGreaterEqual(sum(sleeps), 4.15)

    def test_per_minute_budget(self):
        current = [0.0]

        def sleep(seconds):
            current[0] += seconds

        scheduler = ProviderScheduler(opener=lambda *_args, **_kwargs: Response(), sleep=sleep, clock=lambda: current[0])
        with patch.dict("os.environ", {"MUSIC_APPLE_MAX_PER_MINUTE": "2"}):
            for _ in range(3):
                scheduler.request("apple", "https://itunes.apple.com/search?term=test")
        self.assertGreaterEqual(current[0], 60)


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_store import MusicError, MusicStore
from tests.music_fixtures import GENRE_HTML, chart_html, release_html


class MusicStoreTests(unittest.TestCase):
    def test_collection_import_preserves_existing_rating_and_ranks_artists(self):
        _, first = self.preview_commit("chart.html", chart_html([
            {"id": 42, "artist": "First Artist", "title": "First Album", "year": 2020},
        ]))
        self.store.set_rating(first["releases"][0], 4.5)
        html = '''<html><head><link rel="canonical" href="https://rateyourmusic.com/collection/me/1"></head><body><table>
          <tr id="page_catalog_item_1"><td class="or_q_rating_date_d"><i class="date_element_month">Sep</i><i class="date_element_day">11</i><i class="date_element_year">2022</i></td><td class="or_q_rating_date_s"><img alt="3.50 stars"></td><td class="or_q_albumartist_td"><a class="artist">First Artist</a><a class="album" title="[Album42]" href="https://rateyourmusic.com/release/album/first-artist/first-album/">First Album</a><span class="smallgray">(2020)</span></td></tr>
          <tr id="page_catalog_item_2"><td class="or_q_rating_date_d"><i class="date_element_month">Oct</i><i class="date_element_day">12</i><i class="date_element_year">2023</i></td><td class="or_q_rating_date_s"><img alt="4.00 stars"></td><td class="or_q_albumartist_td"><a class="artist">Second Artist</a><a class="album" title="[Album43]" href="https://rateyourmusic.com/release/album/second-artist/second-album/">Second Album</a><span class="smallgray">(2021)</span></td></tr>
          </table></body></html>'''
        preview, imported = self.preview_commit("collection.html", html)
        self.assertEqual((imported["matched"], imported["created"], imported["ratingsAdded"]), (1, 1, 1))
        self.assertEqual(imported["ratingsAlreadyPresent"], 1)
        self.assertEqual(len(imported["ratingConflicts"]), 1)
        self.assertEqual(self.store.release_detail(first["releases"][0])["release"]["user_rating"], 4.5)
        self.assertEqual(self.store.overview()["stats"]["ratings"], 2)
        ranking = self.store.artist_ranking(min_ratings=1)["rows"]
        self.assertEqual([(row["name"], row["average_rating"]) for row in ranking],
                         [("First Artist", 4.5), ("Second Artist", 4.0)])
        self.assertTrue(self.store.preview_import(filename="collection.html", html=html)["alreadyImported"])
        self.assertTrue(self.store.commit_import(preview["batch"]["id"])["alreadyCommitted"])

    def test_artist_ranking_joins_rym_name_variants(self):
        html = '''<html><head><link rel="canonical" href="https://rateyourmusic.com/collection/me/1"></head><body><table>
          <tr id="page_catalog_item_10"><td class="or_q_rating_date_s"><img alt="4.00 stars"></td><td class="or_q_albumartist_td"><a class="artist" title="[Artist117]">Cure</a><a class="album" title="[Album10]" href="https://rateyourmusic.com/release/album/the-cure/one/">One</a><span class="smallgray">(1980)</span></td></tr>
          <tr id="page_catalog_item_11"><td class="or_q_rating_date_s"><img alt="5.00 stars"></td><td class="or_q_albumartist_td"><a class="artist" title="[Artist117]">The Cure</a><a class="album" title="[Album11]" href="https://rateyourmusic.com/release/album/the-cure/two/">Two</a><span class="smallgray">(1981)</span></td></tr>
          </table></body></html>'''
        self.preview_commit("collection.html", html)
        ranking = self.store.artist_ranking(min_ratings=2)["rows"]
        self.assertEqual(len(ranking), 1)
        self.assertEqual((ranking[0]["rated_count"], ranking[0]["average_rating"]), (2, 4.5))
        releases = self.store.list_releases({"ids": ",".join(map(str, ranking[0]["release_ids"])),
                                             "q": ranking[0]["name"]})
        self.assertEqual(releases["total"], 2)

    def test_artist_weighted_score_matches_bm365_and_excludes_singles(self):
        _, result = self.preview_commit("albums.html", chart_html([
            {"id": 101, "artist": "Alpha", "title": "First"},
            {"id": 102, "artist": "Beta", "title": "Second"},
            {"id": 103, "artist": "Gamma", "title": "Single Track"},
        ]))
        for release_id, rating in zip(result["releases"], (5.0, 3.0, 1.0)):
            self.store.set_rating(release_id, rating)
        with sqlite3.connect(self.store.path) as connection:
            connection.execute("UPDATE music_releases SET release_type='Single' WHERE id=?", (result["releases"][2],))
        ranking = self.store.artist_ranking(min_ratings=1, sort="weighted")
        self.assertEqual(ranking["globalAverage"], 4.0)
        self.assertEqual(ranking["weightPrior"], 3)
        self.assertEqual([(row["name"], row["average_rating"], row["weighted_rating"])
                          for row in ranking["rows"]], [("Alpha", 5.0, 4.25), ("Beta", 3.0, 3.75)])

    def test_release_year_modes_and_rated_visibility(self):
        _, result = self.preview_commit("years.html", chart_html([
            {"id": 201, "artist": "Alpha", "title": "One", "year": 1984},
            {"id": 202, "artist": "Beta", "title": "Two", "year": 1988},
            {"id": 203, "artist": "Gamma", "title": "Three", "year": 1991},
        ]))
        self.store.set_rating(result["releases"][0], 5.0)
        self.assertEqual(self.store.list_releases({"yearMode": "year", "year": "1984"})["total"], 1)
        self.assertEqual(self.store.list_releases({"yearMode": "decade", "decade": "1980"})["total"], 2)
        self.assertEqual(self.store.list_releases({"yearMode": "range", "yearFrom": "1988", "yearTo": "1991"})["total"], 2)
        self.assertEqual(self.store.list_releases({"showRated": "1", "showUnrated": "0"})["total"], 1)
        self.assertEqual(self.store.list_releases({"showRated": "0", "showUnrated": "1"})["total"], 2)
        self.assertEqual(self.store.list_releases({"showRated": "0", "showUnrated": "0"})["total"], 0)
        self.store.set_rating(result["releases"][1], 4.0)
        self.store.set_rating(result["releases"][2], 1.0)
        decade = self.store.artist_ranking(min_ratings=1, period={"yearMode": "decade", "decade": "1980"})
        self.assertEqual(decade["globalAverage"], 4.5)
        self.assertEqual({row["name"] for row in decade["rows"]}, {"Alpha", "Beta"})
        with self.assertRaises(MusicError):
            self.store.list_releases({"yearMode": "range", "yearFrom": "2000", "yearTo": "1980"})

    def test_library_sorts_personal_and_rym_ratings_before_pagination(self):
        _, result = self.preview_commit("sort.html", chart_html([
            {"id": 301, "artist": "Alpha", "title": "Low"},
            {"id": 302, "artist": "Beta", "title": "High"},
            {"id": 303, "artist": "Gamma", "title": "Unrated"},
        ]))
        low, high, unrated = result["releases"]
        self.store.set_rating(low, 2.0)
        self.store.set_rating(high, 5.0)
        with sqlite3.connect(self.store.path) as connection:
            connection.execute("UPDATE music_release_metric_snapshots SET rating=4.8 WHERE release_id=?", (low,))
            connection.execute("UPDATE music_release_metric_snapshots SET rating=3.1 WHERE release_id=?", (high,))
            connection.execute("DELETE FROM music_release_metric_snapshots WHERE release_id=?", (unrated,))
        ids = lambda filters: [row["id"] for row in self.store.list_releases(filters)["rows"]]
        self.assertEqual(ids({}), [high, low, unrated])
        self.assertEqual(ids({"sort": "my_asc"}), [low, high, unrated])
        self.assertEqual(ids({"sort": "rym_desc"}), [low, high, unrated])
        self.assertEqual(ids({"sort": "rym_asc"}), [high, low, unrated])
        self.assertEqual(ids({"sort": "my_desc", "limit": 1, "offset": 1}), [low])
        with self.assertRaises(MusicError):
            self.store.list_releases({"sort": "unknown"})

    def test_library_uses_visible_rating_and_separate_legacy_listened_status(self):
        _, result = self.preview_commit("statuses.html", chart_html([
            {"id": 401, "artist": "Alpha", "title": "Rated"},
            {"id": 402, "artist": "Beta", "title": "Not Listened"},
            {"id": 403, "artist": "Gamma", "title": "RYM Only"},
        ]))
        rated, not_listened, rym_only = result["releases"]
        self.store.set_rating(rated, 2.0)
        with sqlite3.connect(self.store.path) as connection:
            for release_id, module, listened, legacy_rating in (
                (rated, "black_metal_365", 0, 5.0),
                (rated, "brutal_assault_2027", 1, 5.0),
                (not_listened, "black_metal_365", 0, None),
            ):
                link = connection.execute(
                    "INSERT INTO music_legacy_links(legacy_module,legacy_entity_type,legacy_entity_id,"
                    "music_release_id,match_method,created_at) VALUES(?,'album',?,?,'EXACT','2026-01-01')",
                    (module, f"{module}-{release_id}", release_id),
                ).lastrowid
                connection.execute(
                    "INSERT INTO music_legacy_release_state(legacy_link_id,listened,rating,observed_at,payload_json) "
                    "VALUES(?,?,?,'2026-01-01','{}')", (link, listened, legacy_rating),
                )
        ids = lambda filters: {row["id"] for row in self.store.list_releases(filters)["rows"]}
        self.assertEqual(ids({"rating": "4"}), set())
        self.assertEqual(ids({"listened": "yes"}), {rated})
        self.assertEqual(ids({"listened": "no"}), {not_listened})
        self.assertEqual(ids({"showRated": "0", "showUnrated": "1"}), {not_listened, rym_only})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MusicStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def preview_commit(self, filename, html, captured="2026-09-10T10:00:00+00:00"):
        preview = self.store.preview_import(filename=filename, html=html, captured_at=captured)
        return preview, self.store.commit_import(preview["batch"]["id"])

    def test_chart_then_release_page_keeps_one_canonical_release(self):
        chart = chart_html([{"id": 14012000, "artist": "Old Saw", "title": "Country Tropics", "year": 2021}])
        _, first = self.preview_commit("ambient.html", chart)
        self.assertEqual(first["created"], 1)
        preview = self.store.preview_import(filename="country.html", html=release_html())
        self.assertEqual(preview["batch"]["rows"][0]["match_status"], "EXACT_MATCH")
        second = self.store.commit_import(preview["batch"]["id"])
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.overview()["stats"]["releases"], 1)
        release = self.store.release_detail(first["releases"][0])["release"]
        self.assertEqual(len(release["tracks"]), 1)
        self.assertEqual(len(release["genres"]), 4)

    def test_same_file_is_idempotent_and_changed_capture_adds_snapshot(self):
        html = chart_html([{"id": 1, "artist": "Artist", "title": "Album"}])
        preview, _ = self.preview_commit("chart.html", html)
        duplicate = self.store.preview_import(filename="chart.html", html=html)
        self.assertTrue(duplicate["alreadyImported"])
        self.assertTrue(self.store.commit_import(preview["batch"]["id"])["alreadyCommitted"])
        changed = html.replace("<body", "<!-- new capture --><body")
        self.preview_commit("chart-new.html", changed, "2026-10-10T10:00:00+00:00")
        rankings = self.store.rankings()["rows"]
        self.assertEqual(rankings[0]["snapshot_count"], 2)
        self.assertIsNotNone(rankings[0]["genre_id"])
        self.assertEqual(self.store.overview()["stats"]["releases"], 1)

    def test_genre_import_is_idempotent(self):
        self.preview_commit("genres.html", GENRE_HTML)
        changed = GENRE_HTML.replace("</body>", "<!-- second capture --></body>")
        self.preview_commit("genres-2.html", changed)
        genres = self.store.genres({"limit": 100})
        self.assertEqual(genres["total"], 3)
        ambient = next(row for row in genres["rows"] if row["name"] == "Ambient Americana")
        detail = self.store.genre_detail(ambient["id"])["genre"]
        self.assertEqual([row["name"] for row in detail["parents"]], ["Ambient"])

    def test_docx_hierarchy_keeps_equal_names_with_distinct_rym_slugs(self):
        parsed = {
            "rows": [
                {"name": "Hardcore [Punk]", "url": "https://rateyourmusic.com/genre/hardcore-punk-1/", "slug": "hardcore-punk-1"},
                {"name": "Hardcore Punk", "url": "https://rateyourmusic.com/genre/hardcore-punk/", "slug": "hardcore-punk"},
            ],
            "relations": [{
                "parentUrl": "https://rateyourmusic.com/genre/hardcore-punk-1/",
                "childUrl": "https://rateyourmusic.com/genre/hardcore-punk/",
            }],
            "occurrenceCount": 2,
        }
        result = self.store.sync_genre_hierarchy(parsed)
        self.assertEqual(result["genres"], 2)
        self.assertEqual(result["relations"], 1)
        self.assertEqual(result["missingRelations"], 0)
        rows = self.store.genres({"q": "hardcore", "limit": 10})["rows"]
        self.assertEqual({row["slug"] for row in rows}, {"hardcore-punk", "hardcore-punk-1"})

    def test_missing_metadata_queue_updates_after_cover_is_added(self):
        _, result = self.preview_commit("chart.html", chart_html([{"id": 1, "artist": "Artist", "title": "Album"}]))
        release_id = result["releases"][0]
        with sqlite3.connect(self.store.path) as connection:
            connection.execute("UPDATE music_releases SET cover_local=NULL,cover_remote=NULL WHERE id=?", (release_id,))
        before = self.store.missing_metadata({"field": "cover"})
        self.assertEqual(before["total"], 1)
        self.assertIn("cover", before["rows"][0]["missing"])
        self.store.set_cover(release_id, "/covers/artist-album.webp")
        after = self.store.missing_metadata({"field": "cover"})
        self.assertEqual(after["total"], 0)

    def test_fuzzy_match_is_not_silently_merged(self):
        self.preview_commit("first.html", chart_html([{"id": 1, "artist": "Alpha Artist", "title": "Color Fields", "slug": "color-fields"}]))
        other = chart_html([{"id": 2, "artist": "Alpha Artist", "title": "Colour Fields", "slug": "colour-fields"}], canonical="https://rateyourmusic.com/charts/top/album/2020/g:test/")
        preview = self.store.preview_import(filename="other.html", html=other)
        self.assertEqual(preview["batch"]["rows"][0]["match_status"], "AMBIGUOUS")
        result = self.store.commit_import(preview["batch"]["id"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.store.overview()["stats"]["releases"], 1)

    def test_legacy_match_creates_only_a_read_only_mapping(self):
        legacy = [{
            "legacyModule": "black_metal_365",
            "legacyEntityType": "album",
            "legacyEntityId": "42",
            "artist": "Legacy Artist",
            "title": "Legacy Album",
            "year": 2021,
            "rating": 4.0,
            "confidence": 1.0,
        }]
        html = chart_html([{"id": 42, "artist": "Legacy Artist", "title": "Legacy Album", "year": 2021}])
        with patch("music_store.find_legacy_matches", return_value=legacy):
            preview = self.store.preview_import(filename="legacy.html", html=html)
        self.assertEqual(preview["batch"]["rows"][0]["match_status"], "LEGACY_MATCH")
        result = self.store.commit_import(preview["batch"]["id"])
        release = self.store.release_detail(result["releases"][0])["release"]
        self.assertEqual(release["legacyLinks"][0]["legacy_module"], "black_metal_365")

    def test_commit_failure_rolls_back_everything(self):
        html = chart_html([
            {"id": 1, "artist": "One", "title": "First"},
            {"id": 2, "artist": "Two", "title": "Second"},
        ])
        preview = self.store.preview_import(filename="rollback.html", html=html)
        with self.assertRaises(MusicError):
            self.store.commit_import(preview["batch"]["id"], fail_after=1)
        self.assertEqual(self.store.overview()["stats"]["releases"], 0)
        with sqlite3.connect(self.store.path) as connection:
            status = connection.execute("SELECT status FROM music_import_batches WHERE id=?", (preview["batch"]["id"],)).fetchone()[0]
        self.assertEqual(status, "PREVIEW")

    def test_personal_rating_ranking_and_list_are_independent(self):
        _, result = self.preview_commit("chart.html", chart_html([{"id": 1, "artist": "Artist", "title": "Album"}]))
        release_id = result["releases"][0]
        self.store.set_rating(release_id, 4.5)
        ranking = self.store.create_personal_ranking("My ranking")["ranking"]
        self.store.update_personal_ranking(ranking["id"], action="add", release_id=release_id)
        listing = self.store.create_list("To hear")
        self.store.update_list_entry(listing["id"], action="add", release_id=release_id)
        detail = self.store.release_detail(release_id)["release"]
        self.assertEqual(detail["user_rating"], 4.5)
        self.assertEqual(len(detail["rankings"]), 2)  # source + personal
        self.assertEqual(len(detail["lists"]), 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

from music_importers import _build_rym_genre_hierarchy, parse_rym_genre_docx, parse_rym_html
from tests.music_fixtures import GENRE_HTML, chart_html, release_html


class MusicImporterTests(unittest.TestCase):
    def test_collection_extracts_personal_rating_and_identity(self):
        html = '''<html><head><title>My music - Rate Your Music</title>
          <link rel="canonical" href="https://rateyourmusic.com/collection/me/1"></head><body>
          <table><tr id="page_catalog_item_123"><td class="or_q_rating_date_d">
          <span class="date_element_month">Sep</span><span class="date_element_day">11</span>
          <span class="date_element_year">2022</span></td>
          <td class="or_q_rating_date_s"><img alt="3.50 stars"></td>
          <td class="or_q_albumartist_td"><a class="artist" title="[Artist9]">Artist</a>
          <a class="album" title="[Album42]" href="https://rateyourmusic.com/release/album/artist/title/">Title</a>
          <span class="smallgray">(2020)</span></td></tr></table></body></html>'''
        parsed = parse_rym_html(html)
        self.assertEqual(parsed["pageType"], "RYM_COLLECTION")
        self.assertEqual(parsed["rows"][0]["rymReleaseId"], "42")
        self.assertEqual(parsed["rows"][0]["userRating"], 3.5)
        self.assertEqual(parsed["rows"][0]["ratedAt"], "2022-09-11")
        self.assertEqual(parsed["rows"][0]["releaseYear"], 2020)

    def test_docx_hierarchy_builder_preserves_depth_and_multiple_parents(self):
        parsed = _build_rym_genre_hierarchy([
            {"name": "Root A", "url": "https://rateyourmusic.com/genre/root-a/", "depth": 0},
            {"name": "Shared", "url": "https://rateyourmusic.com/genre/shared/", "depth": 1},
            {"name": "Leaf", "url": "https://rateyourmusic.com/genre/leaf/", "depth": 2},
            {"name": "Root B", "url": "https://rateyourmusic.com/genre/root-b/", "depth": 0},
            {"name": "Shared", "url": "https://rateyourmusic.com/genre/shared/", "depth": 1},
        ])
        shared = next(row for row in parsed["rows"] if row["name"] == "Shared")
        self.assertEqual(len(shared["parentUrls"]), 2)
        self.assertEqual(len(parsed["relations"]), 3)

    def test_supplied_docx_contains_a_deep_genre_dag(self):
        source = Path.home() / "OneDrive" / "Desktop" / "New Microsoft Word Document.docx"
        if not source.exists():
            self.skipTest("Supplied genre DOCX is not available")
        parsed = parse_rym_genre_docx(source)
        self.assertGreaterEqual(len(parsed["rows"]), 1700)
        self.assertGreater(len(parsed["relations"]), len(parsed["rows"]))
        self.assertEqual(parsed["anomalyCount"], 0)
        black_ambient = next(row for row in parsed["rows"] if row["name"] == "Black Ambient")
        self.assertIn("https://rateyourmusic.com/genre/dark-ambient/", black_ambient["parentUrls"])

    def test_genre_index_is_a_dag_with_descriptions(self):
        parsed = parse_rym_html(GENRE_HTML)
        self.assertEqual(parsed["pageType"], "RYM_GENRE_INDEX")
        names = {row["name"]: row for row in parsed["rows"]}
        self.assertIn("Ambient", names)
        self.assertIn("Ambient Americana", names)
        self.assertEqual(names["Ambient Americana"]["depth"], 1)
        self.assertIn("Pastoral", names["Ambient Americana"]["description"])
        self.assertEqual(len(parsed["relations"]), 2)

    def test_chart_uses_dom_order_when_rank_is_blank(self):
        parsed = parse_rym_html(chart_html([
            {"id": 1, "artist": "First Artist", "title": "First Album", "year": 2020},
            {"id": 2, "artist": "Old Saw", "title": "Country Tropics", "year": 2021},
        ]))
        self.assertEqual(parsed["pageType"], "RYM_CHART")
        self.assertEqual([row["position"] for row in parsed["rows"]], [1, 2])
        country = parsed["rows"][1]
        self.assertEqual(country["artistCredit"], "Old Saw")
        self.assertEqual(country["releaseYear"], 2021)
        self.assertEqual(country["primaryGenres"][0]["name"], "Ambient Americana")
        self.assertEqual(country["secondaryGenres"][0]["name"], "Drone")
        self.assertEqual(country["rymRating"], 3.8)
        self.assertTrue(country["coverRemote"].startswith("https://"))

    def test_chart_full_release_date_uses_year_not_day(self):
        html = chart_html([
            {"id": 3, "artist": "A Primary Industry", "title": "Ultramarine", "year": 1986},
        ]).replace("<span>1986</span>", "<span>11 March 1986</span>")
        row = parse_rym_html(html)["rows"][0]
        self.assertEqual(row["releaseYear"], 1986)
        self.assertEqual(row["releaseDate"], "1986-03-11")

    def test_release_page_enrichment_fields(self):
        row = parse_rym_html(release_html())["rows"][0]
        self.assertEqual(row["artistCredit"], "Old Saw")
        self.assertEqual(row["title"], "Country Tropics")
        self.assertEqual(row["releaseType"], "Album")
        self.assertEqual(row["releaseDate"], "2021-11-19")
        self.assertEqual([genre["name"] for genre in row["secondaryGenres"]], ["American Primitivism", "Free Folk", "Drone"])
        self.assertEqual(row["rymRating"], 3.78)
        self.assertEqual(row["tracks"][0]["durationSeconds"], 125)
        self.assertEqual(row["credits"][0]["roles"], ["guitar"])

    def test_supplied_full_fixtures(self):
        desktop = Path.home() / "OneDrive" / "Desktop"
        chart = desktop / "Best Ambient Americana albums of all time - Rate Your Music.html"
        release = desktop / "Country Tropics by Old Saw (Album, Ambient Americana)_ Reviews, Ratings, Credits, Song list - Rate Your Music.html"
        genres = desktop / "Music Genres - Rate Your Music.html"
        if not all(path.exists() for path in (chart, release, genres)):
            self.skipTest("Supplied full RYM fixtures are not available")
        chart_data = parse_rym_html(chart.read_text(encoding="utf-8"))
        self.assertEqual(len(chart_data["rows"]), 100)
        country = next(row for row in chart_data["rows"] if row["title"] == "Country Tropics")
        self.assertEqual(country["artistCredit"], "Old Saw")
        release_data = parse_rym_html(release.read_text(encoding="utf-8"))["rows"][0]
        self.assertEqual(len(release_data["tracks"]), 4)
        self.assertEqual(release_data["releaseDate"], "2021-11-19")
        genre_data = parse_rym_html(genres.read_text(encoding="utf-8"))
        ambient = next((row for row in genre_data["rows"] if row["name"] == "Ambient Americana"), None)
        if ambient is None:
            self.skipTest("Saved genre fixture contains only collapsed root categories")
        self.assertTrue(ambient["description"])
        self.assertTrue(ambient["parentUrls"])

if __name__ == "__main__":
    unittest.main()

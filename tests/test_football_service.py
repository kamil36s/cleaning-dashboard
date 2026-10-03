import json
import sqlite3
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from football_service import FootballRequestControl, build_snapshot, possible_duplicate_matches, record_request, record_sync
from football_store import FootballStore


class FootballServiceTests(unittest.TestCase):
    def test_snapshot_reuses_cache_and_maps_known_club_without_fetching(self):
        scores = {
            "updatedAt": "2026-09-29T12:00:00+00:00",
            "matches": [{"id": "espn:1", "provider": "espn", "leagueKey": "premier-league",
                         "playedAt": "2026-09-29T10:00:00+00:00", "home": {"name": "Liverpool FC", "crest": "https://example.test/logo.png"},
                         "away": {"name": "Arsenal"}, "score": {"home": 2, "away": 1}}],
            "nextMatches": [], "standings": {},
        }
        settings = {"sports": {"enabledTeamKeys": ["liverpool"], "enabledLeagueKeys": ["premier-league"]}}
        catalog = [{"key": "liverpool", "name": "Liverpool", "type": "team", "sport": "Soccer",
                    "espn_team_names": ["Liverpool FC"], "thesportsdb_team_id": 123},
                   {"key": "premier-league", "name": "Premier League", "type": "competition", "sport": "Soccer"}]
        view = build_snapshot(scores, settings, catalog, {}, {}, now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc).timestamp())
        self.assertEqual(view["matches"][0]["clubKeys"][0], "liverpool")
        self.assertTrue(next(row for row in view["clubs"] if row["key"] == "liverpool")["followed"])
        self.assertEqual(view["stored"]["matches"], 1)
        self.assertEqual(view["cache"][0]["status"], "stale")
        self.assertEqual(view["news"], [])

    def test_manual_crest_wins_and_unknown_team_remains_distinct(self):
        view = build_snapshot(
            {"updatedAt": "2026-09-29T12:00:00+00:00", "matches": [
                {"id": "one", "provider": "espn", "home": {"name": "Liverpool FC", "crest": "https://provider/logo"},
                 "away": {"name": "Unknown United"}},
                {"id": "two", "provider": "thesportsdb", "home": {"name": "Liverpool"},
                 "away": {"name": "Arsenal"}},
            ]},
            {"sports": {}},
            [{"key": "liverpool", "name": "Liverpool", "type": "team", "sport": "Soccer"}],
            {}, {}, preferred_crests={"liverpool": "https://manual/logo"},
        )
        self.assertEqual(view["matches"][0]["clubKeys"][0], "liverpool")
        self.assertEqual(view["matches"][1]["clubKeys"][0], "liverpool")
        self.assertEqual(view["matches"][0]["home"]["crest"], "https://manual/logo")
        self.assertEqual(view["matches"][0]["home"]["crestSource"], "manual override")
        self.assertIn("name-unknownunited", {item["key"] for item in view["clubs"]})

    def test_request_history_is_bounded_and_drops_query_and_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            for index in range(205):
                record_request(path, f"https://v3.football.api-sports.io/fixtures?secret={index}", 200, 12, 3)
            record_request(path, "https://unrelated.example/secret", 200, 12)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["requests"]), 200)
            self.assertEqual(data["requests"][0]["endpoint"], "/fixtures")
            self.assertNotIn("secret", path.read_text(encoding="utf-8"))
            record_sync(path, {"matches": [{}], "nextMatches": [], "sourceErrors": []}, 3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["runs"][0]["duplicates"], 2)

    def test_request_control_deduplicates_and_honors_429_cooldown(self):
        current = [100.0]
        control = FootballRequestControl(clock=lambda: current[0])
        calls = []
        url = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"

        def fetch():
            calls.append(1)
            return {"events": [1]}, 200

        self.assertEqual(control.get(url, fetch)[2], False)
        self.assertEqual(control.get(url, fetch)[2], True)
        self.assertEqual(len(calls), 1)
        current[0] += 31
        self.assertEqual(control.get(url, fetch)[2], False)

        def rate_limited():
            raise urllib.error.HTTPError(url, 429, "limited", {"Retry-After": "120"}, None)

        with self.assertRaises(urllib.error.HTTPError):
            control.get("https://site.web.api.espn.com/new", rate_limited)
        with self.assertRaisesRegex(RuntimeError, "cooldown"):
            control.get("https://site.web.api.espn.com/other", fetch)
        self.assertGreaterEqual(control.cooldowns()["ESPN"], 119)

    def test_request_control_has_provider_minute_budget(self):
        current = [10.0]
        control = FootballRequestControl(clock=lambda: current[0])
        control.PER_MINUTE = {"ESPN": 2}
        calls = []

        def fetch():
            calls.append(1)
            return {}, 200

        for number in (1, 2):
            control.get(f"https://site.web.api.espn.com/match/{number}", fetch)
        with self.assertRaisesRegex(RuntimeError, "rolling-minute"):
            control.get("https://site.web.api.espn.com/match/3", fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(control.usage()["ESPN"]["minute"], 2)
        current[0] += 61
        control.get("https://site.web.api.espn.com/match/3", fetch)
        self.assertEqual(len(calls), 3)

    def test_request_control_cools_down_after_repeated_timeouts(self):
        control = FootballRequestControl(clock=lambda: 100.0)
        def timeout():
            raise TimeoutError("provider timed out")
        for index in range(3):
            with self.assertRaises(TimeoutError):
                control.get(f"https://www.thesportsdb.com/api/v1/json/123/events{index}.php", timeout)
        self.assertEqual(control.usage()["TheSportsDB"]["consecutiveFailures"], 3)
        with self.assertRaisesRegex(RuntimeError, "cooldown"):
            control.get("https://www.thesportsdb.com/api/v1/json/123/other.php", timeout)

    def test_desktop_endpoint_reads_only_local_data(self):
        import server
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "scores.json").write_text(json.dumps({"updatedAt": "2026-09-29T12:00:00", "matches": []}), encoding="utf-8")
            (base / "settings.json").write_text(json.dumps({"sports": {"enabledTeamKeys": [], "enabledLeagueKeys": []}}), encoding="utf-8")
            with mock.patch.object(server, "KITCHEN_SCORES_JSON", base / "scores.json"), \
                    mock.patch.object(server, "KITCHEN_SETTINGS_JSON", base / "settings.json"), \
                    mock.patch.object(server, "KITCHEN_TEAM_CRESTS_JSON", base / "missing-crests.json"), \
                    mock.patch.object(server, "FOOTBALL_DIAGNOSTICS_JSON", base / "missing-history.json"), \
                    mock.patch.object(server, "_FOOTBALL_STORE", FootballStore(base / "football.sqlite")), \
                    mock.patch.object(server, "http_get_json", side_effect=AssertionError("external fetch")):
                view = server.read_football_dashboard()
                with mock.patch.object(server, "_FOOTBALL_STORE", mock.Mock(
                        ingest=mock.Mock(side_effect=sqlite3.OperationalError("locked")),
                        matches=mock.Mock(side_effect=sqlite3.OperationalError("locked")))), \
                        mock.patch("builtins.print"):
                    degraded = server.read_football_dashboard()
            self.assertTrue(view["ok"])
            self.assertIn("storedData", view)
            self.assertTrue(degraded["ok"])
            self.assertIn("SQLite is unavailable", degraded["storageNote"])

    def test_presentation_settings_validate_bounds(self):
        import server
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(server, "FOOTBALL_SETTINGS_JSON", Path(directory) / "settings.json"):
                self.assertEqual(server.read_football_settings()["kitchenMaxSlides"], 6)
                saved = server.write_football_settings({"kitchenMaxSlides": 4, "kitchenShowStandings": False})
                self.assertEqual(saved["kitchenMaxSlides"], 4)
                self.assertFalse(saved["kitchenShowStandings"])
                with self.assertRaises(ValueError):
                    server.write_football_settings({"kitchenMaxSlides": 0})

    def test_duplicate_candidates_are_visible_without_merging(self):
        rows = [{"provider": "espn", "id": "1", "competitionKey": "league", "playedAt": "2026-09-29T12:00",
                 "clubKeys": ["a", "b"]},
                {"provider": "thesportsdb", "id": "2", "competitionKey": "league", "playedAt": "2026-09-29T13:00",
                 "clubKeys": ["a", "b"]}]
        candidates = possible_duplicate_matches(rows)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["sources"]), 2)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()

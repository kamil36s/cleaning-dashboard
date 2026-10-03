import unittest
import urllib.error
from datetime import datetime, timedelta
from unittest import mock

import server


def standing_rows(count, prefix="Club"):
    return [
        {
            "rank": index,
            "name": f"{prefix} {index}",
            "crest": f"https://example.test/{index}.png",
            "played": "1",
            "wins": "1",
            "draws": "0",
            "losses": "0",
            "goalsFor": "1",
            "goalsAgainst": "0",
            "gd": "+1",
            "points": "3",
            "record": "1-0-0",
            "zoneLabel": "",
        }
        for index in range(1, count + 1)
    ]


class KitchenFootballTests(unittest.TestCase):
    def test_european_table_is_paginated_even_without_recent_results(self):
        settings = {
            "sports": {
                "enabledLeagueKeys": ["champions-league"],
                "standingsLeagueKeys": ["champions-league"],
                "enabledTeamKeys": [],
            }
        }
        standing = {
            "leagueKey": "champions-league",
            "leagueName": "Champions League",
            "complete": True,
            "rows": standing_rows(36),
        }
        display = server.standings_for_display({"champions-league": standing}, {}, [])

        slides = server.build_kitchen_slides([], display, [], settings=settings)

        self.assertEqual([len(slide["rows"]) for slide in slides], [10, 10, 10, 6])
        self.assertEqual(slides[0]["title"], "Tabela - miejsca 1-10")
        self.assertEqual(slides[-1]["title"], "Tabela - miejsca 31-36")

    def test_cache_fallback_preserves_tables(self):
        now = datetime(2026, 9, 20, 12, 0, 0)
        settings = {
            "sports": {
                "windowHours": 24,
                "enabledLeagueKeys": ["champions-league"],
                "standingsLeagueKeys": ["champions-league"],
                "enabledTeamKeys": [],
            }
        }
        cached = {
            "matches": [],
            "nextMatches": [{
                "teamKey": "concacaf-nations-league",
                "kickoffAt": "2026-09-21T19:00:00",
                "home": {"name": "Montserrat"},
                "away": {"name": "Bahamas"},
            }],
            "liveMatches": [],
            "standings": {
                "champions-league": {
                    "leagueKey": "champions-league",
                    "leagueName": "Champions League",
                    "complete": True,
                    "rows": standing_rows(36),
                }
            },
        }
        with mock.patch.object(server, "hydrate_kitchen_team_crests", side_effect=lambda rows, **_: rows), \
                mock.patch.object(server, "hydrate_kitchen_standing_crests", side_effect=lambda rows, **_: rows):
            payload = server.cached_kitchen_scores_fallback(
                cached,
                now - timedelta(hours=24),
                settings,
                24,
                now=now,
                error="provider unavailable",
            )

        self.assertIsNotNone(payload)
        self.assertIn("champions-league", payload["displayStandings"])
        self.assertEqual(payload["nextMatches"], [])
        self.assertEqual(len(payload["slides"]), 4)

    def test_reconstructs_full_table_from_season_results(self):
        events = [
            {
                "strHomeTeam": "Alpha",
                "strAwayTeam": "Beta",
                "strHomeTeamBadge": "alpha.png",
                "strAwayTeamBadge": "beta.png",
                "intHomeScore": "2",
                "intAwayScore": "0",
                "strStatus": "Match Finished",
                "strTimestamp": "2026-09-01T18:00:00",
            },
            {
                "strHomeTeam": "Gamma",
                "strAwayTeam": "Alpha",
                "strHomeTeamBadge": "gamma.png",
                "strAwayTeamBadge": "alpha.png",
                "intHomeScore": "1",
                "intAwayScore": "1",
                "strStatus": "FT",
                "strTimestamp": "2026-09-08T18:00:00",
            },
        ]
        league = {
            "key": "test-league",
            "name": "Test League",
            "thesportsdb_id": 123,
            "season": "2026-2027",
        }
        with mock.patch.object(server, "http_get_json", return_value={"events": events}):
            rows = server.fetch_thesportsdb_reconstructed_standings(
                league,
                now=datetime(2026, 9, 20, 12, 0, 0),
            )

        self.assertEqual([row["name"] for row in rows], ["Alpha", "Gamma", "Beta"])
        self.assertEqual(rows[0]["points"], "4")
        self.assertEqual(rows[0]["crest"], "alpha.png")

    def test_nations_league_and_hutnik_have_real_sources(self):
        nations = server.kitchen_league_by_key("uefa-nations-league")
        hutnik = server.kitchen_league_by_key("hutnik-krakow")

        self.assertEqual(nations["thesportsdb_id"], 4490)
        self.assertEqual(nations["nextTournament"]["startDate"], "2026-09-24")
        self.assertEqual(hutnik["thesportsdb_team_id"], 153534)
        self.assertIn("hutnik-krakow", {team["key"] for team in server.KITCHEN_NEXT_TEAMS})

    def test_concacaf_nations_league_and_afcon_qualifiers_use_espn_for_scores(self):
        concacaf = server.kitchen_league_by_key("concacaf-nations-league")
        afcon_qualifiers = server.kitchen_league_by_key("afcon-qualifiers")

        self.assertEqual(concacaf["name"], "CONCACAF Nations League")
        self.assertEqual(concacaf["espn_league"], "concacaf.nations.league")
        self.assertNotIn("espnNextMatches", concacaf)
        self.assertEqual(afcon_qualifiers["espn_league"], "caf.nations_qual")
        self.assertNotIn("espnNextMatches", afcon_qualifiers)

    def test_afcon_and_concacaf_upcoming_matches_are_hidden(self):
        settings = {
            "sports": {
                "enabledLeagueKeys": ["afcon-qualifiers", "concacaf-nations-league"],
                "standingsLeagueKeys": [],
                "enabledTeamKeys": [],
            }
        }
        now = datetime(2026, 9, 23, 12, 0, 0)
        fixtures = [
            {
                "id": "next:afcon-qualifiers:1",
                "teamKey": "afcon-qualifiers",
                "kickoffAt": "2026-09-23T19:00:00",
                "home": {"name": "Montserrat"},
                "away": {"name": "Turks and Caicos Islands"},
            },
            {
                "id": "next:concacaf-nations-league:2",
                "teamKey": "concacaf-nations-league",
                "kickoffAt": "2026-09-23T20:00:00",
                "home": {"name": "St. Martin"},
                "away": {"name": "Bahamas"},
            },
        ]
        with mock.patch.object(server, "fetch_world_cup_next_matches", return_value=[]), \
                mock.patch.object(server, "fetch_conifa_euro_2026_next_matches", return_value=[]), \
                mock.patch.object(server, "fetch_espn_next_matches_for_source") as fetch_espn, \
                mock.patch.object(server, "fetch_thesportsdb_round_next_matches_for_competition", return_value=fixtures), \
                mock.patch.object(server, "fetch_thesportsdb_next_matches_for_competition", return_value=[]):
            matches = server.fetch_next_kitchen_matches(now=now, settings=settings)

        self.assertEqual(matches, [])
        fetch_espn.assert_not_called()
        self.assertEqual(server.filter_kitchen_next_matches([
            *fixtures,
            {"teamKey": "afcon", "kickoffAt": "2026-09-24T19:00:00"},
            {"teamKey": "concacaf-gold-cup", "kickoffAt": "2026-09-24T20:00:00"},
            {"teamKey": "uefa-nations-league", "kickoffAt": "2026-09-24T21:00:00"},
        ]), [{"teamKey": "uefa-nations-league", "kickoffAt": "2026-09-24T21:00:00"}])

    def test_results_only_competitions_keep_finished_and_live_scores(self):
        event = {
            "id": "1",
            "date": "2026-09-23T19:00:00Z",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"name": "Ghana"}, "score": "2"},
                    {"homeAway": "away", "team": {"name": "Kenya"}, "score": "1"},
                ],
                "status": {"type": {"completed": True, "state": "post"}},
            }],
        }
        for key in ("afcon-qualifiers", "concacaf-nations-league"):
            source = server.kitchen_league_by_key(key)
            self.assertEqual(server.normalize_espn_event(event, source)["score"], {"home": 2, "away": 1})
        event["competitions"][0]["status"]["type"] = {"completed": False, "state": "in"}
        for key in ("afcon-qualifiers", "concacaf-nations-league"):
            source = server.kitchen_league_by_key(key)
            self.assertEqual(server.normalize_espn_live_event(event, source)["score"], {"home": 2, "away": 1})

    def test_official_poland_nations_league_fixtures_survive_provider_outage(self):
        settings = {
            "sports": {
                "enabledLeagueKeys": ["uefa-nations-league"],
                "standingsLeagueKeys": [],
                "enabledTeamKeys": [],
            }
        }
        rate_limit = urllib.error.HTTPError("url", 429, "limited", {}, None)
        with mock.patch.object(server, "fetch_world_cup_next_matches", return_value=[]), \
                mock.patch.object(server, "fetch_conifa_euro_2026_next_matches", return_value=[]), \
                mock.patch.object(server, "fetch_thesportsdb_round_next_matches_for_competition", return_value=[]), \
                mock.patch.object(server, "fetch_thesportsdb_next_matches_for_competition", side_effect=rate_limit):
            matches = server.fetch_next_kitchen_matches(
                now=datetime(2026, 9, 20, 12, 0, 0),
                settings=settings,
            )

        self.assertEqual([match["kickoffAt"][:10] for match in matches], [
            "2026-09-25",
            "2026-09-28",
            "2026-10-02",
        ])
        self.assertTrue(all(match["provider"] == "uefa-schedule" for match in matches))

    def test_polish_and_english_team_names_dedupe_the_same_next_match(self):
        english = {
            "teamKey": "poland",
            "kickoffAt": "2026-09-25T20:45:00",
            "home": {"name": "Poland"},
            "away": {"name": "Bosnia-Herzegovina"},
        }
        polish = {
            "teamKey": "uefa-nations-league",
            "kickoffAt": "2026-09-25T20:45:00+02:00",
            "home": {"name": "Polska"},
            "away": {"name": "Bośnia i Hercegowina"},
        }

        self.assertEqual(server.next_match_key(english), server.next_match_key(polish))


if __name__ == "__main__":
    unittest.main()

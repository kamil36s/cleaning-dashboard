import tempfile
import unittest
from pathlib import Path

from football_store import FootballStore


class FootballStoreTests(unittest.TestCase):
    def test_retains_old_results_and_deduplicates_repeated_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FootballStore(Path(directory) / "football.sqlite")
            match = {"id": "espn:100", "provider": "espn", "category": "result",
                     "competitionKey": "premier-league", "clubKeys": ["liverpool", "arsenal"],
                     "playedAt": "2026-09-28T18:00:00", "home": {"name": "Liverpool"}, "away": {"name": "Arsenal"},
                     "score": {"home": 2, "away": 1}}
            snapshot = {"clubs": [{"key": "liverpool", "name": "Liverpool", "providerIds": {"thesportsdb_team_id": 133602}}],
                        "competitions": [{"key": "premier-league", "name": "Premier League", "providerIds": {"espn_league": "eng.1"}}],
                        "matches": [match]}
            self.assertTrue(store.ingest(snapshot))
            self.assertFalse(store.ingest(snapshot))
            self.assertEqual(store.counts()["matches"], 1)
            self.assertEqual(store.counts()["provider_mappings"], 3)
            self.assertTrue(store.ingest({**snapshot, "matches": []}))
            self.assertEqual(store.matches()[0]["id"], "espn:100")
            self.assertEqual(store.counts()["matches"], 1)

    def test_mapping_conflict_preserves_original_entity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FootballStore(Path(directory) / "football.sqlite")
            first = {"clubs": [{"key": "club-a", "name": "A", "providerIds": {"thesportsdb_team_id": 77}}], "matches": []}
            second = {"clubs": [{"key": "club-b", "name": "B", "providerIds": {"thesportsdb_team_id": 77}}], "matches": []}
            store.ingest(first)
            store.ingest(second)
            mapping = next(row for row in store.mappings() if row["entity_type"] == "club")
            self.assertEqual(mapping["entity_key"], "club-a")
            self.assertEqual(store.mapping_conflicts()[0]["proposed_key"], "club-b")


if __name__ == "__main__":
    unittest.main()

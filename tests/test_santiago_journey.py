import tempfile
import json
import threading
import unittest
import urllib.request
from pathlib import Path

from live_workout_store import LiveWorkoutStore
from santiago_journey import SantiagoJourney
from training_runtime import create_server


ROOT = Path(__file__).resolve().parents[1]


class SantiagoJourneyTests(unittest.TestCase):
    def test_dataset_and_route_endpoints(self):
        journey = SantiagoJourney(ROOT / "data" / "journeys" / "santiago")
        self.assertEqual(len(journey.checkpoints), 365)
        self.assertEqual({item["originalIndex"] for item in journey.checkpoints}, set(range(1, 366)))
        self.assertEqual(len({item["id"] for item in journey.checkpoints}), 365)
        self.assertEqual(sum(bool(item.get("variantCheckpoint")) for item in journey.checkpoints), 4)
        self.assertEqual(journey.previous_checkpoint(0)["name"], "Kraków")
        endpoint = journey.position_at(journey.total_distance_km + 100)
        self.assertAlmostEqual(endpoint["distanceKm"], journey.total_distance_km)
        self.assertEqual(journey.previous_checkpoint(journey.total_distance_km)["name"], "Santiago de Compostela")

    def test_variant_checkpoint_is_crossed_but_not_presented_as_next_main_destination(self):
        journey = SantiagoJourney(ROOT / "data" / "journeys" / "santiago")
        valcarlos = next(item for item in journey.checkpoints if item["name"] == "Valcarlos")
        distance = float(valcarlos["routeDistanceKm"])
        crossed = journey.crossed_checkpoints(distance - 0.01, distance + 0.01)
        self.assertIn("Valcarlos", [item["name"] for item in crossed])
        self.assertNotEqual(journey.next_checkpoint(distance)["name"], "Valcarlos")

    def test_session_commit_is_idempotent_and_refresh_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LiveWorkoutStore(Path(directory) / "live-workout.sqlite")
            store.initialize()
            before = store.journey_progress()["committed_distance_km"]
            first = store.commit_journey_session("session-A", 12.46, committed_at=1_790_000_000_000)
            second = store.commit_journey_session("session-A", 12.46, committed_at=1_790_000_001_000)
            refreshed = store.journey_progress()
            self.assertTrue(first["committed"])
            self.assertFalse(second["committed"])
            self.assertAlmostEqual(refreshed["committed_distance_km"], before + 12.46)
            self.assertEqual(refreshed["committed_session_count"], 1)

    def test_active_session_distance_is_not_committed_until_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LiveWorkoutStore(Path(directory) / "live-workout.sqlite")
            store.initialize()
            session = store.start_dashboard_session({"workout_type": "indoor_cycling"}, timestamp=1_790_000_000_000)
            store.checkpoint_dashboard_session(
                timestamp=1_790_000_010_000,
                session_id=session["id"],
                summary={"distance_km": 5},
            )
            self.assertEqual(store.journey_progress()["committed_distance_km"], 0)
            store.control_dashboard_session(
                "finish",
                timestamp=1_790_000_020_000,
                session_id=session["id"],
                summary={"distance_km": 5},
            )
            self.assertEqual(store.journey_progress()["committed_distance_km"], 5)

    def test_virtual_walk_distance_is_committed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LiveWorkoutStore(Path(directory) / "live-workout.sqlite")
            store.initialize()
            session = store.start_dashboard_session({"workout_type": "virtual_walk"}, timestamp=1_790_000_000_000)
            store.checkpoint_dashboard_session(
                timestamp=1_790_000_010_000,
                session_id=session["id"],
                summary={"distance_km": 0.75},
            )
            self.assertEqual(store.journey_progress()["committed_distance_km"], 0)
            store.control_dashboard_session(
                "finish", timestamp=1_790_000_020_000,
                session_id=session["id"], summary={"distance_km": 0.75},
            )
            self.assertEqual(store.journey_progress()["committed_distance_km"], 0.75)
            self.assertFalse(store.commit_journey_session(session["id"], 0.75)["committed"])
            self.assertEqual(store.journey_progress()["committed_distance_km"], 0.75)

    def test_runtime_journey_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(
                "127.0.0.1",
                0,
                database_path=Path(directory) / "live-workout.sqlite",
                plan_path=ROOT / "data" / "live-workout-plan.json",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with urllib.request.urlopen(
                    f"http://{host}:{port}/api/live-workout/journey/santiago?checkpoints=1",
                    timeout=5,
                ) as response:
                    payload = json.load(response)
                self.assertEqual(payload["journeyId"], "krakow-santiago")
                self.assertEqual(payload["checkpointCount"], 365)
                self.assertEqual(len(payload["checkpoints"]), 365)
                self.assertEqual(payload["previousCheckpoint"]["name"], "Kraków")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

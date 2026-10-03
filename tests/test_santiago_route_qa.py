import json
import unittest
from pathlib import Path

from scripts.audit_santiago_route import (
    HIGHLY_SUSPICIOUS_RATIO,
    SUSPICIOUS_RATIO,
    analyze_leg,
    build_report,
    haversine_km,
)
from scripts.enrich_santiago_checkpoints import simplify_route
from scripts.review_santiago_checkpoint_order import build_review


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "journeys" / "santiago"


class SantiagoRouteQaMetricTests(unittest.TestCase):
    def test_haversine_distance(self):
        self.assertAlmostEqual(haversine_km([0, 0], [1, 0]), 111.195, places=2)

    def test_detour_thresholds_and_metrics(self):
        route = [[0, 0], [0, 1], [1, 1], [1, 0]]
        route_distance = sum(haversine_km(left, right) for left, right in zip(route, route[1:]))
        left = {
            "index": 1,
            "name": "Start",
            "country": "Test",
            "lat": 0,
            "lon": 0,
            "routeDistanceKm": 0,
            "routeVertexIndex": 0,
        }
        right = {
            "index": 2,
            "name": "Finish",
            "country": "Test",
            "lat": 0,
            "lon": 1,
            "routeDistanceKm": route_distance,
            "routeVertexIndex": 3,
        }
        leg = analyze_leg(
            left,
            right,
            route,
            [{"start": 1, "end": 2, "file": "001-002.geojson", "source": "BRouter trekking"}],
        )
        self.assertGreater(leg["detourRatio"], HIGHLY_SUSPICIOUS_RATIO)
        self.assertIn("detour_ratio", leg["flags"])
        self.assertIn("high_detour_ratio", leg["flags"])
        self.assertGreater(leg["metrics"]["maxCorridorDeviationKm"], 100)
        self.assertFalse(leg["fallback"])

    def test_ratio_boundaries_are_strict(self):
        self.assertEqual(SUSPICIOUS_RATIO, 1.8)
        self.assertEqual(HIGHLY_SUSPICIOUS_RATIO, 2.5)


class SantiagoRouteQaDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(DATA_DIR)
        cls.checkpoints = json.loads((DATA_DIR / "checkpoints.json").read_text(encoding="utf-8"))["checkpoints"]
        cls.route = json.loads((DATA_DIR / "route.geojson").read_text(encoding="utf-8"))["geometry"]["coordinates"]

    def test_invariants_and_monotonic_distances(self):
        self.assertEqual(self.report["summary"]["checkpointCount"], 365)
        self.assertEqual(self.report["summary"]["mainRouteCheckpointCount"], 361)
        self.assertEqual(self.report["summary"]["variantCheckpointCount"], 4)
        self.assertEqual(self.report["summary"]["legCount"], 360)
        self.assertEqual(self.checkpoints[0]["name"], "Kraków")
        self.assertEqual(self.checkpoints[182]["name"], "St Jean Pied de Port")
        self.assertEqual(self.checkpoints[-1]["name"], "Santiago de Compostela")
        original_indexes = {item["originalIndex"] for item in self.checkpoints}
        stable_ids = {item["id"] for item in self.checkpoints}
        main = [item for item in self.checkpoints if not item.get("variantCheckpoint")]
        distances = [item["routeDistanceKm"] for item in main]
        self.assertEqual(original_indexes, set(range(1, 366)))
        self.assertEqual(len(stable_ids), 365)
        self.assertTrue(all(left < right for left, right in zip(distances, distances[1:])))
        self.assertAlmostEqual(self.checkpoints[-1]["routeDistanceKm"], self.report["summary"]["auditedDistanceKm"], places=5)

    def test_order_review_preserves_identities_and_documents_every_baseline_retrace(self):
        review = build_review(DATA_DIR)
        self.assertEqual(len(review["runtimeOrderOriginalIndexes"]), 365)
        self.assertEqual(set(review["runtimeOrderOriginalIndexes"]), set(range(1, 366)))
        self.assertEqual(len(review["variantCheckpoints"]), 4)
        self.assertEqual(
            len(review["manualReview"]["allBaselineRetraceFlags"]),
            review["baseline"]["automaticOrderingFlags"],
        )

    def test_variant_checkpoints_share_an_explicit_main_route_association(self):
        main_by_id = {item["id"]: item for item in self.checkpoints if not item.get("variantCheckpoint")}
        variants = [item for item in self.checkpoints if item.get("variantCheckpoint")]
        self.assertEqual(len(variants), 4)
        for variant in variants:
            associated = main_by_id[variant["associatedCheckpointId"]]
            self.assertEqual(variant["routeDistanceKm"], associated["routeDistanceKm"])
            self.assertGreater(variant["variantGeographicOffsetKm"], 0)

    def test_leg_distances_reconstruct_total(self):
        total = sum(item["routeDistanceKm"] for item in self.report["legs"])
        self.assertAlmostEqual(total, self.report["summary"]["auditedDistanceKm"], places=4)
        self.assertEqual(self.report["summary"]["fallbackLegCount"], 0)
        self.assertEqual(self.report["summary"]["motorwayFlaggedLegCount"], 0)
        self.assertEqual(self.report["summary"]["ferryFlaggedLegCount"], 0)

    def test_correction_accounts_for_total_difference(self):
        corrections = self.report["correctedLegs"]
        self.assertEqual(len(corrections), 1)
        correction_delta = sum(item["totalDifferenceKm"] for item in corrections)
        self.assertAlmostEqual(
            correction_delta,
            self.report["summary"]["orderingBaselineDistanceKm"]
            - self.report["summary"]["originalReportedDistanceKm"],
            places=5,
        )
        self.assertEqual(corrections[0]["checkpointIndex"], 84)

    def test_cached_parts_reconstruct_runtime_route(self):
        raw_route = []
        for path in sorted((DATA_DIR / "route-parts").glob("*.geojson")):
            points = json.loads(path.read_text(encoding="utf-8"))["geometry"]["coordinates"]
            if raw_route and points[0] == raw_route[-1]:
                raw_route.extend(points[1:])
            else:
                raw_route.extend(points)
        rebuilt = simplify_route(raw_route)
        self.assertEqual(rebuilt, self.route)


if __name__ == "__main__":
    unittest.main()

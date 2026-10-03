"""Algorithmic budgets for measured Language hot paths."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from language_learning.cloze import ClozeService
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from tests.test_language_cloze import build_reference
from tests.test_language_gamification import FakeClozeService
from scripts.benchmark_language_operations import fixture


class FastTrackQueryBudgetTests(unittest.TestCase):
    def test_fifty_items_read_suppressions_once(self):
        with tempfile.TemporaryDirectory() as temp:
            reference, _, _ = build_reference(temp, 60)
            store = LanguageStore(Path(temp) / "language.sqlite")
            service = LanguageService(store)
            service.initialize()
            profile = service.ensure_bokmal_profile()["profile"]["id"]
            cloze = ClozeService(service, reference.database_path)
            service.attach_cloze_service(cloze)
            with patch.object(store, "cloze_suppressions", wraps=store.cloze_suppressions) as reads:
                result = service.start_cloze_session(profile, {
                    "mode": "FAST_TRACK", "trackKey": "FAST_TRACK_1",
                    "itemCount": 50, "seed": "phase12-budget",
                })["data"]
            self.assertEqual(result["session"]["requestedItemCount"], 50)
            self.assertEqual(reads.call_count, 1)

    def test_reader_page_coverage_is_batched_without_changing_values(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LanguageStore(Path(temp) / "language.sqlite")
            service = LanguageService(store)
            service.initialize()
            profile = service.ensure_bokmal_profile()["profile"]["id"]
            fixture(store, profile, lemmas=100, texts=60, events=100)
            with patch.object(store, "coverage_rows_batch", wraps=store.coverage_rows_batch) as batch, \
                 patch.object(store, "coverage_rows", wraps=store.coverage_rows) as individual:
                items = service.list_texts(profile, limit=50)["data"]["items"]
            self.assertEqual(len(items), 50)
            self.assertEqual(batch.call_count, 1)
            self.assertEqual(individual.call_count, 0)
            for item in items[:3]:
                expected = service.coverage_service.calculate(store.coverage_rows(item["id"]))
                self.assertEqual(item["coverage"], expected)

    def test_collection_denominators_share_one_reference_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LanguageStore(Path(temp) / "language.sqlite")
            service = LanguageService(store)
            service.initialize()
            profile = service.ensure_bokmal_profile()["profile"]["id"]
            cloze = FakeClozeService()
            service.gamification_service.attach_cloze_service(cloze)
            with patch.object(cloze.reference, "targets", wraps=cloze.reference.targets) as ranked, \
                 patch.object(cloze.reference, "playable_target_ids",
                              wraps=cloze.reference.playable_target_ids) as playable:
                items = service.collections(profile)["data"]["items"]
            self.assertEqual(ranked.call_count, 1)
            self.assertEqual(playable.call_count, 1)
            self.assertEqual(items[0]["totalEligible"], 1)
            self.assertEqual(items[0]["unresolved"], 1)


if __name__ == "__main__":
    unittest.main()

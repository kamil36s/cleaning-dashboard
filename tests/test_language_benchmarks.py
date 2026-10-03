import json
import tempfile
import unittest
from pathlib import Path

from language_learning.assessment import load_content, normalize_cloze
from language_learning.errors import LanguageConflictError, LanguageNotFoundError
from language_learning.service import LanguageService
from language_learning.store import LanguageStore


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.profile = self.service.create_profile({
            "languageCode": "nb", "locale": "nb-NO", "displayName": "Test"
        })["data"]["profile"]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def counts(self):
        with self.store.connection() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("vocabulary_lemmas", "lemma_knowledge", "knowledge_events",
                                  "exposure_events", "text_reading_progress", "listening_progress",
                                  "cloze_attempts", "study_sessions", "listening_sessions",
                                  "gamification_awards", "achievement_unlocks", "gamification_quest_snapshots",
                                  "anki_note_links", "goal_definitions", "grammar_occurrences")}

    def finish(self, run, unavailable=False):
        content, _ = load_content()
        keys = {item["id"]: item["answer"] for item in content["forms"][run["formId"]]}
        for item in run["items"]:
            payload = {"itemId": item["id"], "response": keys[item["id"]]}
            if unavailable and item["dimension"] == "LISTENING":
                payload = {"itemId": item["id"], "unavailable": True,
                           "environment": {"browserCapability": "NO_BOKMAL_VOICE"}}
            self.service.benchmark_response(self.profile, run["id"], payload)
        return self.service.complete_benchmark(self.profile, run["id"])["data"]

    def test_content_fingerprint_answers_private_and_resume(self):
        content, fingerprint = load_content()
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(load_content()[1], fingerprint)
        self.assertEqual(content["status"], "INTERNAL_SYNTHETIC")
        positions = {item["options"].index(item["answer"])
                     for form in content["forms"].values() for item in form if "options" in item}
        self.assertEqual(positions, {0, 1, 2, 3})
        run = self.service.start_benchmark(self.profile)["data"]
        self.assertEqual(run["contentFingerprint"], fingerprint)
        self.assertEqual(set(run["comparison"]["itemVersions"]), set(run["selectedItemIds"]))
        self.assertNotIn('"answer"', json.dumps(run))
        self.assertEqual(self.service.start_benchmark(self.profile)["data"]["id"], run["id"])
        self.service.benchmark_response(self.profile, run["id"], {
            "itemId": run["items"][0]["id"], "response": run["items"][0]["options"][0]
        })
        self.assertEqual(len(self.service.benchmark_run(self.profile, run["id"])["data"]["responses"]), 1)
        with self.assertRaises(LanguageConflictError):
            self.service.complete_benchmark(self.profile, run["id"])

    def test_four_scores_baseline_checkpoint_repeat_and_isolation(self):
        before = self.counts()
        baseline = self.finish(self.service.start_benchmark(self.profile)["data"])
        self.assertEqual(baseline["kind"], "BASELINE")
        self.assertEqual({value["percent"] for value in baseline["scores"].values()}, {100.0})
        self.assertNotIn("items", baseline)
        self.assertEqual(self.counts(), before)
        checkpoint = self.finish(self.service.start_benchmark(self.profile)["data"])
        self.assertEqual(checkpoint["formId"], "FORM_B")
        self.assertEqual(checkpoint["comparison"]["state"], "NOT_COMPARABLE")
        self.assertEqual(self.counts(), before)
        repeat = self.finish(self.service.start_benchmark(self.profile)["data"])
        self.assertEqual(repeat["comparison"]["state"], "REPEAT_INFLUENCED")
        self.assertEqual(repeat["comparison"]["repeatInfluence"]["repeatedItemCount"], len(repeat["selectedItemIds"]))
        self.assertEqual(repeat["comparison"]["dimensions"]["READING"]["changePp"], 0.0)

    def test_unavailable_listening_not_zero_and_norway_no_composite(self):
        run = self.service.start_benchmark(self.profile)["data"]
        done = self.finish(run, unavailable=True)
        self.assertEqual(done["scores"]["LISTENING"], {
            "correct": 0, "total": 0, "unavailable": 3, "percent": None, "status": "UNAVAILABLE"
        })
        summary = self.service.norway_preparation(self.profile)["data"]
        self.assertEqual(summary["benchmarks"]["READING"]["percent"], 100.0)
        self.assertIsNone(summary["benchmarks"]["LISTENING"]["percent"])
        self.assertEqual(len(summary["curricula"]), 5)
        canonical = {pack["id"]: pack for pack in self.service.curriculum_service.landing(self.profile)["packs"]}
        for pack in summary["curricula"]:
            source = canonical[pack["packId"]]
            self.assertEqual((pack["completed"], pack["total"]),
                             (source["progress"]["completed"], source["progress"]["eligibleDenominator"]))
        self.assertNotIn("readiness", json.dumps(summary).lower())
        checkpoint = self.service.start_benchmark(self.profile)["data"]
        answers = {item["id"]: item["answer"] for item in load_content()[0]["forms"][checkpoint["formId"]]}
        listening = [item["id"] for item in checkpoint["items"] if item["dimension"] == "LISTENING"]
        for item in checkpoint["items"]:
            payload = {"itemId": item["id"], "response": answers[item["id"]]}
            if item["id"] == listening[0]:
                payload = {"itemId": item["id"], "unavailable": True}
            self.service.benchmark_response(self.profile, checkpoint["id"], payload)
        partial = self.service.complete_benchmark(self.profile, checkpoint["id"])["data"]["scores"]["LISTENING"]
        self.assertEqual((partial["correct"], partial["total"], partial["unavailable"], partial["status"]),
                         (2, 2, 1, "PARTIAL"))

    def test_profile_ownership_and_cloze_normalization(self):
        other = self.service.create_profile({
            "languageCode": "nb", "locale": "nb-SE", "displayName": "Other"
        })["data"]["profile"]["id"]
        run = self.service.start_benchmark(self.profile)["data"]
        with self.assertRaises(LanguageNotFoundError):
            self.service.benchmark_run(other, run["id"])
        with self.assertRaises(LanguageNotFoundError):
            self.service.benchmark_response(other, run["id"], {"itemId": run["items"][0]["id"], "response": "work"})
        self.assertEqual(normalize_cloze("  PÅ  "), "på")
        self.assertNotEqual(normalize_cloze("pa"), "på")

    def test_content_drift_blocks_active_run_and_export_keeps_responses(self):
        run = self.service.start_benchmark(self.profile)["data"]
        item = run["items"][0]
        self.service.benchmark_response(self.profile, run["id"], {
            "itemId": item["id"], "response": item["options"][0]
        })
        exported = self.store.export_data()
        self.assertEqual(exported["exportVersion"], "language-learning-export/v16")
        self.assertEqual(len(exported["data"]["benchmarkRuns"]), 1)
        self.assertEqual(len(exported["data"]["benchmarkResponses"]), 1)
        self.assertNotIn('"answer"', json.dumps(exported))
        self.service.assessment.fingerprint = "0" * 64
        self.assertEqual(self.service.benchmark_runs(self.profile)["data"]["runs"][0]["id"], run["id"])
        with self.assertRaises(LanguageConflictError):
            self.service.benchmark_run(self.profile, run["id"])

    def test_changed_baseline_version_is_not_comparable_even_on_same_form(self):
        baseline = self.finish(self.service.start_benchmark(self.profile)["data"])
        self.finish(self.service.start_benchmark(self.profile)["data"])
        with self.store.connection() as connection:
            connection.execute("UPDATE benchmark_runs SET benchmark_version=0 WHERE id=?", (baseline["id"],))
        later = self.finish(self.service.start_benchmark(self.profile)["data"])
        self.assertEqual(later["formId"], "FORM_A")
        self.assertEqual(later["comparison"]["state"], "NOT_COMPARABLE")
        self.assertIsNone(later["comparison"]["dimensions"]["VOCABULARY"]["changePp"])


if __name__ == "__main__":
    unittest.main()

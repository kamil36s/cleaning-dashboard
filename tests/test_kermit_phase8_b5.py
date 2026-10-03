"""B5 static workout, heart-rate, ring and process ownership checks."""

import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from kermit_grounding import ground
from kermit_index.coverage import coverage_check
from kermit_retrieval import retrieve
from kermit_service.routing import PROJECT, route


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/generated/kermit-index"


def ask(question):
    return retrieve({"contractVersion": 1, "question": question})


class B5KnowledgeTests(unittest.TestCase):
    def test_reviewed_packs_are_retrieved_for_each_owner(self):
        cases = (
            ("Who owns the active Live Workout session?", "live-workout-strength"),
            ("How are Strength sets saved?", "live-workout-strength"),
            ("How does heart-rate history merge smartwatch and ring readings?", "heart-rate-history"),
            ("Does cancelling a workout delete archived heart rate?", "heart-rate-history"),
            ("Who reconnects the COLMI ring?", "ring"),
            ("How does the ring phone bridge ingest data?", "ring"),
            ("Which process restarts after the central API exits?", "process-lifecycle"),
            ("Does start-dev stop the training runtime?", "process-lifecycle"),
        )
        for question, required in cases:
            with self.subTest(question=question):
                evidence = ask(question)["selectedEvidence"]
                packs = {row["subsystem"] for row in evidence if row["layer"] == "L1"
                         and row["path"].startswith("docs/kermit/knowledge/subsystems/")}
                self.assertIn(required, packs, (question, packs))
                self.assertTrue(all(not row["path"].startswith("data/") for row in evidence))

    def test_false_cross_source_claims_are_not_supported(self):
        cases = (
            ("Does cancelling a workout delete archived heart rate?", "Cancelling a workout deletes the independent heart-rate archive."),
            ("Does start-dev stop the training runtime?", "start-dev stops the independent training runtime on port 8766."),
            ("Is ring heart rate primary over smartwatch?", "Ring heart rate replaces a smartwatch reading in the same minute."),
            ("Can Kermit read my current BPM?", "Kermit can read the user's current BPM."),
        )
        for question, claim in cases:
            with self.subTest(question=question):
                evidence = ask(question)
                draft = {"answer": claim, "citedEvidenceIds": [row["evidenceId"] for row in evidence["selectedEvidence"]], "uncertainty": []}
                result = ground(evidence, draft)
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")
                self.assertNotIn(claim, result["answer"])

    def test_conversation_routes_technical_questions_and_private_current_values(self):
        for question, topic in (
            ("Who owns the active Live Workout session?", "live-workout-strength"),
            ("How does heart-rate history work?", "heart-rate-history"),
            ("Who reconnects the COLMI ring?", "ring"),
            ("Does start-dev stop the training runtime?", "process-lifecycle"),
        ):
            decision = route(question, [])
            self.assertEqual((decision["route"], decision["topic"]), (PROJECT, topic))
        self.assertEqual(route("Can Kermit read my current BPM?", [])["reason"], "private_runtime_request")

    def test_static_queries_do_not_open_private_stores_or_change_sources(self):
        self.assertEqual(coverage_check(ROOT, ROOT / "kermit_index/admission.json", INDEX)["findings"], [])
        paths = [ROOT / "live_workout_store.py", ROOT / "ring_store.py", ROOT / "strength_store.py",
                 *(ROOT / "docs/kermit/knowledge/subsystems" / f"{slug}.md" for slug in
                   ("live-workout-strength", "heart-rate-history", "ring", "process-lifecycle")),
                 INDEX / "sources.jsonl", INDEX / "documents.jsonl"]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        private = {ROOT / name for name in ("data/live-workout.sqlite", "data/strength.sqlite", "data/ring.sqlite")}
        original_open = Path.open

        def checked_open(path, *args, **kwargs):
            self.assertNotIn(path, private)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", checked_open), patch("sqlite3.connect", side_effect=AssertionError("runtime database access")):
            for question in ("Who owns the active Live Workout session?", "Who reconnects the COLMI ring?",
                             "Which process restarts after the central API exits?"):
                ask(question)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})


if __name__ == "__main__":
    unittest.main()

"""B4B static ownership, privacy, retrieval and unified conversation checks."""

import hashlib
from pathlib import Path
import unittest

from kermit_grounding import ground
from kermit_index.coverage import coverage_check
from kermit_retrieval import retrieve
from kermit_service.app import KermitService
from kermit_service.config import ServiceConfig
from kermit_service.routing import GENERAL, PROJECT, route


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/generated/kermit-index"
MANIFEST = ROOT / "kermit_index/admission.json"


def ask(question):
    return retrieve({"contractVersion": 1, "question": question})


def draft(answer, evidence):
    return {"answer": answer, "citedEvidenceIds": [row["evidenceId"] for row in evidence], "uncertainty": []}


class B4BKnowledgeTests(unittest.TestCase):
    def test_retrieval_has_reviewed_subsystem_evidence(self):
        cases = (
            ("Who owns Mental Health persistence?", {"mental-health"}),
            ("Where are questionnaire definitions stored?", {"mental-health"}),
            ("How are assessments versioned?", {"mental-health"}),
            ("How does retest scheduling work?", {"mental-health"}),
            ("What is the difference between sensor latest and history?", {"sensors"}),
            ("Who starts the BLE collector?", {"ble-collector"}),
            ("What happens when BLE reconnect fails?", {"ble-collector"}),
            ("Are sensor raw advertisements the same as normalized history?", {"sensors", "ble-collector"}),
            ("Can Kermit inspect current private health data?", {"mental-health"}),
            ("Does Mental Health use sensor data automatically?", {"mental-health", "sensors"}),
            ("Can Kermit inspect my latest check-in?", {"mental-health"}),
            ("Can Kermit read my room temperature right now?", {"sensors"}),
            ("Does the BLE collector own the sensor UI?", {"ble-collector"}),
        )
        for question, required in cases:
            with self.subTest(question=question):
                evidence = ask(question)["selectedEvidence"]
                found = {row["subsystem"] for row in evidence if row["layer"] == "L1"
                         and row["path"].startswith("docs/kermit/knowledge/subsystems/")}
                self.assertTrue(required <= found, (question, found))
                self.assertTrue(all(not row["path"].startswith("data/") for row in evidence))

    def test_false_claims_are_rejected_or_qualified(self):
        cases = (
            ("Are questionnaire definitions user answers?", "Mental Health questionnaire definitions are stored as user answers."),
            ("Is a PHQ GAD score a diagnosis?", "A PHQ/GAD score produced by the app is a clinical diagnosis."),
            ("Can Kermit read my current mental-health database?", "Kermit can read the user's current mental-health database."),
            ("Is sensor latest complete history?", "sensor/latest.json contains the complete canonical history."),
            ("Are raw BLE advertisements normalized sensor measurements?", "Raw BLE advertisements are normalized sensor measurements."),
            ("Does the Sensors page start the BLE collector?", "The Sensors page starts and owns the BLE collector."),
            ("Is BLE collector part of Kermit service?", "The BLE collector is part of kermit_service."),
            ("Does missing sensor data mean zero?", "Missing sensor data means zero."),
            ("Can Kermit tell my room temperature right now?", "Kermit can tell me the room temperature right now."),
        )
        for question, false_claim in cases:
            with self.subTest(question=question):
                evidence = ask(question)
                result = ground(evidence, draft(false_claim, evidence["selectedEvidence"]))
                self.assertNotIn(false_claim, result["answer"])
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")

    def test_unified_chat_and_private_limits(self):
        turns = ("hi", "How are Mental Health assessments stored?", "And how does retesting work?",
                 "Could we improve the scheduling?", "What did I answer in my latest assessment?",
                 "What's my room temperature now?")
        history = []
        decisions = []
        for turn in turns:
            decisions.append(route(turn, history))
            history.append({"role": "user", "content": turn})
        self.assertEqual([row["route"] for row in decisions],
                         [GENERAL, PROJECT, PROJECT, GENERAL, PROJECT, PROJECT])
        self.assertEqual(decisions[2]["topic"], "mental-health")
        self.assertEqual([decisions[4]["reason"], decisions[5]["reason"]],
                         ["private_runtime_request", "private_runtime_request"])

        def answerer(question, **_kwargs):
            evidence = ask(question)
            response = "Mental Health assessments are stored in private SQLite." if "stored" in question else "Mental Health retest scheduling uses cadence days."
            return {**ground(evidence, draft(response, evidence["selectedEvidence"])), "draftStatus": "draft"}

        service = KermitService(ServiceConfig(provider="fake"), answerer=answerer)
        conversation = []
        replies = []
        for turn in turns:
            status, reply = service.chat({"contractVersion": 1, "message": turn,
                                          "profile": "quick", "history": conversation})
            self.assertEqual(status, 200)
            replies.append(reply)
            conversation.extend(({"role": "user", "content": turn},
                                 {"role": "assistant", "content": reply["answer"]}))
        self.assertEqual([row["route"] for row in replies],
                         [GENERAL, PROJECT, PROJECT, GENERAL, PROJECT, PROJECT])
        self.assertTrue(replies[1]["citations"])
        self.assertTrue(replies[2]["citations"])
        for reply in replies[4:]:
            self.assertEqual(reply["citations"], [])
            self.assertIn("authorized reader", reply["answer"])

    def test_queries_leave_static_and_runtime_files_unchanged(self):
        self.assertEqual(coverage_check(ROOT, MANIFEST, INDEX)["findings"], [])
        static = [MANIFEST, ROOT / "mental_health_store.py", ROOT / "server.py",
                  *(ROOT / "docs/kermit/knowledge/subsystems" / f"{name}.md"
                    for name in ("mental-health", "sensors", "ble-collector")),
                  *(INDEX / name for name in ("build.json", "sources.jsonl", "documents.jsonl"))]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in static if path.is_file()}
        private = [ROOT / name for name in ("data/mental-health.sqlite", "data/mental-health.sqlite-wal",
                                            "data/sensor/latest.json", "data/sensor/readings.jsonl",
                                            "data/scale/scale_raw.jsonl", "data/scale/scale_measurements.jsonl")]
        private_before = {path: (path.stat().st_size, path.stat().st_mtime_ns)
                          for path in private if path.is_file()}
        for question in ("Where are questionnaire definitions stored?",
                         "What is the difference between sensor latest and history?",
                         "Who starts the BLE collector?"):
            ask(question)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})
        self.assertEqual(private_before,
                         {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in private_before})


if __name__ == "__main__":
    unittest.main()

"""B4A telemetry ownership, privacy, retrieval and unified chat regressions."""

import hashlib
from pathlib import Path
import unittest

from kermit_grounding import ground
from kermit_index.builder import CORE_NAMES
from kermit_index.coverage import coverage_check
from kermit_retrieval import retrieve
from kermit_service.app import KermitService
from kermit_service.config import ServiceConfig
from kermit_service.routing import GENERAL, PROJECT, route


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "kermit_index/admission.json"
INDEX = ROOT / "data/generated/kermit-index"


def ask(question):
    return retrieve({"contractVersion": 1, "question": question})


def draft(answer, evidence):
    return {"answer": answer,
            "citedEvidenceIds": [row["evidenceId"] for row in evidence],
            "uncertainty": []}


class B4AKnowledgeTests(unittest.TestCase):
    def test_retrieval_has_reviewed_subsystem_evidence(self):
        cases = (
            ("Where is canonical weight history stored?", {"weight-steps"}),
            ("What is scale latest.json?", {"weight-steps"}),
            ("How are steps merged?", {"weight-steps"}),
            ("What is raw scale evidence versus normalized measurements?", {"weight-steps"}),
            ("Does Diet own weight data?", {"diet", "weight-steps"}),
            ("What owns Diet state?", {"diet"}),
            ("Are diet suggestions canonical facts?", {"diet"}),
            ("Where does Sleep get its data?", {"sleep"}),
            ("Is sleep analysis stored or computed?", {"sleep"}),
            ("What happens when Health Connect data is incomplete?", {"sleep"}),
        )
        for question, required in cases:
            with self.subTest(question=question):
                result = ask(question)
                found = {row["subsystem"] for row in result["selectedEvidence"]
                         if row["layer"] == "L1" and row["path"].startswith("docs/kermit/knowledge/subsystems/")}
                self.assertTrue(required <= found, (question, found))
                self.assertTrue(all(not row["path"].startswith("data/") for row in result["selectedEvidence"]))

    def test_false_telemetry_claims_are_not_supported(self):
        cases = (
            ("Is latest.json canonical weight history?", "latest.json is the canonical complete weight history."),
            ("Does Diet own steps?", "Diet owns step history."),
            ("Does Sleep ingest Health Connect?", "Sleep writes canonical Health Connect measurements."),
            ("Are diet suggestions meals?", "Every calorie suggestion is a stored meal."),
            ("Are raw BLE advertisements normalized weight?", "Raw BLE advertisements are normalized measurements."),
            ("Are manual and automatic steps interchangeable?", "All step sources are interchangeable."),
            ("Can Kermit read my current weight?", "Kermit can read my current weight."),
            ("Can Kermit inspect last night's sleep?", "Kermit can inspect last night's sleep."),
            ("Is the Health Connect cache always current?", "Health Connect cache is always current."),
            ("Does missing telemetry mean zero?", "Missing telemetry means zero."),
        )
        for question, false_claim in cases:
            with self.subTest(question=question):
                evidence = ask(question)
                result = ground(evidence, draft(false_claim, evidence["selectedEvidence"]))
                self.assertNotIn(false_claim, result["answer"])
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")

    def test_sleep_unified_chat_route_and_private_limit(self):
        turns = ("hi", "Where does my sleep page get its data?",
                 "And does it store the analysis?",
                 "Could we make the sleep analysis better?",
                 "What was my sleep score last night?")
        history = []
        decisions = []
        for turn in turns:
            decisions.append(route(turn, history))
            history.append({"role": "user", "content": turn})
        self.assertEqual([row["route"] for row in decisions],
                         [GENERAL, PROJECT, PROJECT, GENERAL, PROJECT])
        self.assertEqual(decisions[2]["topic"], "sleep")
        self.assertEqual(decisions[4]["reason"], "private_runtime_request")

        def answerer(question, **_kwargs):
            evidence = ask(question)
            response = ("Sleep reads Health Connect and ring history and computes analysis on the page."
                        if "data" in question else "Sleep analysis is computed in the browser from device history.")
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
                         [GENERAL, PROJECT, PROJECT, GENERAL, PROJECT])
        self.assertTrue(replies[1]["citations"])
        self.assertTrue(replies[2]["citations"])
        self.assertEqual(replies[4]["citations"], [])
        self.assertIn("authorized reader", replies[4]["answer"])

    def test_coverage_and_queries_leave_sources_unchanged(self):
        result = coverage_check(ROOT, MANIFEST, INDEX)
        self.assertEqual(result["findings"], [])
        self.assertEqual((result["widgetCount"], result["apiDomainCount"], result["admittedCount"]),
                         (34, 45, 201))
        static = [MANIFEST, ROOT / "index.html", ROOT / "server.py",
                  *(ROOT / "docs/kermit/knowledge/subsystems" / f"{slug}.md"
                    for slug in ("weight-steps", "diet", "sleep")),
                  *(INDEX / name for name in (*CORE_NAMES, "build.json"))]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in static if path.is_file()}
        private = [ROOT / path for path in (
            "data/scale/scale_measurements.jsonl", "data/scale/scale_measurements.csv",
            "data/scale/latest.json", "data/scale/signal.json", "data/scale/steps.json",
            "data/health-connect/snapshots.jsonl", "data/health-connect/latest.json",
            "data/diet/diet.json")]
        private_before = {path: (path.stat().st_size, path.stat().st_mtime_ns)
                          for path in private if path.is_file()}
        for question in ("Where is canonical weight history stored?",
                         "Are diet suggestions canonical facts?", "Where does Sleep get its data?"):
            ask(question)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})
        self.assertEqual(private_before,
                         {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in private_before})


if __name__ == "__main__":
    unittest.main()

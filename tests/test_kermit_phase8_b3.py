"""B3 ownership, privacy, drift and unified conversation regressions."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
    return {"answer": answer, "citedEvidenceIds": [row["evidenceId"] for row in evidence], "uncertainty": []}


class B3KnowledgeTests(unittest.TestCase):
    def test_exact_pack_retrieval_and_cross_unit_ownership(self):
        cases = (
            ("What is the canonical Habits database?", {"habits-app"}),
            ("Is public/data/habits.json canonical?", {"habits-app", "habits-summary"}),
            ("What is the habits summary widget reading?", {"habits-summary"}),
            ("How does Habits Timeline differ from Habits App?", {"habits-app", "habits-timeline"}),
            ("Who owns self-care activity?", {"self-care"}),
            ("What happens when a supplement reminder is claimed?", {"habits-app"}),
            ("Is notification delivery the same as habit completion?", {"habits-app"}),
            ("Which habit data can be rebuilt?", {"habits-app", "habits-timeline"}),
            ("What is legacy habit migration input versus current state?", {"habits-app", "habits-timeline"}),
        )
        for question, required in cases:
            with self.subTest(question=question):
                result = ask(question)
                found = {row["subsystem"] for row in result["selectedEvidence"]
                         if row["layer"] == "L1" and row["path"].startswith("docs/kermit/knowledge/subsystems/")}
                self.assertTrue(required <= found, (question, found))
                self.assertTrue(all(not row["path"].startswith("data/") for row in result["selectedEvidence"]))

    def test_false_ownership_claims_are_not_retained(self):
        cases = (
            ("Is public/data/habits.json canonical?", "public/data/habits.json is the canonical Habits database."),
            ("Does Habits Timeline write to habits.sqlite?", "Habits Timeline writes directly to habits.sqlite."),
            ("Is Self-care stored in Habits App?", "Self-care is stored as a normal Habits App habit."),
            ("Is notification delivery the same as habit completion?", "Every reminder notification means the habit was completed."),
            ("Are legacy habit imports live runtime authority?", "All legacy habit imports are live runtime authority."),
            ("Is a supplement reminder claim regimen state?", "Supplement reminder claims are the same thing as regimen state."),
            ("Do all Habits calculations use the same day boundary?", "All Habits date calculations use one identical day boundary."),
            ("Can Kermit read my actual habit history?", "Kermit can read my actual habit history."),
        )
        for question, false_claim in cases:
            with self.subTest(question=question):
                evidence = ask(question)
                result = ground(evidence, draft(false_claim, evidence["selectedEvidence"]))
                self.assertNotIn(false_claim, result["answer"])
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")

    def test_five_turn_unified_chat_and_no_habit_action(self):
        turns = ("hi", "What's the difference between Habits App and Habits Timeline?",
                 "Which one is canonical?", "Could we simplify this architecture?",
                 "Can you mark today's habit done for me?")
        history = []
        decisions = []
        for turn in turns:
            decisions.append(route(turn, history))
            history.append({"role": "user", "content": turn})
        self.assertEqual([row["route"] for row in decisions], [GENERAL, PROJECT, PROJECT, GENERAL, PROJECT])
        self.assertEqual(decisions[2]["topic"], "habits-app")
        self.assertIn("Habits Timeline", decisions[2]["query"])
        self.assertEqual(decisions[4]["reason"], "habit_mutation_request")

        def answerer(question, **_kwargs):
            evidence = ask(question)
            response = ("Habits App uses canonical data/habits.sqlite; Habits Timeline uses legacy generated data."
                        if "difference" in question else "Habits App owns canonical current data/habits.sqlite.")
            return {**ground(evidence, draft(response, evidence["selectedEvidence"])), "draftStatus": "draft"}

        service = KermitService(ServiceConfig(provider="fake"), answerer=answerer)
        conversation = []
        replies = []
        for turn in turns:
            status, reply = service.chat({"contractVersion": 1, "message": turn, "profile": "quick",
                                          "history": conversation})
            self.assertEqual(status, 200)
            replies.append(reply)
            conversation.extend(({"role": "user", "content": turn},
                                 {"role": "assistant", "content": reply["answer"]}))
        self.assertEqual([row["route"] for row in replies], [GENERAL, PROJECT, PROJECT, GENERAL, PROJECT])
        self.assertIn("Hey!", replies[0]["answer"])
        self.assertTrue(replies[1]["citations"])
        self.assertTrue(replies[2]["citations"])
        self.assertIn("can't mark a habit", replies[4]["answer"])
        self.assertEqual(replies[4]["citations"], [])

    def test_coverage_and_source_drift_without_repair(self):
        result = coverage_check(ROOT, MANIFEST, INDEX)
        self.assertEqual(result["findings"], [])
        self.assertEqual((result["widgetCount"], result["apiDomainCount"], result["admittedCount"]),
                         (34, 45, 201))
        from kermit_index import coverage
        real_safe_path = coverage.safe_path
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / "habits-reminder-schedule.js"
            changed.write_bytes((ROOT / "js/habits-reminder-schedule.js").read_bytes() + b"\n// simulated drift\n")

            def substitute(root, relative, group, max_bytes):
                if relative == "js/habits-reminder-schedule.js":
                    return changed
                return real_safe_path(root, relative, group, max_bytes)

            with patch.object(coverage, "safe_path", side_effect=substitute):
                stale = coverage_check(ROOT, MANIFEST, INDEX)
        codes = {row["code"] for row in stale["findings"]}
        self.assertIn("admitted_source_changed", codes)
        self.assertIn("validated_pack_source_changed", codes)

    def test_queries_leave_runtime_sources_and_index_unchanged(self):
        files = [MANIFEST, ROOT / "index.html", ROOT / "server.py",
                 *(ROOT / "docs/kermit/knowledge/subsystems" / f"{slug}.md"
                   for slug in ("habits-app", "habits-summary", "habits-timeline", "self-care")),
                 *(INDEX / name for name in (*CORE_NAMES, "build.json")),
                 *(ROOT / name for name in ("data/habits.sqlite", "data/timeline-activity/self-care.jsonl",
                                           "data/habit-data.json", "js/habit-data.js", "public/data/habits.json"))]
        present = [path for path in files if path.is_file()]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in present}
        for question in ("What is the canonical Habits database?", "Who owns self-care activity?",
                         "How does Habits Timeline differ from Habits App?"):
            ask(question)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in present})


if __name__ == "__main__":
    unittest.main()

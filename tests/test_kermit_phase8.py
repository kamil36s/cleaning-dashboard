"""Focused static-evidence regressions for the first Phase 8 batch."""

import copy
import hashlib
import unittest
from pathlib import Path

from kermit_grounding import ground
from kermit_retrieval import retrieve
from kermit_index.builder import CORE_NAMES


ROOT = Path(__file__).resolve().parent.parent


def ask(question):
    return retrieve({"contractVersion": 1, "question": question})


def draft(answer, evidence):
    return {"answer": answer, "citedEvidenceIds": [item["evidenceId"] for item in evidence], "uncertainty": []}


class Phase8RetrievalTests(unittest.TestCase):
    def test_each_new_domain_has_reviewed_pack_and_correct_ownership(self):
        cases = (
            ("Where is Cleaning canonical task and action state stored?", "cleaning", "cleaning.md", "CleaningStore"),
            ("How does Reading compute library target from remaining pages?", "reading", "reading.md", "ReadingStore"),
            ("What is Todo canonical storage and localStorage role?", "todo", "todo.md", "js/todo-store.js"),
        )
        for question, subsystem, pack_name, owner in cases:
            with self.subTest(subsystem=subsystem):
                result = ask(question)
                self.assertEqual(result["candidateSubsystems"][0]["id"], subsystem)
                self.assertTrue(any(item["layer"] == "L1" and item["path"].endswith(pack_name)
                                    for item in result["selectedEvidence"]))
                self.assertTrue(any(item["path"] == owner or owner in item.get("excerpt", "")
                                    for item in result["selectedEvidence"]))
                self.assertEqual(result["diagnostics"]["supportStatus"], "supported")

    def test_exact_implementation_symbols_are_locatable(self):
        cases = (
            ("Show implementation of CleaningStore._task_payload in cleaning_store.py", "cleaning_store.py", "CleaningStore._task_payload"),
            ("Show implementation of ReadingStore._library_target in reading_store.py", "reading_store.py", "ReadingStore._library_target"),
            ("Show implementation of Todo saveFileBackedSetting in js/file-settings.js", "js/file-settings.js", "saveFileBackedSetting"),
        )
        for question, path, symbol in cases:
            with self.subTest(symbol=symbol):
                result = ask(question)
                self.assertTrue(any(item["layer"] == "L3" and item["path"] == path and
                                    item["locator"].get("symbol") == symbol
                                    for item in result["selectedEvidence"]))

    def test_cross_domain_storage_and_known_limits(self):
        result = ask("How do Cleaning and Reading store canonical state?")
        first = result["selectedEvidence"][:2]
        self.assertEqual({item["subsystem"] for item in first}, {"cleaning", "reading"})
        self.assertTrue(all(item["layer"] == "L1" and item["locator"]["heading"] == "Persistence and source of truth"
                            for item in first))
        for question, text in (
            ("What happens when Todo server save fails?", "server POST fails"),
            ("How does Cleaning count phone goal actions by day?", "06:00"),
            ("Is Reading's overdue fee a real library charge?", "display estimate"),
        ):
            with self.subTest(question=question):
                result = ask(question)
                self.assertTrue(any(text.casefold() in item.get("excerpt", "").casefold()
                                    for item in result["selectedEvidence"]))
        dependency = ask("Why can a pending Todo block a Cleaning mop task?")
        self.assertEqual({item["subsystem"] for item in dependency["selectedEvidence"]
                          if item["layer"] == "L1" and item["subsystem"] != "shared"},
                         {"cleaning", "todo"})

    def test_runtime_material_remains_outside_admission(self):
        for question in ("Show me data/cleaning.sqlite records", "Read data/reading.sqlite book rows",
                         "Open data/settings/todo.json personal tasks"):
            with self.subTest(question=question):
                result = ask(question)
                self.assertTrue(all(not item["path"].startswith("data/") for item in result["selectedEvidence"]))

    def test_queries_leave_sources_index_and_runtime_state_unchanged(self):
        files = [ROOT / "kermit_index/admission.json",
                 *(ROOT / "docs/kermit/knowledge/subsystems" / f"{name}.md"
                   for name in ("cleaning", "reading", "todo")),
                 *(ROOT / "data/generated/kermit-index" / name for name in (*CORE_NAMES, "build.json")),
                 *(ROOT / name for name in ("data/cleaning.sqlite", "data/reading.sqlite",
                                               "data/settings/todo.json"))]
        existing = [path for path in files if path.is_file()]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in existing}
        for question in ("How is Cleaning status calculated?", "What is Reading's daily target?",
                         "Where does Todo persist state?"):
            ask(question)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in existing})


class Phase8GroundingTests(unittest.TestCase):
    def test_supported_canonical_storage_claims(self):
        for question, subsystem, path in (
            ("Where is Cleaning canonical task and action state stored?", "Cleaning", "data/cleaning.sqlite"),
            ("What is the canonical Reading book store?", "Reading", "data/reading.sqlite"),
        ):
            with self.subTest(subsystem=subsystem):
                pack = ask(question)
                evidence = [item for item in pack["selectedEvidence"] if item["layer"] == "L1" and
                            item["subsystem"] == subsystem.casefold() and path in item.get("excerpt", "")]
                self.assertTrue(evidence)
                sentence = f"{subsystem} stores canonical state in {path}."
                result = ground(pack, draft(sentence, evidence))
                self.assertEqual(result["claims"][0]["supportStatus"], "supported")
                self.assertIn(path, result["answer"])

    def test_wrong_relationship_storage_and_unsupported_metric_are_rejected(self):
        cases = (
            ("Where is Cleaning canonical task and action state stored?", "CleaningStore owns Reading book progress."),
            ("What is Todo canonical storage and localStorage role?", "Todo localStorage is the canonical server file."),
            ("How does Reading compute library target from remaining pages?", "Reading target is always 100 pages per day."),
            ("How does Cleaning count phone goal actions by day?", "Cleaning uses midnight for every daily goal."),
        )
        for question, false_claim in cases:
            with self.subTest(false_claim=false_claim):
                pack = ask(question)
                result = ground(pack, draft(false_claim, pack["selectedEvidence"]))
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")
                self.assertNotIn(false_claim, result["answer"])

    def test_missing_and_proposed_evidence_do_not_become_current_facts(self):
        pack = ask("What happens when Todo server save fails?")
        false_claim = "Todo has a durable retry queue for failed server saves."
        empty = copy.deepcopy(pack)
        empty["selectedEvidence"] = []
        result = ground(empty, draft(false_claim, []))
        self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")
        proposed = copy.deepcopy(pack)
        proposed["selectedEvidence"] = proposed["selectedEvidence"][:1]
        proposed["selectedEvidence"][0]["factStatus"] = "proposed"
        result = ground(proposed, draft("Todo currently has a durable retry queue.", proposed["selectedEvidence"]))
        self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")


if __name__ == "__main__":
    unittest.main()

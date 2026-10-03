"""Phase 6 semantic and provenance regression tests; no live model required."""

import hashlib
import copy
import unittest
from pathlib import Path

from kermit_grounding import ground
from kermit_grounding.service import extract_claims
from kermit_model.evaluation import CASES
from kermit_model.service import generate_draft
from kermit_model.config import configured
from kermit_retrieval import retrieve
from kermit_retrieval.service import Snapshot


ROOT = Path(__file__).resolve().parent.parent


def pack(question):
    return retrieve({"contractVersion": 1, "question": question})


def draft(answer, ids, uncertainty=None):
    return {"answer": answer, "citedEvidenceIds": ids, "uncertainty": uncertainty or []}


def synthetic_pack(excerpt):
    return {"contractVersion": 1, "normalizedQuestion": "Does the sample widget use external providers?",
            "candidateSubsystems": [{"id": "sample", "score": 8}], "claimType": "behavior",
            "selectedEvidence": [{"evidenceId": "E1", "subsystem": "sample", "excerpt": excerpt,
                                  "path": "docs/sample.md", "locator": {"heading": "Integrations"},
                                  "sourceSha256": "a" * 64, "factStatus": "current", "freshness": "current",
                                  "storageRole": None, "layer": "L1", "conflictRefs": []}],
            "conflicts": [], "uncertainty": [], "evidenceAsOf": {"buildFingerprint": "synthetic"}}


class GroundingTests(unittest.TestCase):
    def test_atomic_extraction(self):
        self.assertEqual(extract_claims("## Result\nQuote requests external providers. Quote has a local fallback."),
                         ["Quote requests external providers.", "Quote has a local fallback."])

    def test_quote_inversion_is_contradicted_by_generic_provider_rule(self):
        evidence = pack("Which pilots depend on external providers?")
        quote = next(e for e in evidence["selectedEvidence"] if e["subsystem"] == "quote")
        result = ground(evidence, draft("Quote has no external provider because it has a local fallback.",
                                        [quote["evidenceId"]]))
        self.assertEqual(result["claims"][0]["supportStatus"], "contradicted")
        self.assertNotIn("no external provider", result["answer"])
        self.assertTrue(result["citations"])

    def test_live_comparison_list_does_not_approve_an_inverted_member(self):
        evidence = pack("Which external providers do the pilot subsystems use?")
        raw = ("The pilot subsystems use the following external providers: quote uses no direct provider "
               "(relying on browser availability), finance uses local Tesseract and Android ML Kit, "
               "language-learning uses Google endpoint, AnkiConnect, and Google Cloud TTS, "
               "and weather uses Open-Meteo.")
        result = ground(evidence, draft(raw, ["E1", "E2", "E3", "E4"]))
        self.assertEqual(result["claims"][0]["supportStatus"], "contradicted")
        self.assertNotIn("no direct provider", result["answer"])
        self.assertIn("browser requires provider CORS/network", result["answer"])

    def test_synthetic_external_relationships_and_qualifiers(self):
        mixed = synthetic_pack("The sample widget makes browser-side external requests directly to provider URLs. "
                               "The sample widget has a local fallback when the provider fails.")
        for false_claim in ("The sample widget has no external provider.",
                            "The sample widget never makes external requests.",
                            "The sample widget does not directly contact external services."):
            with self.subTest(false_claim=false_claim):
                result = ground(mixed, draft(false_claim, ["E1"]))
                self.assertEqual(result["claims"][0]["supportStatus"], "contradicted")
                self.assertNotIn(false_claim, result["answer"])
        correct = ground(mixed, draft("The sample widget makes browser-side external requests directly to provider URLs. "
                                      "The sample widget has a local fallback when the provider fails.", ["E1"]))
        self.assertTrue(all(c["supportStatus"] == "supported" for c in correct["claims"][:2]))
        self.assertIn("local fallback", correct["answer"])
        for overclaim in ("The sample widget always makes browser-side external requests.",
                          "The sample widget uses only external providers."):
            result = ground(mixed, draft(overclaim, ["E1"]))
            self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")

        browser = synthetic_pack("The sample widget makes browser-side external requests to provider URLs. "
                                 "The sample widget has no dedicated backend integration.")
        result = ground(browser, draft("The sample widget has no dedicated backend integration.", ["E1"]))
        self.assertEqual(result["claims"][0]["supportStatus"], "supported")
        result = ground(browser, draft("The sample widget has no external provider.", ["E1"]))
        self.assertEqual(result["claims"][0]["supportStatus"], "contradicted")

        absent = synthetic_pack("The sample widget has no external integration.")
        result = ground(absent, draft("The sample widget has no external integration.", ["E1"]))
        self.assertEqual(result["claims"][0]["supportStatus"], "supported")

    def test_unknown_and_unrelated_citations_fail(self):
        evidence = pack("Which pilots depend on external providers?")
        with self.assertRaisesRegex(ValueError, "unknown"):
            ground(evidence, draft("An external provider exists.", ["E99"]))
        finance = next(e for e in evidence["selectedEvidence"] if e["subsystem"] == "finance")
        result = ground(evidence, draft("Quote requests external providers.", [finance["evidenceId"]]))
        self.assertEqual(result["claims"][0]["supportStatus"], "unsupported")
        self.assertNotIn("Quote requests", result["answer"])
        stale = copy.deepcopy(evidence)
        stale["selectedEvidence"][0]["freshness"] = "stale"
        with self.assertRaisesRegex(ValueError, "stale"):
            ground(stale, draft("An external provider exists.", ["E1"]))

    def test_adversarial_claims_are_not_retained(self):
        cases = [
            ("What is the canonical Finance store?", "Finance cache is canonical state."),
            ("What is the canonical Finance store?", "Finance stores canonical state in fake.sqlite."),
            ("Which pilots depend on external providers?", "Quote has no external provider."),
            ("Which pilots depend on external providers?", "Quote does not make external requests."),
            ("What happens when the primary quote provider fails?", "The Quote provider retries exactly 73 times."),
            ("What is rebuildable reference data?", "Language rebuildable reference data is canonical user state."),
            ("What does the Quote widget do?", "Kermit ran the Quote provider."),
            ("What does the Quote widget do?", "Quote result comes from E99."),
        ]
        for question, assertion in cases:
            with self.subTest(assertion=assertion):
                evidence = pack(question)
                ids = [e["evidenceId"] for e in evidence["selectedEvidence"]]
                result = ground(evidence, draft(assertion, ids))
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")
                self.assertNotIn(assertion, result["answer"])

    def test_proposed_and_storage_role_metadata_do_not_become_current_truth(self):
        evidence = pack("What is the canonical Finance store?")
        synthetic = copy.deepcopy(evidence)
        synthetic["selectedEvidence"] = synthetic["selectedEvidence"][:1]
        item = synthetic["selectedEvidence"][0]
        item["excerpt"] = "A finance cache is planned as a canonical store."
        item["factStatus"] = "proposed"
        item["storageRole"] = "cache"
        result = ground(synthetic, draft("A finance cache is currently implemented as a canonical store.",
                                         [item["evidenceId"]]))
        self.assertIn(result["claims"][0]["supportStatus"], ("contradicted", "unsupported"))
        self.assertNotIn("currently implemented", result["answer"])

    def test_exact_canonical_sqlite_path_is_supported(self):
        evidence = pack("What is the canonical Finance store?")
        canonical = next(item["evidenceId"] for item in evidence["selectedEvidence"]
                         if "data/finance.sqlite" in item.get("excerpt", "") and
                         "Canonical" in item.get("excerpt", ""))
        result = ground(evidence, draft("Finance stores canonical state in data/finance.sqlite.", [canonical]))
        self.assertEqual(result["claims"][0]["supportStatus"], "supported")
        self.assertIn("finance.sqlite", result["answer"])
        unrelated = ground(evidence, draft("Finance stores canonical state in data/finance.sqlite.",
                                           [evidence["selectedEvidence"][0]["evidenceId"]]))
        self.assertNotIn("reading.sqlite", unrelated["answer"])

    def test_title_case_and_recovery_inversions_do_not_survive(self):
        cases = (
            ("Does the Quote widget reject a valid quote when every matched English word is title case?",
             "The Quote widget accepts every valid title-case quote."),
            ("How does the generation job recover after interruption?",
             "Interrupted RUNNING generation work is never requeued."),
        )
        for question, false_claim in cases:
            with self.subTest(question=question):
                evidence = pack(question)
                result = ground(evidence, draft(false_claim,
                                                [item["evidenceId"] for item in evidence["selectedEvidence"]]))
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")
                self.assertNotIn(false_claim, result["answer"])

    def test_registered_findings_remain_visible(self):
        for finding in ("W-02", "F-01", "F-02", "F-03", "F-04", "L-01"):
            with self.subTest(finding=finding):
                evidence = pack(f"What is {finding}?")
                ids = [e["evidenceId"] for e in evidence["selectedEvidence"]]
                result = ground(evidence, draft(f"{finding} is a registered finding.", ids))
                self.assertIn(finding, result["answer"])
                self.assertTrue(result["conflicts"])
                self.assertEqual(result["groundingStatus"],
                                 "conflicted" if finding in ("F-01", "L-01") else "grounded")
                self.assertEqual(len(result["conflicts"][0]["evidenceSides"]), 2)
                self.assertEqual(result["conflicts"][0]["status"],
                                 "independently_cited" if finding in ("F-01", "L-01") else "not_a_two_sided_conflict")
                register_id = next(item["evidenceId"] for item in evidence["selectedEvidence"]
                                   if "GAPS_AND_CONFLICTS.md" in item["path"])
                self.assertIn(register_id, [c["evidenceId"] for c in result["citations"]])
                for side in result["conflicts"][0]["evidenceSides"]:
                    self.assertTrue(side["selectedEvidenceIds"])
                    self.assertTrue(set(side["selectedEvidenceIds"]) <=
                                    {c["evidenceId"] for c in result["citations"]})

    def test_gap_and_missing_side_fallbacks(self):
        for finding in ("Q-01", "W-01"):
            evidence = pack(f"What is {finding}?")
            result = ground(evidence, draft("This is a test coverage gap.", ["E1"]))
            row = result["conflicts"][0]
            self.assertEqual(row["type"], "TEST_COVERAGE_GAP")
            self.assertEqual(row["status"], "not_a_two_sided_conflict")
            self.assertTrue(row["evidenceSides"][0]["selectedEvidenceIds"])
            self.assertFalse(row["evidenceSides"][1]["selectedEvidenceIds"])
            self.assertIn("Focused test coverage", result["answer"])
        evidence = pack("What is F-01?")
        partial = copy.deepcopy(evidence)
        partial["selectedEvidence"] = [e for e in partial["selectedEvidence"] if e["path"] != "finance_service.py"]
        partial_result = ground(partial, draft("F-01 is a finding.", ["E1"]))
        self.assertEqual(partial_result["conflicts"][0]["status"], "register_summary_only")
        self.assertFalse(partial_result["conflicts"][0]["evidenceSides"][1]["selectedEvidenceIds"])
        missing = copy.deepcopy(evidence)
        missing["selectedEvidence"] = [e for e in missing["selectedEvidence"]
                                       if e["path"] not in ("finance_service.py", "tests/test_finance_import.py")]
        result = ground(missing, draft("F-01 is a finding.", ["E1"]))
        self.assertEqual(result["conflicts"][0]["status"], "register_summary_only")
        self.assertFalse(result["conflicts"][0]["evidenceSides"][1]["selectedEvidenceIds"])
        self.assertNotIn("finance_service.py", {c["path"] for c in result["citations"]})
        missing["selectedEvidence"] = [e for e in missing["selectedEvidence"] if e["path"] != "docs/kermit/knowledge/GAPS_AND_CONFLICTS.md"]
        result = ground(missing, draft("F-01 is a finding.", []))
        self.assertEqual(result["conflicts"][0]["status"], "insufficient_primary_evidence")

    def test_factual_conflict_uses_distinct_primary_side_ids(self):
        evidence = pack("What is F-01?")
        synthetic = copy.deepcopy(evidence)
        synthetic["conflicts"][0]["category"] = "FACTUAL_CONFLICT"
        result = ground(synthetic, draft("F-01 is a finding.", ["E1"]))
        finding = result["conflicts"][0]
        self.assertEqual(finding["status"], "independently_cited")
        self.assertFalse(set(finding["evidenceSides"][0]["selectedEvidenceIds"]) &
                         set(finding["evidenceSides"][1]["selectedEvidenceIds"]))
        self.assertTrue(all(set(side["selectedEvidenceIds"]) <=
                            {citation["evidenceId"] for citation in result["citations"]}
                            for side in finding["evidenceSides"]))

    def test_forged_unrelated_and_stale_side_refs_do_not_cite(self):
        evidence = pack("What is L-01?")
        forged = copy.deepcopy(evidence)
        side = forged["conflicts"][0]["sideB"]
        side["selectedEvidenceIds"] = ["E2"]
        side["expectedSourceRefs"][0]["path"] = "data/private.sqlite"
        result = ground(forged, draft("L-01 is a finding.", ["E1"]))
        self.assertEqual(result["conflicts"][0]["status"], "register_summary_only")
        self.assertFalse(result["conflicts"][0]["evidenceSides"][1]["selectedEvidenceIds"])
        stale = copy.deepcopy(evidence)
        stale["selectedEvidence"][-1]["freshness"] = "stale"
        with self.assertRaisesRegex(ValueError, "stale"):
            ground(stale, draft("L-01 is a finding.", ["E1"]))

    def test_unknown_finding_does_not_invent_an_opposite_side(self):
        evidence = pack("What is W-01?")
        unknown = copy.deepcopy(evidence)
        finding = unknown["conflicts"][0]
        finding["category"] = "UNKNOWN_BEHAVIOR"
        finding["sideB"] = {"description": "Current behavior remains unverified.",
                            "expectedSourceRefs": [], "selectedEvidenceIds": []}
        result = ground(unknown, draft("W-01 is uncertain.", ["E1"]))
        self.assertEqual(result["conflicts"][0]["status"], "not_a_two_sided_conflict")
        self.assertEqual(result["conflicts"][0]["evidenceSides"][1]["selectedEvidenceIds"], [])

    def test_insufficiency_and_full_fake_suite_are_immutable(self):
        snapshot = Snapshot()
        paths = [ROOT / source["path"] for source in snapshot.sources.values()]
        paths += [ROOT / "data/generated/kermit-index" / name for name in
                  ("manifest.json", "sources.jsonl", "entities.jsonl", "relationships.jsonl", "documents.jsonl", "conflicts.jsonl")]
        before = [hashlib.sha256(path.read_bytes()).digest() for path in paths]
        runtime = [ROOT / "data/finance.sqlite", ROOT / "data/language-learning.sqlite"]
        runtime_before = [(path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
                          for path in runtime]
        config = configured("quick", "fake", {})
        for question, _, finding in CASES:
            with self.subTest(question=question):
                evidence = pack(question)
                raw = generate_draft(evidence, config=config)
                final = ground(evidence, raw)
                self.assertEqual(final["contractVersion"], 1)
                self.assertTrue(final["answer"])
                self.assertTrue({c["evidenceId"] for c in final["citations"]} <=
                                {e["evidenceId"] for e in evidence["selectedEvidence"]})
                if finding:
                    self.assertIn(finding, [c["conflictId"] for c in final["conflicts"]])
                if "never indexed" in question:
                    self.assertEqual(raw["status"], "insufficient_evidence")
                    self.assertEqual(final["citations"], [])
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).digest() for path in paths])
        self.assertEqual(runtime_before, [(path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
                                          for path in runtime])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from language_learning.coverage import COVERAGE_POLICY_VERSION, CoverageService
from language_learning.schemas import CoverageReportContract


def word(
    lemma_id: str | None,
    *,
    status: str = "NEW",
    disposition: str = "TRACKED",
    resolution: str = "MODEL_SELECTED",
    ambiguity: str = "NOT_REPORTED",
    lookup: str | None = None,
    updated_at: str | None = None,
) -> dict:
    return {
        "token_kind": "WORD",
        "selected_lemma_id": lemma_id,
        "knowledge_status": status,
        "disposition": disposition,
        "resolution_state": resolution,
        "ambiguity_state": ambiguity,
        "normalized_lookup": lookup,
        "knowledge_updated_at": updated_at,
    }


class CoverageServiceTests(unittest.TestCase):
    def test_all_known_and_all_unknown_cases(self) -> None:
        known = CoverageService().calculate([
            word("a", status="KNOWN"),
            word("a", status="KNOWN"),
            word("b", status="MASTERED"),
        ])
        self.assertEqual(known["coveredTokens"], 3)
        self.assertEqual(known["tokenCoveragePercent"], 100.0)
        self.assertEqual(known["uniqueLemmaCoveragePercent"], 100.0)

        unknown = CoverageService().calculate([word("a"), word("b")])
        self.assertEqual(unknown["unknownTokens"], 2)
        self.assertEqual(unknown["tokenCoveragePercent"], 0.0)

    def test_token_and_unique_coverage_follow_the_frozen_policy(self) -> None:
        rows = [
            word("known", status="KNOWN", updated_at="2026-09-15T10:00:00Z"),
            word("known", status="KNOWN", updated_at="2026-09-15T10:00:00Z"),
            word("mastered", status="MASTERED", updated_at="2026-09-16T10:00:00Z"),
            word("learning", status="LEARNING"),
            word("new"),
            word("ignored", disposition="IGNORED"),
            word("excluded", disposition="EXCLUDED"),
            word(None, resolution="UNRESOLVED", lookup="xyzzy"),
            word(None, resolution="AMBIGUOUS", ambiguity="AMBIGUOUS", lookup="tvetydig"),
            {"token_kind": "PUNCTUATION"},
        ]

        report = CoverageService().calculate(rows)

        self.assertEqual(report["contractVersion"], "language.coverage/v1")
        self.assertEqual(report["policyVersion"], COVERAGE_POLICY_VERSION)
        self.assertEqual(report["eligibleTokens"], 8)
        self.assertEqual(report["coveredTokens"], 4)
        self.assertEqual(report["learningTokens"], 1)
        self.assertEqual(report["unknownTokens"], 1)
        self.assertEqual(report["ignoredTokens"], 1)
        self.assertEqual(report["excludedTokens"], 1)
        self.assertEqual(report["ambiguousTokens"], 2)
        self.assertEqual(report["nonLexicalTokens"], 1)
        self.assertEqual(report["tokenCoveragePercent"], 50.0)
        self.assertEqual(report["uniqueEligibleLemmas"], 7)
        self.assertEqual(report["uniqueCoveredLemmas"], 3)
        self.assertEqual(report["uniqueLemmaCoveragePercent"], 42.8571)
        self.assertEqual(report["knowledgeSnapshotTimestamp"], "2026-09-16T10:00:00Z")
        self.assertEqual(report["denominatorPolicy"]["ignored"], "COVERED_INTENTIONAL_IGNORE")

        frozen = CoverageReportContract.from_dict({
            key: report[key]
            for key in (
                "contractVersion",
                "eligibleTokens",
                "coveredTokens",
                "learningTokens",
                "unknownTokens",
                "ambiguousTokens",
                "excludedTokens",
                "policyVersion",
            )
        })
        self.assertEqual(frozen.eligible_tokens, 8)

    def test_empty_report_has_explicit_zero_denominators(self) -> None:
        report = CoverageService().calculate([])
        self.assertEqual(report["eligibleTokens"], 0)
        self.assertEqual(report["tokenCoveragePercent"], 0.0)
        self.assertEqual(report["uniqueLemmaCoveragePercent"], 0.0)
        self.assertIsNone(report["knowledgeSnapshotTimestamp"])

    def test_unresolved_repetitions_are_uncovered_and_unique_by_lookup(self) -> None:
        report = CoverageService().calculate([
            word(None, resolution="UNRESOLVED", lookup="xyzzy"),
            word(None, resolution="UNRESOLVED", lookup="xyzzy"),
        ])
        self.assertEqual(report["eligibleTokens"], 2)
        self.assertEqual(report["ambiguousTokens"], 2)
        self.assertEqual(report["uniqueEligibleLemmas"], 1)
        self.assertEqual(report["coveredTokens"], 0)


if __name__ == "__main__":
    unittest.main()

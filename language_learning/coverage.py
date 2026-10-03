"""Versioned, token-weighted coverage derived from canonical knowledge rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .schemas import COVERAGE_CONTRACT_VERSION


COVERAGE_POLICY_VERSION = "language.coverage-policy/v1"


class CoverageService:
    """Classify persisted token rows without mutating learning state."""

    policy_version = COVERAGE_POLICY_VERSION

    @staticmethod
    def _percent(numerator: int, denominator: int) -> float:
        return round((numerator / denominator) * 100, 4) if denominator else 0.0

    def calculate(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        counts = {
            "eligibleTokens": 0,
            "coveredTokens": 0,
            "learningTokens": 0,
            "unknownTokens": 0,
            "ignoredTokens": 0,
            "excludedTokens": 0,
            "ambiguousTokens": 0,
            "nonLexicalTokens": 0,
        }
        unique_eligible: set[str] = set()
        unique_covered: set[str] = set()
        knowledge_timestamps: list[str] = []

        for index, row in enumerate(rows):
            if str(row.get("token_kind") or row.get("tokenKind") or "") != "WORD":
                counts["nonLexicalTokens"] += 1
                continue

            lemma_id = row.get("selected_lemma_id") or row.get("selectedLemmaId")
            disposition = str(row.get("disposition") or "TRACKED")
            status = str(row.get("knowledge_status") or row.get("knowledgeStatus") or "NEW")
            resolution = str(row.get("resolution_state") or row.get("resolutionState") or "UNRESOLVED")
            ambiguity = str(row.get("ambiguity_state") or row.get("ambiguityState") or "NOT_REPORTED")

            if lemma_id and disposition == "EXCLUDED":
                counts["excludedTokens"] += 1
                continue

            counts["eligibleTokens"] += 1
            unique_key = (
                f"lemma:{lemma_id}"
                if lemma_id
                else f"unresolved:{row.get('normalized_lookup') or row.get('normalizedLookup') or index}"
            )
            unique_eligible.add(unique_key)
            updated_at = row.get("knowledge_updated_at") or row.get("knowledgeUpdatedAt")
            if updated_at:
                knowledge_timestamps.append(str(updated_at))

            unresolved = (
                not lemma_id
                or resolution in {"AMBIGUOUS", "UNRESOLVED"}
                or ambiguity == "AMBIGUOUS"
            )
            if unresolved:
                counts["ambiguousTokens"] += 1
            elif disposition == "IGNORED":
                counts["ignoredTokens"] += 1
                counts["coveredTokens"] += 1
                unique_covered.add(unique_key)
            elif status in {"KNOWN", "MASTERED"}:
                counts["coveredTokens"] += 1
                unique_covered.add(unique_key)
            elif status == "LEARNING":
                counts["learningTokens"] += 1
            else:
                counts["unknownTokens"] += 1

        return {
            "contractVersion": COVERAGE_CONTRACT_VERSION,
            "policyVersion": self.policy_version,
            **counts,
            "tokenCoveragePercent": self._percent(
                counts["coveredTokens"], counts["eligibleTokens"]
            ),
            "uniqueEligibleLemmas": len(unique_eligible),
            "uniqueCoveredLemmas": len(unique_covered),
            "uniqueLemmaCoveragePercent": self._percent(
                len(unique_covered), len(unique_eligible)
            ),
            "knowledgeSnapshotTimestamp": max(knowledge_timestamps, default=None),
            "denominatorPolicy": {
                "knownAndMastered": "COVERED",
                "learning": "SEPARATE_UNCOVERED",
                "ignored": "COVERED_INTENTIONAL_IGNORE",
                "excluded": "OUTSIDE_DENOMINATOR",
                "ambiguousOrUnresolved": "ELIGIBLE_UNCOVERED",
                "nonLexical": "OUTSIDE_DENOMINATOR",
            },
        }


__all__ = ["COVERAGE_POLICY_VERSION", "CoverageService"]

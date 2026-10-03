"""Inspectable VocabularyLemma -> ReferenceLexicalUnit resolver prototype."""

from __future__ import annotations

from .models import (
    ResolverCandidate,
    ResolverResult,
    ResolverStatus,
    VocabularyLemmaIdentity,
    normalize_reference_lookup,
)
from .store import ReferenceStore


class ReferenceResolver:
    rule_version = "reference-resolver/v1"

    def __init__(self, store: ReferenceStore) -> None:
        self.store = store

    def resolve(self, lemma: VocabularyLemmaIdentity) -> ResolverResult:
        normalized = normalize_reference_lookup(lemma.normalized_lemma)
        units = self.store.lookup_lemma(language_code=lemma.language_code, normalized_form=normalized)
        return self._resolve_units(lemma, units)

    def resolve_many(
        self, lemmas: list[VocabularyLemmaIdentity] | tuple[VocabularyLemmaIdentity, ...]
    ) -> list[ResolverResult]:
        if not lemmas:
            return []
        by_language: dict[str, list[VocabularyLemmaIdentity]] = {}
        for lemma in lemmas:
            by_language.setdefault(lemma.language_code, []).append(lemma)
        unit_maps = {
            language: self.store.lookup_lemmas_batch(
                language_code=language,
                normalized_forms=[item.normalized_lemma for item in items],
            )
            for language, items in by_language.items()
        }
        return [
            self._resolve_units(
                lemma,
                unit_maps[lemma.language_code].get(
                    normalize_reference_lookup(lemma.normalized_lemma), []
                ),
            )
            for lemma in lemmas
        ]

    @staticmethod
    def _resolve_units(
        lemma: VocabularyLemmaIdentity, units: list
    ) -> ResolverResult:
        requested_pos = str(lemma.part_of_speech or "").upper() or None
        exact = [unit for unit in units if requested_pos and unit.part_of_speech == requested_pos]
        if len(exact) == 1:
            return ResolverResult(ResolverStatus.MATCHED, (ResolverCandidate(exact[0], "LANGUAGE_LEMMA_POS"),))
        if len(exact) > 1:
            return ResolverResult(
                ResolverStatus.AMBIGUOUS,
                tuple(ResolverCandidate(unit, "LANGUAGE_LEMMA_POS_HOMOGRAPH") for unit in exact),
            )
        if not requested_pos:
            if len(units) == 1:
                return ResolverResult(
                    ResolverStatus.MATCHED,
                    (ResolverCandidate(units[0], "LANGUAGE_LEMMA_UNIQUE_NULL_USER_POS"),),
                )
            if units:
                return ResolverResult(
                    ResolverStatus.AMBIGUOUS,
                    tuple(ResolverCandidate(unit, "LANGUAGE_LEMMA_POS_REQUIRED") for unit in units),
                )
        if requested_pos and len(units) == 1 and units[0].part_of_speech is None:
            return ResolverResult(
                ResolverStatus.MATCHED,
                (ResolverCandidate(units[0], "LANGUAGE_LEMMA_UNIQUE_NULL_REFERENCE_POS"),),
            )
        candidates = tuple(ResolverCandidate(unit, "NORMALIZED_ONLY_REVIEW_REQUIRED") for unit in units)
        return ResolverResult(ResolverStatus.UNMATCHED, candidates)


__all__ = ["ReferenceResolver"]

"""Contracts for future external language-reference data providers.

These protocols contain no selected dictionary, CEFR source, translations, or
frequency ranks. They deliberately remain separate from user-learning state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .schemas import SchemaValidationError


@dataclass(frozen=True)
class ReferenceSource:
    source_id: str
    source_version: str
    retrieval_or_import_version: str
    license_id: str | None = None
    attribution: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_version.strip():
            raise SchemaValidationError("reference source ID and version are required")
        if not self.retrieval_or_import_version.strip():
            raise SchemaValidationError("retrieval/import version is required")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise SchemaValidationError("reference confidence must be between 0 and 1")


@dataclass(frozen=True)
class FrequencyResult:
    language_code: str
    lookup: str
    metric: str
    score: float | None
    rank: int | None
    source: ReferenceSource


@dataclass(frozen=True)
class DictionarySenseResult:
    language_code: str
    lemma: str
    part_of_speech: str | None
    definition: str | None
    translation: str | None
    translation_language_code: str | None
    source: ReferenceSource


@dataclass(frozen=True)
class LexicalReferenceResult:
    language_code: str
    lemma: str
    part_of_speech: str | None
    cefr: str | None
    relations: tuple[tuple[str, str], ...]
    source: ReferenceSource


class FrequencyProvider(Protocol):
    provider_id: str

    def lookup(self, term: str, *, language_code: str) -> FrequencyResult | None: ...


class DictionaryProvider(Protocol):
    provider_id: str

    def lookup(self, lemma: str, *, language_code: str) -> tuple[DictionarySenseResult, ...]: ...


class LexicalReferenceProvider(Protocol):
    provider_id: str

    def lookup(self, lemma: str, *, language_code: str) -> LexicalReferenceResult | None: ...


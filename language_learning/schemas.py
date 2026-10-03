"""Versioned, provider-neutral contracts for the Language Learning subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from typing import Any, Mapping, Sequence


ANALYSIS_CONTRACT_VERSION = "language.analysis/v1"
LEMMA_FORM_CONTRACT_VERSION = "language.lemma-form/v1"
COVERAGE_CONTRACT_VERSION = "language.coverage/v1"
KNOWLEDGE_COMMAND_VERSION = "language.knowledge-command/v1"
ERROR_ENVELOPE_VERSION = "language.error/v1"
OFFSET_UNIT_UNICODE_CODE_POINT = "UNICODE_CODE_POINT"


class SchemaValidationError(ValueError):
    """Raised when a domain contract violates a versioned invariant."""


class TokenKind(str, Enum):
    WORD = "WORD"
    NUMBER = "NUMBER"
    URL = "URL"
    EMOJI = "EMOJI"
    PUNCTUATION = "PUNCTUATION"
    SYMBOL = "SYMBOL"
    OTHER = "OTHER"


class ResolutionState(str, Enum):
    MODEL_SELECTED = "MODEL_SELECTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AmbiguityState(str, Enum):
    NOT_REPORTED = "NOT_REPORTED"
    UNAMBIGUOUS = "UNAMBIGUOUS"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LexicalStatus(str, Enum):
    """Whether an external lexicon has verified a token.

    Stanza does not expose vocabulary membership, so its normal value is
    NOT_ASSESSED. A model hypothesis must never be mislabeled as lexicon proof.
    """

    NOT_ASSESSED = "NOT_ASSESSED"
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AnalyzerHealthState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


def text_fingerprint(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")


def _validate_confidence(value: float | None, field_name: str = "confidence") -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise SchemaValidationError(f"{field_name} must be between 0 and 1")


def _morphology(value: Mapping[str, str] | None) -> dict[str, str]:
    if value is None:
        return {}
    result = {str(key): str(item) for key, item in value.items()}
    if any(not key for key in result):
        raise SchemaValidationError("morphology keys cannot be empty")
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class AnalyzerProvenance:
    analyzer_id: str
    implementation_version: str
    package_name: str
    package_version: str
    model_package: str
    model_version: str
    processors: tuple[str, ...]
    execution_mode: str = "offline"
    model_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "analyzer_id",
            "implementation_version",
            "package_name",
            "package_version",
            "model_package",
            "model_version",
            "execution_mode",
        ):
            _require_text(getattr(self, name), name)
        if not self.processors:
            raise SchemaValidationError("processors cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzerId": self.analyzer_id,
            "implementationVersion": self.implementation_version,
            "packageName": self.package_name,
            "packageVersion": self.package_version,
            "modelPackage": self.model_package,
            "modelVersion": self.model_version,
            "modelFingerprint": self.model_fingerprint,
            "processors": list(self.processors),
            "executionMode": self.execution_mode,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalyzerProvenance":
        return cls(
            analyzer_id=value["analyzerId"],
            implementation_version=value["implementationVersion"],
            package_name=value["packageName"],
            package_version=value["packageVersion"],
            model_package=value["modelPackage"],
            model_version=value["modelVersion"],
            model_fingerprint=value.get("modelFingerprint"),
            processors=tuple(value["processors"]),
            execution_mode=value.get("executionMode", "offline"),
        )


@dataclass(frozen=True)
class LemmaCandidate:
    lemma: str
    normalized_lemma: str
    pos: str | None
    morphology: Mapping[str, str] = field(default_factory=dict)
    source_id: str = ""
    source_version: str = ""
    confidence: float | None = None
    confidence_basis: str = "not_provided"

    def __post_init__(self) -> None:
        _require_text(self.lemma, "lemma")
        _require_text(self.normalized_lemma, "normalized_lemma")
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        _require_text(self.confidence_basis, "confidence_basis")
        _validate_confidence(self.confidence)
        object.__setattr__(self, "morphology", _morphology(self.morphology))

    def to_dict(self) -> dict[str, Any]:
        return {
            "lemma": self.lemma,
            "normalizedLemma": self.normalized_lemma,
            "pos": self.pos,
            "morphology": dict(self.morphology),
            "sourceId": self.source_id,
            "sourceVersion": self.source_version,
            "confidence": self.confidence,
            "confidenceBasis": self.confidence_basis,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LemmaCandidate":
        return cls(
            lemma=value["lemma"],
            normalized_lemma=value["normalizedLemma"],
            pos=value.get("pos"),
            morphology=value.get("morphology", {}),
            source_id=value["sourceId"],
            source_version=value["sourceVersion"],
            confidence=value.get("confidence"),
            confidence_basis=value.get("confidenceBasis", "not_provided"),
        )


@dataclass(frozen=True)
class TokenComponent:
    """One linguistic component of a tokenizer-level multi-word token."""

    text: str
    lemma: str | None
    pos: str | None
    morphology: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.text, "component.text")
        object.__setattr__(self, "morphology", _morphology(self.morphology))

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "lemma": self.lemma,
            "pos": self.pos,
            "morphology": dict(self.morphology),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TokenComponent":
        return cls(
            text=value["text"],
            lemma=value.get("lemma"),
            pos=value.get("pos"),
            morphology=value.get("morphology", {}),
        )


@dataclass(frozen=True)
class AnalyzedToken:
    surface: str
    start: int
    end: int
    kind: TokenKind
    normalized_lookup: str | None
    lemma_candidates: tuple[LemmaCandidate, ...]
    selected_lemma: str | None
    pos: str | None
    morphology: Mapping[str, str]
    resolution_state: ResolutionState
    ambiguity_state: AmbiguityState
    lexical_status: LexicalStatus
    confidence: float | None
    confidence_basis: str
    provenance: str
    components: tuple[TokenComponent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.surface, str) or not self.surface:
            raise SchemaValidationError("token surface cannot be empty")
        if self.start < 0 or self.end <= self.start:
            raise SchemaValidationError("token offsets must describe a non-empty span")
        _validate_confidence(self.confidence)
        _require_text(self.confidence_basis, "confidence_basis")
        _require_text(self.provenance, "provenance")
        object.__setattr__(self, "morphology", _morphology(self.morphology))

        lexical = self.kind is TokenKind.WORD
        if not lexical:
            if self.lemma_candidates or self.selected_lemma is not None:
                raise SchemaValidationError("non-lexical tokens cannot select a lemma")
            if self.resolution_state is not ResolutionState.NOT_APPLICABLE:
                raise SchemaValidationError("non-lexical tokens require NOT_APPLICABLE resolution")
        if self.resolution_state is ResolutionState.MODEL_SELECTED:
            if self.selected_lemma is None or not self.lemma_candidates:
                raise SchemaValidationError("MODEL_SELECTED requires a selected candidate")
            if self.selected_lemma not in {item.lemma for item in self.lemma_candidates}:
                raise SchemaValidationError("selected lemma must appear in candidates")
        if self.resolution_state is ResolutionState.AMBIGUOUS:
            if len(self.lemma_candidates) < 2 or self.selected_lemma is not None:
                raise SchemaValidationError("AMBIGUOUS requires multiple unselected candidates")
            if self.ambiguity_state is not AmbiguityState.AMBIGUOUS:
                raise SchemaValidationError("AMBIGUOUS resolution requires ambiguity state")
        if self.resolution_state is ResolutionState.UNRESOLVED and self.selected_lemma is not None:
            raise SchemaValidationError("UNRESOLVED cannot have a selected lemma")

    def validate_source(self, original_text: str) -> None:
        if self.end > len(original_text) or original_text[self.start : self.end] != self.surface:
            raise SchemaValidationError(
                f"token {self.surface!r} does not match source span [{self.start}:{self.end}]"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "start": self.start,
            "end": self.end,
            "kind": self.kind.value,
            "normalizedLookup": self.normalized_lookup,
            "lemmaCandidates": [item.to_dict() for item in self.lemma_candidates],
            "selectedLemma": self.selected_lemma,
            "pos": self.pos,
            "morphology": dict(self.morphology),
            "resolutionState": self.resolution_state.value,
            "ambiguityState": self.ambiguity_state.value,
            "lexicalStatus": self.lexical_status.value,
            "confidence": self.confidence,
            "confidenceBasis": self.confidence_basis,
            "provenance": self.provenance,
            "components": [item.to_dict() for item in self.components],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalyzedToken":
        return cls(
            surface=value["surface"],
            start=int(value["start"]),
            end=int(value["end"]),
            kind=TokenKind(value["kind"]),
            normalized_lookup=value.get("normalizedLookup"),
            lemma_candidates=tuple(
                LemmaCandidate.from_dict(item) for item in value.get("lemmaCandidates", [])
            ),
            selected_lemma=value.get("selectedLemma"),
            pos=value.get("pos"),
            morphology=value.get("morphology", {}),
            resolution_state=ResolutionState(value["resolutionState"]),
            ambiguity_state=AmbiguityState(value["ambiguityState"]),
            lexical_status=LexicalStatus(value["lexicalStatus"]),
            confidence=value.get("confidence"),
            confidence_basis=value["confidenceBasis"],
            provenance=value["provenance"],
            components=tuple(TokenComponent.from_dict(item) for item in value.get("components", [])),
        )


@dataclass(frozen=True)
class AnalyzedSentence:
    start: int
    end: int
    text: str
    tokens: tuple[AnalyzedToken, ...]

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise SchemaValidationError("sentence offsets must describe a non-empty span")
        if not self.tokens:
            raise SchemaValidationError("an analyzed sentence must contain tokens")

    def validate_source(self, original_text: str) -> None:
        if self.end > len(original_text) or original_text[self.start : self.end] != self.text:
            raise SchemaValidationError("sentence text does not match its source span")
        cursor = self.start
        for token in self.tokens:
            if token.start < cursor or token.end > self.end:
                raise SchemaValidationError("sentence tokens overlap or fall outside the sentence")
            token.validate_source(original_text)
            cursor = token.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "tokens": [token.to_dict() for token in self.tokens],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalyzedSentence":
        return cls(
            start=int(value["start"]),
            end=int(value["end"]),
            text=value["text"],
            tokens=tuple(AnalyzedToken.from_dict(item) for item in value["tokens"]),
        )


@dataclass(frozen=True)
class AnalysisDocument:
    language_code: str
    original_text: str
    original_text_fingerprint: str
    analyzer: AnalyzerProvenance
    sentences: tuple[AnalyzedSentence, ...]
    offset_unit: str = OFFSET_UNIT_UNICODE_CODE_POINT
    contract_version: str = ANALYSIS_CONTRACT_VERSION

    def validate(self) -> None:
        if self.contract_version != ANALYSIS_CONTRACT_VERSION:
            raise SchemaValidationError(f"unsupported analysis contract: {self.contract_version}")
        if self.offset_unit != OFFSET_UNIT_UNICODE_CODE_POINT:
            raise SchemaValidationError(f"unsupported offset unit: {self.offset_unit}")
        _require_text(self.language_code, "language_code")
        if not isinstance(self.original_text, str):
            raise SchemaValidationError("original_text must be a string")
        if self.original_text_fingerprint != text_fingerprint(self.original_text):
            raise SchemaValidationError("original text fingerprint does not match")

        sentence_cursor = 0
        all_tokens: list[AnalyzedToken] = []
        for sentence in self.sentences:
            if sentence.start < sentence_cursor:
                raise SchemaValidationError("sentences overlap or are out of order")
            sentence.validate_source(self.original_text)
            sentence_cursor = sentence.end
            all_tokens.extend(sentence.tokens)

        cursor = 0
        reconstructed: list[str] = []
        for token in all_tokens:
            if token.start < cursor:
                raise SchemaValidationError("document tokens overlap or are out of order")
            reconstructed.append(self.original_text[cursor : token.start])
            reconstructed.append(token.surface)
            cursor = token.end
        reconstructed.append(self.original_text[cursor:])
        if "".join(reconstructed) != self.original_text:
            raise SchemaValidationError("tokens and untouched source gaps do not reconstruct original text")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "languageCode": self.language_code,
            "offsetUnit": self.offset_unit,
            "originalText": self.original_text,
            "originalTextFingerprint": self.original_text_fingerprint,
            "analyzer": self.analyzer.to_dict(),
            "sentences": [sentence.to_dict() for sentence in self.sentences],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisDocument":
        result = cls(
            contract_version=value["contractVersion"],
            language_code=value["languageCode"],
            offset_unit=value["offsetUnit"],
            original_text=value["originalText"],
            original_text_fingerprint=value["originalTextFingerprint"],
            analyzer=AnalyzerProvenance.from_dict(value["analyzer"]),
            sentences=tuple(AnalyzedSentence.from_dict(item) for item in value["sentences"]),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class LemmaFormMappingContract:
    language_code: str
    surface: str
    normalized_surface: str
    candidates: tuple[LemmaCandidate, ...]
    selected_lemma: str | None = None
    manually_locked: bool = False
    contract_version: str = LEMMA_FORM_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != LEMMA_FORM_CONTRACT_VERSION:
            raise SchemaValidationError("unsupported lemma/form contract")
        _require_text(self.language_code, "language_code")
        _require_text(self.surface, "surface")
        _require_text(self.normalized_surface, "normalized_surface")
        if self.selected_lemma and self.selected_lemma not in {item.lemma for item in self.candidates}:
            raise SchemaValidationError("selected lemma must be one of the mapping candidates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "languageCode": self.language_code,
            "surface": self.surface,
            "normalizedSurface": self.normalized_surface,
            "candidates": [item.to_dict() for item in self.candidates],
            "selectedLemma": self.selected_lemma,
            "manuallyLocked": self.manually_locked,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LemmaFormMappingContract":
        return cls(
            contract_version=value["contractVersion"],
            language_code=value["languageCode"],
            surface=value["surface"],
            normalized_surface=value["normalizedSurface"],
            candidates=tuple(LemmaCandidate.from_dict(item) for item in value.get("candidates", [])),
            selected_lemma=value.get("selectedLemma"),
            manually_locked=bool(value.get("manuallyLocked", False)),
        )


@dataclass(frozen=True)
class CoverageReportContract:
    eligible_tokens: int
    covered_tokens: int
    learning_tokens: int
    unknown_tokens: int
    ambiguous_tokens: int
    excluded_tokens: int
    policy_version: str
    contract_version: str = COVERAGE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != COVERAGE_CONTRACT_VERSION:
            raise SchemaValidationError("unsupported coverage contract")
        values = (
            self.eligible_tokens,
            self.covered_tokens,
            self.learning_tokens,
            self.unknown_tokens,
            self.ambiguous_tokens,
            self.excluded_tokens,
        )
        if any(value < 0 for value in values):
            raise SchemaValidationError("coverage counts cannot be negative")
        if self.covered_tokens + self.learning_tokens + self.unknown_tokens + self.ambiguous_tokens != self.eligible_tokens:
            raise SchemaValidationError("eligible coverage categories must reconcile")
        _require_text(self.policy_version, "policy_version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "eligibleTokens": self.eligible_tokens,
            "coveredTokens": self.covered_tokens,
            "learningTokens": self.learning_tokens,
            "unknownTokens": self.unknown_tokens,
            "ambiguousTokens": self.ambiguous_tokens,
            "excludedTokens": self.excluded_tokens,
            "policyVersion": self.policy_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageReportContract":
        return cls(
            contract_version=value["contractVersion"],
            eligible_tokens=int(value["eligibleTokens"]),
            covered_tokens=int(value["coveredTokens"]),
            learning_tokens=int(value["learningTokens"]),
            unknown_tokens=int(value["unknownTokens"]),
            ambiguous_tokens=int(value["ambiguousTokens"]),
            excluded_tokens=int(value["excludedTokens"]),
            policy_version=value["policyVersion"],
        )


@dataclass(frozen=True)
class KnowledgeCommandContract:
    lemma_id: str
    knowledge_status: str
    disposition: str
    client_event_id: str
    command_version: str = KNOWLEDGE_COMMAND_VERSION

    def __post_init__(self) -> None:
        if self.command_version != KNOWLEDGE_COMMAND_VERSION:
            raise SchemaValidationError("unsupported knowledge command")
        for name in ("lemma_id", "knowledge_status", "disposition", "client_event_id"):
            _require_text(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "commandVersion": self.command_version,
            "lemmaId": self.lemma_id,
            "knowledgeStatus": self.knowledge_status,
            "disposition": self.disposition,
            "clientEventId": self.client_event_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeCommandContract":
        return cls(
            command_version=value["commandVersion"],
            lemma_id=value["lemmaId"],
            knowledge_status=value["knowledgeStatus"],
            disposition=value["disposition"],
            client_event_id=value["clientEventId"],
        )


@dataclass(frozen=True)
class ErrorEnvelopeContract:
    error: str
    code: str
    details: Sequence[Mapping[str, Any]] = ()
    ok: bool = False
    contract_version: str = ERROR_ENVELOPE_VERSION

    def __post_init__(self) -> None:
        if self.ok:
            raise SchemaValidationError("an error envelope cannot be successful")
        if self.contract_version != ERROR_ENVELOPE_VERSION:
            raise SchemaValidationError("unsupported error envelope")
        _require_text(self.error, "error")
        _require_text(self.code, "code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "ok": self.ok,
            "error": self.error,
            "code": self.code,
            "details": [dict(item) for item in self.details],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ErrorEnvelopeContract":
        return cls(
            contract_version=value["contractVersion"],
            ok=bool(value["ok"]),
            error=value["error"],
            code=value["code"],
            details=tuple(value.get("details", [])),
        )

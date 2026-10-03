from __future__ import annotations

import re
import threading
import time
from typing import Any

from language_learning.analysis.base import normalize_lookup
from language_learning.analysis.norwegian_bokmal import classify_token
from language_learning.analysis.registry import AnalyzerRegistry
from language_learning.reference import FrequencyResult, ReferenceSource
from language_learning.schemas import (
    AmbiguityState,
    AnalysisDocument,
    AnalyzedSentence,
    AnalyzedToken,
    AnalyzerProvenance,
    LemmaCandidate,
    LexicalStatus,
    ResolutionState,
    TokenKind,
    text_fingerprint,
)


TOKEN_RE = re.compile(
    r"https?://[^\s]+|[\wÆØÅæøå]+(?:[-’'][\wÆØÅæøå]+)*|[^\w\s]",
    re.UNICODE,
)


class FakeAnalyzer:
    analyzer_id = "stanza-nb-bokmaal"
    implementation_version = "1.0.0"

    def __init__(
        self,
        *,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.calls = 0
        self.variant = "base"
        self.entered = entered
        self.release = release
        self.failure = failure

    @staticmethod
    def _candidate(lemma: str, pos: str, morphology: dict[str, str] | None = None) -> LemmaCandidate:
        return LemmaCandidate(
            lemma=lemma,
            normalized_lemma=normalize_lookup(lemma),
            pos=pos,
            morphology=morphology or {},
            source_id=FakeAnalyzer.analyzer_id,
            source_version=FakeAnalyzer.implementation_version,
            confidence=None,
            confidence_basis="stanza_does_not_report_confidence",
        )

    def _word_evidence(
        self, surface: str
    ) -> tuple[tuple[LemmaCandidate, ...], str | None, str | None, dict[str, str], ResolutionState, AmbiguityState]:
        normalized = normalize_lookup(surface)
        if normalized == "tvetydig":
            candidates = (
                self._candidate("tvetydig", "ADJ"),
                self._candidate("tvetydighet", "NOUN"),
            )
            return candidates, None, None, {}, ResolutionState.AMBIGUOUS, AmbiguityState.AMBIGUOUS
        if normalized == "xyzzy":
            return (), None, None, {}, ResolutionState.UNRESOLVED, AmbiguityState.NOT_REPORTED
        if self.variant == "changed" and normalized in {"jobb", "jobben", "jobber", "jobbene"}:
            lemma, pos, morphology = "arbeid", "NOUN", {"Number": "Sing"}
        elif normalized in {"jobb", "jobben", "jobber", "jobbene"}:
            lemma, pos, morphology = "jobb", "NOUN", {"Number": "Plur"} if normalized == "jobbene" else {}
        else:
            lemma, pos, morphology = normalized, "NOUN", {}
        candidate = self._candidate(lemma, pos, morphology)
        return (
            (candidate,),
            lemma,
            pos,
            morphology,
            ResolutionState.MODEL_SELECTED,
            AmbiguityState.NOT_REPORTED,
        )

    def analyze(self, text: str, *, language_code: str, options: Any = None) -> AnalysisDocument:
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(timeout=10)
        if self.failure is not None:
            raise self.failure

        tokens: list[AnalyzedToken] = []
        for match in TOKEN_RE.finditer(text):
            surface = match.group(0)
            kind = classify_token(surface)
            if kind is TokenKind.WORD:
                candidates, selected, pos, morphology, resolution, ambiguity = self._word_evidence(surface)
                normalized_lookup = normalize_lookup(surface)
            else:
                candidates, selected, pos, morphology = (), None, None, {}
                resolution = ResolutionState.NOT_APPLICABLE
                ambiguity = AmbiguityState.NOT_REPORTED
                normalized_lookup = None
            tokens.append(
                AnalyzedToken(
                    surface=surface,
                    start=match.start(),
                    end=match.end(),
                    kind=kind,
                    normalized_lookup=normalized_lookup,
                    lemma_candidates=candidates,
                    selected_lemma=selected,
                    pos=pos,
                    morphology=morphology,
                    resolution_state=resolution,
                    ambiguity_state=ambiguity,
                    lexical_status=LexicalStatus.NOT_ASSESSED,
                    confidence=None,
                    confidence_basis="stanza_does_not_report_confidence",
                    provenance="fake-offline-stanza-evidence",
                )
            )
        provenance = AnalyzerProvenance(
            analyzer_id=self.analyzer_id,
            implementation_version=self.implementation_version,
            package_name="stanza",
            package_version="1.14.0",
            model_package="bokmaal-test",
            model_version="stanza-resources-1.14.0",
            model_fingerprint="sha256:" + "1" * 64,
            processors=("tokenize", "pos", "lemma"),
            execution_mode="offline",
        )
        document = AnalysisDocument(
            language_code=language_code,
            original_text=text,
            original_text_fingerprint=text_fingerprint(text),
            analyzer=provenance,
            sentences=(AnalyzedSentence(0, len(text), text, tuple(tokens)),),
        )
        document.validate()
        return document


class FakeFrequencyProvider:
    provider_id = "wordfreq"
    provider_version = "3.1.1-test"
    metric = "ZIPF_FREQUENCY"

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.scores = scores or {}
        self.calls: list[tuple[str, str]] = []

    def lookup(self, term: str, *, language_code: str) -> FrequencyResult | None:
        self.calls.append((term, language_code))
        score = self.scores.get(term, 5.0)
        return FrequencyResult(
            language_code=language_code,
            lookup=term,
            metric=self.metric,
            score=score,
            rank=None,
            source=ReferenceSource(
                source_id=self.provider_id,
                source_version=self.provider_version,
                retrieval_or_import_version="fake-runtime/v1",
            ),
        )


def registry_for(analyzer: FakeAnalyzer) -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    registry.register(analyzer.analyzer_id, analyzer.implementation_version, lambda: analyzer)
    return registry


def wait_for_job(service: Any, job_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get_analysis_job(job_id)["data"]["job"]
        if job["state"] not in {"QUEUED", "RUNNING"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"language job {job_id} did not reach a terminal state")

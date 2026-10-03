"""Explicitly offline Stanza adapter for Norwegian Bokmål.

The adapter never calls Stanza's model downloader. Pipeline construction always
uses ``DownloadMethod.NONE`` so missing resources are a visible health/error
state instead of a network side effect.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping

from .base import (
    AnalysisOptions,
    AnalyzerHealth,
    AnalyzerUnavailableError,
    UnsupportedLanguageError,
    normalize_lookup,
)
from ..schemas import (
    AmbiguityState,
    AnalysisDocument,
    AnalyzedSentence,
    AnalyzedToken,
    AnalyzerHealthState,
    AnalyzerProvenance,
    LemmaCandidate,
    LexicalStatus,
    ResolutionState,
    SchemaValidationError,
    TokenComponent,
    TokenKind,
    text_fingerprint,
)


ANALYZER_ID = "stanza-nb-bokmaal"
IMPLEMENTATION_VERSION = "1.0.0"
LANGUAGE_CODE = "nb"
PROCESSOR_PACKAGES: dict[str, str] = {
    "tokenize": "bokmaal",
    "pos": "bokmaal_charlm",
    "lemma": "bokmaal_nocharlm",
}
DEPENDENCY_PACKAGES: dict[str, str] = {
    "pretrain": "conll17",
    "forward_charlm": "conll17",
    "backward_charlm": "conll17",
}

_URL_RE = re.compile(r"(?i)^(?:https?://|www\.)\S+$")
_NUMBER_RE = re.compile(r"^\d+(?:[.,:/-]\d+)*[.,]?$")


def _parse_morphology(features: str | None) -> dict[str, str]:
    if not features or features == "_":
        return {}
    result: dict[str, str] = {}
    for item in features.split("|"):
        key, separator, value = item.partition("=")
        if separator and key and value:
            result[key] = value
    return result


def classify_token(surface: str) -> TokenKind:
    if _URL_RE.match(surface):
        return TokenKind.URL
    if _NUMBER_RE.match(surface):
        return TokenKind.NUMBER
    categories = [unicodedata.category(character) for character in surface]
    if categories and all(category.startswith("P") for category in categories):
        return TokenKind.PUNCTUATION
    if any(category == "So" for category in categories):
        return TokenKind.EMOJI
    if categories and all(category.startswith("S") for category in categories):
        return TokenKind.SYMBOL
    if any(category.startswith(("L", "M")) for category in categories):
        return TokenKind.WORD
    return TokenKind.OTHER


def _canonicalize_model_lemma(
    lemma: str, pos: str | None, morphology: Mapping[str, str]
) -> str:
    """Apply the Bokmål display policy without altering proper names/abbreviations."""

    if pos == "PROPN" or morphology.get("Abbr") == "Yes":
        return unicodedata.normalize("NFC", lemma)
    return normalize_lookup(lemma)


class NorwegianBokmalStanzaAnalyzer:
    analyzer_id = ANALYZER_ID
    implementation_version = IMPLEMENTATION_VERSION

    @property
    def runtime_loaded(self) -> bool:
        return self._pipeline is not None

    def __init__(
        self,
        *,
        model_dir: str | Path | None = None,
        pipeline_factory: Any | None = None,
    ) -> None:
        self._configured_model_dir = Path(model_dir) if model_dir is not None else None
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None
        self._pipeline_options: AnalysisOptions | None = None

    @staticmethod
    def _stanza_modules() -> tuple[Any, Any, Any]:
        stanza = importlib.import_module("stanza")
        pipeline_core = importlib.import_module("stanza.pipeline.core")
        resource_common = importlib.import_module("stanza.resources.common")
        return stanza, pipeline_core, resource_common

    def _model_dir(self, resource_common: Any) -> Path:
        if self._configured_model_dir is not None:
            return self._configured_model_dir
        configured = os.environ.get("LANGUAGE_STANZA_MODEL_DIR", "").strip()
        if configured:
            return Path(configured)
        return Path(resource_common.DEFAULT_MODEL_DIR)

    @staticmethod
    def _package_version() -> str | None:
        try:
            return importlib.metadata.version("stanza")
        except importlib.metadata.PackageNotFoundError:
            return None

    def _resource_manifest(
        self, resource_common: Any
    ) -> tuple[Path, str, str | None, list[dict[str, str]], list[str]]:
        model_dir = self._model_dir(resource_common)
        resource_version = str(getattr(resource_common, "DEFAULT_RESOURCES_VERSION", "unknown"))
        resources_path = model_dir / "resources.json"
        if not resources_path.is_file():
            return model_dir, resource_version, None, [], [str(resources_path)]

        try:
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AnalyzerUnavailableError(
                f"Stanza resource manifest is unreadable: {resources_path}", cause=exc
            ) from exc

        language_resources = resources.get(LANGUAGE_CODE, {})
        selections = {**PROCESSOR_PACKAGES, **DEPENDENCY_PACKAGES}
        manifest: list[dict[str, str]] = []
        missing: list[str] = []
        for processor, package in selections.items():
            metadata = language_resources.get(processor, {}).get(package)
            model_path = model_dir / LANGUAGE_CODE / processor / f"{package}.pt"
            if not isinstance(metadata, dict) or not model_path.is_file():
                missing.append(str(model_path))
                continue
            manifest.append(
                {
                    "processor": processor,
                    "package": package,
                    "md5": str(metadata.get("md5", "unknown")),
                }
            )

        manifest.sort(key=lambda item: (item["processor"], item["package"]))
        fingerprint = None
        if manifest:
            encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
            fingerprint = "sha256:" + hashlib.sha256(encoded).hexdigest()
        return model_dir, resource_version, fingerprint, manifest, missing

    def _provenance(self) -> AnalyzerProvenance:
        try:
            _, _, resource_common = self._stanza_modules()
        except (ImportError, ModuleNotFoundError) as exc:
            raise AnalyzerUnavailableError("Stanza is not installed", cause=exc) from exc
        package_version = self._package_version()
        if not package_version:
            raise AnalyzerUnavailableError("The installed Stanza package has no detectable version")
        _, resource_version, fingerprint, _, missing = self._resource_manifest(resource_common)
        if missing:
            raise AnalyzerUnavailableError(
                "Required Bokmål Stanza resources are missing. Run the explicit setup command "
                "documented in docs/LANGUAGE_DATA_SOURCES.md."
            )
        package_description = ";".join(
            f"{processor}={package}" for processor, package in PROCESSOR_PACKAGES.items()
        )
        return AnalyzerProvenance(
            analyzer_id=self.analyzer_id,
            implementation_version=self.implementation_version,
            package_name="stanza",
            package_version=package_version,
            model_package=package_description,
            model_version=f"stanza-resources-{resource_version}",
            model_fingerprint=fingerprint,
            processors=tuple(PROCESSOR_PACKAGES),
            execution_mode="offline",
        )

    def _ensure_pipeline(self, options: AnalysisOptions) -> Any:
        if self._pipeline is not None:
            if self._pipeline_options != options:
                raise ValueError("one analyzer instance cannot switch pipeline options")
            return self._pipeline

        try:
            stanza, pipeline_core, resource_common = self._stanza_modules()
            model_dir = self._model_dir(resource_common)
            factory = self._pipeline_factory or stanza.Pipeline
            self._pipeline = factory(
                lang=LANGUAGE_CODE,
                dir=str(model_dir),
                package=None,
                processors=dict(PROCESSOR_PACKAGES),
                download_method=pipeline_core.DownloadMethod.NONE,
                use_gpu=options.use_gpu,
                verbose=False,
            )
            self._pipeline_options = options
            return self._pipeline
        except AnalyzerUnavailableError:
            raise
        except Exception as exc:
            raise AnalyzerUnavailableError(
                "The offline Bokmål Stanza pipeline could not be loaded; no download was attempted",
                cause=exc,
            ) from exc

    def health(self, *, verify_load: bool = False) -> AnalyzerHealth:
        package_version = self._package_version()
        if package_version is None:
            return AnalyzerHealth(
                state=AnalyzerHealthState.UNAVAILABLE,
                analyzer_id=self.analyzer_id,
                package_version=None,
                model_version=None,
                processors=tuple(PROCESSOR_PACKAGES),
                details={"packageAvailable": False, "modelAvailable": False},
                guidance="Install requirements-language.txt; this diagnostic never installs packages.",
            )

        try:
            _, _, resource_common = self._stanza_modules()
            model_dir, resource_version, fingerprint, manifest, missing = self._resource_manifest(
                resource_common
            )
        except AnalyzerUnavailableError as exc:
            return AnalyzerHealth(
                state=AnalyzerHealthState.ERROR,
                analyzer_id=self.analyzer_id,
                package_version=package_version,
                model_version=None,
                processors=tuple(PROCESSOR_PACKAGES),
                details={"packageAvailable": True, "modelAvailable": False, "error": str(exc)},
                guidance="Repair or explicitly provision the Stanza model directory.",
            )

        if missing:
            return AnalyzerHealth(
                state=AnalyzerHealthState.UNAVAILABLE,
                analyzer_id=self.analyzer_id,
                package_version=package_version,
                model_version=f"stanza-resources-{resource_version}",
                processors=tuple(PROCESSOR_PACKAGES),
                details={
                    "packageAvailable": True,
                    "modelAvailable": False,
                    "modelDir": str(model_dir),
                    "missingResourceCount": len(missing),
                },
                guidance=(
                    "Explicitly provision nb tokenize,pos,lemma resources; the runtime analyzer "
                    "will not download them."
                ),
            )

        if verify_load:
            try:
                self._ensure_pipeline(AnalysisOptions())
            except AnalyzerUnavailableError as exc:
                return AnalyzerHealth(
                    state=AnalyzerHealthState.ERROR,
                    analyzer_id=self.analyzer_id,
                    package_version=package_version,
                    model_version=f"stanza-resources-{resource_version}",
                    processors=tuple(PROCESSOR_PACKAGES),
                    details={
                        "packageAvailable": True,
                        "modelAvailable": True,
                        "modelLoadVerified": False,
                        "error": str(exc),
                    },
                    guidance="Review the local Stanza/PyTorch error; no download was attempted.",
                )

        return AnalyzerHealth(
            state=AnalyzerHealthState.AVAILABLE,
            analyzer_id=self.analyzer_id,
            package_version=package_version,
            model_version=f"stanza-resources-{resource_version}",
            processors=tuple(PROCESSOR_PACKAGES),
            details={
                "packageAvailable": True,
                "modelAvailable": True,
                "modelLoadVerified": verify_load,
                "modelDir": str(model_dir),
                "modelFingerprint": fingerprint,
                "resourceManifest": manifest,
                "downloadMethod": "NONE",
                "mwtRequired": False,
                "mwtReason": "Stanza resources 1.14.0 publish no nb MWT model",
            },
        )

    def analyze(
        self,
        text: str,
        *,
        language_code: str,
        options: AnalysisOptions | None = None,
    ) -> AnalysisDocument:
        if language_code != LANGUAGE_CODE:
            raise UnsupportedLanguageError(
                f"{self.analyzer_id} supports {LANGUAGE_CODE!r}, not {language_code!r}"
            )
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        options = options or AnalysisOptions()
        provenance = self._provenance()
        pipeline = self._ensure_pipeline(options)

        try:
            stanza_document = pipeline(text)
            sentences = tuple(
                self._convert_sentence(sentence, text, provenance, options)
                for sentence in stanza_document.sentences
                if sentence.tokens
            )
        except SchemaValidationError:
            raise
        except Exception as exc:
            raise AnalyzerUnavailableError("Bokmål analysis failed", cause=exc) from exc

        document = AnalysisDocument(
            language_code=language_code,
            original_text=text,
            original_text_fingerprint=text_fingerprint(text),
            analyzer=provenance,
            sentences=sentences,
        )
        document.validate()
        return document

    def _convert_sentence(
        self,
        sentence: Any,
        original_text: str,
        provenance: AnalyzerProvenance,
        options: AnalysisOptions,
    ) -> AnalyzedSentence:
        tokens = tuple(
            self._convert_token(token, provenance, options) for token in sentence.tokens
        )
        start = tokens[0].start
        end = tokens[-1].end
        return AnalyzedSentence(
            start=start,
            end=end,
            text=original_text[start:end],
            tokens=tokens,
        )

    def _convert_token(
        self,
        token: Any,
        provenance: AnalyzerProvenance,
        options: AnalysisOptions,
    ) -> AnalyzedToken:
        if token.start_char is None or token.end_char is None:
            raise SchemaValidationError(f"Stanza omitted offsets for token {token.text!r}")
        surface = str(token.text)
        kind = classify_token(surface)
        normalized = normalize_lookup(surface) if kind is TokenKind.WORD else None
        words = tuple(token.words)
        components = tuple(
            TokenComponent(
                text=str(word.text),
                lemma=str(word.lemma) if word.lemma not in (None, "_") else None,
                pos=str(word.upos) if word.upos not in (None, "_") else None,
                morphology=_parse_morphology(word.feats) if options.include_morphology else {},
            )
            for word in words
        )

        candidates: tuple[LemmaCandidate, ...] = ()
        selected_lemma: str | None = None
        pos: str | None = None
        morphology: Mapping[str, str] = {}
        resolution = ResolutionState.NOT_APPLICABLE
        ambiguity = AmbiguityState.NOT_APPLICABLE
        lexical_status = LexicalStatus.NOT_APPLICABLE

        if kind is TokenKind.WORD:
            lexical_status = LexicalStatus.NOT_ASSESSED
            ambiguity = AmbiguityState.NOT_REPORTED
            if len(words) == 1:
                word = words[0]
                raw_lemma = str(word.lemma) if word.lemma not in (None, "_") else None
                pos = str(word.upos) if word.upos not in (None, "_") else None
                morphology = _parse_morphology(word.feats) if options.include_morphology else {}
                lemma = (
                    _canonicalize_model_lemma(raw_lemma, pos, morphology)
                    if raw_lemma is not None
                    else None
                )
                if lemma:
                    candidates = (
                        LemmaCandidate(
                            lemma=lemma,
                            normalized_lemma=normalize_lookup(lemma),
                            pos=pos,
                            morphology=morphology,
                            source_id=provenance.analyzer_id,
                            source_version=(
                                f"{provenance.package_version}/{provenance.model_version}"
                            ),
                            confidence=None,
                            confidence_basis="stanza_does_not_expose_token_probability",
                        ),
                    )
                if lemma and pos != "X":
                    selected_lemma = lemma
                    resolution = ResolutionState.MODEL_SELECTED
                else:
                    resolution = ResolutionState.UNRESOLVED
            else:
                resolution = ResolutionState.UNRESOLVED

        return AnalyzedToken(
            surface=surface,
            start=int(token.start_char),
            end=int(token.end_char),
            kind=kind,
            normalized_lookup=normalized,
            lemma_candidates=candidates,
            selected_lemma=selected_lemma,
            pos=pos,
            morphology=morphology,
            resolution_state=resolution,
            ambiguity_state=ambiguity,
            lexical_status=lexical_status,
            confidence=None,
            confidence_basis=(
                "stanza_does_not_expose_token_probability"
                if kind is TokenKind.WORD
                else "not_applicable"
            ),
            provenance=(
                "stanza_contextual_model;ambiguity=not_reported;lexicon=not_assessed"
                if kind is TokenKind.WORD
                else "surface_classifier"
            ),
            components=components if len(components) > 1 else (),
        )

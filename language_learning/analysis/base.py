"""Generic analyzer boundary with no Stanza-specific types."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Any, Mapping, Protocol

from ..schemas import AnalysisDocument, AnalyzerHealthState


@dataclass(frozen=True)
class AnalysisOptions:
    include_morphology: bool = True
    use_gpu: bool = False


@dataclass(frozen=True)
class AnalyzerHealth:
    state: AnalyzerHealthState
    analyzer_id: str
    package_version: str | None
    model_version: str | None
    processors: tuple[str, ...]
    details: Mapping[str, Any]
    guidance: str | None = None


class AnalyzerUnavailableError(RuntimeError):
    code = "analyzer_unavailable"

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class UnsupportedLanguageError(ValueError):
    code = "unsupported_language"


class LanguageAnalyzer(Protocol):
    analyzer_id: str
    implementation_version: str

    def health(self, *, verify_load: bool = False) -> AnalyzerHealth: ...

    def analyze(
        self,
        text: str,
        *,
        language_code: str,
        options: AnalysisOptions | None = None,
    ) -> AnalysisDocument: ...


_LOOKUP_TRANSLATION = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "‛": "'",
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
    }
)


def normalize_lookup(value: str) -> str:
    """Normalize only lookup metadata; never use this for displayed source text."""

    return unicodedata.normalize("NFC", value).translate(_LOOKUP_TRANSLATION).casefold()


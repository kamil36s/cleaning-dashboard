"""Language-specific analyzers implementing the generic Phase 0 contract."""

from .base import AnalysisOptions, AnalyzerUnavailableError, LanguageAnalyzer
from .norwegian_bokmal import NorwegianBokmalStanzaAnalyzer
from .registry import AnalyzerRegistry, build_default_registry

__all__ = [
    "AnalysisOptions",
    "AnalyzerUnavailableError",
    "LanguageAnalyzer",
    "NorwegianBokmalStanzaAnalyzer",
    "AnalyzerRegistry",
    "build_default_registry",
]


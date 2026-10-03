"""Explicit, lazy analyzer registry for persisted Language jobs."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

from .base import LanguageAnalyzer, UnsupportedLanguageError
from .norwegian_bokmal import (
    ANALYZER_ID as BOKMAL_ANALYZER_ID,
    IMPLEMENTATION_VERSION as BOKMAL_ANALYZER_VERSION,
    NorwegianBokmalStanzaAnalyzer,
)


@dataclass(frozen=True)
class AnalyzerRegistration:
    analyzer_id: str
    implementation_version: str
    factory: Callable[[], LanguageAnalyzer]


class AnalyzerRegistry:
    """Maps stable analyzer IDs to one lazily constructed, reusable instance."""

    def __init__(self) -> None:
        self._registrations: dict[str, AnalyzerRegistration] = {}
        self._instances: dict[str, LanguageAnalyzer] = {}
        self._lock = threading.RLock()

    def register(
        self,
        analyzer_id: str,
        implementation_version: str,
        factory: Callable[[], LanguageAnalyzer],
    ) -> None:
        registration = AnalyzerRegistration(analyzer_id, implementation_version, factory)
        with self._lock:
            existing = self._registrations.get(analyzer_id)
            if existing and existing != registration:
                raise ValueError(f"analyzer {analyzer_id!r} is already registered")
            self._registrations[analyzer_id] = registration

    def describe(self, analyzer_id: str) -> dict[str, str | bool]:
        with self._lock:
            registration = self._registrations.get(analyzer_id)
            if registration is None:
                raise UnsupportedLanguageError(f"analyzer {analyzer_id!r} is not registered")
            instance = self._instances.get(analyzer_id)
            return {
                "analyzerId": registration.analyzer_id,
                "implementationVersion": registration.implementation_version,
                "loaded": instance is not None,
                "pipelineLoaded": bool(
                    getattr(instance, "runtime_loaded", False)
                ) if instance is not None else False,
            }

    def get(self, analyzer_id: str) -> LanguageAnalyzer:
        with self._lock:
            registration = self._registrations.get(analyzer_id)
            if registration is None:
                raise UnsupportedLanguageError(f"analyzer {analyzer_id!r} is not registered")
            analyzer = self._instances.get(analyzer_id)
            if analyzer is None:
                analyzer = registration.factory()
                if analyzer.analyzer_id != analyzer_id:
                    raise ValueError("analyzer factory returned a mismatched analyzer ID")
                if analyzer.implementation_version != registration.implementation_version:
                    raise ValueError("analyzer factory returned a mismatched implementation version")
                self._instances[analyzer_id] = analyzer
            return analyzer


def build_default_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    registry.register(
        BOKMAL_ANALYZER_ID,
        BOKMAL_ANALYZER_VERSION,
        NorwegianBokmalStanzaAnalyzer,
    )
    return registry


__all__ = ["AnalyzerRegistration", "AnalyzerRegistry", "build_default_registry"]

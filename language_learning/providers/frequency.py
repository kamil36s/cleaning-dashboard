"""Zipf-only wordfreq adapter; it never fabricates exact frequency ranks."""

from __future__ import annotations

import importlib
import importlib.metadata

from ..reference import FrequencyResult, ReferenceSource


class WordfreqFrequencyProvider:
    provider_id = "wordfreq"
    metric = "ZIPF_FREQUENCY"

    def __init__(self, *, package_version: str | None = None) -> None:
        self.provider_version = package_version or importlib.metadata.version("wordfreq")

    def lookup(self, term: str, *, language_code: str) -> FrequencyResult | None:
        if language_code != "nb":
            return None
        normalized = str(term or "").strip()
        if not normalized:
            return None
        module = importlib.import_module("wordfreq")
        score = float(module.zipf_frequency(normalized, language_code))
        return FrequencyResult(
            language_code=language_code,
            lookup=normalized,
            metric=self.metric,
            score=score,
            rank=None,
            source=ReferenceSource(
                source_id=self.provider_id,
                source_version=self.provider_version,
                retrieval_or_import_version=f"wordfreq-{self.provider_version}",
            ),
        )


__all__ = ["WordfreqFrequencyProvider"]

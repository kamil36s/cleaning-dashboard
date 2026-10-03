"""Shared deterministic and optional AI Job Hunt extraction foundations."""

from .deterministic import (
    EXTRACTOR_VERSIONS,
    OUTPUT_SCHEMA_VERSION,
    ExtractionBatch,
    FactCandidate,
    extract_batches,
)
from .normalization import NORMALIZATION_VERSION, concept_match

__all__ = [
    "EXTRACTOR_VERSIONS",
    "OUTPUT_SCHEMA_VERSION",
    "ExtractionBatch",
    "FactCandidate",
    "NORMALIZATION_VERSION",
    "concept_match",
    "extract_batches",
]

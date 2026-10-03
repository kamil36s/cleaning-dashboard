"""Isolated, rebuildable Norwegian reference-lexicon core.

This package never imports or mutates the user LanguageStore. Runtime access
is independently configured and read-only; user data remains in the main
Language database (currently schema v8).
"""

from .config import ReferencePaths, resolve_reference_paths
from .models import (
    ReferenceLexicalUnit,
    ReferenceSourceRecord,
    ResolverCandidate,
    ResolverResult,
    ResolverStatus,
    VocabularyLemmaIdentity,
    make_stable_key,
    normalize_reference_lookup,
)
from .resolver import ReferenceResolver
from .service import ReferenceLexiconService
from .store import REFERENCE_SCHEMA_VERSION, ReferenceStore

__all__ = [
    "REFERENCE_SCHEMA_VERSION",
    "ReferenceLexicalUnit",
    "ReferenceLexiconService",
    "ReferencePaths",
    "ReferenceResolver",
    "ReferenceSourceRecord",
    "ReferenceStore",
    "ResolverCandidate",
    "ResolverResult",
    "ResolverStatus",
    "VocabularyLemmaIdentity",
    "make_stable_key",
    "normalize_reference_lookup",
    "resolve_reference_paths",
]

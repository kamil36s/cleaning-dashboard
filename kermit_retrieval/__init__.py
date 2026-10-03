"""Bounded, read-only retrieval over the Phase 3 Kermit snapshot."""

from .service import RetrievalError, retrieve

__all__ = ("RetrievalError", "retrieve")

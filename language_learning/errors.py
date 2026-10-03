"""Stable, non-sensitive errors for the Language Learning API."""

from __future__ import annotations

from typing import Any


class LanguageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "language_error",
        status: int = 400,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = list(details or [])

    def as_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": str(self),
            "code": self.code,
            "details": self.details,
        }


class LanguageValidationError(LanguageError):
    def __init__(self, message: str, *, code: str = "invalid_language_request", details=None):
        super().__init__(message, code=code, status=400, details=details)


class LanguageNotFoundError(LanguageError):
    def __init__(self, message: str, *, code: str = "language_not_found"):
        super().__init__(message, code=code, status=404)


class LanguageConflictError(LanguageError):
    def __init__(self, message: str, *, code: str = "language_conflict", details=None):
        super().__init__(message, code=code, status=409, details=details)


class LanguageStorageError(LanguageError):
    def __init__(self, message: str = "Language storage operation failed"):
        super().__init__(message, code="language_storage_error", status=500)

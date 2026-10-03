"""Versioned Phase 10 Listening policies and bounded event validation."""

from __future__ import annotations

from typing import Any

from .errors import LanguageValidationError


LISTENING_ACTIVITY_POLICY_VERSION = "language.listening-activity/v2"
LISTENING_EXPOSURE_POLICY_VERSION = "language.listening-exposure/v2"
LISTENING_COMPLETION_POLICY_VERSION = "language.listening-completion/v1"
LISTENING_QUALIFICATION_THRESHOLD = 0.8
LISTENING_EVENT_MAX_MS = 600_000
LISTENING_EXPOSURE_DAILY_SENTENCE_CAP = 1

LISTENING_MODES = frozenset({"READ_LISTEN", "LISTENING_ONLY"})
LISTENING_OUTCOMES = frozenset({"ENDED", "CANCELLED", "ERROR"})
LISTENING_PLAYBACK_SOURCES = frozenset({"BROWSER_TTS", "CLOUD_TTS", "AUTHENTIC_MEDIA"})


def validate_timing(active_ms: Any, duration_ms: Any) -> tuple[int, int | None, float]:
    if isinstance(active_ms, bool) or not isinstance(active_ms, int):
        raise LanguageValidationError("activeMs must be an integer", details=["activeMs"])
    if not 0 <= active_ms <= LISTENING_EVENT_MAX_MS:
        raise LanguageValidationError("activeMs is out of range", details=["activeMs"])
    if duration_ms is None:
        return active_ms, None, 0.0
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise LanguageValidationError("durationMs must be an integer", details=["durationMs"])
    if not 1 <= duration_ms <= LISTENING_EVENT_MAX_MS:
        raise LanguageValidationError("durationMs is out of range", details=["durationMs"])
    if active_ms > duration_ms + 2_000:
        raise LanguageValidationError(
            "activeMs cannot materially exceed durationMs", details=["activeMs", "durationMs"]
        )
    return active_ms, duration_ms, min(1.0, active_ms / duration_ms)


def qualifies_sentence_event(*, outcome: str, completion_ratio: float) -> bool:
    """Only a natural end at or above the explicit threshold is exposure eligible."""
    return outcome == "ENDED" and completion_ratio >= LISTENING_QUALIFICATION_THRESHOLD


def validate_playback_timing(
    active_ms: Any, duration_ms: Any, coverage_ms: Any = None,
) -> tuple[int, int, int | None, float]:
    """Validate actual active time separately from non-seeked interval coverage."""
    active, duration, _ = validate_timing(active_ms, duration_ms)
    coverage_value = active if coverage_ms is None else coverage_ms
    if isinstance(coverage_value, bool) or not isinstance(coverage_value, int):
        raise LanguageValidationError("coverageMs must be an integer", details=["coverageMs"])
    if not 0 <= coverage_value <= LISTENING_EVENT_MAX_MS:
        raise LanguageValidationError("coverageMs is out of range", details=["coverageMs"])
    if duration is not None and coverage_value > duration + 2_000:
        raise LanguageValidationError(
            "coverageMs cannot materially exceed durationMs", details=["coverageMs", "durationMs"]
        )
    ratio = min(1.0, coverage_value / duration) if duration else 0.0
    return active, coverage_value, duration, ratio


__all__ = [
    "LISTENING_ACTIVITY_POLICY_VERSION",
    "LISTENING_COMPLETION_POLICY_VERSION",
    "LISTENING_EVENT_MAX_MS",
    "LISTENING_EXPOSURE_DAILY_SENTENCE_CAP",
    "LISTENING_EXPOSURE_POLICY_VERSION",
    "LISTENING_MODES",
    "LISTENING_OUTCOMES",
    "LISTENING_PLAYBACK_SOURCES",
    "LISTENING_QUALIFICATION_THRESHOLD",
    "qualifies_sentence_event",
    "validate_playback_timing",
    "validate_timing",
]

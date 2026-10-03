"""Job Hunt domain constants and small transport models through Pack J."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LEGACY_STATUSES = frozenset({
    "new",
    "to_review",
    "worth_applying",
    "applied",
    "follow_up",
    "interview",
    "offer",
    "expired",
    "rejected",
    "archived",
})

APPLICATION_STATUSES = frozenset(LEGACY_STATUSES - {"expired"})
PRIORITIES = frozenset({"P1", "P2", "P3", "skip", "unknown"})
NEXT_ACTIONS = frozenset({
    "analyze",
    "tailor_cv",
    "apply",
    "follow_up",
    "prepare_interview",
    "ask_recruiter",
    "archive",
    "none",
})
EVENT_ORIGINS = frozenset({"migration", "user", "system"})
TRACK_STATUSES = frozenset({"exploring", "active", "paused", "archived"})
SEARCH_PROFILE_STATUSES = frozenset({"enabled", "paused", "archived"})
TRACK_ASSIGNMENT_ORIGINS = frozenset({"manual", "seed", "legacy_reviewed"})
PLANNED_SOURCE_KEYS = frozenset({
    "pracuj",
    "nofluffjobs",
    "olx",
    "nav",
    "finn",
    "alfred",
    "jobbnorge",
    "company_sites",
    "email_alerts",
})
EXTRACTION_STATUSES = frozenset({"running", "completed", "completed_with_warnings", "failed"})
FACT_STATES = frozenset({"explicit_positive", "explicit_negative", "derived", "inferred"})
REVIEW_STATES = frozenset({"open", "resolved", "dismissed"})
WORKER_JOB_TYPES = frozenset({
    "nav_feed_poll",
    "nav_fetch_listing",
    "extract_capture",
    "ai_extract_capture",
    "dedupe_scan_job",
    "pracuj_mail_poll",
    "pracuj_process_message",
    "evaluation_recompute",
    "jobbnorge_poll",
})
WORKER_STATES = frozenset({
    "queued",
    "running",
    "retry_wait",
    "completed",
    "failed",
    "cancelled",
})
OVERRIDE_FIELDS = frozenset({
    "title",
    "company",
    "location_city",
    "location_country",
    "work_model",
    "contract_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_tax_type",
})


class JobhuntError(Exception):
    """Expected validation, storage, or not-found error."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: str = "jobhunt_error",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = list(details or [])

    def as_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": str(self),
            "code": self.code,
            "details": self.details,
        }


@dataclass(frozen=True)
class MigrationSnapshot:
    schema_version: int
    idempotency_key: str
    offers: list[dict[str, Any]]
    match_settings: list[dict[str, Any]]
    fingerprint: str
    canonical_bytes: bytes

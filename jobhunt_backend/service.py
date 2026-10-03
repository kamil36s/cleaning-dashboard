"""Validation and orchestration for the durable Job Hunt core."""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any
import unicodedata
from urllib.parse import urlsplit
import uuid
from urllib.parse import urlunsplit

from .assessments import AssessmentManifestLoader, ManifestValidationError, score_assessment
from .dedupe import (
    DEDUPE_RULE_VERSION,
    MAX_COMPANY_BLOCK_CANDIDATES,
    MAX_URL_BLOCK_CANDIDATES,
    PUBLICATION_WINDOW_DAYS,
    build_job_key,
    compare_jobs,
    normalize_url,
)
from .evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATOR_VERSION,
    evaluate as evaluate_candidate,
    validate_policy,
)
from .extraction import (
    OUTPUT_SCHEMA_VERSION,
    NORMALIZATION_VERSION,
    ExtractionBatch,
    FactCandidate,
    concept_match,
    extract_batches,
)
from .extraction.ai import (
    AI_EXTRACTOR_VERSION,
    AI_RESPONSE_JSON_SCHEMA,
    AIExtractionRequest,
    AIProviderError,
    AISchemaError,
    GeminiAIExtractionProvider,
    MAX_RAW_AI_RESPONSE_BYTES,
    PROMPT_ID,
    PROMPT_VERSION,
    RESPONSE_SCHEMA_VERSION,
    SYSTEM_PROMPT,
    UnavailableAIProvider,
    build_user_prompt,
    enabled,
    float_setting,
    integer_setting,
    prepare_source_text,
    prompt_fingerprint,
    validate_ai_output,
)
from .ingestion import (
    JobbnorgeCollectionCoordinator,
    jobbnorge_extraction_batch,
    ManualImportAdapter,
    NavCollectionCoordinator,
    PracujMailCoordinator,
    RawArchive,
)
from .ingestion.archive import hash_file
from .sources.nav import NAV_INITIAL_FEED_PATH, NAV_SOURCE_ID, NavSourceAdapter
from .sources.jobbnorge import (
    JOBBNORGE_SOURCE_ID,
    JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION,
    JobbnorgeSourceAdapter,
)
from .sources.email_transport import ImapMailboxTransport, MailTransportError
from .sources.pracuj import (
    PRACUJ_PARSER_VERSION,
    PRACUJ_SOURCE_ID,
    PracujJobAlertAdapter,
)
from .models import (
    APPLICATION_STATUSES,
    LEGACY_STATUSES,
    NEXT_ACTIONS,
    PRIORITIES,
    PLANNED_SOURCE_KEYS,
    SEARCH_PROFILE_STATUSES,
    TRACK_ASSIGNMENT_ORIGINS,
    TRACK_STATUSES,
    OVERRIDE_FIELDS,
    REVIEW_STATES,
    JobhuntError,
    MigrationSnapshot,
)
from .analytics import JobhuntAnalyticsReadModel
from .career_intelligence import CareerIntelligenceReadModel
from .skill_intelligence import SkillIntelligenceReadModel
from .store import JobhuntStore


MIGRATION_SCHEMA_VERSION = 1
MAX_MIGRATION_BYTES = 4 * 1024 * 1024
MAX_LEGACY_OFFER_BYTES = 1024 * 1024
MAX_MIGRATION_OFFERS = 500
MAX_LOGO_BYTES = 512 * 1024
MAX_TEXT_BYTES = 512 * 1024
MAX_RAW_CAPTURE_BYTES = 1024 * 1024
RAW_MIME_EXTENSIONS = {
    "text/plain": ".txt",
    "text/html": ".html",
    "application/json": ".json",
}
RAW_FILE_EXTENSIONS = {
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
}
LISTING_STATES = frozenset({"active", "expired", "removed", "unknown"})

MATCH_SETTINGS_DEFAULTS = [
    {"id": "manual_qa", "label": "Manual QA", "weight": 10},
    {"id": "uat_iat", "label": "UAT/IAT", "weight": 10},
    {"id": "test_scenarios", "label": "Test scenarios/test cases", "weight": 10},
    {"id": "defect_management", "label": "Defect management", "weight": 10},
    {"id": "stakeholder_coordination", "label": "Client/stakeholder coordination", "weight": 10},
    {"id": "jira_alm_testrail", "label": "Jira/ALM/TestRail", "weight": 10},
    {"id": "api_testing", "label": "API testing", "weight": 8},
    {"id": "automation_path", "label": "Automation as development path", "weight": 7},
    {"id": "krakow_remote_hybrid", "label": "Krakow/remote/hybrid fit", "weight": 8},
    {"id": "uop", "label": "UoP", "weight": 7},
]

PROFILE_ORIGINS = frozenset({
    "manual_user", "assessment", "legacy_reviewed", "imported_record", "career_experiment",
})
PROFILE_FIELD_MAPS = {
    "experience": {
        "jobTitle": "job_title", "employer": "employer", "startDate": "start_date",
        "endDate": "end_date", "isCurrent": "is_current", "location": "location",
        "employmentType": "employment_type", "description": "description",
        "domains": "domains_json", "origin": "origin", "notes": "notes",
    },
    "education": {
        "institution": "institution", "fieldProgram": "field_program",
        "qualification": "qualification", "startDate": "start_date", "endDate": "end_date",
        "completionStatus": "completion_status", "origin": "origin", "notes": "notes",
    },
    "certifications": {
        "name": "name", "issuer": "issuer", "issuedDate": "issued_date",
        "expirationDate": "expiration_date", "credentialReference": "credential_reference",
        "origin": "origin", "notes": "notes",
    },
    "languages": {
        "languageName": "language_name", "proficiency": "proficiency",
        "proficiencyScheme": "proficiency_scheme", "confidence": "confidence",
        "origin": "origin", "notes": "notes",
    },
    "skills": {
        "displayName": "display_name", "normalizedKey": "normalized_key", "level": "level",
        "confidence": "confidence", "developmentInterest": "development_interest",
        "evidenceNotes": "evidence_notes", "origin": "origin",
    },
    "preferences": {
        "dimensionKey": "dimension_key", "value": "value_json", "importance": "importance",
        "confidence": "confidence", "origin": "origin", "notes": "notes",
    },
    "constraints": {
        "constraintKey": "constraint_key", "value": "value_json", "isHard": "is_hard",
        "origin": "origin", "notes": "notes",
    },
    "evidence": {
        "targetType": "target_type", "targetId": "target_id", "fieldName": "field_name",
        "origin": "origin", "sourceReference": "source_reference", "notes": "notes",
    },
}
PROFILE_REQUIRED_FIELDS = {
    "experience": {"jobTitle"}, "education": {"institution"},
    "certifications": {"name"}, "languages": {"languageName"},
    "skills": {"displayName"}, "preferences": {"dimensionKey", "value"},
    "constraints": {"constraintKey", "value"}, "evidence": {"targetType"},
}
ASSESSMENT_CATALOG = {
    "onet-interest-profiler-short-form": "O*NET® Interest Profiler Short Form",
    "ipip-50-big-five-markers": "Big Five — IPIP",
    "career-work-preferences": "Career Work Preferences",
}

LOGO_TYPES = {
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/webp": (".webp", b"RIFF"),
    "image/svg+xml": (".svg", None),
}

CREATE_FIELDS = {
    "id", "legacyId", "company", "role", "seniority", "location", "contract", "salary",
    "source", "branding", "companyLogoDataUrl", "expiresAt", "status", "applicationStatus",
    "sourceExpired",
    "priority", "nextAction", "match", "requirements", "analysis", "cv", "application",
    "notes", "originalText", "createdAt", "updatedAt", "evaluationSource",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, default: str = "", *, limit: int = 4096) -> str:
    result = str(value or "").strip()
    if not result:
        return default
    return result[:limit]


def _nullable_text(value: Any, *, limit: int = 4096) -> str | None:
    result = _text(value, limit=limit)
    return result or None


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _string_list(value: Any, *, limit: int = 200) -> list[str]:
    result = []
    for item in _list(value)[:limit]:
        text = _text(item, limit=500)
        if text:
            result.append(text)
    return result


def _valid_date(value: Any) -> str | None:
    text = _text(value, limit=10)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _valid_url(value: Any) -> str | None:
    text = _text(value, limit=2048)
    if not text:
        return None
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
    except ValueError:
        return None
    return text


def _match_category(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "strong_fit"
    if score >= 65:
        return "good_fit"
    if score >= 50:
        return "stretch"
    return "low_fit"


class JobhuntService:
    def __init__(
        self,
        database_path: str | Path,
        *,
        private_root: str | Path | None = None,
        ai_provider: Any | None = None,
        nav_adapter: Any | None = None,
        jobbnorge_adapter: Any | None = None,
        mail_transport: Any | None = None,
        environment: Any | None = None,
    ) -> None:
        database_path = Path(database_path)
        self.private_root = Path(private_root or database_path.parent / "jobhunt")
        self.assets_directory = self.private_root / "assets"
        self.recovery_directory = self.private_root / "backups"
        self.store = JobhuntStore(
            database_path,
            backup_directory=self.recovery_directory,
        )
        self.skill_intelligence_model = SkillIntelligenceReadModel(self.store)
        self.analytics_model = JobhuntAnalyticsReadModel(self.store)
        self.career_intelligence_model = CareerIntelligenceReadModel(
            self.store, self.analytics_model,
        )
        self.assessment_loader = AssessmentManifestLoader()
        self.raw_archive = RawArchive(self.private_root)
        self.manual_import_adapter = ManualImportAdapter(self.store, self.raw_archive)
        self.environment = environment if environment is not None else os.environ
        self.worker: Any | None = None
        self.nav_adapter_injected = nav_adapter is not None
        self.nav_adapter = nav_adapter
        self.jobbnorge_adapter_injected = jobbnorge_adapter is not None
        self.jobbnorge_adapter = jobbnorge_adapter
        self.mail_transport_injected = mail_transport is not None
        self.mail_transport = mail_transport
        self.ai_provider_injected = ai_provider is not None
        self.ai_provider = ai_provider
        self._configure_ai_runtime()
        self._configure_nav_runtime()
        self._configure_jobbnorge_runtime()
        self._configure_pracuj_runtime()

    def _configure_nav_runtime(self) -> None:
        if not self.nav_adapter_injected:
            self.nav_adapter = NavSourceAdapter(
                environment=self.environment,
                timeout_seconds=float_setting(
                    self.environment, "JOBHUNT_NAV_TIMEOUT_SECONDS", 20.0,
                    minimum=1.0, maximum=120.0,
                ),
            )
        self.nav_coordinator = NavCollectionCoordinator(
            store=self.store,
            archive=self.raw_archive,
            adapter=self.nav_adapter,
            detail_budget=integer_setting(
                self.environment, "JOBHUNT_NAV_DETAIL_BUDGET", 100,
                minimum=1, maximum=500,
            ),
            bootstrap_days=integer_setting(
                self.environment, "JOBHUNT_NAV_BOOTSTRAP_DAYS", 185,
                minimum=1, maximum=366,
            ),
        )

    def _configure_pracuj_runtime(self) -> None:
        if not self.mail_transport_injected:
            self.mail_transport = ImapMailboxTransport(
                environment=self.environment,
                timeout_seconds=float_setting(
                    self.environment, "JOBHUNT_PRACUJ_IMAP_TIMEOUT_SECONDS", 30.0,
                    minimum=1.0, maximum=120.0,
                ),
            )
        self.pracuj_adapter = PracujJobAlertAdapter()
        self.pracuj_coordinator = PracujMailCoordinator(
            store=self.store,
            archive=self.raw_archive,
            transport=self.mail_transport,
            adapter=self.pracuj_adapter,
            bootstrap_days=integer_setting(
                self.environment, "JOBHUNT_PRACUJ_BOOTSTRAP_DAYS", 30,
                minimum=1, maximum=90,
            ),
            bootstrap_messages=integer_setting(
                self.environment, "JOBHUNT_PRACUJ_BOOTSTRAP_MAX_MESSAGES", 500,
                minimum=1, maximum=500,
            ),
        )

    def _configure_jobbnorge_runtime(self) -> None:
        if not self.jobbnorge_adapter_injected:
            self.jobbnorge_adapter = JobbnorgeSourceAdapter(
                timeout_seconds=float_setting(
                    self.environment, "JOBHUNT_JOBBNORGE_TIMEOUT_SECONDS", 20.0,
                    minimum=1.0, maximum=120.0,
                ),
                max_response_bytes=integer_setting(
                    self.environment, "JOBHUNT_JOBBNORGE_MAX_RESPONSE_BYTES", 1024 * 1024,
                    minimum=1024, maximum=8 * 1024 * 1024,
                ),
            )
        self.jobbnorge_coordinator = JobbnorgeCollectionCoordinator(
            store=self.store,
            archive=self.raw_archive,
            adapter=self.jobbnorge_adapter,
            page_size=integer_setting(
                self.environment, "JOBHUNT_JOBBNORGE_PAGE_SIZE", 50,
                minimum=1, maximum=100,
            ),
            max_pages=integer_setting(
                self.environment, "JOBHUNT_JOBBNORGE_MAX_PAGES", 3,
                minimum=1, maximum=20,
            ),
            job_budget=integer_setting(
                self.environment, "JOBHUNT_JOBBNORGE_JOB_BUDGET", 300,
                minimum=1, maximum=2000,
            ),
            cycle_byte_budget=integer_setting(
                self.environment, "JOBHUNT_JOBBNORGE_CYCLE_BYTE_BUDGET", 4 * 1024 * 1024,
                minimum=1024, maximum=32 * 1024 * 1024,
            ),
        )

    def _configure_ai_runtime(self) -> None:
        configured_provider = str(self.environment.get("JOBHUNT_AI_PROVIDER") or "gemini").strip().casefold()
        if not self.ai_provider_injected and configured_provider == "gemini":
            self.ai_provider = GeminiAIExtractionProvider(
                environment=self.environment,
                timeout_seconds=float_setting(
                    self.environment, "JOBHUNT_AI_TIMEOUT_SECONDS", 45.0,
                    minimum=1.0, maximum=120.0,
                ),
            )
        elif not self.ai_provider_injected:
            self.ai_provider = UnavailableAIProvider(
                provider_key=configured_provider or "none",
                model_id=str(self.environment.get("JOBHUNT_AI_MODEL") or ""),
                reason="PROVIDER_NOT_SUPPORTED",
            )
        self.ai_max_source_chars = integer_setting(
            self.environment, "JOBHUNT_AI_MAX_SOURCE_CHARS", 60000,
            minimum=1000, maximum=250000,
        )
        self.ai_max_context_facts = integer_setting(
            self.environment, "JOBHUNT_AI_MAX_CONTEXT_FACTS", 100,
            minimum=0, maximum=300,
        )
        self.ai_max_output_tokens = integer_setting(
            self.environment, "JOBHUNT_AI_MAX_OUTPUT_TOKENS", 4096,
            minimum=256, maximum=8192,
        )
        self.ai_max_attempts = 1 + integer_setting(
            self.environment, "JOBHUNT_AI_MAX_RETRIES", 1,
            minimum=0, maximum=2,
        )
        self.ai_retry_delay_seconds = float_setting(
            self.environment, "JOBHUNT_AI_RETRY_DELAY_SECONDS", 0.2,
            minimum=0.0, maximum=5.0,
        )
        self.ai_daily_call_limit = integer_setting(
            self.environment, "JOBHUNT_AI_DAILY_CALL_LIMIT", 0,
            minimum=0, maximum=100000,
        )
        self.ai_daily_token_limit = integer_setting(
            self.environment, "JOBHUNT_AI_DAILY_TOKEN_LIMIT", 0,
            minimum=0, maximum=1000000000,
        )
        self.ai_prompt_fingerprint = prompt_fingerprint(AI_RESPONSE_JSON_SCHEMA)

    def initialize(self) -> None:
        # server.py loads local environment files immediately before initialization.
        self._configure_ai_runtime()
        self._configure_nav_runtime()
        self._configure_jobbnorge_runtime()
        self._configure_pracuj_runtime()
        self.private_root.mkdir(parents=True, exist_ok=True)
        self.assets_directory.mkdir(parents=True, exist_ok=True)
        self.recovery_directory.mkdir(parents=True, exist_ok=True)
        self.raw_archive.raw_root.mkdir(parents=True, exist_ok=True)
        self.store.initialize()
        self.store.configure_source_limits(
            NAV_SOURCE_ID,
            polling_cadence_seconds=integer_setting(
                self.environment, "JOBHUNT_NAV_POLL_SECONDS", 120,
                minimum=30, maximum=86400,
            ),
            maximum_request_budget=integer_setting(
                self.environment, "JOBHUNT_NAV_DETAIL_BUDGET", 100,
                minimum=1, maximum=500,
            ),
            now=_utc_now(),
        )
        self.store.configure_source_limits(
            PRACUJ_SOURCE_ID,
            polling_cadence_seconds=integer_setting(
                self.environment, "JOBHUNT_PRACUJ_POLL_SECONDS", 300,
                minimum=60, maximum=86400,
            ),
            maximum_request_budget=integer_setting(
                self.environment, "JOBHUNT_PRACUJ_BOOTSTRAP_MAX_MESSAGES", 500,
                minimum=1, maximum=500,
            ),
            now=_utc_now(),
        )
        self.store.configure_source_limits(
            JOBBNORGE_SOURCE_ID,
            polling_cadence_seconds=integer_setting(
                self.environment, "JOBHUNT_JOBBNORGE_POLL_SECONDS", 1800,
                minimum=300, maximum=86400,
            ),
            maximum_request_budget=integer_setting(
                self.environment, "JOBHUNT_JOBBNORGE_REQUEST_BUDGET", 12,
                minimum=1, maximum=100,
            ),
            now=_utc_now(),
        )
        mail_state = self.store.get_mail_sync_state(PRACUJ_SOURCE_ID)
        if mail_state and mail_state.get("mailbox") != self.mail_transport.mailbox:
            self.store.update_mail_sync_state(
                PRACUJ_SOURCE_ID,
                {
                    "mailbox": self.mail_transport.mailbox,
                    "uidvalidity": None,
                    "last_processed_uid": 0,
                    "highest_observed_uid": 0,
                    "bootstrap_started_at": None,
                    "bootstrap_completed_at": None,
                    "last_error_class": None,
                    "last_error_message": None,
                },
                now=_utc_now(),
            )
        if enabled(self.environment.get("JOBHUNT_NAV_ENABLED")) and self.nav_adapter.token_configured:
            self.store.set_source_enabled(NAV_SOURCE_ID, enabled=True, now=_utc_now())
        elif not self.nav_adapter.token_configured and self._nav_source().get("enabled"):
            self.store.set_source_enabled(NAV_SOURCE_ID, enabled=False, now=_utc_now())
        if enabled(self.environment.get("JOBHUNT_PRACUJ_ENABLED")) and self.mail_transport.configured:
            self.store.set_source_enabled(PRACUJ_SOURCE_ID, enabled=True, now=_utc_now())
        elif not self.mail_transport.configured and self._pracuj_source().get("enabled"):
            self.store.set_source_enabled(PRACUJ_SOURCE_ID, enabled=False, now=_utc_now())
        if enabled(self.environment.get("JOBHUNT_JOBBNORGE_ENABLED")):
            self.store.set_source_enabled(JOBBNORGE_SOURCE_ID, enabled=True, now=_utc_now())
        # Migration 9 deliberately stores derived blocking keys separately. Backfill
        # keys only (no pair comparisons or merge decisions) for pre-Pack-H jobs so
        # later scans remain index-bounded even for historical opportunities.
        while True:
            unindexed = self.store.unindexed_dedupe_job_ids("", limit=150)
            if not unindexed:
                break
            for job_id in unindexed:
                self._prepare_dedupe_context(job_id)
        self.assessment_loader.load(refresh=True)
        if self.store.eligible_evaluation_pairs(limit=1, automatic=True):
            profile = self.store.get_profile()
            self._schedule_evaluation_recompute(
                scope="profile", token=str(profile.get("fingerprint") or "current"),
            )

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "data": {
                "authority": "sqlite",
                "database": "data/jobhunt.sqlite",
                "schema": self.store.schema_status(),
            },
        }

    @staticmethod
    def _bounded_optional_text(value: Any, field: str, *, limit: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise JobhuntError(f"{field} must be text or null", code="invalid_track_payload")
        result = value.strip()
        if len(result) > limit:
            raise JobhuntError(f"{field} is too long", code="invalid_track_payload")
        return result or None

    @staticmethod
    def _bounded_list(value: Any, field: str, *, maximum: int = 50) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise JobhuntError(f"{field} must be an array", code="invalid_search_profile")
        if len(value) > maximum:
            raise JobhuntError(f"{field} contains too many values", code="invalid_search_profile")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise JobhuntError(f"{field} must contain text values", code="invalid_search_profile")
            text = item.strip()
            if len(text) > 160:
                raise JobhuntError(f"{field} contains an overlong value", code="invalid_search_profile")
            key = text.casefold()
            if text and key not in seen:
                result.append(text)
                seen.add(key)
        return result

    @staticmethod
    def _slug(value: Any, fallback: str | None = None) -> str:
        source = value if isinstance(value, str) and value.strip() else fallback
        if not source:
            raise JobhuntError("Track slug is required", code="invalid_track_payload")
        normalized = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
        if not slug or len(slug) > 80:
            raise JobhuntError("Track slug is invalid", code="invalid_track_payload")
        return slug

    @staticmethod
    def _nullable_bool(value: Any, field: str) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise JobhuntError(f"{field} must be true, false, or null", code="invalid_track_payload")
        return value

    @staticmethod
    def _track_to_api(track: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": track["id"], "slug": track["slug"], "name": track["name"],
            "purpose": track["purpose"], "status": track["status"],
            "geography": {
                "countries": track.get("countries") or [],
                "regionsCities": track.get("regions_cities") or [],
                "remoteAllowed": track.get("remote_allowed"),
                "relocationRelevant": track.get("relocation_relevant"),
                "primaryCurrency": track.get("primary_currency"),
            },
            "evaluationPolicyVersion": track.get("evaluation_policy_version"),
            "rationale": track.get("rationale"), "notes": track.get("notes"),
            "searchProfileCount": int(track.get("search_profile_count") or 0),
            "assignedJobCount": int(track.get("assigned_job_count") or 0),
            "createdAt": track["created_at"], "updatedAt": track["updated_at"],
        }

    def _search_profile_to_api(self, profile: dict[str, Any]) -> dict[str, Any]:
        resolution = self.store.search_profile_source_resolution(profile["id"])
        return {
            "id": profile["id"], "trackId": profile["track_id"], "name": profile["name"],
            "status": profile["status"], "includeKeywords": profile.get("include_keywords") or [],
            "excludeKeywords": profile.get("exclude_keywords") or [],
            "roleIntent": profile.get("role_intent"), "countries": profile.get("countries") or [],
            "regionsCities": profile.get("regions_cities") or [],
            "workModels": profile.get("work_models") or [],
            "scheduleHints": profile.get("schedule_hints") or [],
            "contractHints": profile.get("contract_hints") or [],
            "languageHints": profile.get("language_hints") or [],
            "seniorityHints": profile.get("seniority_hints") or [],
            "plannedSourceKeys": profile.get("planned_source_keys") or [],
            "resolvedSourceKeys": resolution["resolved"],
            "unresolvedSourceKeys": resolution["unresolved"],
            "notes": profile.get("notes"), "createdAt": profile["created_at"],
            "updatedAt": profile["updated_at"],
        }

    def _validate_track(self, payload: Any, *, current: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Track payload must be an object", code="invalid_track_payload")
        allowed = {"slug", "name", "purpose", "status", "geography", "evaluationPolicyVersion", "rationale", "notes"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise JobhuntError("Track payload contains unsupported fields", code="unknown_track_fields", details=unknown)
        base = current or {}
        name_value = payload.get("name", base.get("name"))
        name = self._bounded_optional_text(name_value, "name", limit=160)
        if not name:
            raise JobhuntError("Track name is required", code="invalid_track_payload")
        purpose_value = payload.get("purpose", base.get("purpose", ""))
        purpose = self._bounded_optional_text(purpose_value, "purpose", limit=4000) or ""
        status = payload.get("status", base.get("status", "exploring"))
        if status not in TRACK_STATUSES:
            raise JobhuntError("Track status is invalid", code="invalid_track_status")
        geography = payload.get("geography")
        if geography is None:
            geography = {
                "countries": base.get("countries", []),
                "regionsCities": base.get("regions_cities", []),
                "remoteAllowed": base.get("remote_allowed"),
                "relocationRelevant": base.get("relocation_relevant"),
                "primaryCurrency": base.get("primary_currency"),
            }
        if not isinstance(geography, dict):
            raise JobhuntError("geography must be an object", code="invalid_track_payload")
        geography_unknown = sorted(set(geography) - {"countries", "regionsCities", "remoteAllowed", "relocationRelevant", "primaryCurrency"})
        if geography_unknown:
            raise JobhuntError("geography contains unsupported fields", code="unknown_track_fields", details=geography_unknown)
        currency = self._bounded_optional_text(geography.get("primaryCurrency"), "primaryCurrency", limit=12)
        requested_policy_version = self._bounded_optional_text(
            payload.get("evaluationPolicyVersion", base.get("evaluation_policy_version")),
            "evaluationPolicyVersion", limit=120,
        )
        if "evaluationPolicyVersion" in payload and requested_policy_version != base.get("evaluation_policy_version"):
            raise JobhuntError(
                "Evaluation Policy versions can only be changed through the policy endpoint",
                code="evaluation_policy_write_required",
            )
        return {
            "slug": self._slug(payload.get("slug"), base.get("slug") or name),
            "name": name, "purpose": purpose, "status": status,
            "countries": self._bounded_list(geography.get("countries"), "countries", maximum=20),
            "regions_cities": self._bounded_list(geography.get("regionsCities"), "regionsCities", maximum=30),
            "remote_allowed": self._nullable_bool(geography.get("remoteAllowed"), "remoteAllowed"),
            "relocation_relevant": self._nullable_bool(geography.get("relocationRelevant"), "relocationRelevant"),
            "primary_currency": currency.upper() if currency else None,
            "evaluation_policy_version": base.get("evaluation_policy_version"),
            "rationale": self._bounded_optional_text(payload.get("rationale", base.get("rationale")), "rationale", limit=8000),
            "notes": self._bounded_optional_text(payload.get("notes", base.get("notes")), "notes", limit=8000),
        }

    def list_tracks(self) -> dict[str, Any]:
        return {"ok": True, "data": {"tracks": [self._track_to_api(item) for item in self.store.list_tracks()]}}

    def get_track(self, track_id: str) -> dict[str, Any]:
        track = self.store.get_track(track_id)
        if not track:
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        profiles = [self._search_profile_to_api(item) for item in self.store.list_search_profiles(track_id)]
        assigned_jobs = [{
            "jobId": item["job_id"], "company": item["company"], "role": item["role_title"],
            "location": {"city": item["location_city"], "country": item["location_country"]},
            "applicationStatus": item["application_status"], "origin": item["origin"],
            "note": item["note"], "createdAt": item["created_at"], "updatedAt": item["updated_at"],
        } for item in self.store.assigned_jobs_for_track(track_id)]
        return {"ok": True, "data": {
            "track": self._track_to_api(track), "searchProfiles": profiles,
            "assignedJobs": assigned_jobs,
            "assignmentMeaning": "Relevant to this Track; this is not a fit or suitability score.",
        }}

    def create_track(self, payload: Any) -> dict[str, Any]:
        values = self._validate_track(payload)
        try:
            track_id = self.store.create_track(values, now=_utc_now())
        except sqlite3.IntegrityError as exc:
            raise JobhuntError("Track slug must be unique", status=409, code="track_slug_conflict") from exc
        return self.get_track(track_id)

    def update_track(self, track_id: str, payload: Any) -> dict[str, Any]:
        current = self.store.get_track(track_id)
        if not current:
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        values = self._validate_track(payload, current=current)
        try:
            self.store.update_track(track_id, values, now=_utc_now())
        except sqlite3.IntegrityError as exc:
            raise JobhuntError("Track slug must be unique", status=409, code="track_slug_conflict") from exc
        response = self.get_track(track_id)
        track = response["data"]["track"]
        if track["status"] in {"active", "exploring"}:
            self._schedule_evaluation_recompute(
                scope="track", track_id=track_id,
                token=_sha(_canonical_bytes({
                    "geography": track.get("geography"),
                    "policyVersion": track.get("evaluationPolicyVersion"),
                })),
                force_if_completed=current.get("status") not in {"active", "exploring"},
            )
        return response

    def _validate_search_profile(self, payload: Any, *, current: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Search Profile payload must be an object", code="invalid_search_profile")
        field_map = {
            "includeKeywords": "include_keywords", "excludeKeywords": "exclude_keywords",
            "countries": "countries", "regionsCities": "regions_cities",
            "workModels": "work_models", "scheduleHints": "schedule_hints",
            "contractHints": "contract_hints", "languageHints": "language_hints",
            "seniorityHints": "seniority_hints", "plannedSourceKeys": "planned_source_keys",
        }
        allowed = {"name", "status", "roleIntent", "notes", *field_map, "trackId"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise JobhuntError("Search Profile contains unsupported fields", code="unknown_search_profile_fields", details=unknown)
        base = current or {}
        if "trackId" in payload and payload["trackId"] != base.get("track_id"):
            raise JobhuntError("Search Profiles cannot be moved between Tracks", status=409, code="search_profile_track_mismatch")
        name = self._bounded_optional_text(payload.get("name", base.get("name")), "name", limit=160)
        if not name:
            raise JobhuntError("Search Profile name is required", code="invalid_search_profile")
        status = payload.get("status", base.get("status", "enabled"))
        if status not in SEARCH_PROFILE_STATUSES:
            raise JobhuntError("Search Profile status is invalid", code="invalid_search_profile_status")
        result = {
            "name": name, "status": status,
            "role_intent": self._bounded_optional_text(payload.get("roleIntent", base.get("role_intent")), "roleIntent", limit=2000),
            "notes": self._bounded_optional_text(payload.get("notes", base.get("notes")), "notes", limit=8000),
        }
        for api_name, store_name in field_map.items():
            result[store_name] = self._bounded_list(payload.get(api_name, base.get(store_name, [])), api_name)
        invalid_sources = sorted(set(result["planned_source_keys"]) - PLANNED_SOURCE_KEYS)
        if invalid_sources:
            raise JobhuntError("Unknown planned source key", code="invalid_source_hint", details=invalid_sources)
        return result

    def list_search_profiles(self, track_id: str) -> dict[str, Any]:
        if not self.store.get_track(track_id):
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        return {"ok": True, "data": {
            "trackId": track_id,
            "searchProfiles": [self._search_profile_to_api(item) for item in self.store.list_search_profiles(track_id)],
        }}

    def create_search_profile(self, track_id: str, payload: Any) -> dict[str, Any]:
        values = self._validate_search_profile(payload)
        profile_id = self.store.save_search_profile(track_id, values, now=_utc_now())
        profile = self.store.get_search_profile(profile_id)
        return {"ok": True, "data": {"searchProfile": self._search_profile_to_api(profile)}}

    def update_search_profile(self, profile_id: str, payload: Any) -> dict[str, Any]:
        current = self.store.get_search_profile(profile_id)
        if not current:
            raise JobhuntError("Search Profile not found", status=404, code="search_profile_not_found")
        values = self._validate_search_profile(payload, current=current)
        self.store.save_search_profile(current["track_id"], values, profile_id=profile_id, now=_utc_now())
        profile = self.store.get_search_profile(profile_id)
        return {"ok": True, "data": {"searchProfile": self._search_profile_to_api(profile)}}

    def get_job_tracks(self, job_id: str) -> dict[str, Any]:
        if not self.store.get_offer_row(job_id):
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        assignments = [{
            "trackId": item["id"], "slug": item["slug"], "name": item["name"],
            "trackStatus": item["status"], "assigned": bool(item.get("active")),
            "origin": item.get("origin"), "note": item.get("note"),
            "createdAt": item.get("created_at"), "updatedAt": item.get("updated_at"),
        } for item in self.store.job_track_assignments(job_id)]
        return {"ok": True, "data": {
            "jobId": job_id, "tracks": assignments,
            "assignmentMeaning": "Relevant to this Track; this is not a fit or suitability score.",
        }}

    def set_job_tracks(self, job_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Track assignment payload must be an object", code="invalid_track_assignment")
        unknown = sorted(set(payload) - {"trackIds", "origin", "note"})
        if unknown:
            raise JobhuntError("Track assignment contains unsupported fields", code="invalid_track_assignment", details=unknown)
        track_ids = self._bounded_list(payload.get("trackIds"), "trackIds", maximum=100)
        origin = payload.get("origin", "manual")
        if origin not in TRACK_ASSIGNMENT_ORIGINS or origin != "manual":
            raise JobhuntError("Interactive assignment origin must be manual", code="invalid_track_assignment_origin")
        note = self._bounded_optional_text(payload.get("note"), "note", limit=2000)
        now = _utc_now()
        self.store.sync_job_tracks(job_id, track_ids, origin=origin, note=note, now=now)
        self.store.prune_ineligible_evaluation_current([job_id])
        self._schedule_evaluation_recompute(
            scope="job", job_id=job_id,
            token=_sha(_canonical_bytes({"trackIds": sorted(track_ids), "changedAt": now})),
        )
        return self.get_job_tracks(job_id)

    @staticmethod
    def _evaluation_policy_to_api(policy: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": policy["id"], "trackId": policy["track_id"],
            "schemaVersion": policy["schema_version"],
            "version": int(policy["policy_version"]),
            "fingerprint": policy["fingerprint"], "origin": policy["origin"],
            "policy": policy["policy"], "createdAt": policy["created_at"],
        }

    def get_track_evaluation_policy(self, track_id: str) -> dict[str, Any]:
        if not self.store.get_track(track_id):
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        policy = self.store.get_track_evaluation_policy(track_id)
        if not policy:
            raise JobhuntError(
                "Track Evaluation Policy is unavailable", status=500,
                code="evaluation_policy_missing",
            )
        return {"ok": True, "data": {"policy": self._evaluation_policy_to_api(policy)}}

    def get_track_evaluation_policy_history(self, track_id: str) -> dict[str, Any]:
        if not self.store.get_track(track_id):
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        policies = self.store.list_track_evaluation_policies(track_id)
        return {"ok": True, "data": {
            "trackId": track_id,
            "items": [self._evaluation_policy_to_api(item) for item in policies],
        }}

    def create_track_evaluation_policy(self, track_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"policy"}:
            raise JobhuntError(
                "Evaluation Policy payload must contain only policy",
                code="invalid_evaluation_policy",
            )
        try:
            policy_value = validate_policy(payload["policy"])
        except ValueError as exc:
            raise JobhuntError(str(exc), code="invalid_evaluation_policy") from exc
        saved, reused = self.store.save_track_evaluation_policy(
            track_id, policy_value, origin="user", now=_utc_now(),
        )
        recompute = self._schedule_evaluation_recompute(
            scope="track", track_id=track_id, token=saved["fingerprint"],
        )
        return {"ok": True, "data": {
            "policy": self._evaluation_policy_to_api(saved),
            "reused": reused, "evaluationRecompute": recompute,
        }}

    def _evaluation_state(self, evaluation: dict[str, Any]) -> str:
        if not evaluation.get("is_pointer"):
            return "historical"
        try:
            context = self.store.evaluation_context(
                evaluation["job_id"], evaluation["track_id"],
            )
        except JobhuntError:
            return "stale"
        return (
            "current" if context["input_fingerprint"] == evaluation["input_fingerprint"]
            else "stale"
        )

    def _evaluation_to_api(
        self, evaluation: dict[str, Any], *, include_details: bool = True,
    ) -> dict[str, Any]:
        result = {
            "id": evaluation["id"], "jobId": evaluation["job_id"],
            "trackId": evaluation["track_id"],
            "job": {
                "company": evaluation.get("company"), "role": evaluation.get("role_title"),
            },
            "trackName": evaluation.get("track_name"),
            "state": self._evaluation_state(evaluation),
            "profileRevision": int(evaluation["profile_revision"]),
            "profileFingerprint": evaluation["profile_fingerprint"],
            "projectionId": evaluation.get("projection_id"),
            "projectionVersion": int(evaluation.get("projection_version") or 0),
            "projectionFingerprint": evaluation["projection_fingerprint"],
            "policyId": evaluation["policy_id"],
            "policyVersion": int(evaluation["policy_version"]),
            "policyFingerprint": evaluation["policy_fingerprint"],
            "trackContextFingerprint": evaluation["track_context_fingerprint"],
            "evaluatorVersion": evaluation["evaluator_version"],
            "evaluationSchemaVersion": evaluation["evaluation_schema_version"],
            "inputFingerprint": evaluation["input_fingerprint"],
            "basis": evaluation.get("evaluation_basis") or {},
            "counts": {
                "blockers": int(evaluation.get("blocker_count") or 0),
                "gaps": int(evaluation.get("gap_count") or 0),
                "unknowns": int(evaluation.get("unknown_count") or 0),
                "requiredGaps": int(evaluation.get("required_gap_count") or 0),
                "supportedRequired": int(evaluation.get("supported_required_count") or 0),
            },
            "createdAt": evaluation["created_at"],
            "completedAt": evaluation.get("completed_at"),
        }
        if include_details:
            result["dimensions"] = [{
                "dimension": item["dimension"], "state": item["state"],
                "importance": item["importance"],
                "findingCount": int(item["finding_count"]),
                "explanationCode": item["explanation_code"],
                "display": item.get("display_params") or {},
            } for item in evaluation.get("dimensions", [])]
            result["findings"] = [{
                "id": item["id"], "dimension": item["dimension"],
                "type": item["finding_type"], "status": item["status"],
                "importance": item["importance"],
                "requirementClass": item["requirement_class"],
                "conceptKey": item.get("concept_key"),
                "jobFactIds": item.get("job_fact_ids") or [],
                "jobEvidence": item.get("job_evidence") or [],
                "profileEvidence": item.get("profile_evidence") or [],
                "policyEvidence": item.get("policy_evidence") or {},
                "explanationCode": item["explanation_code"],
                "display": item.get("display_params") or {},
            } for item in evaluation.get("findings", [])]
        return result

    def evaluate_job_track(
        self, job_id: str, track_id: str, *, explicit: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        context = self.store.evaluation_context(job_id, track_id)
        basis = self.store.evaluation_basis(job_id, track_id, explicit=explicit)
        if not basis["sources"]:
            raise JobhuntError(
                "This Job and Track are not eligible for automatic Evaluation",
                status=409, code="evaluation_pair_not_eligible",
            )
        evaluated = evaluate_candidate(context)
        saved, reused = self.store.save_evaluation(
            context, evaluated, basis=basis, now=_utc_now(),
        )
        detail = self.store.get_evaluation(saved["id"])
        if not detail:
            raise JobhuntError("Evaluation could not be loaded", status=500, code="evaluation_missing")
        return self._evaluation_to_api(detail), reused

    def explicit_evaluate_job_track(
        self, job_id: str, track_id: str, payload: Any = None,
    ) -> dict[str, Any]:
        self._empty_command(payload)
        evaluation, reused = self.evaluate_job_track(job_id, track_id, explicit=True)
        return {"ok": True, "data": {"evaluation": evaluation, "reused": reused}}

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        evaluation = self.store.get_evaluation(evaluation_id)
        if not evaluation:
            raise JobhuntError("Evaluation not found", status=404, code="evaluation_not_found")
        return {"ok": True, "data": {"evaluation": self._evaluation_to_api(evaluation)}}

    def list_job_evaluations(self, job_id: str) -> dict[str, Any]:
        resolved = self.store.resolve_evaluation_job_id(job_id)
        if not resolved:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        pairs = self.store.eligible_evaluation_pairs(
            scope="job", job_id=resolved, limit=200, automatic=False,
        )
        current_rows = {
            item["track_id"]: item for item in self.store.current_evaluation_rows_for_job(resolved)
        }
        targets = []
        for pair in pairs:
            track = self.store.get_track(pair["track_id"])
            row = current_rows.get(pair["track_id"])
            detail = self.store.get_evaluation(row["id"]) if row else None
            targets.append({
                "track": None if not track else self._track_to_api(track),
                "basis": pair["basis"],
                "evaluation": None if not detail else self._evaluation_to_api(detail),
            })
        history = [
            self._evaluation_to_api(item, include_details=False)
            for item in self.store.list_evaluation_rows(job_id=resolved)
        ]
        return {"ok": True, "data": {
            "requestedJobId": job_id, "resolvedJobId": resolved,
            "targets": targets, "history": history,
            "legacySeparation": "legacy_imported scores are separate historical compatibility data.",
        }}

    def list_track_evaluations(self, track_id: str) -> dict[str, Any]:
        track = self.store.get_track(track_id)
        if not track:
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        items = []
        for row in self.store.current_evaluation_rows_for_track(track_id):
            detail = self.store.get_evaluation(row["id"])
            if detail:
                items.append(self._evaluation_to_api(detail))
        return {"ok": True, "data": {
            "track": self._track_to_api(track), "items": items,
            "ordering": "newest evaluation first; no aggregate score is calculated",
        }}

    @staticmethod
    def _skill_intelligence_query(
        *, population: Any = None, window: Any = None,
        requirement_class: Any = None, user_state: Any = None,
        minimum_demand: Any = None, sort: Any = None,
    ) -> dict[str, Any]:
        return {
            "population": population or "current",
            "window": window or "90d",
            "requirement_class": requirement_class or "all",
            "user_state": user_state or "all",
            "minimum_demand": 0 if minimum_demand in (None, "") else minimum_demand,
            "sort": sort or "priority",
        }

    def get_track_skill_intelligence(self, track_id: str, **query: Any) -> dict[str, Any]:
        values = self._skill_intelligence_query(**query)
        return {"ok": True, "data": self.skill_intelligence_model.intelligence(track_id, **values)}

    def get_track_skill_detail(
        self, track_id: str, concept_reference: str, **query: Any,
    ) -> dict[str, Any]:
        values = self._skill_intelligence_query(**query)
        return {"ok": True, "data": self.skill_intelligence_model.detail(
            track_id, concept_reference, **values,
        )}

    def get_track_unmapped_skills(self, track_id: str, **query: Any) -> dict[str, Any]:
        values = self._skill_intelligence_query(**query)
        return {"ok": True, "data": self.skill_intelligence_model.unmapped(track_id, **values)}

    def get_track_skill_meta(self, track_id: str, **query: Any) -> dict[str, Any]:
        values = self._skill_intelligence_query(**query)
        return {"ok": True, "data": self.skill_intelligence_model.meta(track_id, **values)}

    def get_market_analytics(self, **query: Any) -> dict[str, Any]:
        return {"ok": True, "data": self.analytics_model.market(
            window=query.get("window"), track_id=query.get("track_id"),
            source=query.get("source"), geography=query.get("geography"),
        )}

    def get_source_analytics(self, **query: Any) -> dict[str, Any]:
        return {"ok": True, "data": self.analytics_model.sources(window=query.get("window"))}

    def get_application_analytics(self, **query: Any) -> dict[str, Any]:
        return {"ok": True, "data": self.analytics_model.applications(
            window=query.get("window"), track_id=query.get("track_id"),
            source=query.get("source"),
        )}

    def get_track_analytics(self, track_id: str, **query: Any) -> dict[str, Any]:
        return {"ok": True, "data": self.analytics_model.track(
            track_id, window=query.get("window"),
        )}

    def get_tradeoff_analytics(self, track_ids: list[str], **query: Any) -> dict[str, Any]:
        return {"ok": True, "data": self.analytics_model.tradeoff(
            track_ids, window=query.get("window"),
        )}

    @staticmethod
    def _scenario_number(value: Any, field: str, *, positive: bool = False) -> float:
        if isinstance(value, bool):
            raise JobhuntError(f"{field} must be a number", code="invalid_economic_scenario")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise JobhuntError(f"{field} must be a number", code="invalid_economic_scenario") from exc
        if not math.isfinite(result) or result < 0 or (positive and result <= 0):
            raise JobhuntError(f"{field} must be {'positive' if positive else 'zero or greater'}", code="invalid_economic_scenario")
        return result

    @staticmethod
    def _scenario_date(value: Any, field: str) -> str:
        text = _text(value, limit=40)
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise JobhuntError(f"{field} must be an ISO date or timestamp", code="invalid_economic_scenario") from exc
        return text

    def _scenario_value(self, value: Any, field: str, *, positive: bool = False) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {"value", "source", "updatedAt"}:
            raise JobhuntError(
                f"{field} must contain value, source, and updatedAt",
                code="invalid_economic_scenario",
            )
        source = self._bounded_optional_text(value.get("source"), f"{field}.source", limit=500)
        if not source:
            raise JobhuntError(f"{field}.source is required", code="invalid_economic_scenario")
        return {
            "value": self._scenario_number(value.get("value"), f"{field}.value", positive=positive),
            "source": source,
            "updatedAt": self._scenario_date(value.get("updatedAt"), f"{field}.updatedAt"),
        }

    def _validate_economic_scenario(self, payload: Any) -> tuple[str, str, dict[str, Any]]:
        if not isinstance(payload, dict) or set(payload) - {"name", "currency", "assumptions"}:
            raise JobhuntError("Economic Scenario payload is invalid", code="invalid_economic_scenario")
        name = self._bounded_optional_text(payload.get("name"), "name", limit=200)
        currency = self._bounded_optional_text(payload.get("currency"), "currency", limit=12)
        raw = payload.get("assumptions")
        if not name or not currency or not isinstance(raw, dict):
            raise JobhuntError("Economic Scenario name, currency, and assumptions are required", code="invalid_economic_scenario")
        unknown = sorted(set(raw) - {"monthlyCosts", "relocationCost", "netMonthlyEstimate", "fx", "notes"})
        if unknown:
            raise JobhuntError("Economic Scenario contains unsupported assumptions", code="invalid_economic_scenario", details=unknown)
        costs = raw.get("monthlyCosts")
        if not isinstance(costs, dict):
            raise JobhuntError("monthlyCosts must be an object", code="invalid_economic_scenario")
        cost_fields = {"housing", "utilities", "food", "transport", "other"}
        if set(costs) - cost_fields:
            raise JobhuntError("monthlyCosts contains an unsupported category", code="invalid_economic_scenario")
        assumptions: dict[str, Any] = {
            "monthlyCosts": {key: self._scenario_value(costs[key], f"monthlyCosts.{key}") for key in sorted(costs)},
            "notes": self._bounded_optional_text(raw.get("notes"), "notes", limit=4000),
        }
        if raw.get("relocationCost") is not None:
            assumptions["relocationCost"] = self._scenario_value(raw["relocationCost"], "relocationCost")
        if raw.get("netMonthlyEstimate") is not None:
            net = raw["netMonthlyEstimate"]
            allowed = {"amount", "label", "taxModelVersion", "year", "jurisdiction", "deductions", "source", "updatedAt"}
            if not isinstance(net, dict) or set(net) - allowed:
                raise JobhuntError("netMonthlyEstimate is invalid", code="invalid_economic_scenario")
            required = {"amount", "taxModelVersion", "year", "jurisdiction", "deductions", "source", "updatedAt"}
            if not required <= set(net):
                raise JobhuntError("netMonthlyEstimate provenance is incomplete", code="invalid_economic_scenario")
            assumptions["netMonthlyEstimate"] = {
                "amount": self._scenario_number(net["amount"], "netMonthlyEstimate.amount"),
                "label": "estimate",
                "taxModelVersion": _text(net["taxModelVersion"], limit=120),
                "year": int(self._scenario_number(net["year"], "netMonthlyEstimate.year", positive=True)),
                "jurisdiction": _text(net["jurisdiction"], limit=120),
                "deductions": _text(net["deductions"], limit=1000),
                "source": _text(net["source"], limit=500),
                "updatedAt": self._scenario_date(net["updatedAt"], "netMonthlyEstimate.updatedAt"),
                "disclaimer": "Scenario estimate; not official tax advice.",
            }
            if not all(assumptions["netMonthlyEstimate"].get(key) for key in ("taxModelVersion", "jurisdiction", "deductions", "source")):
                raise JobhuntError("netMonthlyEstimate provenance is incomplete", code="invalid_economic_scenario")
        if raw.get("fx") is not None:
            fx = raw["fx"]
            if not isinstance(fx, dict) or set(fx) - {"rateToBase", "baseCurrency", "source", "updatedAt"}:
                raise JobhuntError("fx is invalid", code="invalid_economic_scenario")
            assumptions["fx"] = {
                "rateToBase": self._scenario_number(fx.get("rateToBase"), "fx.rateToBase", positive=True),
                "baseCurrency": _text(fx.get("baseCurrency"), limit=12).upper(),
                "source": _text(fx.get("source"), limit=500),
                "updatedAt": self._scenario_date(fx.get("updatedAt"), "fx.updatedAt"),
            }
            if not assumptions["fx"]["baseCurrency"] or not assumptions["fx"]["source"]:
                raise JobhuntError("fx source and baseCurrency are required", code="invalid_economic_scenario")
        return name, currency.upper(), assumptions

    def list_economic_scenarios(self, track_id: str | None = None) -> dict[str, Any]:
        if track_id and not self.store.get_track(track_id):
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        return {"ok": True, "data": {
            "items": self.store.list_economic_scenarios(track_id),
            "semantics": "Manual, versioned user scenarios; no live tax, FX, or cost feed is implied.",
        }}

    def save_economic_scenario(self, track_id: str, payload: Any) -> dict[str, Any]:
        name, currency, assumptions = self._validate_economic_scenario(payload)
        scenario = self.store.save_economic_scenario(
            track_id, name=name, currency=currency, assumptions=assumptions, now=_utc_now(),
        )
        return {"ok": True, "data": {"scenario": scenario}}

    def get_career_intelligence(self) -> dict[str, Any]:
        data = self.career_intelligence_model.adjacent()
        data["experiments"] = {
            "active": len(self.store.list_experiments(status="active")),
            "planned": len(self.store.list_experiments(status="planned")),
        }
        return {"ok": True, "data": data}

    def get_adjacent_careers(self) -> dict[str, Any]:
        return {"ok": True, "data": self.career_intelligence_model.adjacent()}

    def list_track_proposals(self) -> dict[str, Any]:
        return {"ok": True, "data": {"items": self.store.list_track_proposals()}}

    def _proposal_candidate(self, proposal_key: str) -> dict[str, Any]:
        intelligence = self.career_intelligence_model.adjacent()
        proposal = next((item for item in intelligence["trackProposals"] if item["proposalKey"] == proposal_key), None)
        if proposal:
            return proposal
        saved = self.store.get_track_proposal(proposal_key)
        if saved:
            return saved
        raise JobhuntError("Track proposal not found", status=404, code="track_proposal_not_found")

    def decide_track_proposal(self, proposal_key: str, action: str, payload: Any = None) -> dict[str, Any]:
        if action not in {"save", "dismiss", "accept"}:
            raise JobhuntError("Unsupported Track proposal action", code="invalid_track_proposal_action")
        if payload not in (None, {}) and not isinstance(payload, dict):
            raise JobhuntError("Track proposal command must be an object", code="invalid_track_proposal_action")
        proposal = self._proposal_candidate(proposal_key)
        evidence = proposal.get("evidence") or {}
        fingerprint = proposal.get("evidenceFingerprint") or ("sha256:" + hashlib.sha256(_canonical_bytes(evidence)).hexdigest())
        accepted_track_id = proposal.get("acceptedTrackId")
        if action == "accept" and not accepted_track_id:
            overrides = payload or {}
            if set(overrides) - {"name", "status", "notes"}:
                raise JobhuntError("Track proposal acceptance contains unsupported fields", code="invalid_track_proposal_action")
            track_result = self.create_track({
                "name": overrides.get("name") or proposal["proposedName"],
                "purpose": f"Explore evidence-backed adjacent role family: {proposal['roleFamily']}.",
                "status": overrides.get("status", "exploring"),
                "geography": {"countries": evidence.get("proposedGeography") or []},
                "rationale": "Created only after explicit acceptance of a Pack M Track proposal.",
                "notes": overrides.get("notes"),
            })
            accepted_track_id = track_result["data"]["track"]["id"]
        state = {"save": "saved_for_review", "dismiss": "dismissed", "accept": "accepted"}[action]
        saved = self.store.save_track_proposal(
            proposal_key=proposal_key, role_family=proposal["roleFamily"],
            proposed_name=proposal["proposedName"], state=state, evidence=evidence,
            evidence_fingerprint=fingerprint, accepted_track_id=accepted_track_id, now=_utc_now(),
        )
        return {"ok": True, "data": {"proposal": saved}}

    def list_experiment_templates(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "version": "career-experiment-template@1",
            "items": self.career_intelligence_model.templates(),
            "semantics": "Starting points, not validated psychological instruments.",
        }}

    @staticmethod
    def _experiment_rating(value: Any, field: str, *, minimum: int = 1, maximum: int = 5) -> int:
        if isinstance(value, bool):
            raise JobhuntError(f"{field} must be between {minimum} and {maximum}", code="invalid_experiment")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise JobhuntError(f"{field} must be between {minimum} and {maximum}", code="invalid_experiment") from exc
        if result < minimum or result > maximum:
            raise JobhuntError(f"{field} must be between {minimum} and {maximum}", code="invalid_experiment")
        return result

    def _experiment_values(self, payload: Any, *, creating: bool) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Career Experiment payload must be an object", code="invalid_experiment")
        mapping = {
            "trackId": "track_id", "proposalId": "proposal_id", "skillReference": "skill_reference",
            "hypothesis": "hypothesis", "title": "title", "taskDefinition": "task_definition",
            "taskDefinitionVersion": "task_definition_version", "templateId": "template_id",
            "plannedMinutes": "planned_minutes", "notes": "notes", "evidence": "evidence_json",
        }
        unknown = sorted(set(payload) - set(mapping))
        if unknown:
            raise JobhuntError("Career Experiment contains unsupported fields", code="invalid_experiment", details=unknown)
        template = self.career_intelligence_model.template(str(payload.get("templateId") or ""))
        if payload.get("templateId") and not template:
            raise JobhuntError("Career Experiment template not found", status=404, code="experiment_template_not_found")
        source = {**(template or {}), **payload}
        if creating and not source.get("hypothesis"):
            source["hypothesis"] = template.get("goal") if template else None
        result: dict[str, Any] = {}
        text_limits = {
            "trackId": 100, "proposalId": 100, "skillReference": 300, "hypothesis": 2000,
            "title": 300, "taskDefinition": 8000, "taskDefinitionVersion": 120,
            "templateId": 120, "notes": 12000,
        }
        for api_key, store_key in mapping.items():
            if api_key not in source:
                continue
            if api_key == "plannedMinutes":
                result[store_key] = self._experiment_rating(source[api_key], api_key, minimum=1, maximum=10080)
            elif api_key == "evidence":
                if not isinstance(source[api_key], dict):
                    raise JobhuntError("evidence must be an object", code="invalid_experiment")
                if len(_canonical_bytes(source[api_key])) > 64 * 1024:
                    raise JobhuntError("Career Experiment evidence is too large", status=413, code="experiment_too_large")
                result[store_key] = source[api_key]
            else:
                result[store_key] = self._bounded_optional_text(source[api_key], api_key, limit=text_limits[api_key])
        if template:
            result.setdefault("task_definition", template["taskDefinition"])
            result.setdefault("task_definition_version", template["taskDefinitionVersion"])
            result.setdefault("planned_minutes", template["plannedMinutes"])
            result.setdefault("template_id", template["id"])
        if creating:
            missing = [key for key in ("hypothesis", "title", "task_definition", "task_definition_version") if not result.get(key)]
            if missing:
                raise JobhuntError("Career Experiment hypothesis, title, task, and task version are required", code="invalid_experiment", details=missing)
            result["evidence"] = result.pop("evidence_json", {})
        if result.get("track_id") and not self.store.get_track(result["track_id"]):
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        return result

    def list_experiments(self, **query: Any) -> dict[str, Any]:
        status = str(query.get("status") or "").strip() or None
        if status and status not in {"planned", "active", "completed", "abandoned"}:
            raise JobhuntError("Career Experiment status is invalid", code="invalid_experiment_status")
        return {"ok": True, "data": {"items": self.store.list_experiments(
            status=status, track_id=str(query.get("track_id") or "").strip() or None,
            proposal_id=str(query.get("proposal_id") or "").strip() or None,
        )}}

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        item = self.store.get_experiment(experiment_id)
        if not item:
            raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
        return {"ok": True, "data": {"experiment": item}}

    def create_experiment(self, payload: Any) -> dict[str, Any]:
        item = self.store.create_experiment(self._experiment_values(payload, creating=True), now=_utc_now())
        return {"ok": True, "data": {"experiment": item}}

    def update_experiment(self, experiment_id: str, payload: Any) -> dict[str, Any]:
        changes = self._experiment_values(payload, creating=False)
        item = self.store.update_experiment(experiment_id, changes, now=_utc_now())
        return {"ok": True, "data": {"experiment": item}}

    def start_experiment(self, experiment_id: str, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        current = self.store.get_experiment(experiment_id)
        if not current:
            raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
        if current["status"] != "planned":
            raise JobhuntError("Only a planned Career Experiment can be started", status=409, code="invalid_experiment_transition")
        item = self.store.transition_experiment(experiment_id, status="active", values={}, now=_utc_now())
        return {"ok": True, "data": {"experiment": item}}

    def complete_experiment(self, experiment_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Career Experiment completion must be an object", code="invalid_experiment")
        allowed = {"actualMinutes", "interestRating", "difficultyRating", "frustrationRating", "confidenceChangeRating", "desireToContinue", "notes"}
        if set(payload) - allowed:
            raise JobhuntError("Career Experiment completion contains unsupported fields", code="invalid_experiment")
        required = allowed - {"notes"}
        if not required <= set(payload):
            raise JobhuntError("Career Experiment completion ratings and time are required", code="invalid_experiment", details=sorted(required - set(payload)))
        if not isinstance(payload["desireToContinue"], bool):
            raise JobhuntError("desireToContinue must be true or false", code="invalid_experiment")
        values = {
            "actual_minutes": self._experiment_rating(payload["actualMinutes"], "actualMinutes", minimum=0, maximum=10080),
            "interest_rating": self._experiment_rating(payload["interestRating"], "interestRating"),
            "difficulty_rating": self._experiment_rating(payload["difficultyRating"], "difficultyRating"),
            "frustration_rating": self._experiment_rating(payload["frustrationRating"], "frustrationRating"),
            "confidence_change_rating": self._experiment_rating(payload["confidenceChangeRating"], "confidenceChangeRating", minimum=-2, maximum=2),
            "desire_to_continue": payload["desireToContinue"],
            "notes": self._bounded_optional_text(payload.get("notes"), "notes", limit=12000) or "",
        }
        item = self.store.transition_experiment(experiment_id, status="completed", values=values, now=_utc_now())
        return {"ok": True, "data": {
            "experiment": item,
            "profileUpdate": {"available": True, "requiresExplicitConfirmation": True},
        }}

    def abandon_experiment(self, experiment_id: str, payload: Any = None) -> dict[str, Any]:
        if payload not in (None, {}) and (not isinstance(payload, dict) or set(payload) - {"notes"}):
            raise JobhuntError("Career Experiment abandon payload is invalid", code="invalid_experiment")
        values = {"notes": self._bounded_optional_text((payload or {}).get("notes"), "notes", limit=12000) or ""}
        item = self.store.transition_experiment(experiment_id, status="abandoned", values=values, now=_utc_now())
        return {"ok": True, "data": {"experiment": item}}

    def add_experiment_note(self, experiment_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"note"}:
            raise JobhuntError("Career Experiment note payload is invalid", code="invalid_experiment_note")
        experiment = self.store.get_experiment(experiment_id)
        if not experiment:
            raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
        note = self._bounded_optional_text(payload.get("note"), "note", limit=12000)
        if not note:
            raise JobhuntError("Career Experiment note is required", code="invalid_experiment_note")
        item = self.store.append_experiment_event(
            experiment_id, event_type="note_added", payload={"note": note}, now=_utc_now(),
        )
        return {"ok": True, "data": {"experiment": item}}

    def apply_experiment_insight(self, experiment_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {"confirm", "collection", "record"}:
            raise JobhuntError("Career Experiment Profile proposal is invalid", code="invalid_experiment_profile_update")
        if payload.get("confirm") is not True:
            raise JobhuntError("Explicit confirmation is required", status=409, code="experiment_profile_confirmation_required")
        experiment = self.store.get_experiment(experiment_id)
        if not experiment:
            raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
        if experiment["status"] != "completed":
            raise JobhuntError("Only a completed Career Experiment can update the Profile", status=409, code="experiment_not_completed")
        collection = str(payload.get("collection") or "")
        if collection not in {"skills", "preferences"} or not isinstance(payload.get("record"), dict):
            raise JobhuntError("Profile proposal must target skills or preferences", code="invalid_experiment_profile_update")
        record = dict(payload["record"])
        record["origin"] = "career_experiment"
        reference = f"Career Experiment {experiment_id}: {experiment['title']}"
        note_key = "evidenceNotes" if collection == "skills" else "notes"
        record[note_key] = "\n".join(part for part in [record.get(note_key), reference] if part)
        result = self.save_profile_record(collection, record)
        now = _utc_now()
        self.store.append_experiment_event(
            experiment_id, event_type="insight_applied",
            payload={"collection": collection, "recordId": result["data"]["record"]["id"]}, now=now,
        )
        return {"ok": True, "data": {
            "experiment": self.store.get_experiment(experiment_id),
            "profileRecord": result["data"]["record"],
            "evaluationRecompute": result["data"]["evaluationRecompute"],
        }}

    def _schedule_evaluation_recompute(
        self, *, scope: str, token: str, job_id: str | None = None,
        track_id: str | None = None, after: str | None = None,
        force_if_completed: bool = False,
    ) -> dict[str, Any]:
        if scope not in {"profile", "job", "track", "pair"}:
            raise ValueError("Unsupported Evaluation recompute scope")
        payload = {
            "schemaVersion": "evaluation-recompute@1", "scope": scope,
            "jobId": job_id, "trackId": track_id, "after": after,
        }
        stable = _sha(_canonical_bytes({"payload": payload, "token": str(token)}))
        key = f"evaluation:{scope}:{stable}"
        existing = self.store.get_worker_job_by_idempotency(key)
        if existing and existing["state"] in {"queued", "running", "retry_wait"}:
            return {
                "queued": True, "reused": True,
                "workerJobId": existing["id"], "state": existing["state"],
            }
        if existing and existing["state"] == "completed" and not force_if_completed:
            return {
                "queued": False, "reused": True,
                "workerJobId": existing["id"], "state": existing["state"],
            }
        if self.worker:
            job, reused = self.worker.enqueue(
                job_type="evaluation_recompute", payload=payload,
                idempotency_key=key, priority=1, max_attempts=3,
            )
        else:
            job, reused = self.store.enqueue_worker_job(
                job_type="evaluation_recompute", payload=payload,
                idempotency_key=key, priority=1, max_attempts=3,
                next_attempt_at=_utc_now(), parent_job_id=None, now=_utc_now(),
            )
        return {"queued": True, "reused": reused, "workerJobId": job["id"], "state": job["state"]}

    def recompute_evaluations(
        self, payload: Any, *, cancelled: Any = lambda: False,
        progress: Any = lambda _stage, _value=None: None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Evaluation worker payload is invalid", code="invalid_worker_payload")
        allowed = {"schemaVersion", "scope", "jobId", "trackId", "after"}
        if set(payload) - allowed or payload.get("schemaVersion") != "evaluation-recompute@1":
            raise JobhuntError("Evaluation worker payload is invalid", code="invalid_worker_payload")
        scope = str(payload.get("scope") or "")
        if scope not in {"profile", "job", "track", "pair"}:
            raise JobhuntError("Evaluation worker scope is invalid", code="invalid_worker_payload")
        job_id = str(payload.get("jobId") or "") or None
        track_id = str(payload.get("trackId") or "") or None
        if scope in {"job", "pair"} and not job_id:
            raise JobhuntError("Evaluation worker payload is missing jobId", code="invalid_worker_payload")
        if scope in {"track", "pair"} and not track_id:
            raise JobhuntError("Evaluation worker payload is missing trackId", code="invalid_worker_payload")
        batch_size = 50
        pairs = self.store.eligible_evaluation_pairs(
            scope=scope, job_id=job_id, track_id=track_id,
            after=str(payload.get("after") or "") or None,
            limit=batch_size + 1, automatic=True,
        )
        work = pairs[:batch_size]
        created = reused_count = 0
        evaluation_ids = []
        progress("evaluation_recompute", 0.05)
        for index, pair in enumerate(work):
            if cancelled():
                raise JobhuntError("Evaluation recompute cancelled", code="cancelled")
            evaluation, reused = self.evaluate_job_track(
                pair["job_id"], pair["track_id"], explicit=False,
            )
            evaluation_ids.append(evaluation["id"])
            reused_count += int(reused)
            created += int(not reused)
            progress("evaluation_recompute", 0.05 + (0.85 * (index + 1) / max(1, len(work))))
        result: dict[str, Any] = {
            "scope": scope, "processed": len(work), "created": created,
            "reused": reused_count, "evaluationIds": evaluation_ids,
            "evaluatorVersion": EVALUATOR_VERSION,
            "evaluationSchemaVersion": EVALUATION_SCHEMA_VERSION,
        }
        if len(pairs) > batch_size and work:
            next_payload = {**payload, "after": work[-1]["cursor"]}
            next_key = "evaluation:batch:" + _sha(_canonical_bytes(next_payload))
            result["followups"] = [{
                "job_type": "evaluation_recompute", "payload": next_payload,
                "idempotency_key": next_key, "priority": 1, "max_attempts": 3,
                "next_attempt_at": _utc_now(),
            }]
        progress("evaluation_recompute_complete", 0.95)
        return result

    @staticmethod
    def _source_to_api(source: dict[str, Any]) -> dict[str, Any]:
        access_method = (
            "official_email_alert" if source.get("source_key") == "pracuj"
            else source["access_method"]
        )
        return {
            "id": source["id"], "key": source["source_key"],
            "displayName": source["display_name"], "category": source["source_category"],
            "expectedAccessMethod": source["expected_access_method"],
            "homeUrl": source.get("home_url"), "definitionState": source["definition_state"],
            "adapter": {
                "key": source.get("adapter_key"), "version": source.get("adapter_version"),
                "implemented": bool(source.get("adapter_implemented")),
            },
            "policy": {
                "accessMethod": access_method, "enabled": bool(source["enabled"]),
                "operationalState": source["operational_state"],
                "pollingCadenceSeconds": source.get("polling_cadence_seconds"),
                "maximumRequestBudget": source.get("maximum_request_budget"),
                "concurrencyLimit": source.get("concurrency_limit"),
                "conditionalRequestsSupported": (
                    None if source.get("conditional_requests_supported") is None
                    else bool(source["conditional_requests_supported"])
                ),
                "lastAttemptAt": source.get("last_attempt_at"),
                "lastSuccessAt": source.get("last_success_at"),
                "failureCount": int(source.get("failure_count") or 0),
                "backoffUntil": source.get("backoff_until"),
                "lastErrorClass": source.get("last_error_class"),
                "lastErrorMessage": source.get("last_error_message"),
                "termsReviewedAt": source.get("terms_reviewed_at"),
                "termsReference": source.get("terms_reference"),
                "termsVersion": source.get("terms_version"),
                "robotsReviewedAt": source.get("robots_reviewed_at"),
                "notes": source.get("policy_notes"),
                "updatedAt": source.get("policy_updated_at"),
            },
            "notes": source.get("notes"),
            "listingCount": int(source.get("listing_count") or 0),
            "activeListingCount": int(source.get("active_listing_count") or 0),
            "matchedListingCount": int(source.get("matched_listing_count") or 0),
            "captureCount": int(source.get("capture_count") or 0),
            "collectionCaptureCount": int(source.get("collection_capture_count") or 0),
            "collectionImplemented": bool(source.get("adapter_implemented")),
            "collectionStatus": (
                "Manual import available" if source["source_key"] == "manual"
                else "Official feed available" if source["source_key"] == "nav"
                else "Official JobAlert email available" if source["source_key"] == "pracuj"
                else "Official Public API available" if source["source_key"] == "jobbnorge"
                else "Collection not implemented"
            ),
            "createdAt": source["created_at"], "updatedAt": source["updated_at"],
        }

    def list_sources(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "sources": [self._source_to_api(item) for item in self.store.list_sources()],
            "networkCollectionImplemented": True,
        }}

    def get_source(self, source_id: str) -> dict[str, Any]:
        source = self.store.get_source(source_id)
        if not source:
            raise JobhuntError("Source not found", status=404, code="source_not_found")
        return {"ok": True, "data": {"source": self._source_to_api(source)}}

    def attach_worker(self, worker: Any) -> None:
        self.worker = worker

    def _prepare_dedupe_context(self, job_id: str) -> dict[str, Any] | None:
        context = self.store.dedupe_job_context(job_id)
        if not context or context["job"].get("merged_into_job_id"):
            return None
        description_parts = [str(context["job"].get("original_text") or "")]
        description_parts.extend(
            str(fact.get("source_wording") or "") for fact in context.get("facts", [])
            if fact.get("fact_type") in {
                "responsibility", "requirement_other", "skill", "tool", "experience",
                "education", "language", "certification", "other",
            }
        )
        for capture in context.get("captures", [])[:3]:
            try:
                raw = self.raw_archive.read_verified(
                    relative_path=capture["relative_path"],
                    expected_hash=capture["blob_sha256"],
                    expected_size=int(capture["byte_size"]),
                )
                description_parts.append(raw[:40_000].decode("utf-8", errors="replace"))
            except (OSError, JobhuntError):
                continue
        context["description"] = "\n".join(description_parts)[:60_000]
        key = build_job_key(context)
        key["rule_version"] = DEDUPE_RULE_VERSION
        context["dedupe_key"] = key
        normalized_urls = []
        for item in context.get("urls", []):
            normalized = normalize_url(item.get("url"))
            if normalized:
                normalized_urls.append({
                    "normalized_url": normalized,
                    "kind": item.get("kind") if item.get("kind") in {
                        "listing", "application", "source_fact",
                    } else "listing",
                })
        self.store.save_dedupe_job_key(job_id, key, normalized_urls, now=_utc_now())
        return context

    @staticmethod
    def _application_is_meaningful(context: dict[str, Any]) -> bool:
        application = context.get("application") or {}
        if application.get("current_status") not in {None, "new", "to_review"}:
            return True
        if application.get("priority") not in {None, "unknown"}:
            return True
        if application.get("next_action") not in {None, "analyze"}:
            return True
        if any(application.get(field) not in {None, ""} for field in (
            "date_applied", "follow_up_date", "recruiter_name", "recruiter_contact", "notes",
        )):
            return True
        non_meaningful_events = {"created", "extraction_projection_created"}
        return any(
            event.get("event_type") not in non_meaningful_events
            for event in context.get("application_events", [])
        )

    def _merge_safety(
        self, left: dict[str, Any], right: dict[str, Any], *, requested_survivor: str | None = None,
    ) -> dict[str, Any]:
        left_id, right_id = left["job"]["id"], right["job"]["id"]
        meaningful = {
            left_id: self._application_is_meaningful(left),
            right_id: self._application_is_meaningful(right),
        }
        override_maps = {}
        for context in (left, right):
            override_maps[context["job"]["id"]] = {
                item["field_name"]: item["replacement_value_json"]
                for item in context.get("overrides", [])
            }
        override_conflicts = sorted(
            field for field in set(override_maps[left_id]) & set(override_maps[right_id])
            if override_maps[left_id][field] != override_maps[right_id][field]
        )
        if requested_survivor:
            survivor = requested_survivor
        elif meaningful[left_id] != meaningful[right_id]:
            survivor = left_id if meaningful[left_id] else right_id
        elif bool(override_maps[left_id]) != bool(override_maps[right_id]):
            survivor = left_id if override_maps[left_id] else right_id
        else:
            survivor = min(
                (left["job"], right["job"]),
                key=lambda item: (str(item.get("created_at") or ""), str(item["id"])),
            )["id"]
        absorbed = right_id if survivor == left_id else left_id
        blockers = []
        if meaningful[left_id] and meaningful[right_id]:
            blockers.append("both_applications_have_meaningful_history")
        if meaningful[absorbed] and not meaningful[survivor]:
            blockers.append("meaningful_application_must_survive")
        if override_conflicts:
            blockers.append("conflicting_active_human_overrides")
        missing_absorbed_overrides = sorted(
            field for field, value in override_maps[absorbed].items()
            if override_maps[survivor].get(field) != value
        )
        if missing_absorbed_overrides:
            blockers.append("absorbed_job_overrides_would_lose_precedence")
        return {
            "safe": not blockers,
            "survivorJobId": survivor,
            "absorbedJobId": absorbed,
            "blockers": blockers,
            "applicationHandling": {
                "meaningfulByJob": meaningful,
                "decision": "preserve_survivor_and_alias_absorbed_application",
                "applicationEventsRewritten": False,
            },
            "trackHandling": {
                "decision": "union_active_assignments_on_survivor",
                "discoveryContextRemainsOnSourceListings": True,
            },
            "overrideHandling": {
                "decision": "retain_overrides_on_original_canonical_identity",
                "conflictingFields": override_conflicts,
                "absorbedFieldsWithoutEquivalentSurvivorOverride": missing_absorbed_overrides,
            },
        }

    @staticmethod
    def _candidate_to_api(candidate: dict[str, Any]) -> dict[str, Any]:
        left = {
            "id": candidate["left_job_id"], "company": candidate.get("left_company"),
            "title": candidate.get("left_title"), "city": candidate.get("left_city"),
            "country": candidate.get("left_country"),
            "publishedAt": candidate.get("left_published_at"),
        }
        right = {
            "id": candidate["right_job_id"], "company": candidate.get("right_company"),
            "title": candidate.get("right_title"), "city": candidate.get("right_city"),
            "country": candidate.get("right_country"),
            "publishedAt": candidate.get("right_published_at"),
        }
        return {
            "id": candidate["id"], "leftJob": left, "rightJob": right,
            "pairKey": candidate["pair_key"], "ruleVersion": candidate["rule_version"],
            "evidenceFingerprint": candidate["evidence_fingerprint"],
            "state": candidate["state"], "confidenceClass": candidate["confidence_class"],
            "reasonCodes": candidate["reason_codes"], "evidence": candidate["evidence"],
            "hardContradictions": candidate["hard_contradictions"],
            "generatedAt": candidate["generated_at"], "updatedAt": candidate["updated_at"],
            "reviewedAt": candidate.get("reviewed_at"), "resolution": candidate.get("resolution"),
        }

    def scan_job_for_duplicates(self, job_id: str, *, force_reopen: bool = False) -> dict[str, Any]:
        context = self._prepare_dedupe_context(job_id)
        if context is None:
            return {"jobId": job_id, "outcome": "inactive_or_merged", "candidates": [], "autoMerges": []}
        for other_id in self.store.unindexed_dedupe_job_ids(
            job_id, limit=MAX_COMPANY_BLOCK_CANDIDATES
        ):
            self._prepare_dedupe_context(other_id)
        candidate_ids = self.store.blocked_dedupe_job_ids(
            job_id, context["dedupe_key"], publication_window_days=PUBLICATION_WINDOW_DAYS,
            url_limit=MAX_URL_BLOCK_CANDIDATES,
            company_limit=MAX_COMPANY_BLOCK_CANDIDATES,
        )
        candidates = []
        auto_merges = []
        for other_id in candidate_ids:
            other = self._prepare_dedupe_context(other_id)
            if other is None:
                continue
            comparison = compare_jobs(context, other)
            if comparison is None:
                continue
            candidate, _created, _changed = self.store.save_duplicate_candidate(
                left_job_id=job_id, right_job_id=other_id, comparison=comparison,
                now=_utc_now(), force_reopen=force_reopen,
            )
            candidates.append(candidate["id"])
            if (
                not force_reopen
                and comparison["auto_merge_eligible"]
                and candidate["state"] == "open"
            ):
                safety = self._merge_safety(context, other)
                if safety["safe"]:
                    merged = self._merge_duplicate_candidate(
                        candidate, context, other, safety=safety,
                        origin="deterministic_auto", note=None,
                    )
                    auto_merges.append(merged["id"])
                    break
        return {
            "jobId": job_id, "outcome": "scanned", "ruleVersion": DEDUPE_RULE_VERSION,
            "boundedComparisons": len(candidate_ids), "candidateIds": candidates,
            "autoMergeIds": auto_merges,
        }

    def _schedule_dedupe_scan(self, job_id: str | None, revision_token: Any) -> dict[str, Any] | None:
        if not job_id:
            return None
        token = str(revision_token or "current")
        if self.worker:
            job, reused = self.worker.enqueue(
                job_type="dedupe_scan_job",
                payload={"jobId": job_id, "revisionToken": token},
                idempotency_key=f"dedupe:{job_id}:{hashlib.sha256(token.encode('utf-8')).hexdigest()[:24]}",
                priority=2, max_attempts=3,
            )
            return {"queued": True, "reused": reused, "workerJobId": job["id"]}
        return {"queued": False, "result": self.scan_job_for_duplicates(job_id)}

    def _reproject_job(
        self, job_id: str, *, evaluation_token: str | None = None,
    ) -> dict[str, Any] | None:
        latest = self.store.latest_listing_for_job(job_id)
        if not latest:
            row = self.store.get_offer_row(job_id, include_deleted=True)
            if row and not row.get("merged_into_job_id"):
                self._schedule_evaluation_recompute(
                    scope="job", job_id=job_id,
                    token=evaluation_token or str(row.get("updated_at") or "canonical-current"),
                )
            return None
        projection = self.store.project_listing(latest[0], capture_id=latest[1], now=_utc_now())
        self._schedule_evaluation_recompute(
            scope="job", job_id=projection.get("job_id") or job_id,
            token=evaluation_token or str(projection.get("projection_id") or latest[1]),
        )
        return projection

    def _merge_duplicate_candidate(
        self, candidate: dict[str, Any], left: dict[str, Any], right: dict[str, Any], *,
        safety: dict[str, Any], origin: str, note: str | None,
    ) -> dict[str, Any]:
        comparison = compare_jobs(left, right)
        if not comparison or comparison["evidence_fingerprint"] != candidate["evidence_fingerprint"]:
            raise JobhuntError(
                "Duplicate candidate evidence changed; rescan before merging",
                status=409, code="duplicate_candidate_stale",
            )
        if comparison["hard_contradictions"]:
            raise JobhuntError(
                "Hard duplicate contradictions must be resolved before merging",
                status=409, code="duplicate_hard_contradiction",
                details=list(comparison["hard_contradictions"]),
            )
        if not safety["safe"]:
            raise JobhuntError(
                "Duplicate merge is not currently safe",
                status=409, code="duplicate_merge_unsafe", details=list(safety["blockers"]),
            )
        reason = (
            f"Automatically merged by {DEDUPE_RULE_VERSION}: "
            + ", ".join(comparison["reason_codes"])
            if origin == "deterministic_auto"
            else f"Confirmed by local user under {DEDUPE_RULE_VERSION}: "
            + ", ".join(comparison["reason_codes"])
        )
        merge = self.store.merge_canonical_jobs(
            candidate_id=candidate["id"], survivor_job_id=safety["survivorJobId"],
            origin=origin, rule_version=DEDUPE_RULE_VERSION,
            evidence_fingerprint=comparison["evidence_fingerprint"], reason=reason,
            note=note, application_handling=safety["applicationHandling"],
            track_handling=safety["trackHandling"], override_handling=safety["overrideHandling"],
            now=_utc_now(),
        )
        self.store.prune_ineligible_evaluation_current([
            merge["survivor_job_id"], merge["absorbed_job_id"],
        ])
        projection = self._reproject_job(
            safety["survivorJobId"], evaluation_token=f"merge:{merge['id']}",
        )
        refreshed = next(
            (item for item in self.store.list_canonical_job_merges(state=None, limit=500)
             if item["id"] == merge["id"]),
            merge,
        )
        refreshed["reprojection"] = projection
        return refreshed

    @staticmethod
    def _dedupe_context_to_api(context: dict[str, Any]) -> dict[str, Any]:
        job = context["job"]
        return {
            "job": {
                "id": job["id"], "company": job["company"], "title": job["role_title"],
                "location": {"city": job["location_city"], "country": job["location_country"],
                             "workMode": job["work_mode"]},
                "salary": {"min": job.get("salary_min"), "max": job.get("salary_max"),
                           "currency": job.get("salary_currency"), "period": job.get("salary_period")},
                "publishedAt": context.get("publication_at") or job.get("source_captured_at"),
                "expiresAt": context.get("expiration_at") or job.get("expires_at"),
            },
            "sources": [{
                "listingId": item["id"], "source": item["source_key"],
                "externalId": item.get("external_id"), "lifecycleState": item["lifecycle_state"],
                "firstSeenAt": item["first_seen_at"], "lastSeenAt": item["last_seen_at"],
                "canonicalUrl": item.get("canonical_url"), "observedUrl": item.get("observed_url"),
            } for item in context.get("listings", [])],
            "application": {
                "meaningful": JobhuntService._application_is_meaningful(context),
                "status": (context.get("application") or {}).get("current_status"),
                "eventCount": len(context.get("application_events", [])),
            },
            "tracks": [{
                "trackId": item["track_id"], "origin": item["origin"],
                "active": bool(item["active"]),
            } for item in context.get("tracks", [])],
            "overrides": [{
                "id": item["id"], "field": item["field_name"],
                "replacement": json.loads(item["replacement_value_json"]),
            } for item in context.get("overrides", [])],
        }

    def list_duplicates(self, *, state: Any = "open", limit: Any = 200) -> dict[str, Any]:
        if state in (None, "all"):
            safe_state = None
        elif state in {"open", "merged", "not_duplicate", "dismissed", "stale"}:
            safe_state = str(state)
        else:
            raise JobhuntError("Duplicate candidate state is invalid", code="invalid_duplicate_state")
        try:
            safe_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError) as exc:
            raise JobhuntError("limit must be an integer", code="invalid_pagination") from exc
        items = self.store.list_duplicate_candidates(state=safe_state, limit=safe_limit)
        return {"ok": True, "data": {
            "items": [self._candidate_to_api(item) for item in items],
            "summary": self.store.dedupe_summary(), "limit": safe_limit,
        }}

    def get_duplicate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.store.get_duplicate_candidate(candidate_id)
        if not candidate:
            raise JobhuntError("Duplicate candidate not found", status=404, code="duplicate_candidate_not_found")
        left = self._prepare_dedupe_context(candidate["left_job_id"])
        right = self._prepare_dedupe_context(candidate["right_job_id"])
        safety = None
        current = False
        if left and right:
            comparison = compare_jobs(left, right)
            current = bool(
                comparison and comparison["evidence_fingerprint"] == candidate["evidence_fingerprint"]
            )
            safety = self._merge_safety(left, right)
            if comparison and comparison["hard_contradictions"]:
                safety["safe"] = False
                safety["blockers"] = list(dict.fromkeys(
                    safety["blockers"] + comparison["hard_contradictions"]
                ))
        api_candidate = self._candidate_to_api(candidate)
        api_candidate["events"] = [{
            "id": item["id"], "type": item["event_type"], "origin": item["origin"],
            "payload": item.get("payload") or {}, "createdAt": item["created_at"],
        } for item in candidate.get("events", [])]
        return {"ok": True, "data": {
            "candidate": api_candidate,
            "comparison": {
                "left": self._dedupe_context_to_api(left) if left else None,
                "right": self._dedupe_context_to_api(right) if right else None,
            },
            "safety": safety, "evidenceCurrent": current,
        }}

    @staticmethod
    def _duplicate_decision_payload(payload: Any) -> str:
        if payload is None:
            payload = {}
        if not isinstance(payload, dict) or set(payload) - {"note"}:
            raise JobhuntError("Duplicate decision accepts only note", code="invalid_duplicate_decision")
        return str(payload.get("note") or "")[:2000]

    def decide_duplicate(self, candidate_id: str, payload: Any, *, dismissed: bool) -> dict[str, Any]:
        note = self._duplicate_decision_payload(payload)
        state = "dismissed" if dismissed else "not_duplicate"
        resolution = note or ("deferred_by_local_user" if dismissed else "confirmed_not_duplicate")
        candidate = self.store.decide_duplicate_candidate(
            candidate_id, state=state, resolution=resolution, now=_utc_now()
        )
        return {"ok": True, "data": {"candidate": self._candidate_to_api(candidate)}}

    def merge_duplicate(self, candidate_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {"survivorJobId", "note", "confirm"}:
            raise JobhuntError("Duplicate merge payload is invalid", code="invalid_duplicate_merge")
        if payload.get("confirm") is not True:
            raise JobhuntError("Duplicate merge requires explicit confirmation", code="duplicate_merge_confirmation_required")
        candidate = self.store.get_duplicate_candidate(candidate_id)
        if not candidate:
            raise JobhuntError("Duplicate candidate not found", status=404, code="duplicate_candidate_not_found")
        if candidate["state"] != "open":
            raise JobhuntError("Duplicate candidate is no longer open", status=409, code="duplicate_candidate_stale")
        left = self._prepare_dedupe_context(candidate["left_job_id"])
        right = self._prepare_dedupe_context(candidate["right_job_id"])
        if not left or not right:
            raise JobhuntError("Duplicate candidate is stale", status=409, code="duplicate_candidate_stale")
        requested = str(payload.get("survivorJobId") or "") or None
        if requested and requested not in {candidate["left_job_id"], candidate["right_job_id"]}:
            raise JobhuntError("Survivor must belong to the duplicate pair", code="invalid_merge_survivor")
        safety = self._merge_safety(left, right, requested_survivor=requested)
        merge = self._merge_duplicate_candidate(
            candidate, left, right, safety=safety, origin="manual_user",
            note=str(payload.get("note") or "")[:2000] or None,
        )
        return {"ok": True, "data": {"merge": self._merge_to_api(merge)}}

    @staticmethod
    def _merge_to_api(merge: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": merge["id"], "candidateId": merge.get("candidate_id"),
            "survivorJobId": merge["survivor_job_id"],
            "absorbedJobId": merge["absorbed_job_id"], "origin": merge["origin"],
            "ruleVersion": merge["rule_version"], "state": merge["state"],
            "reason": merge["reason"], "note": merge.get("note"),
            "affectedListingIds": merge.get("affected_listing_ids") or [],
            "applicationHandling": merge.get("application_handling") or {},
            "trackHandling": merge.get("track_handling") or {},
            "overrideHandling": merge.get("override_handling") or {},
            "mergedAt": merge["merged_at"], "revertedAt": merge.get("reverted_at"),
            "survivor": {
                "company": merge.get("survivor_company"), "title": merge.get("survivor_title"),
            },
            "absorbed": {
                "company": merge.get("absorbed_company"), "title": merge.get("absorbed_title"),
            },
        }

    def list_dedupe_merges(self, *, state: Any = None, limit: Any = 200) -> dict[str, Any]:
        if state not in (None, "", "all", "active", "reverted"):
            raise JobhuntError("Merge state is invalid", code="invalid_merge_state")
        try:
            safe_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError) as exc:
            raise JobhuntError("limit must be an integer", code="invalid_pagination") from exc
        merges = self.store.list_canonical_job_merges(
            state=None if state in (None, "", "all") else str(state), limit=safe_limit,
        )
        return {"ok": True, "data": {
            "items": [self._merge_to_api(item) for item in merges],
            "summary": self.store.dedupe_summary(), "limit": safe_limit,
        }}

    def get_dedupe_merge(self, merge_id: str) -> dict[str, Any]:
        merge = self.store.get_canonical_job_merge(merge_id)
        if not merge:
            raise JobhuntError("Canonical Job merge not found", status=404, code="merge_not_found")
        result = self._merge_to_api(merge)
        result["events"] = [{
            "id": item["id"], "type": item["event_type"], "origin": item["origin"],
            "payload": item.get("payload") or {}, "createdAt": item["created_at"],
        } for item in merge.get("events", [])]
        return {"ok": True, "data": {"merge": result}}

    def unmerge(self, merge_id: str, payload: Any = None) -> dict[str, Any]:
        note = self._duplicate_decision_payload(payload)
        merge = self.store.unmerge_canonical_jobs(
            merge_id, note=note or None, now=_utc_now()
        )
        self.store.prune_ineligible_evaluation_current([
            merge["survivor_job_id"], merge["absorbed_job_id"],
        ])
        for job_id in (merge["survivor_job_id"], merge["absorbed_job_id"]):
            self._reproject_job(
                job_id,
                evaluation_token=f"unmerge:{merge_id}:{merge.get('reverted_at')}:{job_id}",
            )
        return self.get_dedupe_merge(merge_id)

    def dedupe_summary(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "summary": self.store.dedupe_summary(),
            "denominators": {
                "sourceListings": "Independent source advertisements/observations.",
                "canonicalJobs": "Active deduplicated opportunity identities.",
                "rawCaptures": "Immutable source observations over time.",
            },
            "ruleVersion": DEDUPE_RULE_VERSION,
        }}

    def explicit_dedupe_scan(self, job_id: str, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        if not self.store.get_offer_row(job_id, include_deleted=True):
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        return {"ok": True, "data": self.scan_job_for_duplicates(job_id, force_reopen=True)}

    @staticmethod
    def _worker_job_to_api(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job["id"], "type": job["job_type"], "state": job["state"],
            "stage": job["stage"], "progress": job.get("progress"),
            "attemptCount": int(job.get("attempt_count") or 0),
            "maxAttempts": int(job.get("max_attempts") or 0),
            "nextAttemptAt": job.get("next_attempt_at"),
            "cancellationRequested": bool(job.get("cancellation_requested")),
            "parentJobId": job.get("parent_job_id"),
            "createdAt": job.get("created_at"), "startedAt": job.get("started_at"),
            "updatedAt": job.get("updated_at"), "completedAt": job.get("completed_at"),
            "error": ({"class": job.get("error_class"), "message": job.get("error_message")}
                      if job.get("error_class") or job.get("error_message") else None),
            "result": job.get("result"),
            "cancellable": job["state"] in {"queued", "running", "retry_wait"},
        }

    def worker_status(self) -> dict[str, Any]:
        status = self.worker.status() if self.worker else {
            "state": "stopped", "workerCount": 0, "counts": self.store.worker_job_counts()
        }
        return {"ok": True, "data": {"worker": status}}

    def list_worker_jobs(self, *, states: Any = None, limit: Any = 100) -> dict[str, Any]:
        requested = []
        if states:
            requested = [item.strip() for item in str(states).split(",") if item.strip()]
            allowed = {"queued", "running", "retry_wait", "completed", "failed", "cancelled"}
            if any(item not in allowed for item in requested):
                raise JobhuntError("Worker job state filter is invalid", code="invalid_worker_state")
        try:
            safe_limit = max(1, min(200, int(limit)))
        except (TypeError, ValueError) as exc:
            raise JobhuntError("limit must be an integer", code="invalid_pagination") from exc
        jobs = self.store.list_worker_jobs(states=requested or None, limit=safe_limit)
        return {"ok": True, "data": {
            "jobs": [self._worker_job_to_api(job) for job in jobs],
            "counts": self.store.worker_job_counts(), "limit": safe_limit,
        }}

    def get_worker_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_worker_job(job_id)
        if not job:
            raise JobhuntError("Worker job not found", status=404, code="worker_job_not_found")
        return {"ok": True, "data": {"job": self._worker_job_to_api(job)}}

    def cancel_worker_job(self, job_id: str) -> dict[str, Any]:
        if not self.worker:
            raise JobhuntError("Job Hunt worker is unavailable", status=503, code="worker_unavailable")
        return {"ok": True, "data": {
            "job": self._worker_job_to_api(self.worker.cancel(job_id))
        }}

    def _nav_source(self) -> dict[str, Any]:
        source = self.store.get_source(NAV_SOURCE_ID)
        if not source:
            raise JobhuntError("NAV source not found", status=404, code="source_not_found")
        return source

    def nav_status(self) -> dict[str, Any]:
        source = self._nav_source()
        state = self.store.get_source_sync_state(NAV_SOURCE_ID)
        recent = self.store.list_source_requests(NAV_SOURCE_ID, limit=10)
        return {"ok": True, "data": {
            "source": self._source_to_api(source),
            "tokenConfigured": bool(self.nav_adapter.token_configured),
            "worker": (self.worker.status() if self.worker else {
                "state": "stopped", "workerCount": 0,
                "counts": self.store.worker_job_counts(),
            }),
            "feedState": state,
            "recentRequests": recent,
        }}

    def nav_feed_state(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "feedState": self.store.get_source_sync_state(NAV_SOURCE_ID),
            "recentRequests": self.store.list_source_requests(NAV_SOURCE_ID, limit=50),
        }}

    def _require_nav_worker(self) -> Any:
        if not self.worker:
            raise JobhuntError("Job Hunt worker is unavailable", status=503, code="worker_unavailable")
        return self.worker

    def ensure_nav_poll_scheduled(self) -> dict[str, Any] | None:
        source = self._nav_source()
        if not source.get("enabled") or not self.nav_adapter.token_configured or not self.worker:
            return None
        state = self.store.get_source_sync_state(NAV_SOURCE_ID) or {}
        path = str(state.get("feed_path") or NAV_INITIAL_FEED_PATH)
        job, reused = self.worker.enqueue(
            job_type="nav_feed_poll", payload={"source": "nav", "feedPath": path},
            idempotency_key="nav-poll:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:24],
            priority=20, max_attempts=8,
            next_attempt_at=source.get("backoff_until") or _utc_now(),
        )
        return {"job": job, "reused": reused}

    @staticmethod
    def _empty_command(payload: Any) -> None:
        if payload not in (None, {}):
            raise JobhuntError("Command payload must be empty", code="invalid_command_payload")

    def nav_enable(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        if not self.nav_adapter.token_configured:
            raise JobhuntError(
                "Configure JOBHUNT_NAV_TOKEN before enabling NAV collection",
                status=409, code="nav_token_not_configured",
            )
        self.store.set_source_enabled(NAV_SOURCE_ID, enabled=True, now=_utc_now())
        scheduled = self.ensure_nav_poll_scheduled()
        data = self.nav_status()["data"]
        data["scheduledJob"] = (
            self._worker_job_to_api(scheduled["job"]) if scheduled else None
        )
        data["jobReused"] = bool(scheduled and scheduled["reused"])
        return {"ok": True, "data": data}

    def nav_pause(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        self.store.set_source_enabled(NAV_SOURCE_ID, enabled=False, now=_utc_now())
        cancelled = self.store.cancel_source_jobs("nav", now=_utc_now())
        if self.worker:
            self.worker.notify()
        data = self.nav_status()["data"]
        data["cancelledJobs"] = cancelled
        return {"ok": True, "data": data}

    def nav_sync(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        source = self._nav_source()
        if not source.get("enabled"):
            raise JobhuntError("NAV collection is paused", status=409, code="nav_source_paused")
        if not self.nav_adapter.token_configured:
            raise JobhuntError("NAV token is not configured", status=409, code="nav_token_not_configured")
        worker = self._require_nav_worker()
        state = self.store.get_source_sync_state(NAV_SOURCE_ID) or {}
        path = str(state.get("feed_path") or NAV_INITIAL_FEED_PATH)
        job, reused = worker.enqueue(
            job_type="nav_feed_poll", payload={"source": "nav", "feedPath": path},
            idempotency_key="nav-poll:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:24],
            priority=100, max_attempts=8,
            next_attempt_at=source.get("backoff_until") or _utc_now(),
        )
        return {"ok": True, "data": {
            "job": self._worker_job_to_api(job), "reused": reused,
            "message": "NAV sync queued; the HTTP request did not traverse the feed.",
        }}

    def _jobbnorge_source(self) -> dict[str, Any]:
        source = self.store.get_source(JOBBNORGE_SOURCE_ID)
        if not source:
            raise JobhuntError("Jobbnorge source not found", status=404, code="source_not_found")
        return source

    @staticmethod
    def _query_state_to_api(state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not state:
            return None
        return {
            "adapterVersion": state.get("adapter_version"),
            "cycleId": state.get("cycle_id"),
            "queryFingerprint": state.get("query_fingerprint"),
            "currentQueryIndex": int(state.get("current_query_index") or 0),
            "currentPage": int(state.get("current_page") or 1),
            "pagesFetched": int(state.get("pages_fetched") or 0),
            "requestsMade": int(state.get("requests_made") or 0),
            "jobsObservedCycle": int(state.get("jobs_observed_cycle") or 0),
            "responseBytesCycle": int(state.get("response_bytes_cycle") or 0),
            "queryCount": int(state.get("query_count") or 0),
            "lastRequestPath": state.get("last_request_path"),
            "lastCollectionCaptureId": state.get("last_collection_capture_id"),
            "cycleStartedAt": state.get("cycle_started_at"),
            "cycleCompletedAt": state.get("cycle_completed_at"),
            "lastPollAt": state.get("last_poll_at"),
            "lastSuccessAt": state.get("last_success_at"),
            "lastErrorClass": state.get("last_error_class"),
            "lastErrorMessage": state.get("last_error_message"),
            "listingsObserved": int(state.get("listings_observed") or 0),
            "matchedListings": int(state.get("matched_listings") or 0),
            "capturesCreated": int(state.get("captures_created") or 0),
            "updatedAt": state.get("updated_at"),
        }

    def jobbnorge_status(self) -> dict[str, Any]:
        source = self._jobbnorge_source()
        return {"ok": True, "data": {
            "source": self._source_to_api(source),
            "auth": {"required": False, "configured": True, "scheme": None},
            "api": {
                "host": "https://publicapi.jobbnorge.no", "version": "v1",
                "route": "/v1/Jobs", "singleJobEndpoint": False,
            },
            "queryState": self._query_state_to_api(
                self.store.get_query_sync_state(JOBBNORGE_SOURCE_ID)
            ),
            "recentRequests": self.store.list_source_requests(JOBBNORGE_SOURCE_ID, limit=10),
            "worker": (self.worker.status() if self.worker else {
                "state": "stopped", "workerCount": 0,
                "counts": self.store.worker_job_counts(),
            }),
        }}

    def jobbnorge_sync_state(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "queryState": self._query_state_to_api(
                self.store.get_query_sync_state(JOBBNORGE_SOURCE_ID)
            ),
            "recentRequests": self.store.list_source_requests(JOBBNORGE_SOURCE_ID, limit=50),
        }}

    @staticmethod
    def _jobbnorge_cycle_id() -> str:
        return "cycle-" + uuid.uuid4().hex[:20]

    def ensure_jobbnorge_poll_scheduled(self) -> dict[str, Any] | None:
        source = self._jobbnorge_source()
        if not source.get("enabled") or not self.worker:
            return None
        state = self.store.get_query_sync_state(JOBBNORGE_SOURCE_ID) or {}
        cycle_id = (
            str(state.get("cycle_id"))
            if state.get("cycle_id") and not state.get("cycle_completed_at")
            else self._jobbnorge_cycle_id()
        )
        query_index = int(state.get("current_query_index") or 0)
        page = int(state.get("current_page") or 1)
        job, reused = self.worker.enqueue(
            job_type="jobbnorge_poll",
            payload={
                "source": "jobbnorge", "cycleId": cycle_id,
                "queryIndex": query_index, "page": page,
            },
            idempotency_key=f"jobbnorge-poll:{cycle_id}:{query_index}:{page}",
            priority=20, max_attempts=6,
            next_attempt_at=source.get("backoff_until") or _utc_now(),
        )
        return {"job": job, "reused": reused}

    def jobbnorge_enable(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        self._require_nav_worker()
        self.store.set_source_enabled(JOBBNORGE_SOURCE_ID, enabled=True, now=_utc_now())
        scheduled = self.ensure_jobbnorge_poll_scheduled()
        data = self.jobbnorge_status()["data"]
        data["scheduledJob"] = self._worker_job_to_api(scheduled["job"]) if scheduled else None
        data["jobReused"] = bool(scheduled and scheduled["reused"])
        return {"ok": True, "data": data}

    def jobbnorge_pause(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        self.store.set_source_enabled(JOBBNORGE_SOURCE_ID, enabled=False, now=_utc_now())
        cancelled = self.store.cancel_source_jobs("jobbnorge", now=_utc_now())
        if self.worker:
            self.worker.notify()
        data = self.jobbnorge_status()["data"]
        data["cancelledJobs"] = cancelled
        return {"ok": True, "data": data}

    def jobbnorge_sync(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        source = self._jobbnorge_source()
        if not source.get("enabled"):
            raise JobhuntError(
                "Jobbnorge collection is paused", status=409, code="jobbnorge_source_paused"
            )
        worker = self._require_nav_worker()
        cycle_id = self._jobbnorge_cycle_id()
        job, reused = worker.enqueue(
            job_type="jobbnorge_poll",
            payload={"source": "jobbnorge", "cycleId": cycle_id, "queryIndex": 0, "page": 1},
            idempotency_key=f"jobbnorge-poll:{cycle_id}:0:1",
            priority=100, max_attempts=6,
            next_attempt_at=source.get("backoff_until") or _utc_now(),
        )
        return {"ok": True, "data": {
            "job": self._worker_job_to_api(job), "reused": reused,
            "message": "Jobbnorge sync queued; this request did not call the Public API inline.",
        }}

    def _pracuj_source(self) -> dict[str, Any]:
        source = self.store.get_source(PRACUJ_SOURCE_ID)
        if not source:
            raise JobhuntError("Pracuj source not found", status=404, code="source_not_found")
        return source

    @staticmethod
    def _mail_state_to_api(state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not state:
            return None
        return {
            "adapterVersion": state.get("adapter_version"),
            "mailbox": state.get("mailbox"),
            "uidValidity": state.get("uidvalidity"),
            "lastProcessedUid": int(state.get("last_processed_uid") or 0),
            "highestObservedUid": int(state.get("highest_observed_uid") or 0),
            "bootstrapStartedAt": state.get("bootstrap_started_at"),
            "bootstrapCompletedAt": state.get("bootstrap_completed_at"),
            "bootstrapDays": int(state.get("bootstrap_days") or 0),
            "bootstrapMaxMessages": int(state.get("bootstrap_max_messages") or 0),
            "lastPollAt": state.get("last_poll_at"),
            "lastSuccessAt": state.get("last_success_at"),
            "lastSuccessfulMessageAt": state.get("last_successful_message_at"),
            "messagesInspected": int(state.get("messages_inspected") or 0),
            "alertsRecognized": int(state.get("alerts_recognized") or 0),
            "listingsDiscovered": int(state.get("listings_discovered") or 0),
            "capturesCreated": int(state.get("captures_created") or 0),
            "lastErrorClass": state.get("last_error_class"),
            "lastErrorMessage": state.get("last_error_message"),
            "updatedAt": state.get("updated_at"),
        }

    def pracuj_status(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "source": self._source_to_api(self._pracuj_source()),
            "mailConfig": self.mail_transport.safe_config(),
            "mailState": self._mail_state_to_api(self.store.get_mail_sync_state(PRACUJ_SOURCE_ID)),
            "worker": (self.worker.status() if self.worker else {
                "state": "stopped", "workerCount": 0,
                "counts": self.store.worker_job_counts(),
            }),
        }}

    def pracuj_mail_state(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "mailConfig": self.mail_transport.safe_config(),
            "mailState": self._mail_state_to_api(self.store.get_mail_sync_state(PRACUJ_SOURCE_ID)),
        }}

    @staticmethod
    def _binding_to_api(binding: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": binding["id"],
            "subjectMatcher": binding.get("subject_matcher"),
            "searchProfileId": binding["search_profile_id"],
            "searchProfileName": binding.get("search_profile_name"),
            "trackId": binding.get("track_id"),
            "trackName": binding.get("track_name"),
            "enabled": bool(binding.get("enabled")),
            "createdAt": binding.get("created_at"),
            "updatedAt": binding.get("updated_at"),
        }

    def pracuj_bindings(self) -> dict[str, Any]:
        return {"ok": True, "data": {
            "bindings": [self._binding_to_api(item) for item in self.store.list_pracuj_bindings()]
        }}

    def _validate_pracuj_binding(
        self, payload: Any, *, current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Binding payload must be an object", code="invalid_binding")
        unknown = set(payload) - {"subjectMatcher", "searchProfileId", "enabled"}
        if unknown:
            raise JobhuntError("Binding contains unsupported fields", code="invalid_binding", details=sorted(unknown))
        profile_id = str(payload.get("searchProfileId") or (current or {}).get("search_profile_id") or "").strip()
        if not profile_id:
            raise JobhuntError("searchProfileId is required", code="invalid_binding")
        matcher_value = payload.get("subjectMatcher", (current or {}).get("subject_matcher"))
        matcher = self._bounded_optional_text(matcher_value, "subjectMatcher", limit=200)
        enabled_value = payload.get("enabled", bool((current or {}).get("enabled", True)))
        if not isinstance(enabled_value, bool):
            raise JobhuntError("enabled must be boolean", code="invalid_binding")
        return {"subject_matcher": matcher, "search_profile_id": profile_id, "enabled": enabled_value}

    def create_pracuj_binding(self, payload: Any) -> dict[str, Any]:
        values = self._validate_pracuj_binding(payload)
        binding = self.store.save_pracuj_binding(binding_id=None, now=_utc_now(), **values)
        return {"ok": True, "data": {"binding": self._binding_to_api(binding)}}

    def update_pracuj_binding(self, binding_id: str, payload: Any) -> dict[str, Any]:
        current = next((item for item in self.store.list_pracuj_bindings() if item["id"] == binding_id), None)
        if not current:
            raise JobhuntError("Pracuj alert binding not found", status=404, code="binding_not_found")
        values = self._validate_pracuj_binding(payload, current=current)
        binding = self.store.save_pracuj_binding(binding_id=binding_id, now=_utc_now(), **values)
        return {"ok": True, "data": {"binding": self._binding_to_api(binding)}}

    def ensure_pracuj_poll_scheduled(self) -> dict[str, Any] | None:
        source = self._pracuj_source()
        if not source.get("enabled") or not self.mail_transport.configured or not self.worker:
            return None
        job, reused = self.worker.enqueue(
            job_type="pracuj_mail_poll",
            payload={"source": "pracuj"},
            idempotency_key="pracuj-mail-poll",
            priority=20,
            max_attempts=8,
            next_attempt_at=source.get("backoff_until") or _utc_now(),
        )
        return {"job": job, "reused": reused}

    def pracuj_enable(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        if not self.mail_transport.configured:
            raise JobhuntError(
                "Configure the backend-only Pracuj IMAP settings before enabling collection",
                status=409, code="pracuj_mailbox_not_configured",
            )
        self.store.set_source_enabled(PRACUJ_SOURCE_ID, enabled=True, now=_utc_now())
        scheduled = self.ensure_pracuj_poll_scheduled()
        data = self.pracuj_status()["data"]
        data["scheduledJob"] = self._worker_job_to_api(scheduled["job"]) if scheduled else None
        data["jobReused"] = bool(scheduled and scheduled["reused"])
        return {"ok": True, "data": data}

    def pracuj_pause(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        self.store.set_source_enabled(PRACUJ_SOURCE_ID, enabled=False, now=_utc_now())
        cancelled = self.store.cancel_source_jobs("pracuj", now=_utc_now())
        if self.worker:
            self.worker.notify()
        data = self.pracuj_status()["data"]
        data["cancelledJobs"] = cancelled
        return {"ok": True, "data": data}

    def pracuj_sync(self, payload: Any = None) -> dict[str, Any]:
        self._empty_command(payload)
        source = self._pracuj_source()
        if not source.get("enabled"):
            raise JobhuntError("Pracuj collection is paused", status=409, code="pracuj_source_paused")
        if not self.mail_transport.configured:
            raise JobhuntError("Pracuj mailbox is not configured", status=409, code="pracuj_mailbox_not_configured")
        worker = self._require_nav_worker()
        job, reused = worker.enqueue(
            job_type="pracuj_mail_poll",
            payload={"source": "pracuj"},
            idempotency_key="pracuj-mail-poll",
            priority=100,
            max_attempts=8,
            next_attempt_at=source.get("backoff_until") or _utc_now(),
        )
        return {"ok": True, "data": {
            "job": self._worker_job_to_api(job), "reused": reused,
            "message": "Pracuj mailbox sync queued; this request did not access the mailbox.",
        }}

    def run_worker_job(self, job: dict[str, Any], *, cancelled: Any, progress: Any) -> dict[str, Any]:
        payload = job.get("payload") or {}
        job_type = job["job_type"]
        if job_type == "nav_feed_poll":
            return self.nav_coordinator.poll_feed(payload, cancelled=cancelled, progress=progress)
        if job_type == "nav_fetch_listing":
            return self.nav_coordinator.fetch_listing(payload, cancelled=cancelled, progress=progress)
        if job_type == "extract_capture":
            capture_id = str(payload.get("captureId") or "")
            progress("extracting_capture", 0.2)
            response = self.extract_capture(capture_id)
            result = {"captureId": capture_id, "extraction": response.get("data")}
            ai_auto_ready = (
                payload.get("source") == "nav"
                and capture_id
                and enabled(self.environment.get("JOBHUNT_NAV_AUTO_AI"))
                and (self.ai_provider_injected or enabled(self.environment.get("JOBHUNT_AI_ENABLED")))
                and bool(self.ai_provider.health().get("configured"))
            )
            if ai_auto_ready:
                result["followups"] = [{
                    "job_type": "ai_extract_capture",
                    "payload": {"source": "nav", "captureId": capture_id},
                    "idempotency_key": f"ai:{capture_id}:{AI_EXTRACTOR_VERSION}",
                    "priority": 1, "max_attempts": 2, "next_attempt_at": _utc_now(),
                }]
            progress("extraction_complete", 0.95)
            return result
        if job_type == "ai_extract_capture":
            capture_id = str(payload.get("captureId") or "")
            progress("ai_extracting_capture", 0.2)
            response = self.ai_extract_capture(capture_id)
            progress("ai_extraction_complete", 0.95)
            return {"captureId": capture_id, "aiExtraction": response.get("data")}
        if job_type == "dedupe_scan_job":
            job_id = str(payload.get("jobId") or "")
            if not job_id:
                raise JobhuntError("Dedupe scan job is missing jobId", code="invalid_worker_payload")
            progress("dedupe_scanning", 0.2)
            result = self.scan_job_for_duplicates(job_id)
            progress("dedupe_scan_complete", 0.95)
            return result
        if job_type == "evaluation_recompute":
            return self.recompute_evaluations(
                payload, cancelled=cancelled, progress=progress,
            )
        if job_type == "pracuj_mail_poll":
            return self.pracuj_coordinator.poll_mail(
                payload, cancelled=cancelled, progress=progress
            )
        if job_type == "pracuj_process_message":
            return self.pracuj_coordinator.process_message(
                payload, cancelled=cancelled, progress=progress
            )
        if job_type == "jobbnorge_poll":
            return self.jobbnorge_coordinator.poll(
                payload, cancelled=cancelled, progress=progress
            )
        raise JobhuntError("Unsupported worker job type", code="unsupported_worker_job")

    def record_worker_failure(
        self, job: dict[str, Any], error: Exception, *, classification: str,
        backoff_until: str | None,
    ) -> None:
        source_key = (job.get("payload") or {}).get("source")
        if source_key not in {"nav", "pracuj", "jobbnorge"}:
            return
        if job.get("job_type") == "ai_extract_capture":
            return
        if classification in {"cancelled", "policy_stop"}:
            return
        message = str(error) or f"{source_key} worker job failed"
        secrets = [
            str(self.environment.get("JOBHUNT_NAV_TOKEN") or ""),
            str(self.environment.get("JOBHUNT_PRACUJ_IMAP_PASSWORD") or ""),
            str(self.environment.get("JOBHUNT_PRACUJ_IMAP_USER") or ""),
        ]
        for secret in secrets:
            if secret:
                message = message.replace(secret, "[redacted]")
        now = _utc_now()
        source_id = {
            "nav": NAV_SOURCE_ID,
            "pracuj": PRACUJ_SOURCE_ID,
            "jobbnorge": JOBBNORGE_SOURCE_ID,
        }[source_key]
        if source_key == "pracuj" and classification in {"authentication", "tls"} and not backoff_until:
            backoff_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        self.store.record_source_failure(
            source_id, error_class=classification, error_message=message,
            backoff_until=backoff_until, now=now,
        )
        if source_key == "nav":
            self.store.update_source_sync_state(
                NAV_SOURCE_ID,
                {"last_error_class": classification, "last_error_message": message},
                now=now,
            )
        elif source_key == "pracuj":
            self.store.update_mail_sync_state(
                PRACUJ_SOURCE_ID,
                {"last_error_class": classification, "last_error_message": message},
                now=now,
            )
        else:
            self.store.update_query_sync_state(
                JOBBNORGE_SOURCE_ID,
                {"last_error_class": classification, "last_error_message": message},
                now=now,
            )

    @staticmethod
    def _canonical_source_url(value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise JobhuntError("Source URL is invalid", code="invalid_source_url") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise JobhuntError("Source URL must use http or https", code="invalid_source_url")
        if parsed.username is not None or parsed.password is not None:
            raise JobhuntError("Source URL must not include credentials", code="invalid_source_url")
        host = parsed.hostname.lower()
        try:
            port = parsed.port
        except ValueError as exc:
            raise JobhuntError("Source URL has an invalid port", code="invalid_source_url") from exc
        if port and not ((parsed.scheme.lower() == "http" and port == 80)
                         or (parsed.scheme.lower() == "https" and port == 443)):
            host = f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", parsed.query, ""))

    @staticmethod
    def _capture_to_api(capture: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": capture["id"], "listingId": capture["listing_id"],
            "sha256": capture["blob_sha256"], "byteSize": int(capture["byte_size"]),
            "contentType": capture["mime_type"], "fileExtension": capture["file_extension"],
            "capturedAt": capture["captured_at"], "inputMethod": capture["input_method"],
            "sourceUrl": capture.get("source_url"), "httpStatus": capture.get("http_status"),
            "metadata": capture.get("safe_metadata") or {},
            "changeState": capture.get("change_state"), "createdAt": capture["created_at"],
        }

    @staticmethod
    def _listing_to_api(listing: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": listing["id"],
            "source": {"id": listing["source_id"], "key": listing["source_key"],
                       "displayName": listing["source_name"]},
            "externalId": listing.get("external_id"),
            "canonicalUrl": listing.get("canonical_url"), "observedUrl": listing.get("observed_url"),
            "hints": {"title": listing.get("title_hint"), "company": listing.get("company_hint"),
                      "location": listing.get("location_hint")},
            "lifecycleState": listing["lifecycle_state"],
            "firstSeenAt": listing["first_seen_at"], "lastSeenAt": listing["last_seen_at"],
            "sourceEndedAt": listing.get("source_ended_at"),
            "canonicalJobId": listing.get("canonical_job_id"), "notes": listing.get("notes"),
            "captureCount": int(listing.get("capture_count") or 0),
            "latestCaptureId": listing.get("latest_capture_id"),
            "latestCaptureAt": listing.get("latest_capture_at"),
            "tracks": [{
                "id": item["id"], "name": item["name"], "slug": item["slug"],
                "discoveredAt": item["discovered_at"], "notes": item.get("notes"),
            } for item in listing.get("tracks", [])],
            "searchProfiles": [{
                "id": item["id"], "name": item["name"], "trackId": item["track_id"],
                "discoveredAt": item["discovered_at"], "notes": item.get("notes"),
            } for item in listing.get("search_profiles", [])],
            "collectionEvidence": [{
                "collectionCaptureId": item["collection_capture_id"],
                "collectionSha256": item.get("blob_sha256"),
                "itemIndex": int(item["item_index"]),
                "jsonPointer": item["json_pointer"],
                "externalId": item["external_id"],
                "derivedCaptureId": item.get("derived_capture_id"),
                "requestPath": item.get("request_path"),
                "queryFingerprint": item.get("query_fingerprint"),
                "page": item.get("page_number"),
                "httpStatus": item.get("http_status"),
                "responseBytes": item.get("response_bytes"),
                "capturedAt": item.get("captured_at"),
            } for item in listing.get("collection_evidence", [])],
            "createdAt": listing["created_at"], "updatedAt": listing["updated_at"],
        }

    def list_source_listings(self, *, source_id: Any = None, limit: Any = 200, offset: Any = 0) -> dict[str, Any]:
        try:
            safe_limit = max(1, min(500, int(limit)))
            safe_offset = max(0, int(offset))
        except (TypeError, ValueError) as exc:
            raise JobhuntError("limit and offset must be integers", code="invalid_pagination") from exc
        resolved_source_id = None
        if source_id:
            source = self.store.get_source(str(source_id))
            if not source:
                raise JobhuntError("Source not found", status=404, code="source_not_found")
            resolved_source_id = source["id"]
        listings = self.store.list_source_listings(
            source_id=resolved_source_id, limit=safe_limit, offset=safe_offset
        )
        return {"ok": True, "data": {
            "listings": [self._listing_to_api(item) for item in listings],
            "limit": safe_limit, "offset": safe_offset,
        }}

    def get_source_listing(self, listing_id: str) -> dict[str, Any]:
        listing = self.store.get_source_listing(listing_id)
        if not listing:
            raise JobhuntError("Source Listing not found", status=404, code="source_listing_not_found")
        captures = [self._capture_to_api(item) for item in self.store.list_captures(listing_id)]
        return {"ok": True, "data": {
            "listing": self._listing_to_api(listing), "captures": captures,
        }}

    def list_listing_captures(self, listing_id: str) -> dict[str, Any]:
        if not self.store.get_source_listing(listing_id):
            raise JobhuntError("Source Listing not found", status=404, code="source_listing_not_found")
        return {"ok": True, "data": {
            "listingId": listing_id,
            "captures": [self._capture_to_api(item) for item in self.store.list_captures(listing_id)],
        }}

    def get_raw_capture(self, capture_id: str) -> dict[str, Any]:
        capture = self.store.get_capture(capture_id)
        if not capture:
            raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
        raw = self.raw_archive.read_verified(
            relative_path=capture["relative_path"], expected_hash=capture["blob_sha256"],
            expected_size=int(capture["byte_size"]),
        )
        if capture["mime_type"] == "message/rfc822":
            metadata = capture.get("safe_metadata") or {}
            content = str(metadata.get("itemSourceWording") or "Exact RFC822 message stored privately.")
        else:
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise JobhuntError("Raw Capture is not valid UTF-8", status=409, code="raw_blob_corrupt") from exc
        return {"ok": True, "data": {
            "capture": self._capture_to_api(capture), "content": content,
            "rendering": "inert_text_only",
        }}

    def _manual_content(self, payload: dict[str, Any]) -> tuple[bytes, str, str, str, dict[str, Any]]:
        mode = payload.get("inputMode", "text")
        if mode not in {"text", "html", "json", "file"}:
            raise JobhuntError("Manual input mode is invalid", code="invalid_manual_input")
        metadata: dict[str, Any] = {"adapterKey": "manual", "adapterVersion": "1.0.0"}
        if mode == "file":
            filename = self._bounded_optional_text(payload.get("filename"), "filename", limit=240)
            if not filename or Path(filename).name != filename:
                raise JobhuntError("Upload filename is invalid", code="invalid_manual_file")
            extension = Path(filename).suffix.lower()
            mime_type = RAW_FILE_EXTENSIONS.get(extension)
            if not mime_type:
                raise JobhuntError("Only .txt, .html, .htm, and .json files are supported", code="invalid_manual_file")
            encoded = payload.get("contentBase64")
            if not isinstance(encoded, str):
                raise JobhuntError("File content is required", code="invalid_manual_file")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise JobhuntError("File content is not valid base64", code="invalid_manual_file") from exc
            metadata["originalFilename"] = filename
            metadata["browserContentType"] = self._bounded_optional_text(
                payload.get("declaredContentType"), "declaredContentType", limit=120
            )
            extension = RAW_MIME_EXTENSIONS[mime_type]
            input_method = "manual_file"
        else:
            expected_mime = {"text": "text/plain", "html": "text/html", "json": "application/json"}[mode]
            supplied_mime = payload.get("contentType", expected_mime)
            if supplied_mime != expected_mime:
                raise JobhuntError("Content type does not match the selected input mode", code="invalid_manual_mime")
            value = payload.get("content")
            if not isinstance(value, str):
                raise JobhuntError("Manual content must be text", code="invalid_manual_input")
            content = value.encode("utf-8")
            mime_type = expected_mime
            extension = RAW_MIME_EXTENSIONS[mime_type]
            input_method = "manual_paste"
        if not content:
            raise JobhuntError("Manual content cannot be empty", code="empty_manual_content")
        if len(content) > MAX_RAW_CAPTURE_BYTES:
            raise JobhuntError("Raw advertisement exceeds the 1 MB limit", status=413, code="raw_capture_too_large")
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JobhuntError("Uploaded files must be UTF-8 text", code="invalid_manual_encoding") from exc
        if "\x00" in decoded:
            raise JobhuntError("Raw advertisement contains unsupported NUL bytes", code="invalid_manual_content")
        if mime_type == "application/json":
            try:
                json.loads(decoded)
            except json.JSONDecodeError as exc:
                raise JobhuntError("JSON capture must contain valid JSON", code="invalid_manual_json") from exc
        return content, mime_type, extension, input_method, metadata

    def manual_import(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Manual import payload must be an object", code="invalid_manual_import")
        allowed = {
            "sourceId", "sourceKey", "originalUrl", "externalListingId", "titleHint",
            "companyHint", "locationHint", "trackId", "searchProfileId", "canonicalJobId",
            "lifecycleState", "sourceEndedAt", "notes", "inputMode", "contentType", "content",
            "filename", "contentBase64", "declaredContentType", "forceNewListing",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise JobhuntError("Manual import contains unsupported fields", code="unknown_manual_import_fields", details=unknown)
        source_ref = payload.get("sourceId") or payload.get("sourceKey") or "manual"
        source = self.store.get_source(str(source_ref))
        if not source:
            raise JobhuntError("Source not found", status=404, code="source_not_found")
        original_url = self._bounded_optional_text(payload.get("originalUrl"), "originalUrl", limit=2048)
        canonical_url = self._canonical_source_url(original_url)
        external_id = self._bounded_optional_text(payload.get("externalListingId"), "externalListingId", limit=300)
        title_hint = self._bounded_optional_text(payload.get("titleHint"), "titleHint", limit=500)
        company_hint = self._bounded_optional_text(payload.get("companyHint"), "companyHint", limit=500)
        location_hint = self._bounded_optional_text(payload.get("locationHint"), "locationHint", limit=500)
        notes = self._bounded_optional_text(payload.get("notes"), "notes", limit=8000)
        track_id = self._bounded_optional_text(payload.get("trackId"), "trackId", limit=200)
        profile_id = self._bounded_optional_text(payload.get("searchProfileId"), "searchProfileId", limit=200)
        canonical_job_id = self._bounded_optional_text(payload.get("canonicalJobId"), "canonicalJobId", limit=200)
        lifecycle = payload.get("lifecycleState", "unknown")
        if lifecycle not in LISTING_STATES:
            raise JobhuntError("Source Listing lifecycle state is invalid", code="invalid_listing_state")
        source_ended_at = self._bounded_optional_text(payload.get("sourceEndedAt"), "sourceEndedAt", limit=80)
        if lifecycle in {"expired", "removed"} and not source_ended_at:
            source_ended_at = _utc_now()
        content, mime_type, extension, input_method, metadata = self._manual_content(payload)
        digest = _sha(content)
        if external_id:
            identity_key = "external:" + hashlib.sha256(external_id.encode("utf-8")).hexdigest()
        elif canonical_url:
            identity_key = "url:" + hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
        else:
            identity_key = "content:" + digest
        if payload.get("forceNewListing") is True:
            identity_key = "explicit:" + uuid.uuid4().hex
        elif payload.get("forceNewListing") not in {None, False}:
            raise JobhuntError("forceNewListing must be true or false", code="invalid_manual_import")
        now = _utc_now()
        result = self.manual_import_adapter.ingest(
            content=content, mime_type=mime_type, extension=extension,
            listing={
                "source_id": source["id"], "identity_key": identity_key,
                "external_id": external_id, "canonical_url": canonical_url,
                "observed_url": original_url, "title_hint": title_hint,
                "company_hint": company_hint, "location_hint": location_hint,
                "lifecycle_state": lifecycle, "source_ended_at": source_ended_at,
                "canonical_job_id": canonical_job_id, "notes": notes,
            },
            capture={"input_method": input_method, "source_url": original_url, "safe_metadata": metadata},
            track_id=track_id, search_profile_id=profile_id, observed_at=now,
        )
        listing = self.store.get_source_listing(result["listing_id"])
        return {"ok": True, "data": {
            "listing": self._listing_to_api(listing),
            "capture": self._capture_to_api(result["capture"]),
            "listingCreated": result["listing_created"],
            "captureReused": result["capture_reused"],
            "blobCreated": result["blob_created"], "blobReused": not result["blob_created"],
            "adapter": {"key": "manual", "version": "1.0.0"},
            "parsingPerformed": False,
        }}

    def storage_health(self) -> dict[str, Any]:
        rows = self.store.raw_blob_rows()
        missing: list[dict[str, Any]] = []
        corrupt: list[dict[str, Any]] = []
        referenced_paths = {item["relative_path"] for item in rows}
        for item in rows:
            target = self.raw_archive.resolve(item["relative_path"])
            if not target.is_file():
                missing.append({"sha256": item["sha256"], "reason": "missing"})
                continue
            size, digest = hash_file(target)
            if size != int(item["byte_size"]) or digest != item["sha256"]:
                corrupt.append({
                    "sha256": item["sha256"], "expectedSize": int(item["byte_size"]),
                    "observedSize": size, "hashMismatch": digest != item["sha256"],
                })
        orphan_hashes = []
        for path in self.raw_archive.blob_files():
            relative = path.relative_to(self.private_root).as_posix()
            if relative not in referenced_paths:
                candidate = path.stem.lower()
                orphan_hashes.append(
                    candidate if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate)
                    else "unexpected-file"
                )
        metrics = self.store.ingestion_metrics()
        return {"ok": True, "data": {
            **metrics, "blobsChecked": len(rows), "capturesChecked": metrics["captures"],
            "missingCount": len(missing), "corruptCount": len(corrupt),
            "orphanCount": len(orphan_hashes), "healthy": not missing and not corrupt,
            "missing": missing, "corrupt": corrupt,
            "orphanHashes": orphan_hashes[:100], "checkedAt": _utc_now(),
        }}

    @staticmethod
    def _extraction_run_to_api(run: dict[str, Any], *, reused: bool | None = None) -> dict[str, Any]:
        result = {
            "id": run["id"], "captureId": run["capture_id"],
            "extractorKind": run["extractor_kind"], "extractorVersion": run["extractor_version"],
            "inputHash": run["input_hash"], "outputSchemaVersion": run["output_schema_version"],
            "startedAt": run["started_at"], "completedAt": run.get("completed_at"),
            "status": run["status"], "validationStatus": run["validation_status"],
            "factCount": int(run.get("fact_count") or 0),
            "warningCount": int(run.get("warning_count") or 0),
            "warnings": run.get("warnings") or [], "errorClass": run.get("error_class"),
            "errorMessage": run.get("error_message"), "createdAt": run["created_at"],
        }
        if reused is not None:
            result["reused"] = reused
        if run.get("extractor_kind") == "ai":
            result["ai"] = {
                "provider": run.get("ai_provider"),
                "providerAdapterVersion": run.get("ai_provider_adapter_version"),
                "model": run.get("ai_model"), "modelVersion": run.get("ai_model_version"),
                "promptId": run.get("ai_prompt_id"), "promptVersion": run.get("ai_prompt_version"),
                "promptFingerprint": run.get("ai_prompt_fingerprint"),
                "responseSchemaVersion": run.get("ai_response_schema_version"),
                "requestedAt": run.get("ai_requested_at"), "respondedAt": run.get("ai_responded_at"),
                "latencyMs": run.get("ai_latency_ms"), "attemptCount": int(run.get("ai_attempt_count") or 0),
                "finishReason": run.get("ai_finish_reason"), "requestId": run.get("ai_provider_request_id"),
                "usage": {
                    "inputTokens": run.get("ai_input_tokens"), "outputTokens": run.get("ai_output_tokens"),
                    "totalTokens": run.get("ai_total_tokens"), "cachedTokens": run.get("ai_cached_tokens"),
                },
                "estimatedCost": run.get("ai_estimated_cost"),
                "costCurrency": run.get("ai_cost_currency"), "priceVersion": run.get("ai_price_version"),
                "validation": run.get("ai_validation_result"),
                "input": {
                    "characters": run.get("ai_input_char_count"), "sentCharacters": run.get("ai_sent_char_count"),
                    "truncated": bool(run.get("ai_input_truncated")),
                    "preparation": run.get("ai_source_preparation"),
                },
            }
        return result

    @staticmethod
    def _fact_to_api(fact: dict[str, Any]) -> dict[str, Any]:
        value = {
            "text": fact.get("value_text"), "number": fact.get("value_number"),
            "boolean": fact.get("value_boolean"), "json": fact.get("value_json"),
        }.get(fact.get("value_type"))
        normalization = fact.get("normalization")
        return {
            "id": fact["id"], "extractionRunId": fact["extraction_run_id"],
            "captureId": fact["capture_id"], "namespace": fact["namespace"],
            "type": fact["fact_type"], "sourceField": fact["source_field"],
            "label": fact.get("label"), "sourceWording": fact["source_wording"],
            "valueType": fact["value_type"], "value": value,
            "unit": fact.get("unit"), "currency": fact.get("currency"),
            "period": fact.get("period"), "requirementPreference": fact["requirement_preference"],
            "state": fact["state"], "confidence": float(fact["confidence"]),
            "evidence": fact["evidence_locator"], "validationState": fact["validation_state"],
            "validationMessage": fact.get("validation_message"),
            "normalizationState": fact["normalization_state"],
            "normalization": None if not normalization else {
                "conceptId": normalization["concept_id"], "conceptType": normalization["concept_type"],
                "conceptKey": normalization["concept_key"], "displayLabel": normalization["display_label"],
                "ruleVersion": normalization["rule_version"],
                "confidence": normalization["confidence"], "origin": normalization["origin"],
                "manual": normalization["is_manual"], "state": normalization["state"],
            },
            "extractor": {
                "kind": fact.get("extractor_kind"), "version": fact.get("extractor_version"),
                "provider": fact.get("ai_provider"),
                "providerAdapterVersion": fact.get("ai_provider_adapter_version"),
                "model": fact.get("ai_model"),
                "promptVersion": fact.get("ai_prompt_version"),
                "promptFingerprint": fact.get("ai_prompt_fingerprint"),
                "responseSchemaVersion": fact.get("ai_response_schema_version"),
            },
            "createdAt": fact["created_at"],
        }

    def _pracuj_extraction_batch(
        self, raw: bytes, capture: dict[str, Any], listing: dict[str, Any]
    ) -> ExtractionBatch:
        parsed = self.pracuj_adapter.parse(raw)
        metadata = capture.get("safe_metadata") or {}
        item_index = int(metadata.get("itemIndex") or 0)
        expected_url = str(metadata.get("pracujUrl") or listing.get("canonical_url") or "")
        item = next((candidate for candidate in parsed.items if candidate.index == item_index), None)
        if item is None and expected_url:
            item = next((candidate for candidate in parsed.items if candidate.url == expected_url), None)
        if item is None:
            raise MailTransportError(
                "The listing-specific item is no longer present in the archived JobAlert.",
                classification="parser_failure",
            )
        base_evidence = {
            "kind": "email_item",
            "messageRecordId": metadata.get("messageRecordId"),
            "mimePart": item.mime_part,
            "itemIndex": item.index,
            "url": item.url,
        }
        facts: list[FactCandidate] = []

        def add(fact_type: str, field: str, value: str | None, *, namespace: str = "job", label: str | None = None) -> None:
            if not value:
                return
            facts.append(FactCandidate(
                namespace=namespace,
                fact_type=fact_type,
                source_field=field,
                source_wording=value[:8000],
                value_type="text",
                value_text=value[:8000],
                label=label,
                confidence=0.98,
                evidence_locator={**base_evidence, "field": field},
            ))

        add("title", "title", item.title)
        add("company", "company", item.company)
        add("location_text", "location", item.location)
        if item.location:
            location_parts = [part.strip() for part in re.split(r"[,|]", item.location) if part.strip()]
            country_names = {
                "poland": "Poland", "polska": "Poland", "norway": "Norway", "norge": "Norway",
                "germany": "Germany", "deutschland": "Germany", "sweden": "Sweden", "sverige": "Sweden",
                "czechia": "Czechia", "czech republic": "Czechia", "slovakia": "Slovakia",
                "united kingdom": "United Kingdom", "uk": "United Kingdom",
            }
            explicit_country = country_names.get(location_parts[-1].casefold()) if len(location_parts) > 1 else None
            if explicit_country:
                add("city", "location.city", location_parts[0])
                add("country", "location.country", explicit_country)
        add("other", "salary", item.salary, namespace="source", label="Salary shown in JobAlert")
        add("other", "url", item.url, namespace="source", label="Pracuj offer URL")
        if item.external_id:
            add("other", "offerId", item.external_id, namespace="source", label="Pracuj offer identifier")
        return ExtractionBatch(
            "manual_hints",
            PRACUJ_PARSER_VERSION,
            tuple(facts),
            tuple(parsed.warnings),
        )

    @staticmethod
    def _jobbnorge_extraction_batch(
        raw: bytes, capture: dict[str, Any], listing: dict[str, Any]
    ) -> ExtractionBatch:
        return jobbnorge_extraction_batch(raw, capture, listing)

    def extract_capture(self, capture_id: str) -> dict[str, Any]:
        capture = self.store.get_capture(capture_id)
        if not capture:
            raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
        listing = self.store.get_source_listing(capture["listing_id"])
        if not listing:
            raise JobhuntError("Source Listing not found", status=404, code="source_listing_not_found")
        now = _utc_now()
        try:
            raw = self.raw_archive.read_verified(
                relative_path=capture["relative_path"], expected_hash=capture["blob_sha256"],
                expected_size=int(capture["byte_size"]),
            )
            if capture.get("input_method") == "jobbnorge_api_derived":
                batches = [self._jobbnorge_extraction_batch(raw, capture, listing)]
            elif capture["mime_type"] == "message/rfc822":
                batches = [self._pracuj_extraction_batch(raw, capture, listing)]
            else:
                content = raw.decode("utf-8")
                batches = extract_batches(content, mime_type=capture["mime_type"], listing=listing)
        except (JobhuntError, UnicodeDecodeError, MailTransportError) as exc:
            self.store.create_review(
                reason="missing_corrupt_raw_capture", severity="error", entity_type="capture",
                entity_id=capture_id, related_fact_ids=[],
                evidence_summary="The immutable capture could not be verified or decoded for extraction.",
                candidates=[], dedupe_key=f"raw:{capture_id}:{capture['blob_sha256']}", now=now,
            )
            self.store.record_failed_extraction(
                capture_id=capture_id,
                # Keep the existing deterministic extractor-kind contract; the
                # source-specific parser identity is carried by the version.
                extractor_kind="manual_hints",
                extractor_version=(PRACUJ_PARSER_VERSION if capture["mime_type"] == "message/rfc822" else "manual_hints@1"),
                input_hash=capture["blob_sha256"],
                output_schema_version=OUTPUT_SCHEMA_VERSION, error_class=type(exc).__name__,
                error_message=str(exc), now=now,
            )
            raise
        except (ValueError, json.JSONDecodeError) as exc:
            jobbnorge_capture = capture.get("input_method") == "jobbnorge_api_derived"
            run = self.store.record_failed_extraction(
                capture_id=capture_id,
                extractor_kind="json_structured" if capture["mime_type"] == "application/json" else "html_metadata",
                extractor_version=(
                    JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION if jobbnorge_capture
                    else "json_structured@1" if capture["mime_type"] == "application/json"
                    else "html_metadata@1"
                ),
                input_hash=capture["blob_sha256"], output_schema_version=OUTPUT_SCHEMA_VERSION,
                error_class=type(exc).__name__, error_message=str(exc), now=now,
            )
            return {"ok": True, "data": {
                "captureId": capture_id, "runs": [self._extraction_run_to_api(run, reused=False)],
                "projection": None, "reviewItemsCreated": 0,
            }}

        saved_runs: list[dict[str, Any]] = []
        malformed_run_ids: list[str] = []
        invalid_salary_run_ids: list[str] = []
        for batch in batches:
            facts = []
            batch_warnings = list(batch.warnings)
            minimums = [item.value_number for item in batch.facts if item.fact_type == "salary_min" and item.value_number is not None]
            maximums = [item.value_number for item in batch.facts if item.fact_type == "salary_max" and item.value_number is not None]
            inconsistent_salary = bool(minimums and maximums and min(minimums) > max(maximums))
            if inconsistent_salary:
                batch_warnings.append("Salary minimum exceeds salary maximum; salary range facts were not projected.")
            for candidate in batch.facts:
                item = asdict(candidate)
                if inconsistent_salary and candidate.fact_type in {"salary_min", "salary_max"}:
                    item["validation_state"] = "invalid"
                    item["validation_message"] = "salary minimum exceeds salary maximum"
                if (candidate.validation_state != "invalid" and candidate.state != "explicit_negative"
                        and candidate.value_type == "text"):
                    matched = concept_match(candidate.fact_type, candidate.value_text or "")
                    if matched:
                        item["normalization"] = {
                            "concept_id": matched[0], "confidence": matched[1],
                            "rule_version": NORMALIZATION_VERSION,
                        }
                    elif candidate.fact_type in {"skill", "tool", "language", "work_model", "contract_type"}:
                        item["normalization_state"] = "unmapped"
                facts.append(item)
            run, reused = self.store.save_extraction_batch(
                capture_id=capture_id, extractor_kind=batch.kind, extractor_version=batch.version,
                input_hash=capture["blob_sha256"], output_schema_version=OUTPUT_SCHEMA_VERSION,
                facts=facts, warnings=batch_warnings, now=now,
            )
            saved_runs.append(self._extraction_run_to_api(run, reused=reused))
            if any("malformed" in warning.casefold() for warning in batch_warnings):
                malformed_run_ids.append(run["id"])
            if inconsistent_salary:
                invalid_salary_run_ids.append(run["id"])

        review_ids: list[str] = []
        for run_id in malformed_run_ids:
            review_ids.append(self.store.create_review(
                reason="malformed_structured_metadata", severity="warning",
                entity_type="extraction_run", entity_id=run_id, related_fact_ids=[],
                evidence_summary="One or more inert JSON-LD blocks were malformed and ignored.",
                candidates=[], dedupe_key=f"malformed:{run_id}", now=now,
            ))
        for run_id in invalid_salary_run_ids:
            salary_facts = [
                fact for fact in self.store.facts_for_run(run_id)
                if fact["fact_type"] in {"salary_min", "salary_max"}
            ]
            review_ids.append(self.store.create_review(
                reason="conflicting_salary", severity="warning",
                entity_type="extraction_run", entity_id=run_id,
                related_fact_ids=[fact["id"] for fact in salary_facts],
                evidence_summary="Salary minimum exceeds salary maximum; invalid range facts were retained but not projected.",
                candidates=[self.store._fact_value(fact) for fact in salary_facts],
                dedupe_key=f"invalid-salary:{run_id}", now=now,
            ))
        projection = self.store.project_listing(capture["listing_id"], capture_id=capture_id, now=now)
        review_ids.extend(projection.get("review_ids") or [])
        dedupe_scan = self._schedule_dedupe_scan(
            projection.get("job_id"), projection.get("projection_id") or capture_id,
        )
        evaluation_recompute = self._schedule_evaluation_recompute(
            scope="job", job_id=projection.get("job_id"),
            token=str(projection.get("projection_id") or capture_id),
        ) if projection.get("job_id") else None
        return {"ok": True, "data": {
            "captureId": capture_id, "runs": saved_runs, "projection": {
                "outcome": projection["outcome"], "canonicalJobId": projection.get("job_id"),
                "projectionId": projection.get("projection_id"),
                "projectionVersion": projection.get("projection_version"),
                "selectedFactIds": projection.get("selected_fact_ids") or [],
                "appliedOverrideIds": projection.get("applied_override_ids") or [],
            }, "reviewItemIds": list(dict.fromkeys(review_ids)),
            "reviewItemsCreated": len(set(review_ids)),
            "dedupeScan": dedupe_scan,
            "evaluationRecompute": evaluation_recompute,
        }}

    @staticmethod
    def _ai_projection_to_api(projection: dict[str, Any] | None) -> dict[str, Any] | None:
        if not projection:
            return None
        return {
            "outcome": projection.get("outcome", "updated"),
            "canonicalJobId": projection.get("job_id"),
            "projectionId": projection.get("projection_id") or projection.get("id"),
            "projectionVersion": projection.get("projection_version"),
            "selectedFactIds": projection.get("selected_fact_ids") or [],
            "appliedOverrideIds": projection.get("applied_override_ids") or [],
        }

    def _ai_daily_usage(self) -> dict[str, int]:
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat(timespec="seconds")
        return self.store.ai_usage_since(start)

    def ai_config_summary(self) -> dict[str, Any]:
        health = self.ai_provider.health()
        usage = self._ai_daily_usage()
        locally_enabled = self.ai_provider_injected or enabled(
            self.environment.get("JOBHUNT_AI_ENABLED")
        )
        configured = bool(health.get("configured")) and locally_enabled
        return {"ok": True, "data": {
            "enabled": locally_enabled,
            "configured": configured,
            "availability": "available" if configured else "unavailable",
            "message": None if configured else "AI extraction unavailable — provider not configured",
            "provider": health.get("provider"), "providerState": health.get("state"),
            "providerReason": health.get("reason"),
            "providerAdapterVersion": health.get("adapterVersion"), "model": health.get("model"),
            "automaticFallback": False, "browserModelSelection": False,
            "prompt": {
                "id": PROMPT_ID, "version": PROMPT_VERSION,
                "fingerprint": self.ai_prompt_fingerprint,
                "responseSchemaVersion": RESPONSE_SCHEMA_VERSION,
            },
            "limits": {
                "maxSourceCharacters": self.ai_max_source_chars,
                "maxDeterministicContextFacts": self.ai_max_context_facts,
                "maxOutputTokens": self.ai_max_output_tokens,
                "maxAttempts": self.ai_max_attempts,
                "dailyCallLimit": self.ai_daily_call_limit or None,
                "dailyTokenLimit": self.ai_daily_token_limit or None,
            },
            "dailyUsage": {
                "requestCount": usage["request_count"], "totalTokens": usage["total_tokens"],
                "callBudgetExceeded": bool(self.ai_daily_call_limit and usage["request_count"] >= self.ai_daily_call_limit),
                "tokenBudgetExceeded": bool(self.ai_daily_token_limit and usage["total_tokens"] >= self.ai_daily_token_limit),
            },
            "costEstimationConfigured": bool(
                self.environment.get("JOBHUNT_AI_PRICE_VERSION")
                and self.environment.get("JOBHUNT_AI_INPUT_USD_PER_MILLION_TOKENS")
                and self.environment.get("JOBHUNT_AI_OUTPUT_USD_PER_MILLION_TOKENS")
            ),
            "privacyNotice": "Advertisement content may be sent to the configured AI provider. Career Profile, assessments, applications, Track preferences, recruiter details, and unrelated dashboard data are not sent.",
        }}

    def ai_status(self) -> dict[str, Any]:
        return self.ai_config_summary()

    def _ai_cost(self, usage: dict[str, int]) -> tuple[float | None, str | None, str | None]:
        version = str(self.environment.get("JOBHUNT_AI_PRICE_VERSION") or "").strip()
        try:
            input_rate = float(str(self.environment.get("JOBHUNT_AI_INPUT_USD_PER_MILLION_TOKENS") or ""))
            output_rate = float(str(self.environment.get("JOBHUNT_AI_OUTPUT_USD_PER_MILLION_TOKENS") or ""))
            cached_raw = self.environment.get("JOBHUNT_AI_CACHED_USD_PER_MILLION_TOKENS")
            cached_rate = input_rate if cached_raw in (None, "") else float(str(cached_raw))
        except (TypeError, ValueError):
            return None, None, None
        if not version or min(input_rate, output_rate, cached_rate) < 0:
            return None, None, None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is None or output_tokens is None:
            return None, None, None
        cached = min(int(usage.get("cached_tokens") or 0), int(input_tokens))
        cost = ((int(input_tokens) - cached) * input_rate + cached * cached_rate + int(output_tokens) * output_rate) / 1_000_000
        return round(cost, 10), "USD", version

    def _ai_reused_projection(self, listing: dict[str, Any]) -> dict[str, Any] | None:
        job_id = listing.get("canonical_job_id")
        projection = self.store.latest_projection(job_id) if job_id else None
        if not projection:
            return None
        return {
            "outcome": "reused", "job_id": job_id, "id": projection["id"],
            "projection_version": projection["projection_version"],
            "selected_fact_ids": projection["selected_fact_ids"],
            "applied_override_ids": projection["applied_override_ids"],
        }

    def ai_extract_capture(self, capture_id: str, payload: Any = None) -> dict[str, Any]:
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise JobhuntError("AI extraction request must be an object", code="invalid_ai_extraction_request")
        unknown = sorted(set(payload) - {"force"})
        if unknown:
            raise JobhuntError(
                "AI extraction request contains unsupported fields",
                code="unknown_ai_extraction_fields", details=unknown,
            )
        force = payload.get("force", False)
        if not isinstance(force, bool):
            raise JobhuntError("force must be boolean", code="invalid_ai_extraction_request")
        capture = self.store.get_capture(capture_id)
        if not capture:
            raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
        listing = self.store.get_source_listing(capture["listing_id"])
        if not listing:
            raise JobhuntError("Source Listing not found", status=404, code="source_listing_not_found")
        if capture["mime_type"] == "message/rfc822":
            raise JobhuntError(
                "AI extraction is disabled for Pracuj JobAlert email captures; deterministic listing-specific extraction is used.",
                status=409,
                code="ai_email_source_not_supported",
            )
        health = self.ai_provider.health()
        locally_enabled = self.ai_provider_injected or enabled(self.environment.get("JOBHUNT_AI_ENABLED"))
        if not locally_enabled or not health.get("configured"):
            raise JobhuntError(
                "AI extraction unavailable — provider not configured",
                status=503, code="ai_provider_not_configured",
            )

        existing_runs = self.store.list_extraction_runs(capture_id)
        if not any(run["extractor_kind"] != "ai" and run["status"] in {"completed", "completed_with_warnings"} for run in existing_runs):
            self.extract_capture(capture_id)

        raw = self.raw_archive.read_verified(
            relative_path=capture["relative_path"], expected_hash=capture["blob_sha256"],
            expected_size=int(capture["byte_size"]),
        )
        try:
            content = raw.decode("utf-8")
            source_text, source_preparation = prepare_source_text(
                content,
                capture["mime_type"],
                redact_contact_fields=(capture.get("source_key") == "nav"),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise JobhuntError("Raw Capture could not be prepared for AI extraction", code="ai_input_invalid") from exc

        identity_material = _canonical_bytes({
            "captureHash": capture["blob_sha256"], "provider": health.get("provider"),
            "adapterVersion": health.get("adapterVersion"), "model": health.get("model"),
            "promptId": PROMPT_ID, "promptVersion": PROMPT_VERSION,
            "promptFingerprint": self.ai_prompt_fingerprint,
            "responseSchemaVersion": RESPONSE_SCHEMA_VERSION,
        })
        idempotency_key = _sha(identity_material)
        run_variant = "default" if not force else f"force:{uuid.uuid4().hex}"
        if not force:
            existing = self.store.find_ai_extraction_run(idempotency_key)
            if existing and existing["status"] in {"completed", "completed_with_warnings"}:
                return {"ok": True, "data": {
                    "captureId": capture_id,
                    "run": self._extraction_run_to_api(existing, reused=True),
                    "projection": self._ai_projection_to_api(self._ai_reused_projection(listing)),
                    "reviewItemIds": [], "reviewItemsCreated": 0,
                }}
            if existing and existing["status"] == "running":
                raise JobhuntError(
                    "An identical AI extraction is already running",
                    status=409, code="ai_extraction_running",
                )
            if existing:
                run_variant = f"retry:{uuid.uuid4().hex}"

        usage_today = self._ai_daily_usage()
        if self.ai_daily_call_limit and usage_today["request_count"] >= self.ai_daily_call_limit:
            raise JobhuntError("Daily AI call budget is exhausted", status=429, code="ai_daily_call_budget_exhausted")
        if self.ai_daily_token_limit and usage_today["total_tokens"] >= self.ai_daily_token_limit:
            raise JobhuntError("Daily AI token budget is exhausted", status=429, code="ai_daily_token_budget_exhausted")

        now = _utc_now()
        input_too_large = len(source_text) > self.ai_max_source_chars
        run = self.store.create_ai_extraction_run(
            capture_id=capture_id, input_hash=capture["blob_sha256"],
            extractor_version=AI_EXTRACTOR_VERSION, output_schema_version=OUTPUT_SCHEMA_VERSION,
            provider=str(health.get("provider") or self.ai_provider.provider_key),
            provider_adapter_version=str(health.get("adapterVersion") or self.ai_provider.adapter_version),
            model=str(health.get("model") or self.ai_provider.model_id),
            prompt_id=PROMPT_ID, prompt_version=PROMPT_VERSION,
            prompt_fingerprint=self.ai_prompt_fingerprint,
            response_schema_version=RESPONSE_SCHEMA_VERSION,
            idempotency_key=idempotency_key,
            run_variant=run_variant,
            input_char_count=len(source_text),
            sent_char_count=0 if input_too_large else len(source_text),
            input_truncated=input_too_large, source_preparation=source_preparation, now=now,
        )
        if input_too_large:
            failed = self.store.fail_ai_extraction(
                run_id=run["id"], error_class="input_too_large",
                error_message="Prepared advertisement exceeds the configured AI input limit",
                validation_result={"valid": False, "inputTruncated": True},
                raw_response=None, attempt_count=0, now=_utc_now(),
            )
            review_id = self.store.create_review(
                reason="ai_input_truncated", severity="warning", entity_type="extraction_run",
                entity_id=run["id"], related_fact_ids=[],
                evidence_summary="The advertisement exceeded the configured AI input limit; no partial extraction was accepted.",
                candidates=[{"characters": len(source_text), "limit": self.ai_max_source_chars}],
                dedupe_key=f"ai-input:{run['id']}", now=_utc_now(),
            )
            return {"ok": True, "data": {
                "captureId": capture_id, "run": self._extraction_run_to_api(failed, reused=False),
                "projection": None, "reviewItemIds": [review_id], "reviewItemsCreated": 1,
            }}

        deterministic_context = []
        for fact in self.store.facts_for_capture(capture_id):
            if fact.get("extractor_kind") == "ai" or fact.get("validation_state") != "valid":
                continue
            deterministic_context.append({
                "type": fact["fact_type"], "state": fact["state"],
                "requirementPreference": fact["requirement_preference"],
                "value": self.store._fact_value(fact),
                "sourceWording": fact["source_wording"][:500],
                "confidence": fact["confidence"],
            })
            if len(deterministic_context) >= self.ai_max_context_facts:
                break
        user_prompt = build_user_prompt(
            capture_id=capture_id, source_type=capture["mime_type"], source_text=source_text,
            source_preparation=source_preparation, deterministic_facts=deterministic_context,
        )
        if len(SYSTEM_PROMPT.encode("utf-8")) + len(user_prompt.encode("utf-8")) > 128 * 1024:
            failed = self.store.fail_ai_extraction(
                run_id=run["id"], error_class="prompt_too_large",
                error_message="Prepared AI prompt exceeds the configured provider prompt limit",
                validation_result={"valid": False, "promptTooLarge": True},
                raw_response=None, attempt_count=0, now=_utc_now(),
            )
            review_id = self.store.create_review(
                reason="ai_input_truncated", severity="warning", entity_type="extraction_run",
                entity_id=run["id"], related_fact_ids=[],
                evidence_summary="The complete prepared prompt exceeded the provider limit; no partial extraction was accepted.",
                candidates=[], dedupe_key=f"ai-prompt:{run['id']}", now=_utc_now(),
            )
            return {"ok": True, "data": {
                "captureId": capture_id, "run": self._extraction_run_to_api(failed, reused=False),
                "projection": None, "reviewItemIds": [review_id], "reviewItemsCreated": 1,
            }}

        request = AIExtractionRequest(
            system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
            response_schema=AI_RESPONSE_JSON_SCHEMA, max_output_tokens=self.ai_max_output_tokens,
        )
        response = None
        last_error: AIProviderError | None = None
        total_latency_ms = 0.0
        attempts = 0
        for attempt in range(1, self.ai_max_attempts + 1):
            if attempt > 1:
                retry_usage = self._ai_daily_usage()
                if self.ai_daily_call_limit and retry_usage["request_count"] >= self.ai_daily_call_limit:
                    last_error = AIProviderError(
                        "Daily AI call budget was reached before retry",
                        code="ai_daily_call_budget_exhausted", classification="budget", status=429,
                    )
                    break
                if self.ai_daily_token_limit and retry_usage["total_tokens"] >= self.ai_daily_token_limit:
                    last_error = AIProviderError(
                        "Daily AI token budget was reached before retry",
                        code="ai_daily_token_budget_exhausted", classification="budget", status=429,
                    )
                    break
            attempts = attempt
            attempt_started = _utc_now()
            measured = time.perf_counter()
            try:
                response = self.ai_provider.extract_facts(request)
                observed_latency = round((time.perf_counter() - measured) * 1000, 3)
                latency = max(float(response.latency_ms or 0.0), observed_latency)
                total_latency_ms += latency
                self.store.record_ai_attempt(
                    run_id=run["id"], attempt_number=attempt, started_at=attempt_started,
                    completed_at=_utc_now(), provider_status="success", error_class=None,
                    error_message=None, provider_request_id=response.request_id,
                    finish_reason=response.finish_reason, usage=response.usage,
                    latency_ms=latency, retryable=False,
                )
                break
            except AIProviderError as exc:
                last_error = exc
                latency = round((time.perf_counter() - measured) * 1000, 3)
                total_latency_ms += latency
                self.store.record_ai_attempt(
                    run_id=run["id"], attempt_number=attempt, started_at=attempt_started,
                    completed_at=_utc_now(), provider_status="failed", error_class=exc.classification,
                    error_message=str(exc), provider_request_id=None, finish_reason=None,
                    usage={}, latency_ms=latency, retryable=exc.retryable,
                )
                if not exc.retryable or attempt >= self.ai_max_attempts:
                    break
                if self.ai_retry_delay_seconds:
                    time.sleep(self.ai_retry_delay_seconds * attempt)
            except Exception as exc:
                latency = round((time.perf_counter() - measured) * 1000, 3)
                total_latency_ms += latency
                last_error = AIProviderError(
                    "AI provider adapter failed unexpectedly",
                    code="ai_provider_internal_error", classification="provider_error",
                    retryable=False, status=502,
                )
                self.store.record_ai_attempt(
                    run_id=run["id"], attempt_number=attempt, started_at=attempt_started,
                    completed_at=_utc_now(), provider_status="failed",
                    error_class=type(exc).__name__, error_message="Provider adapter raised an unexpected exception.",
                    provider_request_id=None, finish_reason=None, usage={},
                    latency_ms=latency, retryable=False,
                )
                break

        if response is None:
            assert last_error is not None
            raw_error = (last_error.raw_response or "")[:MAX_RAW_AI_RESPONSE_BYTES] or None
            failed = self.store.fail_ai_extraction(
                run_id=run["id"], error_class=last_error.classification,
                error_message=str(last_error),
                validation_result={"valid": False, "providerErrorCode": last_error.code},
                raw_response=raw_error, attempt_count=attempts, now=_utc_now(),
            )
            reason = "malformed_ai_response" if last_error.classification == "malformed_response" else (
                "ai_provider_incomplete" if last_error.classification == "incomplete" else "ai_provider_failure"
            )
            review_id = self.store.create_review(
                reason=reason, severity="warning", entity_type="extraction_run", entity_id=run["id"],
                related_fact_ids=[], evidence_summary=f"AI provider output was not accepted: {str(last_error)[:1000]}",
                candidates=[], dedupe_key=f"ai-provider:{run['id']}:{reason}", now=_utc_now(),
            )
            return {"ok": True, "data": {
                "captureId": capture_id, "run": self._extraction_run_to_api(failed, reused=False),
                "projection": None, "reviewItemIds": [review_id], "reviewItemsCreated": 1,
            }}

        if len(response.raw_response.encode("utf-8")) > MAX_RAW_AI_RESPONSE_BYTES:
            schema_error: Exception = AISchemaError("AI response exceeds the stored response limit")
        else:
            try:
                validated = validate_ai_output(response.structured, source_text=source_text)
                schema_error = None
            except AISchemaError as exc:
                schema_error = exc
        if schema_error is not None:
            failed = self.store.fail_ai_extraction(
                run_id=run["id"], error_class="schema_invalid", error_message=str(schema_error),
                validation_result={"valid": False, "schemaError": str(schema_error)},
                raw_response=response.raw_response[:MAX_RAW_AI_RESPONSE_BYTES],
                attempt_count=attempts, now=_utc_now(),
            )
            review_id = self.store.create_review(
                reason="malformed_ai_response", severity="warning", entity_type="extraction_run",
                entity_id=run["id"], related_fact_ids=[],
                evidence_summary=f"AI structured output failed local schema validation: {str(schema_error)[:1000]}",
                candidates=[], dedupe_key=f"ai-schema:{run['id']}", now=_utc_now(),
            )
            return {"ok": True, "data": {
                "captureId": capture_id, "run": self._extraction_run_to_api(failed, reused=False),
                "projection": None, "reviewItemIds": [review_id], "reviewItemsCreated": 1,
            }}

        facts = []
        for candidate in validated.facts:
            item = asdict(candidate)
            if candidate.state != "explicit_negative" and candidate.value_type == "text":
                matched = concept_match(candidate.fact_type, candidate.value_text or "")
                if matched:
                    item["normalization"] = {
                        "concept_id": matched[0], "confidence": matched[1],
                        "rule_version": NORMALIZATION_VERSION,
                    }
                elif candidate.fact_type in {"skill", "tool", "language", "work_model", "contract_type"}:
                    item["normalization_state"] = "unmapped"
            facts.append(item)
        run_warnings = list(validated.warnings)
        run_warnings.extend(f"Rejected AI fact: {item.message}" for item in validated.rejected)
        validation_result = {
            "valid": True, "responseSchemaVersion": RESPONSE_SCHEMA_VERSION,
            "acceptedFacts": len(facts), "rejectedFacts": len(validated.rejected),
            "evidencePolicy": "exact_quote_and_source_wording@1",
            "confidencePolicy": "min(provider_confidence,0.95); not statistically calibrated",
        }
        estimated_cost, cost_currency, price_version = self._ai_cost(response.usage)
        completed = self.store.complete_ai_extraction(
            run_id=run["id"], facts=facts, warnings=run_warnings,
            validation_result=validation_result,
            raw_response=response.raw_response[:MAX_RAW_AI_RESPONSE_BYTES],
            model_version=response.model_version, provider_request_id=response.request_id,
            finish_reason=response.finish_reason, usage=response.usage,
            latency_ms=total_latency_ms, attempt_count=attempts,
            estimated_cost=estimated_cost, cost_currency=cost_currency,
            price_version=price_version, now=_utc_now(),
        )

        review_ids: list[str] = []
        for index, rejected in enumerate(validated.rejected):
            reason = "ai_evidence_not_found" if rejected.reason == "evidence_not_found" else "unsupported_ai_fact"
            review_ids.append(self.store.create_review(
                reason=reason, severity="warning", entity_type="extraction_run", entity_id=run["id"],
                related_fact_ids=[], evidence_summary=f"Rejected AI fact: {rejected.message[:1000]}",
                candidates=[{"type": rejected.candidate.get("type"), "label": rejected.candidate.get("label")}],
                dedupe_key=f"ai-rejected:{run['id']}:{index}:{reason}", now=_utc_now(),
            ))
        saved_ai_facts = self.store.facts_for_run(run["id"])
        low_confidence = [fact for fact in saved_ai_facts if float(fact["confidence"]) < 0.8]
        if low_confidence:
            review_ids.append(self.store.create_review(
                reason="low_confidence", severity="warning", entity_type="extraction_run",
                entity_id=run["id"], related_fact_ids=[fact["id"] for fact in low_confidence],
                evidence_summary="Validated AI facts below the 0.80 review threshold remain preserved and labelled.",
                candidates=[], dedupe_key=f"ai-confidence:{run['id']}", now=_utc_now(),
            ))

        singleton_types = {
            "title", "company", "city", "country", "location_text", "work_model",
            "contract_type", "salary_min", "salary_max", "salary_exact", "salary_currency",
            "salary_period", "salary_tax_type", "valid_through",
        }
        deterministic = [
            fact for fact in self.store.facts_for_capture(capture_id)
            if fact.get("extractor_kind") != "ai" and fact.get("validation_state") == "valid"
        ]
        for fact_type in singleton_types:
            ai_group = [fact for fact in saved_ai_facts if fact["fact_type"] == fact_type]
            deterministic_group = [fact for fact in deterministic if fact["fact_type"] == fact_type]
            if not ai_group or not deterministic_group:
                continue
            ai_values = {json.dumps(self.store._fact_value(fact), ensure_ascii=False, sort_keys=True) for fact in ai_group}
            deterministic_values = {json.dumps(self.store._fact_value(fact), ensure_ascii=False, sort_keys=True) for fact in deterministic_group}
            if ai_values != deterministic_values:
                related = deterministic_group + ai_group
                digest = _sha(_canonical_bytes({"run": run["id"], "type": fact_type, "values": sorted(ai_values | deterministic_values)}))
                review_ids.append(self.store.create_review(
                    reason="source_disagreement", severity="warning", entity_type="extraction_run",
                    entity_id=run["id"], related_fact_ids=[fact["id"] for fact in related],
                    evidence_summary=f"Validated AI and deterministic evidence disagree for {fact_type}; deterministic projection precedence is retained.",
                    candidates=[self.store._fact_value(fact) for fact in related[:20]],
                    dedupe_key=f"ai-conflict:{digest}", now=_utc_now(),
                ))
        projection = self.store.project_listing(capture["listing_id"], capture_id=capture_id, now=_utc_now())
        review_ids.extend(projection.get("review_ids") or [])
        dedupe_scan = self._schedule_dedupe_scan(
            projection.get("job_id"), projection.get("projection_id") or run["id"],
        )
        evaluation_recompute = self._schedule_evaluation_recompute(
            scope="job", job_id=projection.get("job_id"),
            token=str(projection.get("projection_id") or run["id"]),
        ) if projection.get("job_id") else None
        return {"ok": True, "data": {
            "captureId": capture_id, "run": self._extraction_run_to_api(completed, reused=False),
            "projection": self._ai_projection_to_api(projection),
            "reviewItemIds": list(dict.fromkeys(review_ids)),
            "reviewItemsCreated": len(set(review_ids)),
            "dedupeScan": dedupe_scan,
            "evaluationRecompute": evaluation_recompute,
        }}

    def list_capture_extraction_runs(self, capture_id: str) -> dict[str, Any]:
        if not self.store.get_capture(capture_id):
            raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
        return {"ok": True, "data": {
            "captureId": capture_id,
            "runs": [self._extraction_run_to_api(run) for run in self.store.list_extraction_runs(capture_id)],
        }}

    def get_extraction_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_extraction_run(run_id)
        if not run:
            raise JobhuntError("Extraction Run not found", status=404, code="extraction_run_not_found")
        return {"ok": True, "data": {
            "run": self._extraction_run_to_api(run),
            "attempts": self.store.list_ai_attempts(run_id) if run["extractor_kind"] == "ai" else [],
        }}

    def get_extraction_facts(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_extraction_run(run_id)
        if not run:
            raise JobhuntError("Extraction Run not found", status=404, code="extraction_run_not_found")
        facts = self.store.facts_for_run(run_id)
        return {"ok": True, "data": {
            "run": self._extraction_run_to_api(run),
            "facts": [self._fact_to_api(fact) for fact in facts],
            "attempts": self.store.list_ai_attempts(run_id) if run["extractor_kind"] == "ai" else [],
        }}

    def get_job_facts(self, job_id: str) -> dict[str, Any]:
        if not self.store.get_offer_row(job_id):
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        projection = self.store.latest_projection(job_id)
        return {"ok": True, "data": {
            "jobId": job_id, "facts": [self._fact_to_api(fact) for fact in self.store.facts_for_job(job_id)],
            "projection": None if not projection else {
                "id": projection["id"], "version": projection["projection_version"],
                "ruleVersion": projection["rule_version"],
                "selectedFactIds": projection["selected_fact_ids"],
                "appliedOverrideIds": projection["applied_override_ids"],
                "snapshot": projection["snapshot"], "createdAt": projection["created_at"],
            },
            "overrides": [self._override_to_api(item) for item in self.store.list_overrides(job_id)],
        }}

    @staticmethod
    def _review_to_api(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item["id"], "reason": item["reason"], "severity": item["severity"],
            "entityType": item["entity_type"], "entityId": item["entity_id"],
            "relatedFactIds": item["related_fact_ids"], "evidenceSummary": item["evidence_summary"],
            "candidateResolutions": item["candidate_resolutions"], "state": item["state"],
            "createdAt": item["created_at"], "resolvedAt": item.get("resolved_at"),
            "resolution": item.get("resolution"), "note": item.get("note"),
        }

    def list_reviews(self, *, state: Any = "open", limit: Any = 200) -> dict[str, Any]:
        safe_state = str(state or "open")
        if safe_state not in REVIEW_STATES:
            raise JobhuntError("Review state is invalid", code="invalid_review_state")
        try:
            safe_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError) as exc:
            raise JobhuntError("limit must be an integer", code="invalid_pagination") from exc
        items = self.store.list_reviews(state=safe_state, limit=safe_limit)
        return {"ok": True, "data": {"items": [self._review_to_api(item) for item in items]}}

    def get_review(self, review_id: str) -> dict[str, Any]:
        item = self.store.get_review(review_id)
        if not item:
            raise JobhuntError("Review Item not found", status=404, code="review_item_not_found")
        facts = []
        for fact_id in item["related_fact_ids"][:100]:
            with self.store.read_connection() as connection:
                row = connection.execute(self.store._fact_query("f.id=?"), (fact_id,)).fetchone()
            if row:
                facts.append(self._fact_to_api(self.store._decode_fact(row)))
        return {"ok": True, "data": {"item": self._review_to_api(item), "facts": facts}}

    def close_review(self, review_id: str, payload: Any, *, dismissed: bool = False) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Review resolution must be an object", code="invalid_review_resolution")
        unknown = sorted(set(payload) - {"resolution", "note", "override"})
        if unknown:
            raise JobhuntError("Review resolution contains unsupported fields", code="unknown_review_fields", details=unknown)
        item = self.store.get_review(review_id)
        if not item:
            raise JobhuntError("Review Item not found", status=404, code="review_item_not_found")
        override_result = None
        if payload.get("override") is not None:
            if dismissed:
                raise JobhuntError("A dismissed review cannot create an override", code="invalid_review_resolution")
            override = dict(payload["override"]) if isinstance(payload["override"], dict) else None
            if not override or item["entity_type"] != "job":
                raise JobhuntError("This review cannot create a Human Override", code="invalid_review_override")
            override_result = self.create_override(item["entity_id"], override)["data"]
        resolution = self._bounded_optional_text(payload.get("resolution"), "resolution", limit=1000)
        note = self._bounded_optional_text(payload.get("note"), "note", limit=4000)
        self.store.close_review(
            review_id, state="dismissed" if dismissed else "resolved",
            resolution=resolution or ("dismissed" if dismissed else "resolved"), note=note,
            now=_utc_now(),
        )
        return {"ok": True, "data": {
            "item": self._review_to_api(self.store.get_review(review_id)),
            "override": override_result,
        }}

    @staticmethod
    def _override_to_api(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item["id"], "jobId": item["job_id"], "field": item["field_name"],
            "previousValue": json.loads(item["previous_value_json"]) if item.get("previous_value_json") else None,
            "replacementValue": json.loads(item["replacement_value_json"]),
            "reason": item["reason"], "note": item.get("note"), "author": item["author"],
            "state": item["state"], "createdAt": item["created_at"],
            "retiredAt": item.get("retired_at"),
        }

    def create_override(self, job_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Human Override must be an object", code="invalid_human_override")
        unknown = sorted(set(payload) - {"field", "value", "reason", "note"})
        if unknown:
            raise JobhuntError("Human Override contains unsupported fields", code="unknown_override_fields", details=unknown)
        field = str(payload.get("field") or "")
        if field not in OVERRIDE_FIELDS:
            raise JobhuntError("Human Override field is not supported", code="invalid_override_field")
        if "value" not in payload or isinstance(payload.get("value"), (dict, list)):
            raise JobhuntError("Human Override value must be a scalar", code="invalid_override_value")
        value = payload.get("value")
        if field in {"salary_min", "salary_max"}:
            value = _number(value)
            if value is None or value < 0:
                raise JobhuntError("Salary override must be a non-negative number", code="invalid_override_value")
        else:
            value = self._bounded_optional_text(value, "value", limit=500)
            if not value:
                raise JobhuntError("Human Override value cannot be empty", code="invalid_override_value")
        reason = self._bounded_optional_text(payload.get("reason"), "reason", limit=1000)
        if not reason:
            raise JobhuntError("Human Override reason is required", code="invalid_override_reason")
        note = self._bounded_optional_text(payload.get("note"), "note", limit=4000)
        now = _utc_now()
        override_id = self.store.create_override(
            job_id=job_id, field_name=field, replacement=value, reason=reason, note=note, now=now,
        )
        listing = self.store.latest_listing_for_job(job_id)
        projection = None
        evaluation_recompute = None
        if listing:
            projection = self.store.project_listing(listing[0], capture_id=listing[1], now=now)
            evaluation_recompute = self._schedule_evaluation_recompute(
                scope="job", job_id=job_id,
                token=str(projection.get("projection_id") or override_id),
            )
        item = next(entry for entry in self.store.list_overrides(job_id) if entry["id"] == override_id)
        return {"ok": True, "data": {
            "override": self._override_to_api(item), "projection": projection,
            "evaluationRecompute": evaluation_recompute,
        }}

    @staticmethod
    def _profile_record_to_api(kind: str, record: dict[str, Any]) -> dict[str, Any]:
        reverse = {column: field for field, column in PROFILE_FIELD_MAPS[kind].items()}
        result = {"id": record["id"]}
        for column, field in reverse.items():
            value = record.get(column)
            if column in {"is_current", "is_hard"} and value is not None:
                value = bool(value)
            result[field] = value
        if record.get("created_at") is not None:
            result["createdAt"] = record["created_at"]
        if record.get("updated_at") is not None:
            result["updatedAt"] = record["updated_at"]
        return result

    def _profile_to_api(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "default",
            "currentRoleTitle": raw.get("current_role_title"),
            "headline": raw.get("headline"),
            "professionalSummary": raw.get("professional_summary"),
            "revision": int(raw.get("revision") or 0),
            "fingerprint": raw.get("fingerprint"),
            "createdAt": raw.get("created_at"),
            "updatedAt": raw.get("updated_at"),
            **{
                kind: [self._profile_record_to_api(kind, record) for record in raw.get(kind, [])]
                for kind in PROFILE_FIELD_MAPS
            },
            "skillLevelScale": {
                "0": "no experience", "1": "awareness", "2": "basic / guided use",
                "3": "independent working ability", "4": "strong practical ability",
                "5": "advanced / expert-level practical ability",
            },
            "unknownSemantics": "Missing values are unknown, not false, zero, or neutral.",
        }

    def get_profile(self) -> dict[str, Any]:
        return {"ok": True, "data": {"profile": self._profile_to_api(self.store.get_profile())}}

    def update_profile(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Career Profile payload must be an object", code="invalid_profile_payload")
        mapping = {
            "currentRoleTitle": "current_role_title",
            "headline": "headline",
            "professionalSummary": "professional_summary",
        }
        unknown = sorted(set(payload) - set(mapping))
        if unknown:
            raise JobhuntError("Career Profile contains unsupported fields", code="unknown_profile_fields", details=unknown)
        limits = {"currentRoleTitle": 300, "headline": 500, "professionalSummary": 12000}
        values = {
            mapping[key]: _nullable_text(value, limit=limits[key])
            for key, value in payload.items()
        }
        raw = self.store.update_profile(values, now=_utc_now())
        recompute = self._schedule_evaluation_recompute(
            scope="profile", token=str(raw.get("fingerprint") or "current"),
        )
        return {"ok": True, "data": {
            "profile": self._profile_to_api(raw), "evaluationRecompute": recompute,
        }}

    @staticmethod
    def _profile_scale(value: Any, *, minimum: int, maximum: int, field: str) -> int | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            raise JobhuntError(f"{field} must be between {minimum} and {maximum}", code="invalid_profile_value")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise JobhuntError(f"{field} must be between {minimum} and {maximum}", code="invalid_profile_value") from exc
        if result < minimum or result > maximum:
            raise JobhuntError(f"{field} must be between {minimum} and {maximum}", code="invalid_profile_value")
        return result

    def _validate_profile_record(
        self, kind: str, payload: Any, *, creating: bool
    ) -> dict[str, Any]:
        mapping = PROFILE_FIELD_MAPS.get(kind)
        if not mapping or not isinstance(payload, dict):
            raise JobhuntError("Career Profile record payload is invalid", code="invalid_profile_record")
        if not payload:
            raise JobhuntError("Career Profile record payload cannot be empty", code="invalid_profile_record")
        unknown = sorted(set(payload) - set(mapping))
        if unknown:
            raise JobhuntError("Career Profile record contains unsupported fields", code="unknown_profile_fields", details=unknown)
        if creating:
            missing = sorted(field for field in PROFILE_REQUIRED_FIELDS[kind] if field not in payload)
            if missing:
                raise JobhuntError("Career Profile record is missing required fields", code="missing_profile_fields", details=missing)
        result: dict[str, Any] = {}
        text_fields = set(mapping) - {
            "domains", "value", "isCurrent", "isHard", "level", "confidence",
            "developmentInterest", "importance",
        }
        date_fields = {"startDate", "endDate", "issuedDate", "expirationDate"}
        for field, value in payload.items():
            column = mapping[field]
            if field in date_fields:
                if value in (None, ""):
                    result[column] = None
                else:
                    parsed = _valid_date(value)
                    if not parsed:
                        raise JobhuntError(f"{field} must use YYYY-MM-DD", code="invalid_profile_date")
                    result[column] = parsed
            elif field == "domains":
                if not isinstance(value, list):
                    raise JobhuntError("domains must be an array", code="invalid_profile_value")
                result[column] = _string_list(value, limit=50)
            elif field in {"isCurrent", "isHard"}:
                if value is not None and not isinstance(value, bool):
                    raise JobhuntError(f"{field} must be true, false, or null", code="invalid_profile_value")
                result[column] = None if value is None else int(value)
            elif field in {"level"}:
                result[column] = self._profile_scale(value, minimum=0, maximum=5, field=field)
            elif field in {"confidence", "developmentInterest", "importance"}:
                result[column] = self._profile_scale(value, minimum=1, maximum=5, field=field)
            elif field == "value":
                try:
                    encoded = json.dumps(value, ensure_ascii=False)
                except (TypeError, ValueError) as exc:
                    raise JobhuntError("value must be JSON-compatible", code="invalid_profile_value") from exc
                if len(encoded.encode("utf-8")) > 16 * 1024:
                    raise JobhuntError("value is too large", status=413, code="profile_value_too_large")
                result[column] = value
            elif field in text_fields:
                limit = 12000 if field in {"description", "notes", "evidenceNotes"} else 1000
                text = _nullable_text(value, limit=limit)
                if creating and field in PROFILE_REQUIRED_FIELDS[kind] and not text:
                    raise JobhuntError(f"{field} is required", code="missing_profile_fields")
                result[column] = text
        if "origin" not in payload and creating:
            result["origin"] = "manual_user"
        origin = result.get("origin")
        if origin is not None and origin not in PROFILE_ORIGINS:
            raise JobhuntError("Unsupported profile origin", code="invalid_profile_origin")
        return result

    def save_profile_record(
        self, kind: str, payload: Any, *, record_id: str | None = None
    ) -> dict[str, Any]:
        values = self._validate_profile_record(kind, payload, creating=record_id is None)
        try:
            identifier = self.store.save_profile_record(
                kind, values, record_id=record_id, now=_utc_now()
            )
        except sqlite3.IntegrityError as exc:
            raise JobhuntError(
                "A Career Profile record with this key already exists",
                status=409, code="duplicate_profile_record",
            ) from exc
        profile = self._profile_to_api(self.store.get_profile())
        saved = next((item for item in profile[kind] if item["id"] == identifier), None)
        recompute = self._schedule_evaluation_recompute(
            scope="profile", token=str(profile.get("fingerprint") or "current"),
        )
        return {"ok": True, "data": {
            "record": saved, "profile": profile, "evaluationRecompute": recompute,
        }}

    def delete_profile_record(self, kind: str, record_id: str) -> dict[str, Any]:
        if kind not in PROFILE_FIELD_MAPS:
            raise JobhuntError("Unsupported Career Profile collection", status=404, code="profile_collection_not_found")
        self.store.delete_profile_record(kind, record_id, now=_utc_now())
        profile = self._profile_to_api(self.store.get_profile())
        recompute = self._schedule_evaluation_recompute(
            scope="profile", token=str(profile.get("fingerprint") or "current"),
        )
        return {
            "ok": True,
            "data": {
                "deleted": record_id, "profile": profile,
                "evaluationRecompute": recompute,
            },
        }

    @staticmethod
    def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(manifest)

    @staticmethod
    def _run_to_api(run: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        labels = {
            item["id"]: item["label"] for item in (manifest or {}).get("dimensions", [])
        }
        return {
            "id": run["id"], "instrumentId": run["instrument_id"],
            "instrumentVersion": run["instrument_version"], "definitionHash": run["definition_hash"],
            "status": run["status"], "scoringVersion": run["scoring_version"],
            "startedAt": run["started_at"], "completedAt": run.get("completed_at"),
            "createdAt": run["created_at"], "updatedAt": run["updated_at"],
            "responses": run.get("responses", {}),
            "responseTimestamps": run.get("response_timestamps", {}),
            "scores": [{
                "dimension": score["dimension"],
                "label": labels.get(score["dimension"], score["dimension"]),
                "rawScore": score["raw_score"],
                "normalizedScore": score.get("normalized_score"),
                "interpretationBand": score.get("interpretation_band"),
                "scoringVersion": score["scoring_version"],
            } for score in run.get("scores", [])],
        }

    def list_assessments(self) -> dict[str, Any]:
        manifests = {item["instrumentId"]: item for item in self.assessment_loader.load()}
        runs = self.store.list_assessment_runs()
        instruments = []
        for instrument_id, title in ASSESSMENT_CATALOG.items():
            manifest = manifests.get(instrument_id)
            history = [run for run in runs if run["instrument_id"] == instrument_id]
            completed = [run for run in history if run["status"] == "completed"]
            draft = next((run for run in history if run["status"] == "draft"), None)
            instruments.append({
                "instrumentId": instrument_id,
                "instrumentVersion": manifest.get("instrumentVersion") if manifest else None,
                "definitionHash": manifest.get("definitionHash") if manifest else None,
                "title": manifest.get("title", title) if manifest else title,
                "description": manifest.get("description", "Authoritative manifest pending verification.") if manifest else "Authoritative manifest pending verification.",
                "available": manifest is not None,
                "unavailableReason": None if manifest else "Authoritative definition or licensing has not been verified.",
                "status": "draft" if draft else ("completed" if completed else "not_started"),
                "draftRunId": draft["id"] if draft else None,
                "latestCompletedAt": completed[0]["completed_at"] if completed else None,
                "history": [self._run_to_api(run, manifest) for run in history],
                "source": manifest.get("source") if manifest else None,
                "interpretationLimits": manifest.get("interpretationLimits", []) if manifest else [],
            })
        return {"ok": True, "data": {"instruments": instruments, "manifestErrors": self.assessment_loader.errors}}

    def get_assessment(self, instrument_id: str, version: str | None = None) -> dict[str, Any]:
        manifest = self.assessment_loader.get(instrument_id, version)
        if not manifest:
            raise JobhuntError("Assessment instrument is unavailable", status=404, code="assessment_unavailable")
        return {"ok": True, "data": {"instrument": self._public_manifest(manifest)}}

    def start_assessment(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {"instrumentId", "instrumentVersion"}:
            raise JobhuntError("Assessment run payload is invalid", code="invalid_assessment_run")
        instrument_id = _text(payload.get("instrumentId"), limit=200)
        version = _nullable_text(payload.get("instrumentVersion"), limit=100)
        manifest = self.assessment_loader.get(instrument_id, version)
        if not manifest:
            raise JobhuntError("Assessment instrument is unavailable", status=404, code="assessment_unavailable")
        now = _utc_now()
        run_id = self.store.create_assessment_run({
            "instrument_id": manifest["instrumentId"],
            "instrument_version": manifest["instrumentVersion"],
            "definition_hash": manifest["definitionHash"],
            "scoring_version": manifest["scoringVersion"],
            "started_at": now, "created_at": now, "updated_at": now,
        })
        return self.get_assessment_run(run_id)

    def get_assessment_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_assessment_run(run_id)
        if not run:
            raise JobhuntError("Assessment run not found", status=404, code="assessment_run_not_found")
        manifest = self.assessment_loader.get(run["instrument_id"], run["instrument_version"])
        if not manifest or manifest["definitionHash"] != run["definition_hash"]:
            raise JobhuntError(
                "The exact assessment definition for this run is unavailable",
                status=409, code="assessment_definition_unavailable",
            )
        return {
            "ok": True,
            "data": {"run": self._run_to_api(run, manifest), "instrument": self._public_manifest(manifest)},
        }

    def save_assessment_responses(self, run_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"responses"} or not isinstance(payload["responses"], dict):
            raise JobhuntError("Assessment responses payload is invalid", code="invalid_assessment_responses")
        run = self.store.get_assessment_run(run_id)
        if not run:
            raise JobhuntError("Assessment run not found", status=404, code="assessment_run_not_found")
        manifest = self.assessment_loader.get(run["instrument_id"], run["instrument_version"])
        if not manifest or manifest["definitionHash"] != run["definition_hash"]:
            raise JobhuntError("Assessment definition is unavailable", status=409, code="assessment_definition_unavailable")
        item_ids = {item["id"] for item in manifest["items"]}
        scale = manifest["answerScale"]
        responses: dict[str, int] = {}
        for item_id, raw in payload["responses"].items():
            if item_id not in item_ids:
                raise JobhuntError("Assessment response contains an unknown item", code="unknown_assessment_item", details=[item_id])
            if isinstance(raw, bool):
                raise JobhuntError("Assessment answer is invalid", code="invalid_assessment_answer")
            try:
                numeric = float(raw)
            except (TypeError, ValueError) as exc:
                raise JobhuntError("Assessment answer is invalid", code="invalid_assessment_answer") from exc
            if not numeric.is_integer():
                raise JobhuntError("Assessment answer is invalid", code="invalid_assessment_answer")
            answer = int(numeric)
            if answer < scale["min"] or answer > scale["max"]:
                raise JobhuntError("Assessment answer is outside the answer scale", code="invalid_assessment_answer")
            responses[item_id] = answer
        self.store.save_assessment_responses(run_id, responses, answered_at=_utc_now())
        return self.get_assessment_run(run_id)

    def complete_assessment(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_assessment_run(run_id)
        if not run:
            raise JobhuntError("Assessment run not found", status=404, code="assessment_run_not_found")
        manifest = self.assessment_loader.get(run["instrument_id"], run["instrument_version"])
        if not manifest or manifest["definitionHash"] != run["definition_hash"]:
            raise JobhuntError("Assessment definition is unavailable", status=409, code="assessment_definition_unavailable")
        try:
            scores = score_assessment(manifest, run["responses"])
        except ManifestValidationError as exc:
            raise JobhuntError(str(exc), code="assessment_incomplete") from exc
        self.store.complete_assessment_run(run_id, scores, completed_at=_utc_now())
        return self.get_assessment_run(run_id)

    def abandon_assessment(self, run_id: str) -> dict[str, Any]:
        self.store.abandon_assessment_run(run_id, now=_utc_now())
        return self.get_assessment_run(run_id)

    def _validate_write_fields(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Job payload must be an object", code="invalid_job_payload")
        unknown = sorted(set(payload) - CREATE_FIELDS)
        if unknown:
            raise JobhuntError(
                "Job payload contains unsupported fields",
                code="unknown_job_fields",
                details=unknown,
            )
        return payload

    def _save_logo(
        self,
        data_url: Any,
        *,
        strict: bool,
    ) -> tuple[dict[str, str | None], str | None]:
        text = str(data_url or "").strip()
        if not text:
            return {"path": None, "mime": None, "sha256": None}, None
        match = re.fullmatch(r"data:([^;,]+);base64,([A-Za-z0-9+/=\s]+)", text)
        if not match or match.group(1).lower() not in LOGO_TYPES:
            message = "Company logo was not migrated because its data URL is invalid."
            if strict:
                raise JobhuntError(message, code="invalid_job_logo")
            return {"path": None, "mime": None, "sha256": None}, message
        mime = match.group(1).lower()
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
        except (ValueError, binascii.Error):
            message = "Company logo was not migrated because its base64 data is malformed."
            if strict:
                raise JobhuntError(message, code="invalid_job_logo")
            return {"path": None, "mime": None, "sha256": None}, message
        if not raw or len(raw) > MAX_LOGO_BYTES:
            message = "Company logo was not migrated because it is empty or larger than 512 KB."
            if strict:
                raise JobhuntError(message, code="invalid_job_logo")
            return {"path": None, "mime": None, "sha256": None}, message
        extension, magic = LOGO_TYPES[mime]
        valid = raw.startswith(magic) if magic else b"<svg" in raw[:1024].lower()
        if mime == "image/webp":
            valid = valid and raw[8:12] == b"WEBP"
        if not valid:
            message = "Company logo was not migrated because its bytes do not match its media type."
            if strict:
                raise JobhuntError(message, code="invalid_job_logo")
            return {"path": None, "mime": None, "sha256": None}, message
        digest = _sha(raw)
        relative = Path("branding") / f"{digest}{extension}"
        target = self.assets_directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(raw)
            if _sha(temporary.read_bytes()) != digest:
                temporary.unlink(missing_ok=True)
                raise JobhuntError(
                    "Company logo verification failed",
                    status=500,
                    code="jobhunt_logo_write_failed",
                )
            os.replace(temporary, target)
        return {
            "path": relative.as_posix(),
            "mime": mime,
            "sha256": digest,
        }, None

    def _logo_data_url(self, row: dict[str, Any]) -> str:
        relative = row.get("branding_path")
        mime = row.get("branding_mime")
        expected = row.get("branding_sha256")
        if not relative or mime not in LOGO_TYPES or not expected:
            return ""
        target = (self.assets_directory / str(relative)).resolve()
        root = self.assets_directory.resolve()
        if root not in target.parents or not target.is_file():
            return ""
        raw = target.read_bytes()
        if len(raw) > MAX_LOGO_BYTES or _sha(raw) != expected:
            return ""
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    def _normalize_settings(self, value: Any) -> list[dict[str, Any]]:
        incoming = {}
        if isinstance(value, list):
            for item in value[:100]:
                if not isinstance(item, dict):
                    continue
                setting_id = _text(item.get("id"), limit=100)
                if setting_id:
                    incoming[setting_id] = item
        normalized = []
        for default in MATCH_SETTINGS_DEFAULTS:
            candidate = incoming.get(default["id"], {})
            weight = _number(candidate.get("weight"))
            normalized.append({
                **default,
                "weight": max(0, min(100, round(weight if weight is not None else default["weight"]))),
            })
        return normalized

    def _normalize_offer(
        self,
        raw: dict[str, Any],
        *,
        strict: bool,
        now: str,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise JobhuntError("Every offer must be an object", code="invalid_job_payload")
        encoded = _canonical_bytes(raw)
        if len(encoded) > MAX_LEGACY_OFFER_BYTES:
            raise JobhuntError(
                "One legacy offer exceeds the 1 MB compatibility limit",
                status=413,
                code="legacy_offer_too_large",
            )
        warnings: list[str] = []
        company = _text(raw.get("company"), "unknown", limit=300)
        role = _text(raw.get("role"), "unknown", limit=300)
        if strict and (company == "unknown" or role == "unknown"):
            raise JobhuntError("Company and role are required", code="missing_job_fields")
        location = _dict(raw.get("location"))
        contract = _dict(raw.get("contract"))
        salary = _dict(raw.get("salary"))
        source = _dict(raw.get("source"))
        application_input = _dict(raw.get("application"))
        match_input = _dict(raw.get("match"))
        analysis = _dict(raw.get("analysis"))
        cv = _dict(raw.get("cv"))
        requirements = _dict(raw.get("requirements"))

        raw_status = _text(raw.get("applicationStatus") or raw.get("status"), "to_review", limit=40)
        if raw_status not in LEGACY_STATUSES:
            if strict:
                raise JobhuntError(f'Unsupported status "{raw_status}"', code="invalid_job_status")
            warnings.append(f'Unsupported legacy status "{raw_status}" was mapped to "to_review".')
            raw_status = "to_review"
        source_expired = bool(raw.get("sourceExpired")) or _text(raw.get("status"), limit=40) == "expired"
        application_status = "to_review" if raw_status == "expired" else raw_status
        if application_status not in APPLICATION_STATUSES:
            application_status = "to_review"
        priority = _text(raw.get("priority"), "unknown", limit=20)
        if priority not in PRIORITIES:
            if strict:
                raise JobhuntError(f'Unsupported priority "{priority}"', code="invalid_job_priority")
            warnings.append(f'Unsupported legacy priority "{priority}" was mapped to "unknown".')
            priority = "unknown"
        next_action = _text(raw.get("nextAction"), "analyze", limit=40)
        if next_action not in NEXT_ACTIONS:
            warnings.append(f'Unsupported legacy next action "{next_action}" was mapped to "analyze".')
            next_action = "analyze"

        source_url_text = _nullable_text(source.get("url"), limit=2048)
        source_url = _valid_url(source_url_text)
        if source_url_text and not source_url:
            warnings.append("Invalid source URL was retained only in the lossless compatibility payload.")
            if strict:
                raise JobhuntError("Source URL must be an http(s) URL", code="invalid_job_url")

        expires_input = _nullable_text(raw.get("expiresAt"), limit=40)
        expires_at = _valid_date(expires_input)
        if expires_input and not expires_at:
            warnings.append("Invalid expiration date was retained only in the compatibility payload.")
            if strict:
                raise JobhuntError("Expiration date must use YYYY-MM-DD", code="invalid_expiration_date")

        score_value = _number(match_input.get("score"))
        score = None if score_value is None else round(score_value)
        if score is not None and not 0 <= score <= 100:
            if strict:
                raise JobhuntError("Match score must be between 0 and 100", code="invalid_match_score")
            warnings.append("Out-of-range legacy match score was preserved only in the compatibility payload.")
            score = None

        branding = _dict(raw.get("branding"))
        logo_value = branding.get("logoDataUrl") or raw.get("companyLogoDataUrl")
        if logo_value:
            logo, logo_warning = self._save_logo(logo_value, strict=strict)
            if logo_warning:
                warnings.append(logo_warning)
        elif existing:
            logo = {
                "path": existing.get("branding_path"),
                "mime": existing.get("branding_mime"),
                "sha256": existing.get("branding_sha256"),
            }
        else:
            logo = {"path": None, "mime": None, "sha256": None}

        legacy_id = _nullable_text(raw.get("legacyId") or raw.get("id"), limit=300)
        if existing:
            legacy_id = existing.get("legacy_id")
            legacy_fingerprint = existing["legacy_fingerprint"]
            legacy_payload = json.loads(existing["legacy_payload_json"])
            created_at = existing["created_at"]
        else:
            legacy_fingerprint = _sha(encoded)
            legacy_payload = deepcopy(raw)
            if logo_value:
                legacy_branding = legacy_payload.get("branding")
                if isinstance(legacy_branding, dict):
                    legacy_branding.pop("logoDataUrl", None)
                legacy_payload.pop("companyLogoDataUrl", None)
                legacy_payload["_jobhuntBrandingEvidence"] = {
                    "status": "stored" if logo.get("path") else "rejected",
                    "path": logo.get("path"),
                    "mime": logo.get("mime"),
                    "sha256": logo.get("sha256"),
                    "exactSourceRetainedInMigrationRecovery": not strict,
                }
            created_at = _text(raw.get("createdAt"), now, limit=80)
        updated_at = now if existing else _text(raw.get("updatedAt"), now, limit=80)
        if existing and raw.get("createdAt"):
            created_at = existing["created_at"]

        original_text = _text(raw.get("originalText"), limit=MAX_TEXT_BYTES)
        if len(original_text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise JobhuntError("Original job text is too large", status=413, code="job_text_too_large")

        salary_min = _number(salary.get("min"))
        salary_max = _number(salary.get("max"))
        salary_known = bool(salary.get("isKnown", salary_min is not None or salary_max is not None))
        date_applied = _valid_date(application_input.get("dateApplied"))
        follow_up_date = _valid_date(application_input.get("followUpDate"))
        if application_input.get("dateApplied") and not date_applied:
            warnings.append("Invalid application date was retained only in the compatibility payload.")
        if application_input.get("followUpDate") and not follow_up_date:
            warnings.append("Invalid follow-up date was retained only in the compatibility payload.")

        archived_at = now if application_status == "archived" else None
        if existing and application_status != "archived":
            archived_at = None
        item = {
            "job": {
                "legacy_id": legacy_id,
                "legacy_fingerprint": legacy_fingerprint,
                "company": company,
                "role_title": role,
                "seniority": _text(raw.get("seniority"), "unknown", limit=100),
                "location_city": _text(location.get("city"), "unknown", limit=200),
                "location_country": _text(location.get("country"), "unknown", limit=200),
                "work_mode": _text(location.get("workMode"), "unknown", limit=100),
                "hybrid_details": _text(location.get("hybridDetails"), "unknown", limit=500),
                "contract_type": _text(contract.get("type"), "unknown", limit=100),
                "contract_details": _text(contract.get("details"), "unknown", limit=500),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_currency": _text(salary.get("currency"), "unknown", limit=20),
                "salary_period": _text(salary.get("period"), "unknown", limit=40),
                "salary_tax_type": _text(salary.get("taxType"), "unknown", limit=40),
                "salary_is_known": salary_known,
                "source_name": _text(source.get("name"), "unknown", limit=200),
                "source_url": source_url,
                "source_captured_at": _nullable_text(source.get("capturedAt"), limit=80),
                "expires_at": expires_at,
                "original_text": original_text,
                "requirements": {
                    "mustHave": _string_list(requirements.get("mustHave")),
                    "niceToHave": _string_list(requirements.get("niceToHave")),
                    "tools": _string_list(requirements.get("tools")),
                },
                "branding_path": logo["path"],
                "branding_mime": logo["mime"],
                "branding_sha256": logo["sha256"],
                "legacy_payload": legacy_payload,
                "created_at": created_at,
                "updated_at": updated_at,
                "archived_at": archived_at,
                "deleted_at": existing.get("deleted_at") if existing else None,
            },
            "application": {
                "current_status": application_status,
                "source_expired": source_expired,
                "priority": priority,
                "next_action": next_action,
                "date_applied": date_applied,
                "follow_up_date": follow_up_date,
                "recruiter_name": _nullable_text(application_input.get("recruiterName"), limit=300),
                "recruiter_contact": _nullable_text(application_input.get("recruiterContact"), limit=500),
                "notes": _text(raw.get("notes"), limit=MAX_TEXT_BYTES),
                "created_at": existing.get("application_created_at") if existing else created_at,
                "updated_at": updated_at,
            },
            "evaluation": {
                "match_score": score,
                "match_category": _text(match_input.get("category"), _match_category(score), limit=100),
                "match_summary": _text(match_input.get("summary"), "No match summary yet.", limit=4000),
                "is_experimental": match_input.get("isExperimental") is not False,
                "green_flags": _string_list(analysis.get("greenFlags")),
                "red_flags": _string_list(analysis.get("redFlags")),
                "skill_gaps": _string_list(analysis.get("skillGaps")),
                "fit_reasons": _string_list(analysis.get("fitReasons")),
                "recommended_cv_version": _text(cv.get("recommendedVersion"), "unknown", limit=300),
                "cv_bullets": _string_list(cv.get("bulletsToEmphasize")),
                "created_at": existing.get("evaluation_created_at") if existing else created_at,
                "updated_at": updated_at,
            },
            "warnings": warnings,
        }
        return item

    def _migration_events(self, item: dict[str, Any], raw: dict[str, Any], now: str) -> list[dict[str, Any]]:
        app = item["application"]
        events = [{
            "type": "imported",
            "timestamp": now,
            "origin": "migration",
            "payload": {
                "legacyId": item["job"].get("legacy_id"),
                "legacyStatus": _text(raw.get("status"), "to_review", limit=40),
                "sourceExpired": bool(app["source_expired"]),
            },
        }]
        if app["current_status"] != "to_review" or _text(raw.get("status"), limit=40) == "expired":
            events.append({
                "type": "status_changed",
                "timestamp": now,
                "origin": "migration",
                "payload": {
                    "from": None,
                    "to": app["current_status"],
                    "legacyStatus": _text(raw.get("status"), "to_review", limit=40),
                },
            })
        if app.get("date_applied"):
            events.append({
                "type": "applied",
                "timestamp": now,
                "origin": "migration",
                "payload": {"dateApplied": app["date_applied"]},
            })
        if app.get("follow_up_date"):
            events.append({
                "type": "follow_up_scheduled",
                "timestamp": now,
                "origin": "migration",
                "payload": {"followUpDate": app["follow_up_date"]},
            })
        if app.get("recruiter_name") or app.get("recruiter_contact"):
            events.append({
                "type": "recruiter_updated",
                "timestamp": now,
                "origin": "migration",
                "payload": {
                    "recruiterName": app.get("recruiter_name"),
                    "recruiterContact": app.get("recruiter_contact"),
                },
            })
        if app.get("notes"):
            events.append({
                "type": "note_changed",
                "timestamp": now,
                "origin": "migration",
                "payload": {"imported": True},
            })
        if app["current_status"] == "archived":
            events.append({
                "type": "archived",
                "timestamp": now,
                "origin": "migration",
                "payload": {},
            })
        return events

    def _row_to_offer(self, row: dict[str, Any]) -> dict[str, Any]:
        requirements = json.loads(row.get("requirements_json") or "{}")
        has_evaluation = bool(row.get("evaluation_id"))
        today = datetime.now().astimezone().date()
        expires_at = _valid_date(row.get("expires_at"))
        expired_by_date = bool(expires_at and date.fromisoformat(expires_at) < today)
        source_expired = bool(row.get("source_expired")) or expired_by_date
        application_status = row["current_status"]
        display_status = (
            "expired"
            if source_expired and application_status not in {"offer", "rejected", "archived"}
            else application_status
        )
        return {
            "id": row["id"],
            "legacyId": row.get("legacy_id"),
            "company": row["company"],
            "role": row["role_title"],
            "seniority": row["seniority"],
            "location": {
                "city": row["location_city"],
                "country": row["location_country"],
                "workMode": row["work_mode"],
                "hybridDetails": row["hybrid_details"],
            },
            "contract": {"type": row["contract_type"], "details": row["contract_details"]},
            "salary": {
                "min": row.get("salary_min"),
                "max": row.get("salary_max"),
                "currency": row["salary_currency"],
                "period": row["salary_period"],
                "taxType": row["salary_tax_type"],
                "isKnown": bool(row["salary_is_known"]),
            },
            "source": {
                "name": row["source_name"],
                "url": row.get("source_url") or "",
                "capturedAt": row.get("source_captured_at"),
            },
            "branding": {"logoDataUrl": self._logo_data_url(row)},
            "expiresAt": expires_at,
            "sourceExpired": source_expired,
            "status": display_status,
            "applicationStatus": application_status,
            "priority": row["priority"],
            "nextAction": row["next_action"],
            "match": {
                "score": row.get("match_score") if has_evaluation else None,
                "category": row.get("match_category") or "unknown",
                "summary": row.get("match_summary") or (
                    "No candidate evaluation exists." if not has_evaluation else "No match summary yet."
                ),
                "isExperimental": bool(row.get("is_experimental", 1)) if has_evaluation else False,
            },
            "evaluationSource": "legacy_imported" if has_evaluation else "none",
            "requirements": requirements,
            "analysis": {
                "greenFlags": json.loads(row.get("green_flags_json") or "[]"),
                "redFlags": json.loads(row.get("red_flags_json") or "[]"),
                "skillGaps": json.loads(row.get("skill_gaps_json") or "[]"),
                "fitReasons": json.loads(row.get("fit_reasons_json") or "[]"),
            },
            "cv": {
                "recommendedVersion": row.get("recommended_cv_version") or "unknown",
                "bulletsToEmphasize": json.loads(row.get("cv_bullets_json") or "[]"),
            },
            "application": {
                "id": row["application_id"],
                "dateApplied": row.get("date_applied"),
                "followUpDate": row.get("follow_up_date"),
                "recruiterName": row.get("recruiter_name"),
                "recruiterContact": row.get("recruiter_contact"),
            },
            "notes": row.get("notes") or "",
            "originalText": row.get("original_text") or "",
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "archivedAt": row.get("archived_at"),
            "mergedInto": row.get("merged_into_job_id"),
            "mergedAt": row.get("merged_at"),
        }

    def list_jobs(self, *, limit: Any = 500, offset: Any = 0) -> dict[str, Any]:
        try:
            safe_limit = max(1, min(500, int(limit)))
            safe_offset = max(0, int(offset))
        except (TypeError, ValueError) as exc:
            raise JobhuntError("limit and offset must be integers", code="invalid_pagination") from exc
        jobs = [
            self._row_to_offer(row)
            for row in self.store.list_offer_rows(limit=safe_limit, offset=safe_offset)
        ]
        return {
            "ok": True,
            "data": {
                "jobs": jobs,
                "total": self.store.visible_job_count(),
                "limit": safe_limit,
                "offset": safe_offset,
                "authority": "sqlite",
            },
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.store.get_offer_row(job_id)
        if not row:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        projection = self.store.latest_projection(job_id)
        provenance = None if not projection else {
            "projectionId": projection["id"], "projectionVersion": projection["projection_version"],
            "ruleVersion": projection["rule_version"],
            "selectedFactIds": projection["selected_fact_ids"],
            "appliedOverrideIds": projection["applied_override_ids"],
            "snapshot": projection["snapshot"], "createdAt": projection["created_at"],
        }
        alias = None
        if row.get("merged_into_job_id"):
            survivor = self.store.get_offer_row(row["merged_into_job_id"], include_deleted=True)
            alias = {
                "state": "merged", "survivorJobId": row["merged_into_job_id"],
                "survivor": None if not survivor else {
                    "id": survivor["id"], "company": survivor["company"],
                    "role": survivor["role_title"],
                },
            }
        return {"ok": True, "data": {
            "job": self._row_to_offer(row), "provenance": provenance, "mergeAlias": alias,
        }}

    def get_application(self, job_id: str) -> dict[str, Any]:
        row = self.store.get_offer_row(job_id)
        if not row:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        offer = self._row_to_offer(row)
        return {
            "ok": True,
            "data": {
                "jobId": job_id,
                "application": {
                    **offer["application"],
                    "status": offer["applicationStatus"],
                    "displayStatus": offer["status"],
                    "priority": offer["priority"],
                    "nextAction": offer["nextAction"],
                    "notes": offer["notes"],
                },
                "events": self.store.application_events(row["application_id"]),
            },
        }

    def create_job(self, payload: Any) -> dict[str, Any]:
        raw = self._validate_write_fields(payload)
        now = _utc_now()
        item = self._normalize_offer(raw, strict=True, now=now)
        item["events"] = [{
            "type": "created",
            "timestamp": now,
            "origin": "user",
            "payload": {"source": "manual"},
        }]
        job_id = self.store.create_offer(item)
        self._schedule_dedupe_scan(job_id, item.get("updated_at") or now)
        self._schedule_evaluation_recompute(
            scope="job", job_id=job_id, token=self._job_evaluation_token(item),
        )
        return self.get_job(job_id)

    @staticmethod
    def _job_evaluation_token(item: dict[str, Any]) -> str:
        job = item["job"]
        fields = (
            "company", "role_title", "seniority", "location_city", "location_country",
            "work_mode", "hybrid_details", "contract_type", "contract_details",
            "salary_min", "salary_max", "salary_currency", "salary_period",
            "salary_tax_type", "salary_is_known", "source_name", "source_url",
            "source_captured_at", "expires_at", "original_text", "requirements",
        )
        return _sha(_canonical_bytes({key: job.get(key) for key in fields}))

    def update_job(self, job_id: str, payload: Any) -> dict[str, Any]:
        patch = self._validate_write_fields(payload)
        existing = self.store.get_offer_row(job_id)
        if not existing:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        current = self._row_to_offer(existing)
        merged = deepcopy(current)
        for key, value in patch.items():
            if key in {"location", "contract", "salary", "source", "branding", "match", "requirements", "analysis", "cv", "application"}:
                merged[key] = {**_dict(merged.get(key)), **_dict(value)}
            else:
                merged[key] = value
        if "status" in patch and "applicationStatus" not in patch:
            merged["applicationStatus"] = "to_review" if patch["status"] == "expired" else patch["status"]
            merged["sourceExpired"] = patch["status"] == "expired"
        now = _utc_now()
        item = self._normalize_offer(merged, strict=True, now=now, existing=existing)
        events = []
        if item["application"]["current_status"] != existing["current_status"]:
            events.append({
                "type": "status_changed",
                "timestamp": now,
                "origin": "user",
                "payload": {"from": existing["current_status"], "to": item["application"]["current_status"]},
            })
        if bool(item["application"]["source_expired"]) != bool(existing["source_expired"]):
            events.append({
                "type": "source_expiration_changed",
                "timestamp": now,
                "origin": "user",
                "payload": {"sourceExpired": bool(item["application"]["source_expired"])},
            })
        if (
            item["application"].get("recruiter_name") != existing.get("recruiter_name")
            or item["application"].get("recruiter_contact") != existing.get("recruiter_contact")
        ):
            events.append({
                "type": "recruiter_updated",
                "timestamp": now,
                "origin": "user",
                "payload": {
                    "recruiterName": item["application"].get("recruiter_name"),
                    "recruiterContact": item["application"].get("recruiter_contact"),
                },
            })
        if item["application"]["notes"] != (existing.get("notes") or ""):
            events.append({"type": "note_changed", "timestamp": now, "origin": "user", "payload": {}})
        if not events:
            events.append({"type": "job_updated", "timestamp": now, "origin": "user", "payload": {}})
        self.store.update_offer(job_id, item, events)
        self._schedule_dedupe_scan(job_id, now)
        factual_fields = {
            "company", "role", "seniority", "location", "contract", "salary",
            "source", "requirements", "originalText", "expiresAt",
        }
        if set(patch).intersection(factual_fields):
            self._schedule_evaluation_recompute(
                scope="job", job_id=job_id, token=self._job_evaluation_token(item),
            )
        return self.get_job(job_id)

    def application_command(self, job_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise JobhuntError("Application command must be an object", code="invalid_application_command")
        unknown = sorted(set(payload) - {"type", "status", "priority", "nextAction", "recruiterName", "recruiterContact", "notes", "followUpDate"})
        if unknown:
            raise JobhuntError("Application command contains unsupported fields", code="unknown_application_fields", details=unknown)
        command = _text(payload.get("type"), limit=80)
        row = self.store.get_offer_row(job_id)
        if not row:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        now = _utc_now()
        today = datetime.now().astimezone().date()
        changes: dict[str, Any] = {"updated_at": now}
        events: list[dict[str, Any]] = []
        archived_at: str | None | object = ...
        attribution: dict[str, Any] | None = None
        if command == "applied":
            follow_up = (today + timedelta(days=7)).isoformat()
            changes.update({
                "current_status": "applied",
                "next_action": "follow_up",
                "date_applied": today.isoformat(),
                "follow_up_date": follow_up,
            })
            events.extend([
                {"type": "applied", "timestamp": now, "origin": "user", "payload": {"dateApplied": today.isoformat()}},
                {"type": "follow_up_scheduled", "timestamp": now, "origin": "user", "payload": {"followUpDate": follow_up}},
            ])
            attribution = self.store.application_attribution_context(job_id, captured_at=now)
        elif command == "follow_up_sent":
            follow_up = (today + timedelta(days=7)).isoformat()
            note_line = f"[{today.isoformat()}] Follow-up sent."
            notes = "\n".join(part for part in [row.get("notes") or "", note_line] if part)
            changes.update({
                "current_status": "follow_up" if row["current_status"] == "applied" else row["current_status"],
                "follow_up_date": follow_up,
                "notes": notes,
            })
            events.extend([
                {"type": "follow_up_sent", "timestamp": now, "origin": "user", "payload": {}},
                {"type": "follow_up_scheduled", "timestamp": now, "origin": "user", "payload": {"followUpDate": follow_up}},
            ])
        elif command == "archive":
            changes.update({"current_status": "archived", "next_action": "none"})
            archived_at = now
            events.append({"type": "archived", "timestamp": now, "origin": "user", "payload": {}})
        elif command == "status_changed":
            status = _text(payload.get("status"), limit=40)
            if status not in APPLICATION_STATUSES:
                raise JobhuntError("Unsupported application status", code="invalid_job_status")
            changes["current_status"] = status
            archived_at = now if status == "archived" else None
            events.append({
                "type": "status_changed",
                "timestamp": now,
                "origin": "user",
                "payload": {"from": row["current_status"], "to": status},
            })
        elif command == "recruiter_updated":
            changes.update({
                "recruiter_name": _nullable_text(payload.get("recruiterName"), limit=300),
                "recruiter_contact": _nullable_text(payload.get("recruiterContact"), limit=500),
            })
            events.append({
                "type": "recruiter_updated", "timestamp": now, "origin": "user",
                "payload": {"recruiterName": changes["recruiter_name"], "recruiterContact": changes["recruiter_contact"]},
            })
        else:
            raise JobhuntError("Unsupported application command", code="unsupported_application_command")
        self.store.update_application_with_events(
            job_id, changes, events, archived_at=archived_at, attribution=attribution,
        )
        return self.get_application(job_id)

    def delete_job(self, job_id: str) -> dict[str, Any]:
        row = self.store.get_offer_row(job_id)
        if not row:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        now = _utc_now()
        self.store.update_application_with_events(
            job_id,
            {"current_status": "archived", "next_action": "none", "updated_at": now},
            [{"type": "deleted", "timestamp": now, "origin": "user", "payload": {"soft": True}}],
            archived_at=now,
            deleted_at=now,
        )
        return {"ok": True, "data": {"deleted": job_id, "soft": True}}

    def get_match_settings(self) -> dict[str, Any]:
        settings = self.store.get_setting("match_settings")
        return {"ok": True, "data": {"settings": self._normalize_settings(settings), "source": "legacy_compatibility"}}

    def update_match_settings(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {"settings"}:
            raise JobhuntError("Match settings payload must contain only settings", code="invalid_match_settings")
        settings = self._normalize_settings(payload.get("settings"))
        self.store.set_setting("match_settings", settings, source="user", updated_at=_utc_now())
        return {"ok": True, "data": {"settings": settings, "source": "legacy_compatibility"}}

    def _summary(self, offers: list[dict[str, Any]]) -> dict[str, Any]:
        today = datetime.now().astimezone().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=7)
        closed = {"rejected", "archived", "offer", "expired"}
        active = [offer for offer in offers if offer["status"] not in closed]
        worth = [
            offer for offer in active
            if offer["status"] == "worth_applying" or offer["priority"] in {"P1", "P2"}
        ]
        def score(offer: dict[str, Any]) -> int:
            return int(offer.get("match", {}).get("score") or 0)
        best_candidates = [
            offer for offer in offers
            if offer["status"] not in {"archived", "expired"}
            and offer.get("evaluationSource") != "none"
        ]
        priority_order = {"P1": 0, "P2": 1, "P3": 2, "unknown": 3, "skip": 4}
        best = sorted(
            best_candidates,
            key=lambda offer: (-score(offer), priority_order.get(offer["priority"], 3), str(offer.get("createdAt") or "")),
        )[0] if best_candidates else None
        due = sorted([
            offer for offer in active
            if offer.get("application", {}).get("followUpDate")
            and offer["application"]["followUpDate"] <= today.isoformat()
        ], key=lambda offer: (offer["application"]["followUpDate"], priority_order.get(offer["priority"], 3), -score(offer)))
        expiring = []
        for offer in active:
            expires_at = _valid_date(offer.get("expiresAt"))
            if expires_at:
                days = (date.fromisoformat(expires_at) - today).days
                if 0 <= days <= 7:
                    expiring.append({"offer": offer, "days": days})
        expiring.sort(key=lambda item: (item["days"], priority_order.get(item["offer"]["priority"], 3)))
        applied_this_week = 0
        for offer in offers:
            applied = _valid_date(offer.get("application", {}).get("dateApplied"))
            if applied and week_start <= date.fromisoformat(applied) < week_end:
                applied_this_week += 1
        if due:
            focus = due[0]
            next_action = {
                "type": "follow_up", "title": f"Send follow-up to {focus['company']} - {focus['role']}",
                "reason": "Follow-up date is due or overdue.", "offerId": focus["id"],
            }
        else:
            focus = next((offer for offer in offers if offer["priority"] == "P1" and offer["status"] not in {"applied", "follow_up", "interview", "offer", "expired", "rejected", "archived"}), None)
            if focus:
                next_action = {
                    "type": "apply", "title": f"Apply to {focus['company']} - {focus['role']}",
                    "reason": (
                        f"P1 priority, {score(focus)}/100 match, not applied yet."
                        if focus.get("evaluationSource") != "none"
                        else "P1 priority, not applied yet; no candidate evaluation exists."
                    ),
                    "offerId": focus["id"],
                }
            else:
                review_count = sum(offer["status"] in {"new", "to_review"} for offer in offers)
                interview = next((offer for offer in offers if offer["status"] == "interview"), None)
                if review_count:
                    next_action = {
                        "type": "review", "title": f"Review {review_count} new offers",
                        "reason": "New or to-review offers need a decision.", "offerId": None,
                    }
                elif interview:
                    next_action = {
                        "type": "prepare_interview", "title": f"Prepare for interview: {interview['company']} - {interview['role']}",
                        "reason": "Interview status is active.", "offerId": interview["id"],
                    }
                else:
                    next_action = {
                        "type": "none", "title": "No urgent jobhunt action",
                        "reason": "Nothing needs attention right now.", "offerId": None,
                    }
        gaps: dict[str, dict[str, Any]] = {}
        for offer in offers:
            if offer["status"] == "archived":
                continue
            for value in offer.get("analysis", {}).get("skillGaps", []):
                key = value.lower()
                gaps.setdefault(key, {"skill": value, "count": 0})["count"] += 1
        def summary_offer(offer: dict[str, Any] | None) -> dict[str, Any] | None:
            if not offer:
                return None
            return {
                key: offer.get(key)
                for key in (
                    "id", "company", "role", "branding", "expiresAt", "sourceExpired",
                    "status", "priority", "nextAction", "match", "evaluationSource", "createdAt",
                )
            }
        return {
            "total": len(offers),
            "worthApplying": len(worth),
            "appliedThisWeek": applied_this_week,
            "followUpsDue": len(due),
            "expired": sum(offer["status"] == "expired" for offer in offers),
            "expiringSoon": len(expiring),
            "nextExpiration": (
                {"offer": summary_offer(expiring[0]["offer"]), "days": expiring[0]["days"]}
                if expiring else None
            ),
            "interviewsActive": sum(offer["status"] == "interview" for offer in offers),
            "activeOffers": len(active),
            "bestMatch": summary_offer(best),
            "bestMatchScore": score(best) if best else None,
            "nextAction": next_action,
            "pipeline": {status: sum(offer["status"] == status for offer in offers) for status in sorted(LEGACY_STATUSES)},
            "skillGaps": sorted(gaps.values(), key=lambda item: (-item["count"], item["skill"].lower()))[:6],
        }

    def overview(self) -> dict[str, Any]:
        offers = [self._row_to_offer(row) for row in self.store.list_offer_rows()]
        summary = self._summary(offers)
        tracks = [self._track_to_api(item) for item in self.store.list_tracks()]
        profile = self._profile_to_api(self.store.get_profile())
        review_items = self.store.list_reviews(state="open", limit=200)
        dedupe = self.store.dedupe_summary()

        evaluation_by_job: dict[str, list[dict[str, Any]]] = {}
        track_pulse: list[dict[str, Any]] = []
        jobs_with_unknowns: set[str] = set()
        blocker_free_jobs: set[str] = set()
        for track in tracks:
            evaluations = []
            gap_counts: dict[str, int] = {}
            for row in self.store.current_evaluation_rows_for_track(track["id"]):
                detail = self.store.get_evaluation(row["id"])
                if not detail:
                    continue
                item = self._evaluation_to_api(detail)
                evaluations.append(item)
                evaluation_by_job.setdefault(item["jobId"], []).append(item)
                if item["counts"]["unknowns"]:
                    jobs_with_unknowns.add(item["jobId"])
                if not item["counts"]["blockers"]:
                    blocker_free_jobs.add(item["jobId"])
                for finding in item.get("findings", []):
                    if finding.get("status") not in {"gap", "blocker"}:
                        continue
                    label = (
                        finding.get("conceptKey")
                        or (finding.get("display") or {}).get("label")
                        or (finding.get("display") or {}).get("requirement")
                        or finding.get("type")
                    )
                    if label:
                        gap_counts[str(label)] = gap_counts.get(str(label), 0) + 1
            top_gap = None
            if gap_counts:
                top_gap = sorted(gap_counts.items(), key=lambda item: (-item[1], item[0].casefold()))[0][0]
            track_pulse.append({
                "id": track["id"], "name": track["name"], "status": track["status"],
                "currentJobs": len(evaluations),
                "blockerFree": sum(not item["counts"]["blockers"] for item in evaluations),
                "withUnknowns": sum(bool(item["counts"]["unknowns"]) for item in evaluations),
                "topGap": top_gap,
            })

        def opportunity(offer: dict[str, Any]) -> dict[str, Any]:
            return {
                key: offer.get(key)
                for key in (
                    "id", "company", "role", "location", "source", "expiresAt",
                    "applicationStatus", "status", "createdAt", "sourceExpired",
                )
            } | {
                "isNew": offer.get("status") in {"new", "to_review"},
                "evaluations": evaluation_by_job.get(offer["id"], [])[:4],
            }

        active = [
            offer for offer in offers
            if offer.get("applicationStatus") not in {"archived", "rejected"}
            and not offer.get("sourceExpired")
        ]
        source_rows = [self._source_to_api(item) for item in self.store.list_sources()]
        source_setup = {
            "nav": bool(self.nav_adapter.token_configured),
            "pracuj": bool(self.mail_transport.configured),
            "jobbnorge": True,
        }
        source_home = []
        for source in source_rows:
            if source["key"] not in source_setup:
                continue
            policy = source.get("policy") or {}
            setup_ready = source_setup[source["key"]]
            error = policy.get("lastErrorMessage")
            source_home.append({
                "key": source["key"], "name": source["displayName"],
                "enabled": bool(policy.get("enabled")), "setupReady": setup_ready,
                "operationalState": policy.get("operationalState"),
                "actionRequired": bool(error) or (bool(policy.get("enabled")) and not setup_ready),
                "message": error or ("Setup is incomplete." if not setup_ready else None),
            })

        profile_empty = (
            not profile.get("currentRoleTitle")
            and not profile.get("headline")
            and not profile.get("professionalSummary")
            and all(not profile.get(key) for key in (
                "experience", "education", "certifications", "languages",
                "skills", "preferences", "constraints",
            ))
        )
        source_enabled = any(item.get("enabled") for item in source_home)
        selected_tracks = [item for item in tracks if item["status"] in {"active", "paused"}]
        first_run = profile_empty and not offers and not selected_tracks and not source_enabled
        attention = {
            "newJobs": sum(offer.get("status") in {"new", "to_review"} for offer in active),
            "reviewItems": len(review_items),
            "duplicateCandidates": int(dedupe.get("openCandidates") or 0),
            "followUpsDue": summary["followUpsDue"],
            "jobsWithUnknowns": len(jobs_with_unknowns),
            "blockerFreeJobs": len(blocker_free_jobs),
            "interviewsUpcoming": summary["interviewsActive"],
            "applicationsNeedingAction": sum(
                offer.get("nextAction") not in {None, "none", "archive"}
                and offer.get("applicationStatus") not in {"archived", "rejected", "offer"}
                for offer in offers
            ),
        }
        home = {
            "firstRun": first_run,
            "profileEmpty": profile_empty,
            "attention": attention,
            "recentOpportunities": [opportunity(item) for item in active[:6]],
            "tracks": [item for item in track_pulse if item["status"] != "archived"],
            "sources": source_home,
            "onboarding": [
                {"order": 1, "title": "Complete your Career Profile", "description": "Add the evidence Evaluations should use.", "href": "profile", "complete": not profile_empty},
                {"order": 2, "title": "Choose the Tracks you want to explore", "description": "Activate or refine a search strategy.", "href": "tracks", "complete": bool(selected_tracks)},
                {"order": 3, "title": "Enable a job source", "description": "Connect NAV, Pracuj JobAlert, or Jobbnorge.", "href": "sources", "complete": source_enabled},
            ],
        }
        market_signal = self.analytics_model.market(window="30d")
        application_signal = self.analytics_model.applications(window="90d")
        active_experiments = self.store.list_experiments(status="active")
        planned_experiments = self.store.list_experiments(status="planned")
        saved_proposals = [
            item for item in self.store.list_track_proposals()
            if item["state"] == "saved_for_review"
        ]
        home["insights"] = {
            "newJobs30d": market_signal["populations"]["observed"]["denominator"],
            "currentJobs": market_signal["populations"]["current"]["denominator"],
            "salaryCoveragePercent": market_signal["coverage"]["salary"]["knownPercent"],
            "applicationResponseRate90d": application_signal["rates"]["response"],
            "activeExperiments": len(active_experiments),
            "plannedExperiments": len(planned_experiments),
            "savedTrackProposals": len(saved_proposals),
            "href": "insights",
            "semantics": "Compact signals only; denominators and evidence are available in Insights.",
        }
        return {"ok": True, "data": {
            "authority": "sqlite", "summary": summary, "home": home,
        }}

    def _parse_migration_snapshot(self, payload: Any) -> MigrationSnapshot:
        if not isinstance(payload, dict):
            raise JobhuntError("Migration payload must be an object", code="invalid_migration_payload")
        unknown = sorted(set(payload) - {"schemaVersion", "idempotencyKey", "offers", "matchSettings"})
        if unknown:
            raise JobhuntError("Migration payload contains unsupported fields", code="unknown_migration_fields", details=unknown)
        if payload.get("schemaVersion") != MIGRATION_SCHEMA_VERSION:
            raise JobhuntError("Unsupported migration schema version", code="unsupported_migration_version")
        key = _text(payload.get("idempotencyKey"), limit=128)
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
            raise JobhuntError("Migration idempotency key is invalid", code="invalid_idempotency_key")
        offers = payload.get("offers")
        settings = payload.get("matchSettings")
        if not isinstance(offers, list) or not isinstance(settings, list):
            raise JobhuntError("Migration offers and matchSettings must be arrays", code="invalid_migration_payload")
        if len(offers) > MAX_MIGRATION_OFFERS or len(settings) > 100:
            raise JobhuntError("Migration payload contains too many records", status=413, code="migration_record_limit")
        if any(not isinstance(offer, dict) for offer in offers):
            raise JobhuntError("Every migrated offer must be an object", code="invalid_migration_payload")
        meaningful = {
            "schemaVersion": MIGRATION_SCHEMA_VERSION,
            "offers": offers,
            "matchSettings": settings,
        }
        canonical = _canonical_bytes(meaningful)
        if len(canonical) > MAX_MIGRATION_BYTES:
            raise JobhuntError("Migration payload is too large", status=413, code="migration_payload_too_large")
        fingerprint = _sha(canonical)
        return MigrationSnapshot(
            schema_version=MIGRATION_SCHEMA_VERSION,
            idempotency_key=key,
            offers=offers,
            match_settings=settings,
            fingerprint=fingerprint,
            canonical_bytes=canonical,
        )

    def _write_recovery(self, snapshot: MigrationSnapshot) -> str:
        self.recovery_directory.mkdir(parents=True, exist_ok=True)
        target = self.recovery_directory / f"local-storage-{snapshot.fingerprint}.json"
        if target.exists():
            if _sha(target.read_bytes()) != snapshot.fingerprint:
                raise JobhuntError("Recovery snapshot hash mismatch", status=500, code="recovery_hash_mismatch")
        else:
            temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(snapshot.canonical_bytes)
            if _sha(temporary.read_bytes()) != snapshot.fingerprint:
                temporary.unlink(missing_ok=True)
                raise JobhuntError("Recovery snapshot verification failed", status=500, code="recovery_write_failed")
            os.replace(temporary, target)
        return target.relative_to(self.store.database_path.parent).as_posix()

    def migrate_local_storage(self, payload: Any) -> dict[str, Any]:
        snapshot = self._parse_migration_snapshot(payload)
        successful = self.store.get_migration_by_fingerprint(snapshot.fingerprint)
        if successful and successful["status"] == "succeeded":
            return {"ok": True, "data": successful["result"]}
        same_key = self.store.get_migration_by_idempotency_key(snapshot.idempotency_key)
        if same_key and same_key["fingerprint"] != snapshot.fingerprint:
            raise JobhuntError(
                "This idempotency key was already used for a different migration payload",
                status=409,
                code="idempotency_key_conflict",
            )
        recovery_path = self._write_recovery(snapshot)
        now = _utc_now()
        migration = {
            "id": f"mig_{snapshot.fingerprint[:24]}",
            "schema_version": snapshot.schema_version,
            "fingerprint": snapshot.fingerprint,
            "idempotency_key": snapshot.idempotency_key,
            "payload_sha256": snapshot.fingerprint,
            "recovery_path": recovery_path,
            "offers_submitted": len(snapshot.offers),
            "started_at": now,
            "completed_at": now,
        }
        try:
            seen_legacy_ids: set[str] = set()
            items = []
            for index, raw in enumerate(snapshot.offers):
                legacy_id = _nullable_text(raw.get("id"), limit=300)
                if legacy_id and legacy_id in seen_legacy_ids:
                    raise JobhuntError(
                        f'Duplicate legacy ID "{legacy_id}" at offer {index + 1}',
                        code="duplicate_legacy_id",
                    )
                if legacy_id:
                    seen_legacy_ids.add(legacy_id)
                item = self._normalize_offer(raw, strict=False, now=now)
                item["events"] = self._migration_events(item, raw, now)
                items.append(item)
            settings = self._normalize_settings(snapshot.match_settings)
            result = self.store.import_legacy_snapshot(
                migration=migration,
                items=items,
                match_settings=settings,
            )
        except Exception as exc:
            failure = {
                "code": exc.code if isinstance(exc, JobhuntError) else "jobhunt_migration_failed",
                "message": str(exc) if isinstance(exc, JobhuntError) else "Migration failed",
            }
            self.store.record_failed_migration(migration, failure)
            if isinstance(exc, JobhuntError):
                raise
            raise JobhuntError(
                "Job Hunt migration failed; no canonical records were committed",
                status=500,
                code="jobhunt_migration_failed",
            ) from exc
        return {"ok": True, "data": result}

    def get_migration(self, migration_id: str) -> dict[str, Any]:
        row = self.store.get_migration(migration_id)
        if not row:
            raise JobhuntError("Migration not found", status=404, code="jobhunt_migration_not_found")
        data = row.get("result") or {
            "migrationId": row["id"],
            "status": row["status"],
            "fingerprint": row["fingerprint"],
            "failure": row.get("failure"),
        }
        return {"ok": True, "data": data}

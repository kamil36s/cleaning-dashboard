"""SQLite persistence boundary for the Job Hunt feature."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator
import uuid

from .evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATOR_VERSION,
    default_policy,
    fingerprint as evaluation_fingerprint,
    input_fingerprint as make_evaluation_input_fingerprint,
    track_context,
)
from .extraction.normalization import CONCEPTS
from .migrations import SCHEMA_VERSION, apply_migrations, validate_schema
from .models import JobhuntError, WORKER_JOB_TYPES
from .sources.nav import NAV_ADAPTER_KEY, NAV_ADAPTER_VERSION, NAV_SOURCE_ID
from .sources.jobbnorge import (
    JOBBNORGE_ADAPTER_KEY,
    JOBBNORGE_ADAPTER_VERSION,
    JOBBNORGE_BASE_URL,
    JOBBNORGE_SOURCE_ID,
)
from .sources.pracuj import (
    PRACUJ_ADAPTER_KEY,
    PRACUJ_ADAPTER_VERSION,
    PRACUJ_PARSER_VERSION,
    PRACUJ_SOURCE_ID,
)


PROFILE_COLLECTIONS = {
    "experience": {
        "table": "career_experience", "prefix": "exp",
        "columns": ("job_title", "employer", "start_date", "end_date", "is_current", "location", "employment_type", "description", "domains_json", "origin", "notes"),
        "json": {"domains_json"},
    },
    "education": {
        "table": "career_education", "prefix": "edu",
        "columns": ("institution", "field_program", "qualification", "start_date", "end_date", "completion_status", "origin", "notes"),
        "json": set(),
    },
    "certifications": {
        "table": "career_certifications", "prefix": "cert",
        "columns": ("name", "issuer", "issued_date", "expiration_date", "credential_reference", "origin", "notes"),
        "json": set(),
    },
    "languages": {
        "table": "career_languages", "prefix": "lang",
        "columns": ("language_name", "proficiency", "proficiency_scheme", "confidence", "origin", "notes"),
        "json": set(),
    },
    "skills": {
        "table": "career_skills", "prefix": "skill",
        "columns": ("display_name", "normalized_key", "level", "confidence", "development_interest", "evidence_notes", "origin"),
        "json": set(),
    },
    "preferences": {
        "table": "career_preferences", "prefix": "pref",
        "columns": ("dimension_key", "value_json", "importance", "confidence", "origin", "notes"),
        "json": {"value_json"},
    },
    "constraints": {
        "table": "career_constraints", "prefix": "constraint",
        "columns": ("constraint_key", "value_json", "is_hard", "origin", "notes"),
        "json": {"value_json"},
    },
    "evidence": {
        "table": "career_profile_evidence", "prefix": "evidence",
        "columns": ("target_type", "target_id", "field_name", "origin", "source_reference", "notes"),
        "json": set(), "created_only": True,
    },
}

TRACK_SEEDS = (
    {
        "id": "track_seed_qa_poland", "seed_key": "qa-poland", "slug": "qa-poland",
        "name": "QA Poland", "purpose": "Primary professional path using existing QA and testing experience in Poland, Kraków, or remote-compatible roles.",
        "countries": ["PL"], "regions_cities": ["Kraków"], "remote_allowed": True,
        "relocation_relevant": None, "primary_currency": "PLN",
        "profiles": (
            ("manual-qa", "Manual QA", ["manual QA", "software tester"], "Manual software testing roles"),
            ("qa-analyst", "QA Analyst / Test Analyst", ["QA analyst", "test analyst"], "QA and test analysis roles"),
            ("technical-qa", "QA Engineer / Technical QA", ["QA engineer", "technical QA"], "Technical quality engineering roles"),
            ("uat-coordinator", "UAT / Test Coordinator", ["UAT", "test coordinator"], "UAT and test coordination roles"),
        ),
        "sources": ["pracuj", "nofluffjobs", "company_sites"],
    },
    {
        "id": "track_seed_krakow_weekend", "seed_key": "krakow-weekend", "slug": "krakow-weekend",
        "name": "Kraków Weekend Work", "purpose": "Short-term supplementary income from flexible weekend or temporary work in Kraków.",
        "countries": ["PL"], "regions_cities": ["Kraków"], "remote_allowed": None,
        "relocation_relevant": False, "primary_currency": "PLN",
        "profiles": (
            ("weekend-retail", "Weekend retail", ["weekend retail", "weekend shop assistant"], "Flexible weekend retail work"),
            ("event-staff", "Event staff", ["event staff", "event crew"], "Event support and staffing"),
            ("hospitality-gastro", "Hospitality / gastro", ["weekend hospitality", "weekend gastro"], "Weekend hospitality and food-service work"),
            ("warehouse-stocking", "Warehouse / stocking", ["weekend warehouse", "stocking"], "Weekend warehouse and stocking work"),
            ("flexible-temporary", "Flexible temporary work", ["temporary work", "weekend work"], "Flexible short-term work"),
        ),
        "sources": ["olx", "pracuj", "company_sites"],
    },
    {
        "id": "track_seed_norway_physical", "seed_key": "norway-physical", "slug": "norway-physical",
        "name": "Norway Physical Work", "purpose": "Potential relocation route through physical or entry-level work, focused on savings potential and entry barriers.",
        "countries": ["NO"], "regions_cities": [], "remote_allowed": False,
        "relocation_relevant": True, "primary_currency": "NOK",
        "profiles": (
            ("warehouse", "Warehouse", ["warehouse", "lagermedarbeider"], "Warehouse roles in Norway"),
            ("production", "Production", ["production worker", "produksjonsmedarbeider"], "Production roles in Norway"),
            ("fish-processing", "Fish processing", ["fish processing", "seafood production"], "Fish and seafood processing roles"),
            ("cleaning", "Cleaning", ["cleaner", "renholder"], "Cleaning roles in Norway"),
            ("hotel-hospitality", "Hotel / hospitality", ["hotel worker", "hospitality"], "Hotel and hospitality roles"),
            ("construction-helper", "Construction helper", ["construction helper", "labourer"], "Entry-level construction support roles"),
        ),
        "sources": ["nav", "finn", "company_sites"],
    },
    {
        "id": "track_seed_norway_qa", "seed_key": "norway-qa", "slug": "norway-qa",
        "name": "Norway QA", "purpose": "Potential relocation route that preserves and develops QA career capital in Norway.",
        "countries": ["NO"], "regions_cities": [], "remote_allowed": True,
        "relocation_relevant": True, "primary_currency": "NOK",
        "profiles": (
            ("software-tester", "Software tester", ["software tester"], "Software testing roles in Norway"),
            ("qa-engineer", "QA engineer", ["QA engineer"], "Quality engineering roles in Norway"),
            ("test-analyst", "Test analyst", ["test analyst"], "Test analysis roles in Norway"),
            ("manual-qa", "Manual QA", ["manual QA"], "Manual QA roles in Norway"),
            ("technical-qa", "Technical QA", ["technical QA"], "Technical QA roles in Norway"),
        ),
        "sources": ["nav", "finn", "jobbnorge", "company_sites"],
    },
    {
        "id": "track_seed_iceland_physical", "seed_key": "iceland-physical", "slug": "iceland-physical",
        "name": "Iceland Physical Work", "purpose": "Exploratory international route through physical, seasonal, or entry-level employment in Iceland.",
        "countries": ["IS"], "regions_cities": [], "remote_allowed": False,
        "relocation_relevant": True, "primary_currency": "ISK",
        "profiles": (
            ("hotel-hospitality", "Hotel / hospitality", ["hotel worker", "hospitality"], "Hotel and hospitality roles in Iceland"),
            ("warehouse", "Warehouse", ["warehouse worker"], "Warehouse roles in Iceland"),
            ("production", "Production", ["production worker"], "Production roles in Iceland"),
            ("cleaning", "Cleaning", ["cleaner"], "Cleaning roles in Iceland"),
            ("seasonal-work", "Seasonal work", ["seasonal work"], "Seasonal employment in Iceland"),
        ),
        "sources": ["alfred", "company_sites"],
    },
)

SOURCE_SEEDS = (
    ("source_manual", "manual", "Manual import", "manual", "manual", "active", "manual", "1.0.0", 1,
     "User-supplied source material. This is the only Pack D ingestion adapter."),
    ("source_pracuj", "pracuj", "Pracuj.pl", "email_alert", "email", "active",
     PRACUJ_ADAPTER_KEY, PRACUJ_ADAPTER_VERSION, 1,
     "Official user-requested JobAlert email adapter; no Pracuj job pages are fetched."),
    ("source_nofluffjobs", "nofluffjobs", "No Fluff Jobs", "job_board", "unknown", "planned", None, None, 0, None),
    ("source_olx", "olx", "OLX", "job_board", "unknown", "planned", None, None, 0, None),
    ("source_nav", "nav", "NAV / Arbeidsplassen", "official_feed", "official_feed", "active",
     NAV_ADAPTER_KEY, NAV_ADAPTER_VERSION, 1,
     "Official pam-stilling-feed adapter. Collection remains disabled until explicitly enabled."),
    ("source_finn", "finn", "FINN", "job_board", "unknown", "planned", None, None, 0, None),
    ("source_alfred", "alfred", "Alfred", "job_board", "unknown", "planned", None, None, 0, None),
    ("source_jobbnorge", "jobbnorge", "Jobbnorge", "official_api", "official_api", "active",
     JOBBNORGE_ADAPTER_KEY, JOBBNORGE_ADAPTER_VERSION, 1,
     "Official Jobbnorge Public API v1 adapter; collection remains disabled until explicitly enabled."),
    ("source_company_sites", "company_sites", "Company sites", "company_site", "unknown", "planned", None, None, 0, None),
    ("source_email_alerts", "email_alerts", "Email alerts", "email_alert", "unknown", "planned", None, None, 0, None),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobhuntStore:
    def __init__(
        self,
        database_path: str | Path,
        *,
        backup_directory: str | Path | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.backup_directory = Path(backup_directory or self.database_path.parent / "jobhunt" / "backups")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            apply_migrations(
                connection,
                database_path=self.database_path,
                backup_directory=self.backup_directory,
                applied_at=_now(),
            )
            validate_schema(connection)
            self._ensure_profile(connection, _now())
            self._seed_tracks(connection, _now())
            self._seed_evaluation_policies(connection, _now())
            self._seed_sources(connection, _now())
            self._resolve_search_profile_sources(connection, _now())
            self._seed_normalization_concepts(connection, _now())

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schema_status(self) -> dict[str, Any]:
        with self.read_connection() as connection:
            version = int(connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM jobhunt_schema_migrations"
            ).fetchone()[0])
            foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        return {
            "version": version,
            "expectedVersion": SCHEMA_VERSION,
            "foreignKeys": bool(foreign_keys),
            "journalMode": journal_mode,
        }

    @staticmethod
    def _select_offer_sql() -> str:
        return """
        SELECT
            j.*,
            a.id AS application_id,
            a.current_status,
            a.source_expired,
            a.priority,
            a.next_action,
            a.date_applied,
            a.follow_up_date,
            a.recruiter_name,
            a.recruiter_contact,
            a.notes,
            a.created_at AS application_created_at,
            a.updated_at AS application_updated_at,
            e.id AS evaluation_id,
            e.snapshot_kind,
            e.match_score,
            e.match_category,
            e.match_summary,
            e.is_experimental,
            e.green_flags_json,
            e.red_flags_json,
            e.skill_gaps_json,
            e.fit_reasons_json,
            e.recommended_cv_version,
            e.cv_bullets_json,
            e.created_at AS evaluation_created_at,
            e.updated_at AS evaluation_updated_at
        FROM canonical_jobs j
        JOIN applications a ON a.job_id = j.id
        LEFT JOIN legacy_evaluation_snapshots e ON e.job_id = j.id
        """

    def list_offer_rows(
        self,
        *,
        include_deleted: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = "" if include_deleted else "WHERE j.deleted_at IS NULL AND j.merged_into_job_id IS NULL"
        with self.read_connection() as connection:
            rows = connection.execute(
                self._select_offer_sql() + where + " ORDER BY j.created_at DESC, j.id LIMIT ? OFFSET ?",
                (max(1, min(500, int(limit))), max(0, int(offset))),
            ).fetchall()
        return [dict(row) for row in rows]

    def visible_job_count(self) -> int:
        with self.read_connection() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM canonical_jobs WHERE deleted_at IS NULL AND merged_into_job_id IS NULL"
            ).fetchone()[0])

    def get_offer_row(self, job_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        deleted_clause = "" if include_deleted else " AND j.deleted_at IS NULL"
        with self.read_connection() as connection:
            row = connection.execute(
                self._select_offer_sql() + f" WHERE j.id=?{deleted_clause}",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def application_events(self, application_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT id,event_type,occurred_at,payload_json,origin
                   FROM application_events WHERE application_id=?
                   ORDER BY occurred_at,id""",
                (application_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "type": row["event_type"],
                "timestamp": row["occurred_at"],
                "payload": _loads(row["payload_json"], {}),
                "origin": row["origin"],
            }
            for row in rows
        ]

    def _append_event(
        self,
        connection: sqlite3.Connection,
        application_id: str,
        event: dict[str, Any],
    ) -> str:
        event_id = event.get("id") or _id("evt")
        connection.execute(
            """INSERT INTO application_events(
                   id,application_id,event_type,occurred_at,payload_json,origin
               ) VALUES(?,?,?,?,?,?)""",
            (
                event_id,
                application_id,
                event["type"],
                event["timestamp"],
                _json(event.get("payload") or {}),
                event.get("origin") or "user",
            ),
        )
        return event_id

    def _insert_offer(
        self,
        connection: sqlite3.Connection,
        item: dict[str, Any],
    ) -> tuple[str, str]:
        job = item["job"]
        application = item["application"]
        evaluation = item["evaluation"]
        job_id = job.get("id") or _id("job")
        application_id = application.get("id") or _id("app")
        connection.execute(
            """INSERT INTO canonical_jobs(
                   id,legacy_id,legacy_fingerprint,company,role_title,seniority,
                   location_city,location_country,work_mode,hybrid_details,
                   contract_type,contract_details,salary_min,salary_max,
                   salary_currency,salary_period,salary_tax_type,salary_is_known,
                   source_name,source_url,source_captured_at,expires_at,original_text,
                   requirements_json,branding_path,branding_mime,branding_sha256,
                   legacy_payload_json,created_at,updated_at,archived_at,deleted_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                job.get("legacy_id"),
                job["legacy_fingerprint"],
                job["company"],
                job["role_title"],
                job["seniority"],
                job["location_city"],
                job["location_country"],
                job["work_mode"],
                job["hybrid_details"],
                job["contract_type"],
                job["contract_details"],
                job.get("salary_min"),
                job.get("salary_max"),
                job["salary_currency"],
                job["salary_period"],
                job["salary_tax_type"],
                int(job["salary_is_known"]),
                job["source_name"],
                job.get("source_url"),
                job.get("source_captured_at"),
                job.get("expires_at"),
                job["original_text"],
                _json(job.get("requirements") or {}),
                job.get("branding_path"),
                job.get("branding_mime"),
                job.get("branding_sha256"),
                _json(job["legacy_payload"]),
                job["created_at"],
                job["updated_at"],
                job.get("archived_at"),
                job.get("deleted_at"),
            ),
        )
        connection.execute(
            """INSERT INTO applications(
                   id,job_id,current_status,source_expired,priority,next_action,
                   date_applied,follow_up_date,recruiter_name,recruiter_contact,
                   notes,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                application_id,
                job_id,
                application["current_status"],
                int(application["source_expired"]),
                application["priority"],
                application["next_action"],
                application.get("date_applied"),
                application.get("follow_up_date"),
                application.get("recruiter_name"),
                application.get("recruiter_contact"),
                application["notes"],
                application["created_at"],
                application["updated_at"],
            ),
        )
        connection.execute(
            """INSERT INTO legacy_evaluation_snapshots(
                   id,job_id,snapshot_kind,match_score,match_category,match_summary,
                   is_experimental,green_flags_json,red_flags_json,skill_gaps_json,
                   fit_reasons_json,recommended_cv_version,cv_bullets_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                evaluation.get("id") or _id("eval"),
                job_id,
                "legacy_imported",
                evaluation.get("match_score"),
                evaluation["match_category"],
                evaluation["match_summary"],
                int(evaluation["is_experimental"]),
                _json(evaluation.get("green_flags") or []),
                _json(evaluation.get("red_flags") or []),
                _json(evaluation.get("skill_gaps") or []),
                _json(evaluation.get("fit_reasons") or []),
                evaluation["recommended_cv_version"],
                _json(evaluation.get("cv_bullets") or []),
                evaluation["created_at"],
                evaluation["updated_at"],
            ),
        )
        for event in item.get("events") or []:
            self._append_event(connection, application_id, event)
        return job_id, application_id

    def create_offer(self, item: dict[str, Any]) -> str:
        try:
            with self.transaction() as connection:
                job_id, _ = self._insert_offer(connection, item)
            return job_id
        except sqlite3.IntegrityError as exc:
            raise JobhuntError(
                "A job with this legacy identity already exists",
                status=409,
                code="jobhunt_duplicate_job",
            ) from exc

    def update_offer(
        self,
        job_id: str,
        item: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        job = item["job"]
        application = item["application"]
        evaluation = item["evaluation"]
        with self.transaction() as connection:
            current = connection.execute(
                """SELECT a.id FROM canonical_jobs j JOIN applications a ON a.job_id=j.id
                   WHERE j.id=? AND j.deleted_at IS NULL""",
                (job_id,),
            ).fetchone()
            if not current:
                raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
            connection.execute(
                """UPDATE canonical_jobs SET
                       company=?,role_title=?,seniority=?,location_city=?,location_country=?,
                       work_mode=?,hybrid_details=?,contract_type=?,contract_details=?,
                       salary_min=?,salary_max=?,salary_currency=?,salary_period=?,salary_tax_type=?,
                       salary_is_known=?,source_name=?,source_url=?,source_captured_at=?,expires_at=?,
                       original_text=?,requirements_json=?,branding_path=?,branding_mime=?,branding_sha256=?,
                       legacy_payload_json=?,updated_at=?,archived_at=?
                   WHERE id=?""",
                (
                    job["company"], job["role_title"], job["seniority"],
                    job["location_city"], job["location_country"], job["work_mode"],
                    job["hybrid_details"], job["contract_type"], job["contract_details"],
                    job.get("salary_min"), job.get("salary_max"), job["salary_currency"],
                    job["salary_period"], job["salary_tax_type"], int(job["salary_is_known"]),
                    job["source_name"], job.get("source_url"), job.get("source_captured_at"),
                    job.get("expires_at"), job["original_text"], _json(job.get("requirements") or {}),
                    job.get("branding_path"), job.get("branding_mime"), job.get("branding_sha256"),
                    _json(job["legacy_payload"]), job["updated_at"], job.get("archived_at"), job_id,
                ),
            )
            connection.execute(
                """UPDATE applications SET current_status=?,source_expired=?,priority=?,next_action=?,
                       date_applied=?,follow_up_date=?,recruiter_name=?,recruiter_contact=?,notes=?,updated_at=?
                   WHERE job_id=?""",
                (
                    application["current_status"], int(application["source_expired"]),
                    application["priority"], application["next_action"],
                    application.get("date_applied"), application.get("follow_up_date"),
                    application.get("recruiter_name"), application.get("recruiter_contact"),
                    application["notes"], application["updated_at"], job_id,
                ),
            )
            connection.execute(
                """UPDATE legacy_evaluation_snapshots SET
                       match_score=?,match_category=?,match_summary=?,is_experimental=?,
                       green_flags_json=?,red_flags_json=?,skill_gaps_json=?,fit_reasons_json=?,
                       recommended_cv_version=?,cv_bullets_json=?,updated_at=? WHERE job_id=?""",
                (
                    evaluation.get("match_score"), evaluation["match_category"],
                    evaluation["match_summary"], int(evaluation["is_experimental"]),
                    _json(evaluation.get("green_flags") or []), _json(evaluation.get("red_flags") or []),
                    _json(evaluation.get("skill_gaps") or []), _json(evaluation.get("fit_reasons") or []),
                    evaluation["recommended_cv_version"], _json(evaluation.get("cv_bullets") or []),
                    evaluation["updated_at"], job_id,
                ),
            )
            for event in events:
                self._append_event(connection, current["id"], event)

    def update_application_with_events(
        self,
        job_id: str,
        changes: dict[str, Any],
        events: list[dict[str, Any]],
        *,
        archived_at: str | None | object = ...,
        deleted_at: str | None | object = ...,
        attribution: dict[str, Any] | None = None,
    ) -> None:
        allowed = {
            "current_status", "source_expired", "priority", "next_action", "date_applied",
            "follow_up_date", "recruiter_name", "recruiter_contact", "notes", "updated_at",
        }
        if set(changes) - allowed:
            raise ValueError("Unsupported application projection field")
        with self.transaction() as connection:
            row = connection.execute(
                """SELECT a.id FROM applications a JOIN canonical_jobs j ON j.id=a.job_id
                   WHERE j.id=? AND j.deleted_at IS NULL""",
                (job_id,),
            ).fetchone()
            if not row:
                raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
            if changes:
                assignments = ",".join(f"{column}=?" for column in changes)
                connection.execute(
                    f"UPDATE applications SET {assignments} WHERE job_id=?",
                    (*changes.values(), job_id),
                )
            job_updates: dict[str, Any] = {}
            if archived_at is not ...:
                job_updates["archived_at"] = archived_at
            if deleted_at is not ...:
                job_updates["deleted_at"] = deleted_at
            if job_updates:
                assignments = ",".join(f"{column}=?" for column in job_updates)
                connection.execute(
                    f"UPDATE canonical_jobs SET {assignments},updated_at=? WHERE id=?",
                    (*job_updates.values(), changes.get("updated_at") or _now(), job_id),
                )
            for event in events:
                self._append_event(connection, row["id"], event)
            if attribution:
                connection.execute(
                    """INSERT OR IGNORE INTO application_attributions(
                           application_id,track_id,discovery_source_id,attribution_basis,captured_at
                       ) VALUES(?,?,?,?,?)""",
                    (
                        row["id"], attribution.get("track_id"),
                        attribution.get("discovery_source_id"),
                        attribution["attribution_basis"], attribution["captured_at"],
                    ),
                )

    def application_attribution_context(self, job_id: str, *, captured_at: str) -> dict[str, Any]:
        with self.read_connection() as connection:
            assignments = connection.execute(
                """SELECT track_id,origin,created_at FROM track_job_assignments
                    WHERE job_id=? AND active=1
                    ORDER BY CASE origin WHEN 'manual' THEN 0 ELSE 1 END,created_at,track_id""",
                (job_id,),
            ).fetchall()
            source = connection.execute(
                """SELECT source_id FROM source_listings WHERE canonical_job_id=?
                    ORDER BY first_seen_at,id LIMIT 1""",
                (job_id,),
            ).fetchone()
        if len(assignments) == 1:
            track_id = assignments[0]["track_id"]
            basis = "captured_at_application"
        elif assignments:
            track_id = assignments[0]["track_id"]
            basis = "multiple_current_tracks"
        else:
            track_id = None
            basis = "unattributed"
        return {
            "track_id": track_id,
            "discovery_source_id": source["source_id"] if source else None,
            "attribution_basis": basis,
            "captured_at": captured_at,
        }

    def get_setting(self, key: str) -> Any | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM compatibility_settings WHERE setting_key=?",
                (key,),
            ).fetchone()
        return _loads(row[0], None) if row else None

    def set_setting(self, key: str, value: Any, *, source: str, updated_at: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO compatibility_settings(setting_key,value_json,source,updated_at)
                   VALUES(?,?,?,?) ON CONFLICT(setting_key) DO UPDATE SET
                   value_json=excluded.value_json,source=excluded.source,updated_at=excluded.updated_at""",
                (key, _json(value), source, updated_at),
            )

    def get_migration_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._get_migration("fingerprint", fingerprint)

    def get_migration_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        return self._get_migration("idempotency_key", key)

    def get_migration(self, migration_id: str) -> dict[str, Any] | None:
        return self._get_migration("id", migration_id)

    def _get_migration(self, column: str, value: str) -> dict[str, Any] | None:
        if column not in {"id", "fingerprint", "idempotency_key"}:
            raise ValueError("Invalid migration lookup")
        with self.read_connection() as connection:
            row = connection.execute(
                f"SELECT * FROM local_storage_migrations WHERE {column}=?",
                (value,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = _loads(result.pop("result_json"), None)
        result["failure"] = _loads(result.pop("failure_json"), None)
        return result

    def import_legacy_snapshot(
        self,
        *,
        migration: dict[str, Any],
        items: list[dict[str, Any]],
        match_settings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            existing_success = connection.execute(
                "SELECT result_json FROM local_storage_migrations WHERE fingerprint=? AND status='succeeded'",
                (migration["fingerprint"],),
            ).fetchone()
            if existing_success:
                return _loads(existing_success[0], {})
            connection.execute(
                """INSERT INTO local_storage_migrations(
                       id,schema_version,fingerprint,idempotency_key,status,payload_sha256,
                       recovery_path,offers_submitted,started_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                       idempotency_key=excluded.idempotency_key,status='in_progress',
                       payload_sha256=excluded.payload_sha256,recovery_path=excluded.recovery_path,
                       offers_submitted=excluded.offers_submitted,started_at=excluded.started_at,
                       completed_at=NULL,failure_json=NULL""",
                (
                    migration["id"], migration["schema_version"], migration["fingerprint"],
                    migration["idempotency_key"], "in_progress", migration["payload_sha256"],
                    migration["recovery_path"], len(items), migration["started_at"],
                ),
            )
            connection.execute(
                "DELETE FROM local_storage_migration_items WHERE migration_id=?",
                (migration["id"],),
            )
            imported = 0
            already_existing = 0
            mappings = []
            warnings: list[str] = []
            for index, item in enumerate(items):
                job = item["job"]
                existing = None
                if job.get("legacy_id"):
                    existing = connection.execute(
                        "SELECT id FROM canonical_jobs WHERE legacy_id=?",
                        (job["legacy_id"],),
                    ).fetchone()
                if not existing:
                    existing = connection.execute(
                        "SELECT id FROM canonical_jobs WHERE legacy_fingerprint=?",
                        (job["legacy_fingerprint"],),
                    ).fetchone()
                if existing:
                    job_id = existing["id"]
                    outcome = "already_existing"
                    already_existing += 1
                else:
                    job_id, _ = self._insert_offer(connection, item)
                    outcome = "imported"
                    imported += 1
                item_warnings = list(item.get("warnings") or [])
                warnings.extend(item_warnings)
                connection.execute(
                    """INSERT INTO local_storage_migration_items(
                           migration_id,item_index,legacy_id,job_id,outcome,warnings_json
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        migration["id"], index, job.get("legacy_id"), job_id,
                        outcome, _json(item_warnings),
                    ),
                )
                mappings.append({
                    "index": index,
                    "legacyId": job.get("legacy_id"),
                    "jobId": job_id,
                    "outcome": outcome,
                })
            connection.execute(
                """INSERT INTO compatibility_settings(setting_key,value_json,source,updated_at)
                   VALUES('match_settings',?,'legacy_imported',?)
                   ON CONFLICT(setting_key) DO UPDATE SET
                   value_json=excluded.value_json,source=excluded.source,updated_at=excluded.updated_at""",
                (_json(match_settings), migration["completed_at"]),
            )
            mapped = connection.execute(
                """SELECT COUNT(*) FROM local_storage_migration_items mi
                   JOIN canonical_jobs j ON j.id=mi.job_id
                   JOIN applications a ON a.job_id=j.id
                   JOIN legacy_evaluation_snapshots e ON e.job_id=j.id
                   WHERE mi.migration_id=?""",
                (migration["id"],),
            ).fetchone()[0]
            if int(mapped) != len(items):
                raise JobhuntError(
                    "Migration verification failed",
                    status=500,
                    code="jobhunt_migration_verification_failed",
                )
            result = {
                "migrationId": migration["id"],
                "status": "succeeded",
                "schemaVersion": migration["schema_version"],
                "fingerprint": migration["fingerprint"],
                "payloadSha256": migration["payload_sha256"],
                "offersSubmitted": len(items),
                "imported": imported,
                "alreadyExisting": already_existing,
                "skipped": already_existing,
                "warnings": warnings,
                "failures": [],
                "mappings": mappings,
                "verified": True,
                "recoverySnapshot": {
                    "path": migration["recovery_path"],
                    "sha256": migration["payload_sha256"],
                },
            }
            connection.execute(
                """UPDATE local_storage_migrations SET status='succeeded',offers_imported=?,
                       offers_existing=?,result_json=?,failure_json=NULL,completed_at=? WHERE id=?""",
                (
                    imported, already_existing, _json(result), migration["completed_at"], migration["id"],
                ),
            )
            return result

    def record_failed_migration(self, migration: dict[str, Any], failure: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO local_storage_migrations(
                       id,schema_version,fingerprint,idempotency_key,status,payload_sha256,
                       recovery_path,offers_submitted,failure_json,started_at,completed_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                       status='failed',failure_json=excluded.failure_json,
                       recovery_path=excluded.recovery_path,completed_at=excluded.completed_at""",
                (
                    migration["id"], migration["schema_version"], migration["fingerprint"],
                    migration["idempotency_key"], "failed", migration["payload_sha256"],
                    migration["recovery_path"], migration.get("offers_submitted", 0),
                    _json(failure), migration["started_at"], migration["completed_at"],
                ),
            )

    def counts(self) -> dict[str, int]:
        with self.read_connection() as connection:
            return {
                "jobs": int(connection.execute("SELECT COUNT(*) FROM canonical_jobs").fetchone()[0]),
                "applications": int(connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]),
                "events": int(connection.execute("SELECT COUNT(*) FROM application_events").fetchone()[0]),
                "evaluations": int(connection.execute("SELECT COUNT(*) FROM legacy_evaluation_snapshots").fetchone()[0]),
                "migrations": int(connection.execute("SELECT COUNT(*) FROM local_storage_migrations").fetchone()[0]),
            }

    def _seed_normalization_concepts(self, connection: sqlite3.Connection, now: str) -> None:
        for concept_id, concept_type, concept_key, label, aliases in CONCEPTS:
            connection.execute(
                """INSERT OR IGNORE INTO normalization_concepts(
                       id,concept_type,concept_key,display_label,aliases_json,active,created_at,updated_at
                   ) VALUES(?,?,?,?,?,1,?,?)""",
                (concept_id, concept_type, concept_key, label, _json(list(aliases)), now, now),
            )

    def _seed_sources(self, connection: sqlite3.Connection, now: str) -> None:
        for seed in SOURCE_SEEDS:
            connection.execute(
                """INSERT OR IGNORE INTO source_definitions(
                       id,source_key,display_name,source_category,expected_access_method,
                       home_url,definition_state,adapter_key,adapter_version,
                       adapter_implemented,notes,created_at,updated_at
                   ) VALUES(?,?,?,?,?,NULL,?,?,?,?,?,?,?)""",
                (*seed[:5], seed[5], seed[6], seed[7], seed[8], seed[9], now, now),
            )
            source_id, key = seed[0], seed[1]
            connection.execute(
                """INSERT OR IGNORE INTO source_policies(
                       source_id,access_method,enabled,operational_state,failure_count,notes,updated_at
                   ) VALUES(?,?,?,?,0,?,?)""",
                (
                    source_id,
                    "manual" if key == "manual" else "unknown",
                    1 if key == "manual" else 0,
                    "manual_only" if key == "manual" else "planned",
                    "Manual imports run synchronously." if key == "manual" else "Collection not implemented.",
                    now,
                ),
            )
        connection.execute(
            """UPDATE source_definitions SET
                   source_category='official_feed',expected_access_method='official_feed',
                   home_url='https://pam-stilling-feed.nav.no',definition_state='active',
                   adapter_key=?,adapter_version=?,adapter_implemented=1,
                   notes='Official NAV pam-stilling-feed adapter; bearer token remains backend-only.',
                   updated_at=?
               WHERE id=?""",
            (NAV_ADAPTER_KEY, NAV_ADAPTER_VERSION, now, NAV_SOURCE_ID),
        )
        connection.execute(
            """UPDATE source_policies SET
                   access_method='official_feed',
                   operational_state=CASE WHEN operational_state='planned' THEN 'disabled' ELSE operational_state END,
                   polling_cadence_seconds=COALESCE(polling_cadence_seconds,120),
                   maximum_request_budget=COALESCE(maximum_request_budget,100),
                   concurrency_limit=1,conditional_requests_supported=1,
                   terms_reviewed_at=COALESCE(terms_reviewed_at,'2026-09-23T00:00:00+00:00'),
                   terms_reference='https://arbeidsplassen.nav.no/vilkar-api',
                   terms_version='reviewed-2026-09-23',
                   notes=CASE WHEN notes='Collection not implemented.' OR notes IS NULL
                              THEN 'Official feed; explicit enablement and a configured private token are required.'
                              ELSE notes END,
                   updated_at=?
               WHERE source_id=?""",
            (now, NAV_SOURCE_ID),
        )
        connection.execute(
            """INSERT OR IGNORE INTO source_sync_state(
                   source_id,adapter_version,bootstrap_horizon_days,updated_at
               ) VALUES(?,?,185,?)""",
            (NAV_SOURCE_ID, NAV_ADAPTER_VERSION, now),
        )
        connection.execute(
            """UPDATE source_definitions SET
                   display_name='Pracuj.pl',source_category='email_alert',
                   expected_access_method='email',definition_state='active',
                   adapter_key=?,adapter_version=?,adapter_implemented=1,
                   notes='Official user-requested JobAlert email adapter; no Pracuj job pages are fetched.',
                   updated_at=?
               WHERE id=?""",
            (PRACUJ_ADAPTER_KEY, PRACUJ_ADAPTER_VERSION, now, PRACUJ_SOURCE_ID),
        )
        connection.execute(
            """UPDATE source_policies SET
                   access_method='email',
                   operational_state=CASE WHEN operational_state='planned' THEN 'disabled' ELSE operational_state END,
                   polling_cadence_seconds=COALESCE(polling_cadence_seconds,300),
                   maximum_request_budget=COALESCE(maximum_request_budget,500),
                   concurrency_limit=1,conditional_requests_supported=0,
                   terms_reviewed_at=COALESCE(terms_reviewed_at,'2026-09-23T00:00:00+00:00'),
                   terms_reference='https://pomoc.pracuj.pl/hc/pl/articles/221006447-Co-to-jest-zapisane-wyszukiwanie',
                   terms_version='reviewed-2026-09-23',
                   notes=CASE WHEN notes='Collection not implemented.' OR notes IS NULL
                              THEN 'Official JobAlert email only; explicit enablement and backend IMAP configuration are required.'
                              ELSE notes END,
                   updated_at=?
               WHERE source_id=?""",
            (now, PRACUJ_SOURCE_ID),
        )
        connection.execute(
            """INSERT OR IGNORE INTO source_mail_sync_state(
                   source_id,adapter_version,mailbox,bootstrap_days,bootstrap_max_messages,updated_at
               ) VALUES(?,?,?,30,500,?)""",
            (PRACUJ_SOURCE_ID, PRACUJ_PARSER_VERSION, "INBOX", now),
        )
        connection.execute(
            """UPDATE source_definitions SET
                   display_name='Jobbnorge',source_category='official_api',
                   expected_access_method='official_api',home_url=?,definition_state='active',
                   adapter_key=?,adapter_version=?,adapter_implemented=1,
                   notes='Official Jobbnorge Public API v1 adapter; no vacancy pages or Integration API are used.',
                   updated_at=?
               WHERE id=?""",
            (
                JOBBNORGE_BASE_URL, JOBBNORGE_ADAPTER_KEY,
                JOBBNORGE_ADAPTER_VERSION, now, JOBBNORGE_SOURCE_ID,
            ),
        )
        connection.execute(
            """UPDATE source_policies SET
                   access_method='official_api',
                   operational_state=CASE WHEN operational_state='planned' THEN 'disabled' ELSE operational_state END,
                   polling_cadence_seconds=COALESCE(polling_cadence_seconds,1800),
                   maximum_request_budget=COALESCE(maximum_request_budget,12),
                   concurrency_limit=1,conditional_requests_supported=0,
                   terms_reviewed_at=COALESCE(terms_reviewed_at,'2026-09-24T00:00:00+00:00'),
                   terms_reference='https://publicapi.jobbnorge.no/swagger/index.html',
                   terms_version='public-api-v1-reviewed-2026-09-24',
                   notes=CASE WHEN notes='Collection not implemented.' OR notes IS NULL
                              THEN 'Unauthenticated official Public API; explicit enablement is required.'
                              ELSE notes END,
                   updated_at=?
               WHERE source_id=?""",
            (now, JOBBNORGE_SOURCE_ID),
        )
        connection.execute(
            """INSERT OR IGNORE INTO source_query_sync_state(
                   source_id,adapter_version,updated_at
               ) VALUES(?,?,?)""",
            (JOBBNORGE_SOURCE_ID, JOBBNORGE_ADAPTER_VERSION, now),
        )

    def _resolve_search_profile_sources(self, connection: sqlite3.Connection, now: str) -> None:
        source_ids = {
            row["source_key"]: row["id"]
            for row in connection.execute("SELECT id,source_key FROM source_definitions")
        }
        rows = connection.execute(
            "SELECT id,planned_source_keys_json FROM track_search_profiles"
        ).fetchall()
        for row in rows:
            for key in _loads(row["planned_source_keys_json"], []):
                source_id = source_ids.get(str(key))
                if source_id:
                    connection.execute(
                        """INSERT OR IGNORE INTO search_profile_sources(
                               search_profile_id,source_id,legacy_source_key,resolved_at
                           ) VALUES(?,?,?,?)""",
                        (row["id"], source_id, str(key), now),
                    )

    def search_profile_source_resolution(self, profile_id: str) -> dict[str, list[str]]:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT planned_source_keys_json FROM track_search_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if not row:
                return {"resolved": [], "unresolved": []}
            planned = [str(item) for item in _loads(row[0], [])]
            resolved = {
                str(item[0]) for item in connection.execute(
                    "SELECT legacy_source_key FROM search_profile_sources WHERE search_profile_id=?",
                    (profile_id,),
                )
            }
        return {
            "resolved": [key for key in planned if key in resolved],
            "unresolved": [key for key in planned if key not in resolved],
        }

    def list_sources(self) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT d.*,p.access_method,p.enabled,p.operational_state,
                          p.polling_cadence_seconds,p.maximum_request_budget,p.concurrency_limit,
                          p.conditional_requests_supported,p.last_attempt_at,p.last_success_at,
                          p.failure_count,p.backoff_until,p.last_error_class,p.terms_reviewed_at,
                          p.last_error_message,p.terms_reference,p.terms_version,
                          p.robots_reviewed_at,p.notes AS policy_notes,p.updated_at AS policy_updated_at,
                          (SELECT COUNT(*) FROM source_listings l WHERE l.source_id=d.id) AS listing_count,
                          (SELECT COUNT(*) FROM source_listings l
                           WHERE l.source_id=d.id AND l.lifecycle_state='active') AS active_listing_count,
                          (SELECT COUNT(DISTINCT l.id) FROM source_listings l
                           JOIN source_listing_search_profiles sp ON sp.listing_id=l.id
                           WHERE l.source_id=d.id) AS matched_listing_count,
                          (SELECT COUNT(*) FROM raw_captures c JOIN source_listings l ON l.id=c.listing_id
                           WHERE l.source_id=d.id) AS capture_count,
                          (SELECT COUNT(*) FROM source_collection_captures cc
                           WHERE cc.source_id=d.id) AS collection_capture_count
                   FROM source_definitions d JOIN source_policies p ON p.source_id=d.id
                   ORDER BY CASE d.source_key WHEN 'manual' THEN 0 ELSE 1 END,d.display_name COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_source(self, source_id_or_key: str) -> dict[str, Any] | None:
        return next((item for item in self.list_sources()
                     if item["id"] == source_id_or_key or item["source_key"] == source_id_or_key), None)

    @staticmethod
    def _decode_listing(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["capture_count"] = int(result.get("capture_count") or 0)
        return result

    def list_source_listings(
        self, *, source_id: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        clause = "WHERE l.source_id=?" if source_id else ""
        parameters: list[Any] = [source_id] if source_id else []
        parameters.extend([max(1, min(500, limit)), max(0, offset)])
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT l.*,d.source_key,d.display_name AS source_name,
                           COUNT(c.id) AS capture_count,
                           (SELECT c2.id FROM raw_captures c2 WHERE c2.listing_id=l.id
                            ORDER BY c2.captured_at DESC,c2.rowid DESC LIMIT 1) AS latest_capture_id,
                           (SELECT c2.captured_at FROM raw_captures c2 WHERE c2.listing_id=l.id
                            ORDER BY c2.captured_at DESC,c2.rowid DESC LIMIT 1) AS latest_capture_at
                    FROM source_listings l JOIN source_definitions d ON d.id=l.source_id
                    LEFT JOIN raw_captures c ON c.listing_id=l.id {clause}
                    GROUP BY l.id ORDER BY l.last_seen_at DESC,l.id LIMIT ? OFFSET ?""",
                parameters,
            ).fetchall()
            results = []
            for row in rows:
                result = self._decode_listing(row)
                listing_id = result["id"]
                result["tracks"] = [dict(item) for item in connection.execute(
                    """SELECT t.id,t.name,t.slug,lt.discovered_at,lt.notes
                       FROM source_listing_tracks lt JOIN career_tracks t ON t.id=lt.track_id
                       WHERE lt.listing_id=? ORDER BY t.name COLLATE NOCASE""",
                    (listing_id,),
                )]
                result["search_profiles"] = [dict(item) for item in connection.execute(
                    """SELECT p.id,p.name,p.track_id,lp.discovered_at,lp.notes
                       FROM source_listing_search_profiles lp
                       JOIN track_search_profiles p ON p.id=lp.search_profile_id
                       WHERE lp.listing_id=? ORDER BY p.name COLLATE NOCASE""",
                    (listing_id,),
                )]
                results.append(result)
        return results

    def get_source_listing(self, listing_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT l.*,d.source_key,d.display_name AS source_name,
                          COUNT(c.id) AS capture_count,
                          (SELECT c2.id FROM raw_captures c2 WHERE c2.listing_id=l.id
                           ORDER BY c2.captured_at DESC,c2.rowid DESC LIMIT 1) AS latest_capture_id,
                          (SELECT c2.captured_at FROM raw_captures c2 WHERE c2.listing_id=l.id
                           ORDER BY c2.captured_at DESC,c2.rowid DESC LIMIT 1) AS latest_capture_at
                   FROM source_listings l JOIN source_definitions d ON d.id=l.source_id
                   LEFT JOIN raw_captures c ON c.listing_id=l.id WHERE l.id=? GROUP BY l.id""",
                (listing_id,),
            ).fetchone()
            if not row:
                return None
            result = self._decode_listing(row)
            result["tracks"] = [dict(item) for item in connection.execute(
                """SELECT t.id,t.name,t.slug,lt.discovered_at,lt.notes
                   FROM source_listing_tracks lt JOIN career_tracks t ON t.id=lt.track_id
                   WHERE lt.listing_id=? ORDER BY t.name COLLATE NOCASE""", (listing_id,)
            )]
            result["search_profiles"] = [dict(item) for item in connection.execute(
                """SELECT p.id,p.name,p.track_id,lp.discovered_at,lp.notes
                   FROM source_listing_search_profiles lp
                   JOIN track_search_profiles p ON p.id=lp.search_profile_id
                   WHERE lp.listing_id=? ORDER BY p.name COLLATE NOCASE""", (listing_id,)
            )]
            result["collection_evidence"] = [dict(item) for item in connection.execute(
                """SELECT e.*,c.blob_sha256,c.request_path,c.query_fingerprint,c.page_number,
                          c.http_status,c.response_bytes,c.captured_at
                   FROM source_listing_collection_evidence e
                   JOIN source_collection_captures c ON c.id=e.collection_capture_id
                   WHERE e.listing_id=? ORDER BY c.captured_at DESC,e.item_index""",
                (listing_id,),
            )]
        return result

    def list_captures(self, listing_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT c.*,c.rowid AS capture_sequence,b.byte_size,b.relative_path
                   FROM raw_captures c JOIN raw_blobs b ON b.sha256=c.blob_sha256
                   WHERE c.listing_id=? ORDER BY c.captured_at,c.rowid""", (listing_id,)
            ).fetchall()
        result: list[dict[str, Any]] = []
        previous_hash = None
        for index, row in enumerate(rows):
            item = dict(row)
            item.pop("capture_sequence", None)
            item["safe_metadata"] = _loads(item.pop("safe_metadata_json"), {})
            item["change_state"] = "first" if index == 0 else (
                "unchanged" if item["blob_sha256"] == previous_hash else "changed"
            )
            previous_hash = item["blob_sha256"]
            result.append(item)
        return list(reversed(result))

    def get_capture(self, capture_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT c.*,b.byte_size,b.relative_path,
                          l.source_id,d.source_key,d.display_name AS source_name
                   FROM raw_captures c JOIN raw_blobs b ON b.sha256=c.blob_sha256
                   JOIN source_listings l ON l.id=c.listing_id
                   JOIN source_definitions d ON d.id=l.source_id WHERE c.id=?""", (capture_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["safe_metadata"] = _loads(result.pop("safe_metadata_json"), {})
        return result

    def raw_blob_rows(self) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT sha256,byte_size,mime_type,file_extension,relative_path FROM raw_blobs ORDER BY sha256"
            )]

    def get_raw_blob(self, sha256: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute("SELECT * FROM raw_blobs WHERE sha256=?", (sha256,)).fetchone()
        return dict(row) if row else None

    def ensure_raw_blob(self, blob: dict[str, Any], *, now: str) -> dict[str, Any]:
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM raw_blobs WHERE sha256=?", (blob["sha256"],)
            ).fetchone()
            if existing:
                if (
                    int(existing["byte_size"]) != int(blob["byte_size"])
                    or existing["relative_path"] != blob["relative_path"]
                ):
                    raise JobhuntError(
                        "Raw blob metadata conflict", status=500, code="raw_blob_metadata_conflict"
                    )
                return dict(existing)
            connection.execute(
                """INSERT INTO raw_blobs(
                       sha256,byte_size,mime_type,file_extension,relative_path,created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    blob["sha256"], blob["byte_size"], blob["mime_type"],
                    blob["file_extension"], blob["relative_path"], now,
                ),
            )
        return self.get_raw_blob(blob["sha256"]) or {}

    def save_collection_capture(
        self,
        *,
        source_id: str,
        blob: dict[str, Any],
        capture: dict[str, Any],
        captured_at: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM source_definitions WHERE id=?", (source_id,)
            ).fetchone():
                raise JobhuntError("Source not found", status=404, code="source_not_found")
            existing_blob = connection.execute(
                "SELECT * FROM raw_blobs WHERE sha256=?", (blob["sha256"],)
            ).fetchone()
            if existing_blob:
                if (
                    int(existing_blob["byte_size"]) != int(blob["byte_size"])
                    or existing_blob["relative_path"] != blob["relative_path"]
                ):
                    raise JobhuntError(
                        "Raw blob metadata conflict", status=500, code="raw_blob_metadata_conflict"
                    )
            else:
                connection.execute(
                    """INSERT INTO raw_blobs(
                           sha256,byte_size,mime_type,file_extension,relative_path,created_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        blob["sha256"], blob["byte_size"], blob["mime_type"],
                        blob["file_extension"], blob["relative_path"], captured_at,
                    ),
                )
            existing = connection.execute(
                """SELECT * FROM source_collection_captures
                   WHERE source_id=? AND operation_type=? AND request_path=? AND blob_sha256=?""",
                (
                    source_id, capture["operation_type"], capture["request_path"],
                    blob["sha256"],
                ),
            ).fetchone()
            if existing:
                result = dict(existing)
                result["safe_metadata"] = _loads(result.pop("safe_metadata_json"), {})
                result["reused"] = True
                return result
            capture_id = _id("collection_capture")
            connection.execute(
                """INSERT INTO source_collection_captures(
                       id,source_id,blob_sha256,operation_type,request_path,query_fingerprint,
                       page_number,http_status,mime_type,response_bytes,duration_ms,etag,last_modified,
                       safe_metadata_json,captured_at,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    capture_id, source_id, blob["sha256"], capture["operation_type"],
                    capture["request_path"], capture["query_fingerprint"],
                    capture.get("page_number"), capture.get("http_status"),
                    capture["mime_type"], capture["response_bytes"], capture.get("duration_ms"),
                    capture.get("etag"), capture.get("last_modified"),
                    _json(capture.get("safe_metadata") or {}), captured_at, captured_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM source_collection_captures WHERE id=?", (capture_id,)
            ).fetchone()
        result = dict(row)
        result["safe_metadata"] = _loads(result.pop("safe_metadata_json"), {})
        result["reused"] = False
        return result

    def link_listing_collection_evidence(
        self,
        *,
        listing_id: str,
        collection_capture_id: str,
        item_index: int,
        json_pointer: str,
        external_id: str,
        derived_capture_id: str | None,
        linked_at: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO source_listing_collection_evidence(
                       listing_id,collection_capture_id,item_index,json_pointer,external_id,
                       derived_capture_id,linked_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(listing_id,collection_capture_id,item_index) DO UPDATE SET
                       derived_capture_id=COALESCE(excluded.derived_capture_id,derived_capture_id)""",
                (
                    listing_id, collection_capture_id, int(item_index), json_pointer,
                    external_id, derived_capture_id, linked_at,
                ),
            )

    def get_query_sync_state(self, source_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_query_sync_state WHERE source_id=?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_query_sync_state(
        self, source_id: str, changes: dict[str, Any], *, now: str
    ) -> dict[str, Any]:
        allowed = {
            "adapter_version", "cycle_id", "query_fingerprint", "current_query_index",
            "current_page", "pages_fetched", "requests_made", "jobs_observed_cycle",
            "response_bytes_cycle", "query_count", "last_request_path",
            "last_collection_capture_id", "cycle_started_at", "cycle_completed_at",
            "last_poll_at", "last_success_at", "last_error_class", "last_error_message",
            "listings_observed", "matched_listings", "captures_created",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported query sync fields: {sorted(unknown)}")
        encoded = {**changes, "updated_at": now}
        with self.transaction() as connection:
            assignments = ",".join(f"{column}=?" for column in encoded)
            cursor = connection.execute(
                f"UPDATE source_query_sync_state SET {assignments} WHERE source_id=?",
                (*encoded.values(), source_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError(
                    "Source query sync state not found", status=404,
                    code="source_query_sync_state_not_found",
                )
        return self.get_query_sync_state(source_id) or {}

    def get_mail_sync_state(self, source_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_mail_sync_state WHERE source_id=?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_mail_sync_state(
        self, source_id: str, changes: dict[str, Any], *, now: str
    ) -> dict[str, Any]:
        allowed = {
            "adapter_version", "mailbox", "uidvalidity", "last_processed_uid",
            "highest_observed_uid", "bootstrap_started_at", "bootstrap_completed_at",
            "bootstrap_days", "bootstrap_max_messages", "last_poll_at", "last_success_at",
            "last_successful_message_at", "messages_inspected", "alerts_recognized",
            "listings_discovered", "captures_created", "last_error_class", "last_error_message",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported mail sync fields: {sorted(unknown)}")
        encoded = {**changes, "updated_at": now}
        with self.transaction() as connection:
            assignments = ",".join(f"{column}=?" for column in encoded)
            cursor = connection.execute(
                f"UPDATE source_mail_sync_state SET {assignments} WHERE source_id=?",
                (*encoded.values(), source_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError(
                    "Source mail sync state not found", status=404,
                    code="source_mail_sync_state_not_found",
                )
        return self.get_mail_sync_state(source_id) or {}

    def get_source_email_message(self, message_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT m.*,b.byte_size,b.mime_type,b.file_extension,b.relative_path
                   FROM source_email_messages m JOIN raw_blobs b ON b.sha256=m.raw_blob_sha256
                   WHERE m.id=?""",
                (message_id,),
            ).fetchone()
        return dict(row) if row else None

    def source_email_message_by_uid(
        self, source_id: str, mailbox: str, uidvalidity: str, uid: int
    ) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT id FROM source_email_messages
                   WHERE source_id=? AND mailbox=? AND uidvalidity=? AND uid=?""",
                (source_id, mailbox, uidvalidity, int(uid)),
            ).fetchone()
        return self.get_source_email_message(row["id"]) if row else None

    def save_source_email_message(self, values: dict[str, Any], *, now: str) -> tuple[dict[str, Any], bool]:
        existing = self.source_email_message_by_uid(
            values["source_id"], values["mailbox"], values["uidvalidity"], values["uid"]
        )
        if existing:
            return existing, True
        message_id = _id("source_email")
        with self.transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO source_email_messages(
                           id,source_id,mailbox,uidvalidity,uid,message_id,raw_blob_sha256,
                           received_at,sender,subject,trust_state,parser_version,processing_state,
                           item_count,error_class,error_message,created_at,processed_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,NULL,?,NULL,?)""",
                    (
                        message_id, values["source_id"], values["mailbox"],
                        values["uidvalidity"], int(values["uid"]), values.get("message_id"),
                        values["raw_blob_sha256"], values.get("received_at"),
                        values.get("sender"), values.get("subject"), values["trust_state"],
                        values["parser_version"], "pending", now, now,
                    ),
                )
            except sqlite3.IntegrityError:
                pass
        saved = self.source_email_message_by_uid(
            values["source_id"], values["mailbox"], values["uidvalidity"], values["uid"]
        )
        if not saved:
            raise JobhuntError("Source email message could not be saved", status=500, code="mail_message_save_failed")
        return saved, saved["id"] != message_id

    def update_source_email_message(
        self,
        message_id: str,
        *,
        processing_state: str,
        item_count: int = 0,
        error_class: str | None = None,
        error_message: str | None = None,
        processed_at: str | None = None,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE source_email_messages SET processing_state=?,item_count=?,
                          error_class=?,error_message=?,processed_at=?,updated_at=? WHERE id=?""",
                (
                    processing_state, max(0, int(item_count)), error_class,
                    (error_message or None), processed_at, now, message_id,
                ),
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Source email message not found", status=404, code="source_email_not_found")
        return self.get_source_email_message(message_id) or {}

    def list_pracuj_bindings(self) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT b.*,p.name AS search_profile_name,p.track_id,t.name AS track_name
                   FROM pracuj_alert_bindings b
                   JOIN track_search_profiles p ON p.id=b.search_profile_id
                   JOIN career_tracks t ON t.id=p.track_id
                   WHERE b.source_id=? ORDER BY t.name COLLATE NOCASE,p.name COLLATE NOCASE,b.id""",
                (PRACUJ_SOURCE_ID,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_pracuj_binding(
        self,
        *,
        binding_id: str | None,
        subject_matcher: str | None,
        search_profile_id: str,
        enabled: bool,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            profile = connection.execute(
                "SELECT id FROM track_search_profiles WHERE id=?", (search_profile_id,)
            ).fetchone()
            if not profile:
                raise JobhuntError("Search Profile not found", status=404, code="search_profile_not_found")
            if binding_id:
                cursor = connection.execute(
                    """UPDATE pracuj_alert_bindings SET subject_matcher=?,search_profile_id=?,
                              enabled=?,updated_at=? WHERE id=? AND source_id=?""",
                    (
                        subject_matcher, search_profile_id, int(enabled), now,
                        binding_id, PRACUJ_SOURCE_ID,
                    ),
                )
                if cursor.rowcount != 1:
                    raise JobhuntError("Pracuj alert binding not found", status=404, code="binding_not_found")
            else:
                binding_id = _id("pracuj_binding")
                connection.execute(
                    """INSERT INTO pracuj_alert_bindings(
                           id,source_id,subject_matcher,search_profile_id,enabled,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        binding_id, PRACUJ_SOURCE_ID, subject_matcher,
                        search_profile_id, int(enabled), now, now,
                    ),
                )
            connection.execute(
                """INSERT OR IGNORE INTO search_profile_sources(
                       search_profile_id,source_id,legacy_source_key,resolved_at
                   ) VALUES(?,?,?,?)""",
                (search_profile_id, PRACUJ_SOURCE_ID, "pracuj", now),
            )
        return next(item for item in self.list_pracuj_bindings() if item["id"] == binding_id)

    def ingestion_metrics(self) -> dict[str, int]:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT
                     (SELECT COUNT(*) FROM source_listings),
                     (SELECT COUNT(*) FROM raw_captures),
                     (SELECT COUNT(*) FROM source_collection_captures),
                     (SELECT COUNT(*) FROM raw_blobs),
                     (SELECT COALESCE(SUM(byte_size),0) FROM raw_blobs)"""
            ).fetchone()
        listings, captures, collection_captures, blobs, total_bytes = map(int, row)
        return {
            "listings": listings, "captures": captures, "uniqueBlobs": blobs,
            "collectionCaptures": collection_captures,
            "totalRawBytes": total_bytes,
            "reusedBlobReferences": max(0, captures + collection_captures - blobs),
        }

    def source_stats(self, source_id: str) -> dict[str, int]:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT
                     (SELECT COUNT(*) FROM source_listings WHERE source_id=?),
                     (SELECT COUNT(*) FROM source_listings WHERE source_id=? AND lifecycle_state='active'),
                     (SELECT COUNT(DISTINCT l.id) FROM source_listings l
                      JOIN source_listing_search_profiles p ON p.listing_id=l.id WHERE l.source_id=?),
                     (SELECT COUNT(*) FROM raw_captures c
                      JOIN source_listings l ON l.id=c.listing_id WHERE l.source_id=?)""",
                (source_id, source_id, source_id, source_id),
            ).fetchone()
        return {
            "listings": int(row[0]), "active": int(row[1]),
            "matched": int(row[2]), "captures": int(row[3]),
        }

    def enabled_source_profiles(self, source_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT p.*,t.name AS track_name,t.status AS track_status
                   FROM search_profile_sources binding
                   JOIN track_search_profiles p ON p.id=binding.search_profile_id
                   JOIN career_tracks t ON t.id=p.track_id
                   WHERE binding.source_id=? AND p.status='enabled'
                     AND t.status IN ('exploring','active')
                   ORDER BY p.id""",
                (source_id,),
            ).fetchall()
        return [self._decode_search_profile(row) for row in rows]

    def source_listing_by_external_id(
        self, source_id: str, external_id: str
    ) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT id FROM source_listings WHERE source_id=? AND external_id=?",
                (source_id, external_id),
            ).fetchone()
        return self.get_source_listing(row["id"]) if row else None

    @staticmethod
    def _set_application_source_state(
        connection: sqlite3.Connection,
        *,
        listing_id: str,
        canonical_job_id: str | None,
        lifecycle_state: str,
        now: str,
    ) -> None:
        if not canonical_job_id:
            return
        application = connection.execute(
            "SELECT id,source_expired FROM applications WHERE job_id=?", (canonical_job_id,)
        ).fetchone()
        if not application:
            return
        if lifecycle_state == "active":
            source_expired = 0
        elif lifecycle_state in {"expired", "removed"}:
            active = connection.execute(
                """SELECT COUNT(*) FROM source_listings
                   WHERE canonical_job_id=? AND lifecycle_state='active'""",
                (canonical_job_id,),
            ).fetchone()[0]
            source_expired = 0 if int(active) else 1
        else:
            return
        if int(application["source_expired"]) == source_expired:
            return
        connection.execute(
            "UPDATE applications SET source_expired=?,updated_at=? WHERE id=?",
            (source_expired, now, application["id"]),
        )
        connection.execute(
            """INSERT INTO application_events(
                   id,application_id,event_type,occurred_at,payload_json,origin
               ) VALUES(?,?,?,?,?,'system')""",
            (
                _id("event"), application["id"], "source_lifecycle_changed", now,
                _json({
                    "sourceExpired": bool(source_expired),
                    "sourceListingId": listing_id,
                    "lifecycleState": lifecycle_state,
                }),
            ),
        )

    def upsert_source_listing(
        self,
        *,
        listing: dict[str, Any],
        search_profile_ids: list[str] | None,
        observed_at: str,
    ) -> dict[str, Any]:
        profile_ids = list(dict.fromkeys(str(item) for item in (search_profile_ids or []) if item))
        with self.transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM source_definitions WHERE id=?", (listing["source_id"],)
            ).fetchone():
                raise JobhuntError("Source not found", status=404, code="source_not_found")
            existing = connection.execute(
                "SELECT * FROM source_listings WHERE source_id=? AND identity_key=?",
                (listing["source_id"], listing["identity_key"]),
            ).fetchone()
            listing_id = existing["id"] if existing else _id("listing")
            created = existing is None
            canonical_job_id = existing["canonical_job_id"] if existing else listing.get("canonical_job_id")
            if existing:
                connection.execute(
                    """UPDATE source_listings SET
                           external_id=COALESCE(?,external_id),canonical_url=COALESCE(?,canonical_url),
                           observed_url=COALESCE(?,observed_url),title_hint=COALESCE(?,title_hint),
                           company_hint=COALESCE(?,company_hint),location_hint=COALESCE(?,location_hint),
                           lifecycle_state=?,last_seen_at=?,source_ended_at=?,updated_at=?
                       WHERE id=?""",
                    (
                        listing.get("external_id"), listing.get("canonical_url"),
                        listing.get("observed_url"), listing.get("title_hint"),
                        listing.get("company_hint"), listing.get("location_hint"),
                        listing["lifecycle_state"], observed_at, listing.get("source_ended_at"),
                        observed_at, listing_id,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO source_listings(
                           id,source_id,identity_key,external_id,canonical_url,observed_url,
                           title_hint,company_hint,location_hint,lifecycle_state,first_seen_at,last_seen_at,
                           source_ended_at,canonical_job_id,notes,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        listing_id, listing["source_id"], listing["identity_key"],
                        listing.get("external_id"), listing.get("canonical_url"),
                        listing.get("observed_url"), listing.get("title_hint"),
                        listing.get("company_hint"), listing.get("location_hint"),
                        listing["lifecycle_state"], observed_at, observed_at,
                        listing.get("source_ended_at"), listing.get("canonical_job_id"),
                        listing.get("notes"), observed_at, observed_at,
                    ),
                )
            for profile_id in profile_ids:
                profile = connection.execute(
                    """SELECT p.track_id FROM track_search_profiles p
                       JOIN search_profile_sources b ON b.search_profile_id=p.id
                       WHERE p.id=? AND b.source_id=?""",
                    (profile_id, listing["source_id"]),
                ).fetchone()
                if not profile:
                    raise JobhuntError(
                        "Search Profile is not bound to this source",
                        status=409, code="search_profile_source_mismatch",
                    )
                connection.execute(
                    """INSERT OR IGNORE INTO source_listing_search_profiles(
                           listing_id,search_profile_id,discovered_at,notes
                       ) VALUES(?,?,?,?)""",
                    (listing_id, profile_id, observed_at, listing.get("notes")),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO source_listing_tracks(
                           listing_id,track_id,discovered_at,notes
                       ) VALUES(?,?,?,?)""",
                    (listing_id, profile["track_id"], observed_at, listing.get("notes")),
                )
            self._set_application_source_state(
                connection,
                listing_id=listing_id,
                canonical_job_id=canonical_job_id,
                lifecycle_state=listing["lifecycle_state"],
                now=observed_at,
            )
        return {"listing_id": listing_id, "created": created}

    def save_source_capture(
        self,
        *,
        listing_id: str,
        blob: dict[str, Any],
        capture: dict[str, Any],
        search_profile_ids: list[str],
        observed_at: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            listing = connection.execute(
                "SELECT source_id FROM source_listings WHERE id=?", (listing_id,)
            ).fetchone()
            if not listing:
                raise JobhuntError("Source Listing not found", status=404, code="source_listing_not_found")
            existing_blob = connection.execute(
                "SELECT * FROM raw_blobs WHERE sha256=?", (blob["sha256"],)
            ).fetchone()
            if existing_blob:
                if (
                    int(existing_blob["byte_size"]) != int(blob["byte_size"])
                    or existing_blob["relative_path"] != blob["relative_path"]
                ):
                    raise JobhuntError("Raw blob metadata conflict", status=500, code="raw_blob_metadata_conflict")
            else:
                connection.execute(
                    """INSERT INTO raw_blobs(
                           sha256,byte_size,mime_type,file_extension,relative_path,created_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        blob["sha256"], blob["byte_size"], blob["mime_type"],
                        blob["file_extension"], blob["relative_path"], observed_at,
                    ),
                )
            input_method = str(capture.get("input_method") or "nav_api")
            existing_capture = connection.execute(
                """SELECT id FROM raw_captures
                   WHERE listing_id=? AND blob_sha256=? AND input_method=?
                   ORDER BY captured_at DESC,rowid DESC LIMIT 1""",
                (listing_id, blob["sha256"], input_method),
            ).fetchone()
            capture_reused = existing_capture is not None
            capture_id = existing_capture["id"] if existing_capture else _id("capture")
            if not existing_capture:
                connection.execute(
                    """INSERT INTO raw_captures(
                           id,listing_id,blob_sha256,mime_type,file_extension,captured_at,input_method,
                           source_url,http_status,safe_metadata_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        capture_id, listing_id, blob["sha256"], capture["mime_type"],
                        capture["file_extension"], observed_at, input_method, capture.get("source_url"),
                        capture.get("http_status"), _json(capture.get("safe_metadata") or {}),
                        observed_at,
                    ),
                )
            for profile_id in list(dict.fromkeys(search_profile_ids)):
                profile = connection.execute(
                    """SELECT p.track_id FROM track_search_profiles p
                       JOIN search_profile_sources b ON b.search_profile_id=p.id
                       WHERE p.id=? AND b.source_id=?""",
                    (profile_id, listing["source_id"]),
                ).fetchone()
                if not profile:
                    continue
                connection.execute(
                    """INSERT OR IGNORE INTO source_listing_search_profiles(
                           listing_id,search_profile_id,discovered_at,notes
                       ) VALUES(?,?,?,NULL)""",
                    (listing_id, profile_id, observed_at),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO source_listing_tracks(
                           listing_id,track_id,discovered_at,notes
                       ) VALUES(?,?,?,NULL)""",
                    (listing_id, profile["track_id"], observed_at),
                )
        captures = self.list_captures(listing_id)
        row = next(item for item in captures if item["id"] == capture_id)
        return {"capture": row, "capture_reused": capture_reused}

    def set_source_enabled(self, source_id: str, *, enabled: bool, now: str) -> dict[str, Any]:
        state = "enabled" if enabled else "paused"
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE source_policies SET enabled=?,operational_state=?,
                          backoff_until=NULL,last_error_class=NULL,last_error_message=NULL,updated_at=?
                   WHERE source_id=?""",
                (int(enabled), state, now, source_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Source not found", status=404, code="source_not_found")
        source = self.get_source(source_id)
        return source or {}

    def configure_source_limits(
        self, source_id: str, *, polling_cadence_seconds: int,
        maximum_request_budget: int, now: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE source_policies SET polling_cadence_seconds=?,
                          maximum_request_budget=?,concurrency_limit=1,updated_at=?
                   WHERE source_id=?""",
                (
                    max(30, min(86400, int(polling_cadence_seconds))),
                    max(1, min(500, int(maximum_request_budget))),
                    now, source_id,
                ),
            )

    def record_source_attempt(self, source_id: str, *, now: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE source_policies SET last_attempt_at=?,updated_at=? WHERE source_id=?",
                (now, now, source_id),
            )

    def record_source_success(self, source_id: str, *, now: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE source_policies SET last_attempt_at=?,last_success_at=?,failure_count=0,
                          backoff_until=NULL,last_error_class=NULL,last_error_message=NULL,
                          operational_state=CASE WHEN enabled=1 THEN 'enabled' ELSE operational_state END,
                          updated_at=? WHERE source_id=?""",
                (now, now, now, source_id),
            )

    def record_source_failure(
        self,
        source_id: str,
        *,
        error_class: str,
        error_message: str,
        backoff_until: str | None,
        now: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE source_policies SET last_attempt_at=?,failure_count=failure_count+1,
                          backoff_until=?,last_error_class=?,last_error_message=?,
                          operational_state='degraded',updated_at=? WHERE source_id=?""",
                (now, backoff_until, error_class[:100], error_message[:1000], now, source_id),
            )

    @staticmethod
    def _decode_sync_state(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        return result

    def get_source_sync_state(self, source_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_sync_state WHERE source_id=?", (source_id,)
            ).fetchone()
        return self._decode_sync_state(row) if row else None

    def update_source_sync_state(
        self, source_id: str, changes: dict[str, Any], *, now: str
    ) -> dict[str, Any]:
        allowed = {
            "adapter_version", "feed_path", "current_feed_page_id", "next_feed_page_id",
            "etag", "last_modified", "conditional_feed_path", "bootstrap_if_modified_since",
            "bootstrap_started_at", "bootstrap_completed_at",
            "bootstrap_horizon_days", "last_feed_event_at", "last_poll_at", "last_success_at",
            "last_error_class", "last_error_message", "feed_version", "listings_observed",
            "active_listings", "matched_listings", "captures_created",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported source sync fields: {sorted(unknown)}")
        encoded = {**changes, "updated_at": now}
        with self.transaction() as connection:
            assignments = ",".join(f"{column}=?" for column in encoded)
            cursor = connection.execute(
                f"UPDATE source_sync_state SET {assignments} WHERE source_id=?",
                (*encoded.values(), source_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Source sync state not found", status=404, code="source_sync_state_not_found")
        return self.get_source_sync_state(source_id) or {}

    def record_source_request(self, values: dict[str, Any], *, retain: int = 1000) -> str:
        observation_id = _id("source_request")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO source_request_observations(
                       id,source_id,operation_type,request_path,status_code,started_at,completed_at,
                       duration_ms,response_bytes,retry_classification,etag,last_modified,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id, values["source_id"], values["operation_type"],
                    values["request_path"][:2048], values.get("status_code"),
                    values["started_at"], values["completed_at"], values.get("duration_ms"),
                    values.get("response_bytes"), values.get("retry_classification"),
                    values.get("etag"), values.get("last_modified"), values["completed_at"],
                ),
            )
            connection.execute(
                """DELETE FROM source_request_observations
                   WHERE source_id=? AND id NOT IN (
                       SELECT id FROM source_request_observations WHERE source_id=?
                       ORDER BY created_at DESC,id DESC LIMIT ?
                   )""",
                (values["source_id"], values["source_id"], max(100, min(10000, retain))),
            )
        return observation_id

    def list_source_requests(self, source_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT * FROM source_request_observations WHERE source_id=?
                   ORDER BY created_at DESC,id DESC LIMIT ?""",
                (source_id, max(1, min(200, limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _decode_worker_job(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = _loads(result.pop("payload_json", "{}"), {})
        result["result"] = _loads(result.pop("result_json", None), None)
        result["cancellation_requested"] = bool(result.get("cancellation_requested"))
        return result

    def enqueue_worker_job(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 5,
        next_attempt_at: str,
        parent_job_id: str | None = None,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        if job_type not in WORKER_JOB_TYPES:
            raise ValueError("Unsupported Job Hunt worker job type")
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 500:
            raise ValueError("Worker idempotency key is invalid")
        job_id = _id("worker")
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT * FROM worker_jobs WHERE idempotency_key=?
                   AND state IN ('queued','running','retry_wait')
                   ORDER BY created_at,id LIMIT 1""",
                (key,),
            ).fetchone()
            if existing:
                if existing["state"] == "queued" and next_attempt_at < existing["next_attempt_at"]:
                    connection.execute(
                        "UPDATE worker_jobs SET next_attempt_at=?,updated_at=? WHERE id=?",
                        (next_attempt_at, now, existing["id"]),
                    )
                    existing = connection.execute(
                        "SELECT * FROM worker_jobs WHERE id=?", (existing["id"],)
                    ).fetchone()
                return self._decode_worker_job(existing), True
            if parent_job_id and not connection.execute(
                "SELECT 1 FROM worker_jobs WHERE id=?", (parent_job_id,)
            ).fetchone():
                raise JobhuntError("Parent worker job not found", status=404, code="worker_parent_not_found")
            connection.execute(
                """INSERT INTO worker_jobs(
                       id,job_type,payload_version,payload_json,idempotency_key,priority,state,stage,
                       progress,attempt_count,max_attempts,next_attempt_at,lease_owner,lease_expires_at,
                       cancellation_requested,parent_job_id,created_at,started_at,updated_at,completed_at,
                       error_class,error_message,result_json
                   ) VALUES(?,?,1,?,?,?,'queued','queued',0,0,?,?,NULL,NULL,0,?,?,NULL,?,NULL,NULL,NULL,NULL)""",
                (
                    job_id, job_type, _json(payload), key, int(priority),
                    max(1, min(20, int(max_attempts))), next_attempt_at,
                    parent_job_id, now, now,
                ),
            )
            row = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_worker_job(row), False

    def recover_worker_jobs(self, *, now: str) -> dict[str, int]:
        result = {"requeued": 0, "cancelled": 0, "failed": 0}
        with self.transaction() as connection:
            result["cancelled"] += connection.execute(
                """UPDATE worker_jobs SET state='cancelled',stage='cancelled',completed_at=?,
                          lease_owner=NULL,lease_expires_at=NULL,error_class='cancelled',
                          error_message='Cancellation requested before restart recovery',updated_at=?
                   WHERE state='running' AND lease_expires_at<=? AND cancellation_requested=1""",
                (now, now, now),
            ).rowcount
            result["failed"] += connection.execute(
                """UPDATE worker_jobs SET state='failed',stage='failed',completed_at=?,
                          lease_owner=NULL,lease_expires_at=NULL,error_class='internal',
                          error_message='Worker lease expired after all attempts',updated_at=?
                   WHERE state='running' AND lease_expires_at<=? AND cancellation_requested=0
                     AND attempt_count>=max_attempts""",
                (now, now, now),
            ).rowcount
            result["requeued"] += connection.execute(
                """UPDATE worker_jobs SET state='retry_wait',stage='restart_recovery',
                          next_attempt_at=?,lease_owner=NULL,lease_expires_at=NULL,
                          error_class='internal',error_message='Recovered after an expired worker lease',
                          updated_at=?
                   WHERE state='running' AND lease_expires_at<=? AND cancellation_requested=0
                     AND attempt_count<max_attempts""",
                (now, now, now),
            ).rowcount
        return result

    def claim_worker_job(
        self, *, lease_owner: str, lease_expires_at: str, now: str
    ) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                """SELECT j.* FROM worker_jobs j
                   LEFT JOIN worker_jobs parent ON parent.id=j.parent_job_id
                   WHERE j.state IN ('queued','retry_wait') AND j.next_attempt_at<=?
                     AND j.cancellation_requested=0
                     AND (j.parent_job_id IS NULL OR parent.state='completed')
                   ORDER BY j.priority DESC,j.next_attempt_at,j.created_at,j.id LIMIT 1""",
                (now,),
            ).fetchone()
            if not row:
                return None
            cursor = connection.execute(
                """UPDATE worker_jobs SET state='running',stage='starting',progress=0,
                          attempt_count=attempt_count+1,lease_owner=?,lease_expires_at=?,
                          started_at=COALESCE(started_at,?),updated_at=?,completed_at=NULL
                   WHERE id=? AND state IN ('queued','retry_wait')""",
                (lease_owner, lease_expires_at, now, now, row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM worker_jobs WHERE id=?", (row["id"],)
            ).fetchone()
        return self._decode_worker_job(claimed)

    def update_worker_job_stage(
        self, job_id: str, *, stage: str, progress: float | None, now: str
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE worker_jobs SET stage=?,progress=?,updated_at=?
                   WHERE id=? AND state='running'""",
                (stage[:100], progress, now, job_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Running worker job not found", status=404, code="worker_job_not_running")
            row = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_worker_job(row)

    def renew_worker_job_lease(
        self, job_id: str, *, lease_owner: str, lease_expires_at: str, now: str
    ) -> bool:
        with self.transaction() as connection:
            updated = connection.execute(
                """UPDATE worker_jobs SET lease_expires_at=?,updated_at=?
                   WHERE id=? AND state='running' AND lease_owner=?""",
                (lease_expires_at, now, job_id, lease_owner),
            ).rowcount
        return updated == 1

    def complete_worker_job(
        self, job_id: str, *, result: dict[str, Any] | None, now: str,
        followups: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise JobhuntError("Worker job not found", status=404, code="worker_job_not_found")
            state = "cancelled" if row["cancellation_requested"] else "completed"
            stage = state
            connection.execute(
                """UPDATE worker_jobs SET state=?,stage=?,progress=1,lease_owner=NULL,
                          lease_expires_at=NULL,completed_at=?,error_class=?,error_message=?,
                          result_json=?,updated_at=? WHERE id=?""",
                (
                    state, stage, now, "cancelled" if state == "cancelled" else None,
                    "Cancellation requested" if state == "cancelled" else None,
                    _json(result) if result is not None else None, now, job_id,
                ),
            )
            if state == "completed":
                for followup in followups or []:
                    job_type = str(followup.get("job_type") or "")
                    key = str(followup.get("idempotency_key") or "").strip()
                    if job_type not in WORKER_JOB_TYPES or not key or len(key) > 500:
                        raise ValueError("Worker follow-up is invalid")
                    if connection.execute(
                        """SELECT 1 FROM worker_jobs WHERE idempotency_key=?
                           AND state IN ('queued','running','retry_wait')""",
                        (key,),
                    ).fetchone():
                        continue
                    parent_id = followup.get("parent_job_id") or job_id
                    child_id = _id("worker")
                    connection.execute(
                        """INSERT INTO worker_jobs(
                               id,job_type,payload_version,payload_json,idempotency_key,priority,
                               state,stage,progress,attempt_count,max_attempts,next_attempt_at,
                               lease_owner,lease_expires_at,cancellation_requested,parent_job_id,
                               created_at,started_at,updated_at,completed_at,error_class,error_message,
                               result_json
                           ) VALUES(?,?,1,?,?,?,'queued','queued',0,0,?,?,NULL,NULL,0,?,?,NULL,?,NULL,NULL,NULL,NULL)""",
                        (
                            child_id, job_type, _json(followup.get("payload") or {}), key,
                            int(followup.get("priority") or 0),
                            max(1, min(20, int(followup.get("max_attempts") or 5))),
                            str(followup.get("next_attempt_at") or now),
                            parent_id, now, now,
                        ),
                    )
            completed = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_worker_job(completed)

    def fail_worker_job(
        self,
        job_id: str,
        *,
        error_class: str,
        error_message: str,
        retryable: bool,
        next_attempt_at: str | None,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise JobhuntError("Worker job not found", status=404, code="worker_job_not_found")
            cancelled = bool(row["cancellation_requested"])
            retry = bool(retryable and not cancelled and int(row["attempt_count"]) < int(row["max_attempts"]))
            state = "cancelled" if cancelled else "retry_wait" if retry else "failed"
            completed_at = None if retry else now
            connection.execute(
                """UPDATE worker_jobs SET state=?,stage=?,progress=NULL,next_attempt_at=?,
                          lease_owner=NULL,lease_expires_at=NULL,completed_at=?,error_class=?,
                          error_message=?,updated_at=? WHERE id=?""",
                (
                    state, state, next_attempt_at or row["next_attempt_at"], completed_at,
                    "cancelled" if cancelled else error_class[:100],
                    ("Cancellation requested" if cancelled else error_message)[:1000],
                    now, job_id,
                ),
            )
            failed = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_worker_job(failed)

    def get_worker_job(self, job_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_worker_job(row) if row else None

    def get_worker_job_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT * FROM worker_jobs WHERE idempotency_key=?
                   ORDER BY rowid DESC LIMIT 1""",
                (idempotency_key,),
            ).fetchone()
        return self._decode_worker_job(row) if row else None

    def list_worker_jobs(
        self, *, states: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        where = ""
        parameters: list[Any] = []
        if states:
            placeholders = ",".join("?" for _ in states)
            where = f"WHERE state IN ({placeholders})"
            parameters.extend(states)
        parameters.append(max(1, min(500, limit)))
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT * FROM worker_jobs {where}
                    ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'queued' THEN 1
                         WHEN 'retry_wait' THEN 2 WHEN 'failed' THEN 3 ELSE 4 END,
                         updated_at DESC,id DESC LIMIT ?""",
                parameters,
            ).fetchall()
        return [self._decode_worker_job(row) for row in rows]

    def worker_job_counts(self) -> dict[str, int]:
        result = {state: 0 for state in ("queued", "running", "retry_wait", "completed", "failed", "cancelled")}
        with self.read_connection() as connection:
            for row in connection.execute("SELECT state,COUNT(*) AS total FROM worker_jobs GROUP BY state"):
                result[str(row["state"])] = int(row["total"])
        return result

    def cancel_worker_job(self, job_id: str, *, now: str) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise JobhuntError("Worker job not found", status=404, code="worker_job_not_found")
            if row["state"] in {"queued", "retry_wait"}:
                connection.execute(
                    """UPDATE worker_jobs SET state='cancelled',stage='cancelled',
                              cancellation_requested=1,completed_at=?,updated_at=?,
                              error_class='cancelled',error_message='Cancellation requested'
                       WHERE id=?""",
                    (now, now, job_id),
                )
            elif row["state"] == "running":
                connection.execute(
                    "UPDATE worker_jobs SET cancellation_requested=1,updated_at=? WHERE id=?",
                    (now, job_id),
                )
            updated = connection.execute("SELECT * FROM worker_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_worker_job(updated)

    def cancel_source_jobs(self, source_key: str, *, now: str) -> int:
        with self.transaction() as connection:
            queued = connection.execute(
                """UPDATE worker_jobs SET state='cancelled',stage='cancelled',
                          cancellation_requested=1,completed_at=?,updated_at=?,
                          error_class='cancelled',error_message='Source paused'
                   WHERE state IN ('queued','retry_wait')
                     AND json_extract(payload_json,'$.source')=?""",
                (now, now, source_key),
            ).rowcount
            running = connection.execute(
                """UPDATE worker_jobs SET cancellation_requested=1,updated_at=?
                   WHERE state='running' AND json_extract(payload_json,'$.source')=?""",
                (now, source_key),
            ).rowcount
        return int(queued) + int(running)

    def save_manual_capture(
        self, *, listing: dict[str, Any], blob: dict[str, Any], capture: dict[str, Any],
        track_id: str | None, search_profile_id: str | None, observed_at: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            source = connection.execute(
                "SELECT id FROM source_definitions WHERE id=?", (listing["source_id"],)
            ).fetchone()
            if not source:
                raise JobhuntError("Source not found", status=404, code="source_not_found")
            derived_track_id = None
            if search_profile_id:
                profile = connection.execute(
                    "SELECT track_id FROM track_search_profiles WHERE id=?", (search_profile_id,)
                ).fetchone()
                if not profile:
                    raise JobhuntError("Search Profile not found", status=404, code="search_profile_not_found")
                derived_track_id = profile["track_id"]
                if track_id and track_id != derived_track_id:
                    raise JobhuntError(
                        "Search Profile belongs to another Track", status=409,
                        code="search_profile_track_mismatch",
                    )
            track_id = track_id or derived_track_id
            if track_id and not connection.execute(
                "SELECT 1 FROM career_tracks WHERE id=?", (track_id,)
            ).fetchone():
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            canonical_job_id = listing.get("canonical_job_id")
            if canonical_job_id and not connection.execute(
                "SELECT 1 FROM canonical_jobs WHERE id=?", (canonical_job_id,)
            ).fetchone():
                raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")

            existing = connection.execute(
                "SELECT id FROM source_listings WHERE source_id=? AND identity_key=?",
                (listing["source_id"], listing["identity_key"]),
            ).fetchone()
            listing_created = existing is None
            listing_id = existing["id"] if existing else _id("listing")
            if existing:
                connection.execute(
                    """UPDATE source_listings SET external_id=COALESCE(?,external_id),
                           canonical_url=COALESCE(?,canonical_url),observed_url=COALESCE(?,observed_url),
                           title_hint=COALESCE(?,title_hint),company_hint=COALESCE(?,company_hint),
                           location_hint=COALESCE(?,location_hint),lifecycle_state=?,last_seen_at=?,
                           source_ended_at=COALESCE(?,source_ended_at),
                           canonical_job_id=COALESCE(?,canonical_job_id),notes=COALESCE(?,notes),updated_at=?
                       WHERE id=?""",
                    (
                        listing.get("external_id"), listing.get("canonical_url"), listing.get("observed_url"),
                        listing.get("title_hint"), listing.get("company_hint"), listing.get("location_hint"),
                        listing["lifecycle_state"], observed_at, listing.get("source_ended_at"),
                        canonical_job_id, listing.get("notes"), observed_at, listing_id,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO source_listings(
                           id,source_id,identity_key,external_id,canonical_url,observed_url,
                           title_hint,company_hint,location_hint,lifecycle_state,first_seen_at,last_seen_at,
                           source_ended_at,canonical_job_id,notes,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        listing_id, listing["source_id"], listing["identity_key"], listing.get("external_id"),
                        listing.get("canonical_url"), listing.get("observed_url"), listing.get("title_hint"),
                        listing.get("company_hint"), listing.get("location_hint"), listing["lifecycle_state"],
                        observed_at, observed_at, listing.get("source_ended_at"), canonical_job_id,
                        listing.get("notes"), observed_at, observed_at,
                    ),
                )

            existing_blob = connection.execute(
                "SELECT * FROM raw_blobs WHERE sha256=?", (blob["sha256"],)
            ).fetchone()
            if existing_blob:
                if (int(existing_blob["byte_size"]) != int(blob["byte_size"])
                        or existing_blob["relative_path"] != blob["relative_path"]):
                    raise JobhuntError("Raw blob metadata conflict", status=500, code="raw_blob_metadata_conflict")
            else:
                connection.execute(
                    """INSERT INTO raw_blobs(
                           sha256,byte_size,mime_type,file_extension,relative_path,created_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (blob["sha256"], blob["byte_size"], blob["mime_type"], blob["file_extension"],
                     blob["relative_path"], observed_at),
                )

            source_url = capture.get("source_url")
            existing_capture = connection.execute(
                """SELECT id FROM raw_captures WHERE listing_id=? AND blob_sha256=?
                   AND mime_type=? AND input_method=? AND COALESCE(source_url,'')=COALESCE(?,'')
                   ORDER BY captured_at DESC,rowid DESC LIMIT 1""",
                (listing_id, blob["sha256"], capture["mime_type"], capture["input_method"], source_url),
            ).fetchone()
            capture_reused = existing_capture is not None
            if existing_capture:
                capture_id = existing_capture["id"]
            else:
                capture_id = _id("capture")
                connection.execute(
                    """INSERT INTO raw_captures(
                           id,listing_id,blob_sha256,mime_type,file_extension,captured_at,input_method,
                           source_url,http_status,safe_metadata_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,NULL,?,?)""",
                    (capture_id, listing_id, blob["sha256"], capture["mime_type"],
                     capture["file_extension"], observed_at, capture["input_method"], source_url,
                     _json(capture.get("safe_metadata") or {}), observed_at),
                )
            if track_id:
                connection.execute(
                    """INSERT OR IGNORE INTO source_listing_tracks(
                           listing_id,track_id,discovered_at,notes
                       ) VALUES(?,?,?,?)""",
                    (listing_id, track_id, observed_at, listing.get("notes")),
                )
            if search_profile_id:
                connection.execute(
                    """INSERT OR IGNORE INTO source_listing_search_profiles(
                           listing_id,search_profile_id,discovered_at,notes
                       ) VALUES(?,?,?,?)""",
                    (listing_id, search_profile_id, observed_at, listing.get("notes")),
                )
        captures = self.list_captures(listing_id)
        capture_row = next(item for item in captures if item["id"] == capture_id)
        return {
            "listing_id": listing_id, "capture_id": capture_id,
            "listing_created": listing_created, "capture_reused": capture_reused,
            "capture": capture_row,
        }

    # Pack E: immutable extraction, facts, normalization, projection, and review.

    @staticmethod
    def _decode_extraction_run(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["warnings"] = _loads(result.pop("warnings_json", "[]"), [])
        result["ai_validation_result"] = _loads(
            result.pop("ai_validation_result_json", None), None
        )
        if result.get("ai_input_truncated") is not None:
            result["ai_input_truncated"] = bool(result["ai_input_truncated"])
        return result

    @staticmethod
    def _decode_fact(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["value_boolean"] = (
            None if result.get("value_boolean") is None else bool(result["value_boolean"])
        )
        result["value_json"] = _loads(result.get("value_json"), None)
        result["evidence_locator"] = _loads(result.pop("evidence_locator_json", "{}"), {})
        if result.get("concept_id"):
            result["normalization"] = {
                "concept_id": result.get("concept_id"),
                "concept_type": result.get("concept_type"),
                "concept_key": result.get("concept_key"),
                "display_label": result.get("display_label"),
                "rule_version": result.get("mapping_rule_version"),
                "confidence": result.get("mapping_confidence"),
                "origin": result.get("mapping_origin"),
                "is_manual": bool(result.get("mapping_is_manual")),
                "state": result.get("mapping_state"),
            }
        else:
            result["normalization"] = None
        for key in (
            "concept_id", "concept_type", "concept_key", "display_label",
            "mapping_rule_version", "mapping_confidence", "mapping_origin",
            "mapping_is_manual", "mapping_state",
        ):
            result.pop(key, None)
        return result

    def save_extraction_batch(
        self,
        *,
        capture_id: str,
        extractor_kind: str,
        extractor_version: str,
        input_hash: str,
        output_schema_version: str,
        facts: list[dict[str, Any]],
        warnings: list[str],
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT * FROM extraction_runs WHERE capture_id=? AND extractor_kind=?
                   AND extractor_version=? AND input_hash=?""",
                (capture_id, extractor_kind, extractor_version, input_hash),
            ).fetchone()
            if existing:
                return self._decode_extraction_run(existing), True
            if not connection.execute(
                "SELECT 1 FROM raw_captures WHERE id=?", (capture_id,)
            ).fetchone():
                raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
            run_id = _id("extract")
            connection.execute(
                """INSERT INTO extraction_runs(
                       id,capture_id,extractor_kind,extractor_version,input_hash,
                       output_schema_version,started_at,status,validation_status,created_at
                   ) VALUES(?,?,?,?,?,?,?,'running','pending',?)""",
                (run_id, capture_id, extractor_kind, extractor_version, input_hash,
                 output_schema_version, now, now),
            )
            invalid = 0
            warning_count = len(warnings)
            for item in facts:
                fact_id = _id("fact")
                validation_state = item.get("validation_state", "valid")
                invalid += int(validation_state == "invalid")
                warning_count += int(validation_state == "warning")
                concept = item.get("normalization")
                normalization_state = "mapped" if concept else item.get(
                    "normalization_state", "not_applicable"
                )
                connection.execute(
                    """INSERT INTO extracted_facts(
                           id,extraction_run_id,capture_id,namespace,fact_type,source_field,label,
                           source_wording,value_type,value_text,value_number,value_boolean,value_json,
                           unit,currency,period,requirement_preference,state,confidence,
                           evidence_locator_json,validation_state,validation_message,
                           normalization_state,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fact_id, run_id, capture_id, item["namespace"], item["fact_type"],
                        item["source_field"], item.get("label"), item["source_wording"],
                        item["value_type"], item.get("value_text"), item.get("value_number"),
                        None if item.get("value_boolean") is None else int(item["value_boolean"]),
                        _json(item["value_json"]) if item.get("value_json") is not None else None,
                        item.get("unit"), item.get("currency"), item.get("period"),
                        item.get("requirement_preference", "unknown"), item["state"],
                        item["confidence"], _json(item["evidence_locator"]), validation_state,
                        item.get("validation_message"), normalization_state, now,
                    ),
                )
                if concept:
                    connection.execute(
                        """INSERT INTO fact_normalizations(
                               id,fact_id,concept_id,rule_version,confidence,mapping_origin,
                               is_manual,state,created_at
                           ) VALUES(?,?,?,?,?,'deterministic_rule',0,'active',?)""",
                        (_id("mapping"), fact_id, concept["concept_id"], concept["rule_version"],
                         concept["confidence"], now),
                    )
            status = "completed_with_warnings" if warning_count or invalid else "completed"
            validation_status = "invalid" if invalid and invalid == len(facts) and facts else (
                "valid_with_warnings" if warning_count or invalid else "valid"
            )
            connection.execute(
                """UPDATE extraction_runs SET completed_at=?,status=?,validation_status=?,
                       fact_count=?,warning_count=?,warnings_json=? WHERE id=?""",
                (now, status, validation_status, len(facts), warning_count, _json(warnings), run_id),
            )
            row = connection.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode_extraction_run(row), False

    def find_ai_extraction_run(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT * FROM extraction_runs
                   WHERE extractor_kind='ai' AND ai_idempotency_key=?
                   ORDER BY CASE status WHEN 'completed' THEN 0 WHEN 'completed_with_warnings' THEN 0
                                        WHEN 'running' THEN 1 ELSE 2 END,
                            created_at DESC,id DESC LIMIT 1""",
                (idempotency_key,),
            ).fetchone()
        return self._decode_extraction_run(row) if row else None

    def create_ai_extraction_run(
        self,
        *,
        capture_id: str,
        input_hash: str,
        extractor_version: str,
        output_schema_version: str,
        provider: str,
        provider_adapter_version: str,
        model: str,
        prompt_id: str,
        prompt_version: str,
        prompt_fingerprint: str,
        response_schema_version: str,
        idempotency_key: str,
        run_variant: str,
        input_char_count: int,
        sent_char_count: int,
        input_truncated: bool,
        source_preparation: str,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM raw_captures WHERE id=?", (capture_id,)
            ).fetchone():
                raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
            run_id = _id("extract")
            connection.execute(
                """INSERT INTO extraction_runs(
                       id,capture_id,extractor_kind,extractor_version,input_hash,
                       output_schema_version,started_at,status,validation_status,created_at,
                       ai_provider,ai_provider_adapter_version,ai_model,ai_prompt_id,
                       ai_prompt_version,ai_prompt_fingerprint,ai_response_schema_version,
                       ai_requested_at,ai_attempt_count,ai_idempotency_key,ai_run_variant,
                       ai_input_char_count,ai_sent_char_count,ai_input_truncated,ai_source_preparation
                   ) VALUES(?,?,'ai',?,?,?,?,'running','pending',?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)""",
                (
                    run_id, capture_id, extractor_version, input_hash, output_schema_version,
                    now, now, provider, provider_adapter_version, model, prompt_id,
                    prompt_version, prompt_fingerprint, response_schema_version, now,
                    idempotency_key, run_variant, input_char_count, sent_char_count,
                    int(input_truncated), source_preparation,
                ),
            )
            row = connection.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode_extraction_run(row)

    def record_ai_attempt(
        self,
        *,
        run_id: str,
        attempt_number: int,
        started_at: str,
        completed_at: str,
        provider_status: str,
        error_class: str | None,
        error_message: str | None,
        provider_request_id: str | None,
        finish_reason: str | None,
        usage: dict[str, int] | None,
        latency_ms: float | None,
        retryable: bool,
    ) -> None:
        usage = usage or {}
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO ai_extraction_attempts(
                       id,extraction_run_id,attempt_number,started_at,completed_at,provider_status,
                       error_class,error_message,provider_request_id,finish_reason,input_tokens,
                       output_tokens,total_tokens,cached_tokens,latency_ms,retryable
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _id("aiattempt"), run_id, attempt_number, started_at, completed_at,
                    provider_status[:100], error_class, (error_message or "")[:2000] or None,
                    provider_request_id, finish_reason, usage.get("input_tokens"),
                    usage.get("output_tokens"), usage.get("total_tokens"),
                    usage.get("cached_tokens"), latency_ms, int(retryable),
                ),
            )

    def complete_ai_extraction(
        self,
        *,
        run_id: str,
        facts: list[dict[str, Any]],
        warnings: list[str],
        validation_result: dict[str, Any],
        raw_response: str,
        model_version: str | None,
        provider_request_id: str | None,
        finish_reason: str | None,
        usage: dict[str, int],
        latency_ms: float,
        attempt_count: int,
        estimated_cost: float | None,
        cost_currency: str | None,
        price_version: str | None,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            current = connection.execute(
                "SELECT status,capture_id FROM extraction_runs WHERE id=? AND extractor_kind='ai'",
                (run_id,),
            ).fetchone()
            if not current:
                raise JobhuntError("Extraction Run not found", status=404, code="extraction_run_not_found")
            if current["status"] != "running":
                raise JobhuntError("AI Extraction Run is already complete", status=409, code="extraction_run_complete")
            capture_id = str(current["capture_id"])
            for item in facts:
                fact_id = _id("fact")
                concept = item.get("normalization")
                normalization_state = "mapped" if concept else item.get("normalization_state", "not_applicable")
                connection.execute(
                    """INSERT INTO extracted_facts(
                           id,extraction_run_id,capture_id,namespace,fact_type,source_field,label,
                           source_wording,value_type,value_text,value_number,value_boolean,value_json,
                           unit,currency,period,requirement_preference,state,confidence,
                           evidence_locator_json,validation_state,validation_message,
                           normalization_state,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fact_id, run_id, capture_id, item["namespace"], item["fact_type"],
                        item["source_field"], item.get("label"), item["source_wording"],
                        item["value_type"], item.get("value_text"), item.get("value_number"),
                        None if item.get("value_boolean") is None else int(item["value_boolean"]),
                        _json(item["value_json"]) if item.get("value_json") is not None else None,
                        item.get("unit"), item.get("currency"), item.get("period"),
                        item.get("requirement_preference", "unknown"), item["state"],
                        item["confidence"], _json(item["evidence_locator"]),
                        item.get("validation_state", "valid"), item.get("validation_message"),
                        normalization_state, now,
                    ),
                )
                if concept:
                    connection.execute(
                        """INSERT INTO fact_normalizations(
                               id,fact_id,concept_id,rule_version,confidence,mapping_origin,
                               is_manual,state,created_at
                           ) VALUES(?,?,?,?,?,'deterministic_rule',0,'active',?)""",
                        (_id("mapping"), fact_id, concept["concept_id"], concept["rule_version"],
                         concept["confidence"], now),
                    )
            warning_count = len(warnings)
            status = "completed_with_warnings" if warning_count else "completed"
            validation_status = "valid_with_warnings" if warning_count else "valid"
            connection.execute(
                """UPDATE extraction_runs SET completed_at=?,status=?,validation_status=?,
                       fact_count=?,warning_count=?,warnings_json=?,ai_model_version=?,
                       ai_responded_at=?,ai_latency_ms=?,ai_attempt_count=?,ai_finish_reason=?,
                       ai_provider_request_id=?,ai_input_tokens=?,ai_output_tokens=?,ai_total_tokens=?,
                       ai_cached_tokens=?,ai_estimated_cost=?,ai_cost_currency=?,ai_price_version=?,
                       ai_raw_response_json=?,ai_validation_result_json=? WHERE id=?""",
                (
                    now, status, validation_status, len(facts), warning_count, _json(warnings),
                    model_version, now, latency_ms, attempt_count, finish_reason,
                    provider_request_id, usage.get("input_tokens"), usage.get("output_tokens"),
                    usage.get("total_tokens"), usage.get("cached_tokens"), estimated_cost,
                    cost_currency, price_version, raw_response, _json(validation_result), run_id,
                ),
            )
            row = connection.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode_extraction_run(row)

    def fail_ai_extraction(
        self,
        *,
        run_id: str,
        error_class: str,
        error_message: str,
        validation_result: dict[str, Any],
        raw_response: str | None,
        attempt_count: int,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE extraction_runs SET completed_at=?,status='failed',validation_status='invalid',
                       error_class=?,error_message=?,ai_responded_at=?,ai_attempt_count=?,
                       ai_raw_response_json=?,ai_validation_result_json=?
                   WHERE id=? AND status='running'""",
                (
                    now, error_class[:200], error_message[:2000], now, attempt_count,
                    raw_response, _json(validation_result), run_id,
                ),
            )
            row = connection.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise JobhuntError("Extraction Run not found", status=404, code="extraction_run_not_found")
        return self._decode_extraction_run(row)

    def list_ai_attempts(self, run_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT * FROM ai_extraction_attempts WHERE extraction_run_id=?
                   ORDER BY attempt_number""",
                (run_id,),
            ).fetchall()
        return [{**dict(row), "retryable": bool(row["retryable"])} for row in rows]

    def ai_usage_since(self, started_at: str) -> dict[str, int]:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS request_count,COALESCE(SUM(total_tokens),0) AS total_tokens
                   FROM ai_extraction_attempts WHERE started_at>=?""",
                (started_at,),
            ).fetchone()
        return {"request_count": int(row["request_count"]), "total_tokens": int(row["total_tokens"])}

    def record_failed_extraction(
        self, *, capture_id: str, extractor_kind: str, extractor_version: str,
        input_hash: str, output_schema_version: str, error_class: str,
        error_message: str, now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT * FROM extraction_runs WHERE capture_id=? AND extractor_kind=?
                   AND extractor_version=? AND input_hash=?""",
                (capture_id, extractor_kind, extractor_version, input_hash),
            ).fetchone()
            if existing:
                return self._decode_extraction_run(existing)
            run_id = _id("extract")
            connection.execute(
                """INSERT INTO extraction_runs(
                       id,capture_id,extractor_kind,extractor_version,input_hash,output_schema_version,
                       started_at,completed_at,status,validation_status,fact_count,warning_count,
                       warnings_json,error_class,error_message,created_at
                   ) VALUES(?,?,?,?,?,?,?,?, 'failed','invalid',0,0,'[]',?,?,?)""",
                (run_id, capture_id, extractor_kind, extractor_version, input_hash,
                 output_schema_version, now, now, error_class[:200], error_message[:2000], now),
            )
            row = connection.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode_extraction_run(row)

    def list_extraction_runs(self, capture_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT * FROM extraction_runs WHERE capture_id=?
                   ORDER BY created_at DESC,id DESC LIMIT 100""", (capture_id,)
            ).fetchall()
        return [self._decode_extraction_run(row) for row in rows]

    def get_extraction_run(self, run_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
        return self._decode_extraction_run(row) if row else None

    @staticmethod
    def _fact_query(where: str) -> str:
        return f"""SELECT f.*,r.extractor_kind,r.extractor_version,
                          r.ai_provider,r.ai_provider_adapter_version,r.ai_model,
                          r.ai_prompt_version,r.ai_prompt_fingerprint,r.ai_response_schema_version,
                          n.concept_id,c.concept_type,c.concept_key,c.display_label,
                          n.rule_version AS mapping_rule_version,n.confidence AS mapping_confidence,
                          n.mapping_origin,n.is_manual AS mapping_is_manual,n.state AS mapping_state
                   FROM extracted_facts f
                   JOIN extraction_runs r ON r.id=f.extraction_run_id
                   LEFT JOIN fact_normalizations n ON n.fact_id=f.id AND n.state='active'
                   LEFT JOIN normalization_concepts c ON c.id=n.concept_id
                   WHERE {where} ORDER BY f.created_at,f.id LIMIT 2000"""

    def facts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(self._fact_query("f.extraction_run_id=?"), (run_id,)).fetchall()
        return [self._decode_fact(row) for row in rows]

    def facts_for_capture(self, capture_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(self._fact_query("f.capture_id=?"), (capture_id,)).fetchall()
        return [self._decode_fact(row) for row in rows]

    def facts_for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                self._fact_query(
                    "f.capture_id IN (SELECT rc.id FROM raw_captures rc "
                    "JOIN source_listings sl ON sl.id=rc.listing_id WHERE sl.canonical_job_id=?)"
                ), (job_id,),
            ).fetchall()
        return [self._decode_fact(row) for row in rows]

    @staticmethod
    def _fact_value(fact: dict[str, Any]) -> Any:
        return {
            "text": fact.get("value_text"),
            "number": fact.get("value_number"),
            "boolean": fact.get("value_boolean"),
            "json": fact.get("value_json"),
        }.get(fact.get("value_type"))

    def _create_review(
        self, connection: sqlite3.Connection, *, reason: str, severity: str,
        entity_type: str, entity_id: str, related_fact_ids: list[str],
        evidence_summary: str, candidates: list[Any], dedupe_key: str, now: str,
    ) -> str:
        review_id = _id("review")
        connection.execute(
            """INSERT OR IGNORE INTO review_items(
                   id,reason,severity,entity_type,entity_id,related_fact_ids_json,
                   evidence_summary,candidate_resolutions_json,state,dedupe_key,created_at
               ) VALUES(?,?,?,?,?,?,?,?,'open',?,?)""",
            (review_id, reason, severity, entity_type, entity_id, _json(related_fact_ids[:100]),
             evidence_summary[:4000], _json(candidates[:50]), dedupe_key, now),
        )
        row = connection.execute("SELECT id FROM review_items WHERE dedupe_key=?", (dedupe_key,)).fetchone()
        return str(row[0])

    def create_review(
        self, *, reason: str, severity: str, entity_type: str, entity_id: str,
        related_fact_ids: list[str], evidence_summary: str, candidates: list[Any],
        dedupe_key: str, now: str,
    ) -> str:
        with self.transaction() as connection:
            return self._create_review(
                connection, reason=reason, severity=severity, entity_type=entity_type,
                entity_id=entity_id, related_fact_ids=related_fact_ids,
                evidence_summary=evidence_summary, candidates=candidates,
                dedupe_key=dedupe_key, now=now,
            )

    def _projection_facts(self, connection: sqlite3.Connection, listing_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """SELECT f.*,r.extractor_kind,r.extractor_version,r.completed_at,
                      c.captured_at,c.rowid AS capture_sequence
               FROM extracted_facts f
               JOIN extraction_runs r ON r.id=f.extraction_run_id
               JOIN raw_captures c ON c.id=f.capture_id
               WHERE c.listing_id IN (
                   SELECT related.id FROM source_listings related
                   WHERE related.canonical_job_id=(
                       SELECT target.canonical_job_id FROM source_listings target WHERE target.id=?
                   )
                   UNION SELECT ?
               ) AND r.status IN ('completed','completed_with_warnings')
                 AND f.validation_state='valid'
               ORDER BY c.captured_at DESC,c.rowid DESC,
                 CASE r.extractor_kind WHEN 'manual_hints' THEN 0 WHEN 'json_structured' THEN 0
                      WHEN 'json_ld_jobposting' THEN 0 WHEN 'ai' THEN 1 ELSE 2 END,
                 f.confidence DESC,
                 r.completed_at DESC,f.id""",
            (listing_id, listing_id),
        ).fetchall()
        return [self._decode_fact(row) for row in rows]

    def project_listing(self, listing_id: str, *, capture_id: str, now: str) -> dict[str, Any]:
        field_types = {
            "title": "title", "company": "company", "city": "location_city",
            "country": "location_country", "location_text": "location_text",
            "work_model": "work_model", "contract_type": "contract_type",
            "salary_min": "salary_min", "salary_max": "salary_max",
            "salary_exact": "salary_exact", "salary_currency": "salary_currency",
            "salary_period": "salary_period", "salary_tax_type": "salary_tax_type",
            "valid_through": "valid_through",
        }
        with self.transaction() as connection:
            listing_row = connection.execute(
                """SELECT l.*,d.display_name AS source_name FROM source_listings l
                   JOIN source_definitions d ON d.id=l.source_id WHERE l.id=?""",
                (listing_id,),
            ).fetchone()
            if not listing_row:
                raise JobhuntError("Source Listing not found", status=404, code="source_listing_not_found")
            listing = dict(listing_row)
            capture_row = connection.execute(
                "SELECT captured_at FROM raw_captures WHERE id=? AND listing_id=?",
                (capture_id, listing_id),
            ).fetchone()
            if not capture_row:
                raise JobhuntError("Raw Capture not found", status=404, code="raw_capture_not_found")
            captured_at = str(capture_row["captured_at"])
            facts = self._projection_facts(connection, listing_id)
            projection_rule_version = "projection@2-ai-precedence" if any(
                fact.get("extractor_kind") == "ai" for fact in facts
            ) else "projection@1"
            chosen: dict[str, dict[str, Any]] = {}
            selected_ids: list[str] = []
            for fact in facts:
                target = field_types.get(fact["fact_type"])
                if target and target not in chosen and fact["state"] != "explicit_negative":
                    chosen[target] = fact
                    selected_ids.append(fact["id"])
            if "salary_exact" in chosen:
                chosen.setdefault("salary_min", chosen["salary_exact"])
                chosen.setdefault("salary_max", chosen["salary_exact"])
            job_id = listing.get("canonical_job_id")
            if not job_id and "title" not in chosen:
                dedupe = "insufficient:" + hashlib.sha256(f"{listing_id}:{capture_id}".encode()).hexdigest()
                review_id = self._create_review(
                    connection, reason="insufficient_identity", severity="warning",
                    entity_type="capture", entity_id=capture_id, related_fact_ids=selected_ids,
                    evidence_summary="No supported title fact was available; no Canonical Job was created.",
                    candidates=[], dedupe_key=dedupe, now=now,
                )
                return {"job_id": None, "projection_id": None, "created": False,
                        "selected_fact_ids": selected_ids, "review_ids": [review_id],
                        "outcome": "review_required"}

            if not job_id:
                job_id = _id("job")
                application_id = _id("app")
                title = str(self._fact_value(chosen["title"]))
                company = str(self._fact_value(chosen["company"])) if "company" in chosen else "unknown"
                fingerprint = "pack-e:" + hashlib.sha256(listing_id.encode("utf-8")).hexdigest()
                connection.execute(
                    """INSERT INTO canonical_jobs(
                           id,legacy_id,legacy_fingerprint,company,role_title,seniority,
                           location_city,location_country,work_mode,hybrid_details,
                           contract_type,contract_details,salary_min,salary_max,
                           salary_currency,salary_period,salary_tax_type,salary_is_known,
                           source_name,source_url,source_captured_at,expires_at,original_text,
                           requirements_json,legacy_payload_json,created_at,updated_at
                       ) VALUES(?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?)""",
                    (
                        job_id, fingerprint, company, title, "unknown",
                        "unknown", "unknown", "unknown", "unknown", "unknown", "unknown",
                        None, None, "unknown", "unknown", "unknown", 0,
                        listing["source_name"], listing.get("observed_url"), captured_at, None, "",
                        "{}", _json({"origin": "pack_e_projection", "listingId": listing_id}), now, now,
                    ),
                )
                connection.execute(
                    """INSERT INTO applications(
                           id,job_id,current_status,source_expired,priority,next_action,notes,created_at,updated_at
                       ) VALUES(?,?,'to_review',0,'unknown','analyze','',?,?)""",
                    (application_id, job_id, now, now),
                )
                self._append_event(connection, application_id, {
                    "type": "extraction_projection_created", "timestamp": now,
                    "origin": "system", "payload": {"listingId": listing_id, "captureId": capture_id},
                })
                connection.execute(
                    "UPDATE source_listings SET canonical_job_id=?,updated_at=? WHERE id=?",
                    (job_id, now, listing_id),
                )
                created = True
            else:
                created = False

            overrides = [dict(row) for row in connection.execute(
                "SELECT * FROM human_overrides WHERE job_id=? AND state='active' ORDER BY created_at,id",
                (job_id,),
            )]
            values = {field: self._fact_value(fact) for field, fact in chosen.items()}
            applied_override_ids: list[str] = []
            for override in overrides:
                values[override["field_name"]] = _loads(override["replacement_value_json"], None)
                applied_override_ids.append(override["id"])

            all_requirement_facts = [fact for fact in facts if fact["fact_type"] in {
                "skill", "tool", "language", "education", "experience", "certification",
                "driving_licence", "requirement_other",
            }]
            requirement_capture_id = next(
                (fact["capture_id"] for fact in all_requirement_facts), None
            )
            requirement_facts = [
                fact for fact in all_requirement_facts
                if fact["capture_id"] == requirement_capture_id
            ]
            requirements = {"mustHave": [], "niceToHave": [], "tools": []}
            for fact in requirement_facts:
                if fact["state"] == "explicit_negative":
                    continue
                value = self._fact_value(fact)
                if value in (None, ""):
                    continue
                if fact["id"] not in selected_ids:
                    selected_ids.append(fact["id"])
                if fact["fact_type"] == "tool":
                    requirements["tools"].append(str(value))
                elif fact["requirement_preference"] in {"preferred", "optional"}:
                    requirements["niceToHave"].append(str(value))
                else:
                    requirements["mustHave"].append(str(value))
            requirements = {key: list(dict.fromkeys(items))[:100] for key, items in requirements.items()}

            assignments = ["updated_at=?", "source_name=?", "source_url=?", "source_captured_at=?"]
            parameters: list[Any] = [now, listing["source_name"], listing.get("observed_url"), captured_at]
            columns = {
                "title": "role_title", "company": "company", "location_city": "location_city",
                "location_country": "location_country", "work_model": "work_mode",
                "contract_type": "contract_type", "salary_min": "salary_min",
                "salary_max": "salary_max", "salary_currency": "salary_currency",
                "salary_period": "salary_period", "salary_tax_type": "salary_tax_type",
                "valid_through": "expires_at",
            }
            for field, column in columns.items():
                if field in values and values[field] is not None:
                    assignments.append(f"{column}=?")
                    parameters.append(values[field])
            if any(key in values for key in ("salary_min", "salary_max")):
                assignments.append("salary_is_known=1")
            if requirement_facts:
                assignments.append("requirements_json=?")
                parameters.append(_json(requirements))
            parameters.append(job_id)
            connection.execute(f"UPDATE canonical_jobs SET {','.join(assignments)} WHERE id=?", parameters)

            snapshot = {key: values[key] for key in sorted(values) if values[key] is not None}
            if requirement_facts:
                snapshot["requirements"] = requirements
            fingerprint = hashlib.sha256(_json({
                "ruleVersion": projection_rule_version,
                "snapshot": snapshot,
                "selectedFactIds": selected_ids,
                "appliedOverrideIds": applied_override_ids,
            }).encode("utf-8")).hexdigest()
            existing_projection = connection.execute(
                "SELECT id,projection_version FROM canonical_job_projections WHERE job_id=? AND snapshot_fingerprint=?",
                (job_id, fingerprint),
            ).fetchone()
            if existing_projection:
                projection_id = existing_projection["id"]
                projection_version = int(existing_projection["projection_version"])
            else:
                projection_version = int(connection.execute(
                    "SELECT COALESCE(MAX(projection_version),0)+1 FROM canonical_job_projections WHERE job_id=?",
                    (job_id,),
                ).fetchone()[0])
                projection_id = _id("projection")
                connection.execute(
                    """INSERT INTO canonical_job_projections(
                           id,job_id,capture_id,projection_version,rule_version,selected_fact_ids_json,
                           applied_override_ids_json,snapshot_json,snapshot_fingerprint,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (projection_id, job_id, capture_id, projection_version, projection_rule_version, _json(selected_ids),
                     _json(applied_override_ids), _json(snapshot), fingerprint, now),
                )

            review_ids: list[str] = []
            conflict_groups = {
                "conflicting_salary": ("salary_min", "salary_max", "salary_exact", "salary_currency", "salary_period"),
                "conflicting_location": ("city", "country", "location_text", "work_model"),
                "conflicting_company_title": ("company", "title"),
            }
            for reason, types in conflict_groups.items():
                related = [fact for fact in facts if fact["fact_type"] in types]
                values_by_type: dict[str, set[str]] = {}
                for fact in related:
                    values_by_type.setdefault(fact["fact_type"], set()).add(
                        _json(self._fact_value(fact))
                    )
                conflicting_types = {
                    fact_type: values for fact_type, values in values_by_type.items()
                    if len(values) > 1
                }
                if conflicting_types:
                    distinct = {value for values in conflicting_types.values() for value in values}
                    conflicting = [
                        fact for fact in related if fact["fact_type"] in conflicting_types
                    ]
                    digest = hashlib.sha256((job_id + reason + "|".join(sorted(distinct))).encode()).hexdigest()
                    review_ids.append(self._create_review(
                        connection, reason=reason, severity="warning", entity_type="job",
                        entity_id=job_id, related_fact_ids=[fact["id"] for fact in conflicting],
                        evidence_summary=f"Conflicting supported {reason.removeprefix('conflicting_').replace('_', ' ')} facts remain preserved.",
                        candidates=[self._fact_value(fact) for fact in conflicting[:20]],
                        dedupe_key=f"conflict:{digest}", now=now,
                    ))
            open_facts = [fact for fact in facts if fact["fact_type"] == "other" and fact["capture_id"] == capture_id]
            if open_facts:
                digest = hashlib.sha256((capture_id + "|".join(sorted(fact["id"] for fact in open_facts))).encode()).hexdigest()
                review_ids.append(self._create_review(
                    connection, reason="unsupported_unexpected_fact", severity="info",
                    entity_type="capture", entity_id=capture_id,
                    related_fact_ids=[fact["id"] for fact in open_facts],
                    evidence_summary="Source observations were retained as open facts and are not projected automatically.",
                    candidates=[{"label": fact.get("label"), "value": self._fact_value(fact)} for fact in open_facts[:20]],
                    dedupe_key=f"open:{digest}", now=now,
                ))
            low_confidence = [fact for fact in facts if fact["capture_id"] == capture_id and float(fact["confidence"]) < 0.8]
            if low_confidence:
                digest = hashlib.sha256((capture_id + "|".join(sorted(fact["id"] for fact in low_confidence))).encode()).hexdigest()
                review_ids.append(self._create_review(
                    connection, reason="low_confidence", severity="warning", entity_type="capture",
                    entity_id=capture_id, related_fact_ids=[fact["id"] for fact in low_confidence],
                    evidence_summary="One or more extracted facts have confidence below 0.80.",
                    candidates=[], dedupe_key=f"confidence:{digest}", now=now,
                ))
        return {
            "job_id": job_id, "projection_id": projection_id, "projection_version": projection_version,
            "created": created, "selected_fact_ids": selected_ids,
            "applied_override_ids": applied_override_ids, "review_ids": review_ids,
            "outcome": "created" if created else "updated",
        }

    @staticmethod
    def _decode_review(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["related_fact_ids"] = _loads(result.pop("related_fact_ids_json", "[]"), [])
        result["candidate_resolutions"] = _loads(result.pop("candidate_resolutions_json", "[]"), [])
        result.pop("dedupe_key", None)
        return result

    def list_reviews(self, *, state: str = "open", limit: int = 200) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT * FROM review_items WHERE state=?
                   ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                            created_at DESC,id LIMIT ?""",
                (state, max(1, min(500, limit))),
            ).fetchall()
        return [self._decode_review(row) for row in rows]

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute("SELECT * FROM review_items WHERE id=?", (review_id,)).fetchone()
        return self._decode_review(row) if row else None

    def close_review(
        self, review_id: str, *, state: str, resolution: str | None, note: str | None, now: str,
    ) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT state FROM review_items WHERE id=?", (review_id,)).fetchone()
            if not row:
                raise JobhuntError("Review Item not found", status=404, code="review_item_not_found")
            if row["state"] != "open":
                raise JobhuntError("Review Item is already closed", status=409, code="review_item_closed")
            connection.execute(
                "UPDATE review_items SET state=?,resolved_at=?,resolution=?,note=? WHERE id=?",
                (state, now, resolution, note, review_id),
            )

    def list_overrides(self, job_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM human_overrides WHERE job_id=? ORDER BY created_at DESC,id DESC",
                (job_id,),
            )]

    def create_override(
        self, *, job_id: str, field_name: str, replacement: Any, reason: str,
        note: str | None, now: str,
    ) -> str:
        with self.transaction() as connection:
            job = connection.execute("SELECT * FROM canonical_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
            field_columns = {
                "title": "role_title", "company": "company", "location_city": "location_city",
                "location_country": "location_country", "work_model": "work_mode",
                "contract_type": "contract_type", "salary_min": "salary_min",
                "salary_max": "salary_max", "salary_currency": "salary_currency",
                "salary_period": "salary_period", "salary_tax_type": "salary_tax_type",
            }
            previous = job[field_columns[field_name]] if field_name in field_columns else None
            active = connection.execute(
                "SELECT id,replacement_value_json FROM human_overrides WHERE job_id=? AND field_name=? AND state='active'",
                (job_id, field_name),
            ).fetchone()
            if active:
                previous = _loads(active["replacement_value_json"], previous)
                connection.execute(
                    "UPDATE human_overrides SET state='retired',retired_at=? WHERE id=?",
                    (now, active["id"]),
                )
            override_id = _id("override")
            connection.execute(
                """INSERT INTO human_overrides(
                       id,job_id,field_name,previous_value_json,replacement_value_json,
                       reason,note,author,state,created_at
                   ) VALUES(?,?,?,?,?,?,?,'local_user','active',?)""",
                (override_id, job_id, field_name, _json(previous), _json(replacement),
                 reason, note, now),
            )
        return override_id

    def latest_listing_for_job(self, job_id: str) -> tuple[str, str] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT l.id,c.id FROM source_listings l JOIN raw_captures c ON c.listing_id=l.id
                   WHERE l.canonical_job_id=? ORDER BY c.captured_at DESC,c.rowid DESC LIMIT 1""",
                (job_id,),
            ).fetchone()
        return (str(row[0]), str(row[1])) if row else None

    def latest_projection(self, job_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT * FROM canonical_job_projections WHERE job_id=?
                   ORDER BY projection_version DESC LIMIT 1""", (job_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["selected_fact_ids"] = _loads(result.pop("selected_fact_ids_json"), [])
        result["applied_override_ids"] = _loads(result.pop("applied_override_ids_json"), [])
        result["snapshot"] = _loads(result.pop("snapshot_json"), {})
        return result

    @staticmethod
    def _decode_duplicate_candidate(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["reason_codes"] = _loads(result.pop("reason_codes_json", "[]"), [])
        result["evidence"] = _loads(result.pop("evidence_json", "{}"), {})
        result["hard_contradictions"] = _loads(
            result.pop("hard_contradictions_json", "[]"), []
        )
        return result

    @staticmethod
    def _decode_merge(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for column in (
            "affected_listing_ids_json", "before_state_json", "application_handling_json",
            "track_handling_json", "override_handling_json",
        ):
            result[column.removesuffix("_json")] = _loads(result.pop(column, None), {})
        return result

    def dedupe_job_context(self, job_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            job_row = connection.execute(
                "SELECT * FROM canonical_jobs WHERE id=? AND deleted_at IS NULL", (job_id,)
            ).fetchone()
            if not job_row:
                return None
            listings = [dict(row) for row in connection.execute(
                """SELECT l.*,d.source_key,d.display_name AS source_display_name
                   FROM source_listings l JOIN source_definitions d ON d.id=l.source_id
                   WHERE l.canonical_job_id=? ORDER BY l.first_seen_at,l.id""",
                (job_id,),
            )]
            facts = [self._decode_fact(row) for row in connection.execute(
                self._fact_query(
                    "f.capture_id IN (SELECT rc.id FROM raw_captures rc "
                    "JOIN source_listings sl ON sl.id=rc.listing_id WHERE sl.canonical_job_id=?)"
                ),
                (job_id,),
            )]
            application = connection.execute(
                "SELECT * FROM applications WHERE job_id=?", (job_id,)
            ).fetchone()
            events = [] if not application else [dict(row) for row in connection.execute(
                "SELECT * FROM application_events WHERE application_id=? ORDER BY occurred_at,id",
                (application["id"],),
            )]
            tracks = [dict(row) for row in connection.execute(
                "SELECT * FROM track_job_assignments WHERE job_id=? ORDER BY track_id", (job_id,)
            )]
            overrides = [dict(row) for row in connection.execute(
                "SELECT * FROM human_overrides WHERE job_id=? AND state='active' ORDER BY field_name,id",
                (job_id,),
            )]
            captures = [dict(row) for row in connection.execute(
                """SELECT c.*,b.relative_path,b.byte_size,b.sha256 AS blob_hash
                   FROM raw_captures c JOIN raw_blobs b ON b.sha256=c.blob_sha256
                   WHERE c.listing_id IN (
                       SELECT id FROM source_listings WHERE canonical_job_id=?
                   ) ORDER BY c.captured_at DESC,c.rowid DESC LIMIT 8""",
                (job_id,),
            )]
        urls: list[dict[str, str]] = []
        if job_row["source_url"]:
            urls.append({"url": str(job_row["source_url"]), "kind": "listing"})
        for listing in listings:
            for column in ("canonical_url", "observed_url"):
                if listing.get(column):
                    urls.append({"url": str(listing[column]), "kind": "listing"})
        publication_at = None
        expiration_at = None
        for fact in facts:
            value = self._fact_value(fact)
            if fact["fact_type"] == "date_posted" and publication_at is None:
                publication_at = value
            elif fact["fact_type"] == "valid_through" and expiration_at is None:
                expiration_at = value
            elif fact["fact_type"] == "other" and str(fact.get("label") or "").casefold() in {
                "application url", "source url",
            } and isinstance(value, str):
                urls.append({
                    "url": value,
                    "kind": "application" if "application" in str(fact.get("label")).casefold()
                    else "source_fact",
                })
        return {
            "job": dict(job_row), "listings": listings, "facts": facts,
            "application": dict(application) if application else None,
            "application_events": events, "tracks": tracks, "overrides": overrides,
            "captures": captures, "urls": urls,
            "publication_at": publication_at, "expiration_at": expiration_at,
        }

    def save_dedupe_job_key(
        self, job_id: str, key: dict[str, Any], urls: list[dict[str, str]], *, now: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO dedupe_job_keys(
                       job_id,company_key,title_key,title_tokens_json,city_key,country_key,
                       publication_at,expiration_at,identity_fingerprint,rule_version,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET
                       company_key=excluded.company_key,title_key=excluded.title_key,
                       title_tokens_json=excluded.title_tokens_json,city_key=excluded.city_key,
                       country_key=excluded.country_key,publication_at=excluded.publication_at,
                       expiration_at=excluded.expiration_at,
                       identity_fingerprint=excluded.identity_fingerprint,
                       rule_version=excluded.rule_version,updated_at=excluded.updated_at""",
                (
                    job_id, key["company_key"], key["title_key"], _json(key["title_tokens"]),
                    key["city_key"], key["country_key"], key.get("publication_at"),
                    key.get("expiration_at"), key["identity_fingerprint"],
                    key.get("rule_version") or "dedupe@1", now,
                ),
            )
            connection.execute("DELETE FROM dedupe_job_urls WHERE job_id=?", (job_id,))
            for item in urls:
                if item.get("normalized_url"):
                    connection.execute(
                        """INSERT OR IGNORE INTO dedupe_job_urls(
                               job_id,normalized_url,url_kind,rule_version
                           ) VALUES(?,?,?,?)""",
                        (job_id, item["normalized_url"], item["kind"], key.get("rule_version") or "dedupe@1"),
                    )

    def blocked_dedupe_job_ids(
        self, job_id: str, key: dict[str, Any], *, publication_window_days: int,
        url_limit: int, company_limit: int,
    ) -> list[str]:
        selected: list[str] = []
        with self.read_connection() as connection:
            for row in connection.execute(
                """SELECT DISTINCT u2.job_id FROM dedupe_job_urls u1
                   JOIN dedupe_job_urls u2 ON u2.normalized_url=u1.normalized_url
                   JOIN canonical_jobs j ON j.id=u2.job_id
                   WHERE u1.job_id=? AND u2.job_id!=?
                     AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                   ORDER BY u2.job_id LIMIT ?""",
                (job_id, job_id, max(1, min(200, int(url_limit)))),
            ):
                selected.append(str(row[0]))
            company_key = str(key.get("company_key") or "")
            if company_key:
                for row in connection.execute(
                    """SELECT k.job_id FROM dedupe_job_keys k
                       JOIN canonical_jobs j ON j.id=k.job_id
                       WHERE k.company_key=? AND k.job_id!=?
                         AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                         AND (
                           k.publication_at IS NULL OR ? IS NULL OR
                           ABS(julianday(k.publication_at)-julianday(?))<=?
                         )
                       ORDER BY ABS(COALESCE(julianday(k.publication_at)-julianday(?),0)),
                                k.updated_at DESC,k.job_id
                       LIMIT ?""",
                    (
                        company_key, job_id, key.get("publication_at"), key.get("publication_at"),
                        max(1, int(publication_window_days)), key.get("publication_at"),
                        max(1, min(500, int(company_limit))),
                    ),
                ):
                    selected.append(str(row[0]))
        return list(dict.fromkeys(selected))

    def unindexed_dedupe_job_ids(self, job_id: str, *, limit: int = 150) -> list[str]:
        """Bound first-time comparison work for pre-Pack-H Canonical Jobs."""
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT j.id FROM canonical_jobs j
                   LEFT JOIN dedupe_job_keys k ON k.job_id=j.id
                   WHERE j.id!=? AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                     AND k.job_id IS NULL
                   ORDER BY j.updated_at DESC,j.id LIMIT ?""",
                (job_id, max(1, min(500, int(limit)))),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def save_duplicate_candidate(
        self, *, left_job_id: str, right_job_id: str, comparison: dict[str, Any], now: str,
        force_reopen: bool = False,
    ) -> tuple[dict[str, Any], bool, bool]:
        left, right = sorted((left_job_id, right_job_id))
        pair_key = f"{left}:{right}"
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM duplicate_candidates WHERE pair_key=?", (pair_key,)
            ).fetchone()
            created = row is None
            evidence_changed = bool(
                row and row["evidence_fingerprint"] != comparison["evidence_fingerprint"]
            )
            if row is None:
                candidate_id = _id("duplicate")
                state = "open"
                connection.execute(
                    """INSERT INTO duplicate_candidates(
                           id,left_job_id,right_job_id,pair_key,rule_version,evidence_fingerprint,
                           left_identity_fingerprint,right_identity_fingerprint,state,
                           confidence_class,reason_codes_json,evidence_json,hard_contradictions_json,
                           generated_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        candidate_id, left, right, pair_key, comparison["rule_version"],
                        comparison["evidence_fingerprint"],
                        comparison["left_identity_fingerprint"] if left == left_job_id else comparison["right_identity_fingerprint"],
                        comparison["right_identity_fingerprint"] if right == right_job_id else comparison["left_identity_fingerprint"],
                        state, comparison["confidence_class"], _json(comparison["reason_codes"]),
                        _json(comparison["evidence"]), _json(comparison["hard_contradictions"]),
                        now, now,
                    ),
                )
                connection.execute(
                    "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,'generated','deterministic_policy',?,?)",
                    (_id("duplicate_event"), candidate_id, _json({"evidenceFingerprint": comparison["evidence_fingerprint"]}), now),
                )
            elif evidence_changed:
                candidate_id = str(row["id"])
                old_state = str(row["state"])
                state = "open" if old_state != "merged" else "stale"
                connection.execute(
                    """UPDATE duplicate_candidates SET rule_version=?,evidence_fingerprint=?,
                           left_identity_fingerprint=?,right_identity_fingerprint=?,state=?,
                           confidence_class=?,reason_codes_json=?,evidence_json=?,
                           hard_contradictions_json=?,updated_at=?,reviewed_at=NULL,
                           resolution=NULL,reviewer=NULL WHERE id=?""",
                    (
                        comparison["rule_version"], comparison["evidence_fingerprint"],
                        comparison["left_identity_fingerprint"] if left == left_job_id else comparison["right_identity_fingerprint"],
                        comparison["right_identity_fingerprint"] if right == right_job_id else comparison["left_identity_fingerprint"],
                        state, comparison["confidence_class"], _json(comparison["reason_codes"]),
                        _json(comparison["evidence"]), _json(comparison["hard_contradictions"]),
                        now, candidate_id,
                    ),
                )
                event_type = "reopened" if old_state in {"not_duplicate", "dismissed", "stale"} else "evidence_changed"
                connection.execute(
                    "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (_id("duplicate_event"), candidate_id, event_type, "deterministic_policy", _json({
                        "previousState": old_state,
                        "previousEvidenceFingerprint": row["evidence_fingerprint"],
                        "evidenceFingerprint": comparison["evidence_fingerprint"],
                    }), now),
                )
            elif force_reopen and row["state"] in {"not_duplicate", "dismissed", "stale"}:
                candidate_id = str(row["id"])
                connection.execute(
                    """UPDATE duplicate_candidates SET state='open',reviewed_at=NULL,
                           resolution=NULL,reviewer=NULL,updated_at=? WHERE id=?""",
                    (now, candidate_id),
                )
                connection.execute(
                    "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,'reopened','manual_user',?,?)",
                    (_id("duplicate_event"), candidate_id, _json({"explicitRescan": True}), now),
                )
            else:
                candidate_id = str(row["id"])
            saved = connection.execute(
                "SELECT * FROM duplicate_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        return self._decode_duplicate_candidate(saved), created, evidence_changed

    def list_duplicate_candidates(
        self, *, state: str | None = "open", limit: int = 200,
    ) -> list[dict[str, Any]]:
        where = "" if state is None else "WHERE c.state=?"
        parameters: list[Any] = [] if state is None else [state]
        parameters.append(max(1, min(500, int(limit))))
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT c.*,
                       l.company AS left_company,l.role_title AS left_title,
                       l.location_city AS left_city,l.location_country AS left_country,
                       l.source_captured_at AS left_published_at,
                       r.company AS right_company,r.role_title AS right_title,
                       r.location_city AS right_city,r.location_country AS right_country,
                       r.source_captured_at AS right_published_at
                    FROM duplicate_candidates c
                    JOIN canonical_jobs l ON l.id=c.left_job_id
                    JOIN canonical_jobs r ON r.id=c.right_job_id
                    {where} ORDER BY c.updated_at DESC,c.id LIMIT ?""",
                parameters,
            ).fetchall()
        return [self._decode_duplicate_candidate(row) for row in rows]

    def get_duplicate_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM duplicate_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if not row:
                return None
            result = self._decode_duplicate_candidate(row)
            result["events"] = [
                {**dict(item), "payload": _loads(item["payload_json"], {})}
                for item in connection.execute(
                    "SELECT * FROM duplicate_candidate_events WHERE candidate_id=? ORDER BY created_at,id",
                    (candidate_id,),
                )
            ]
            for item in result["events"]:
                item.pop("payload_json", None)
        return result

    def decide_duplicate_candidate(
        self, candidate_id: str, *, state: str, resolution: str, now: str,
    ) -> dict[str, Any]:
        event_type = "marked_not_duplicate" if state == "not_duplicate" else "dismissed"
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM duplicate_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if not row:
                raise JobhuntError("Duplicate candidate not found", status=404, code="duplicate_candidate_not_found")
            if row["state"] != "open":
                raise JobhuntError("Duplicate candidate is no longer open", status=409, code="duplicate_candidate_stale")
            connection.execute(
                "UPDATE duplicate_candidates SET state=?,reviewed_at=?,resolution=?,reviewer='local_user',updated_at=? WHERE id=?",
                (state, now, resolution, now, candidate_id),
            )
            connection.execute(
                "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,?,'manual_user',?,?)",
                (_id("duplicate_event"), candidate_id, event_type, _json({"resolution": resolution}), now),
            )
        return self.get_duplicate_candidate(candidate_id)  # type: ignore[return-value]

    def merge_canonical_jobs(
        self, *, candidate_id: str, survivor_job_id: str, origin: str,
        rule_version: str, evidence_fingerprint: str, reason: str, note: str | None,
        application_handling: dict[str, Any], track_handling: dict[str, Any],
        override_handling: dict[str, Any], now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            candidate = connection.execute(
                "SELECT * FROM duplicate_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if not candidate:
                raise JobhuntError("Duplicate candidate not found", status=404, code="duplicate_candidate_not_found")
            if candidate["state"] != "open" or candidate["evidence_fingerprint"] != evidence_fingerprint:
                raise JobhuntError("Duplicate candidate is stale", status=409, code="duplicate_candidate_stale")
            pair = {str(candidate["left_job_id"]), str(candidate["right_job_id"])}
            if survivor_job_id not in pair:
                raise JobhuntError("Survivor must belong to the duplicate pair", code="invalid_merge_survivor")
            absorbed_job_id = next(iter(pair - {survivor_job_id}))
            jobs = {
                str(row["id"]): dict(row) for row in connection.execute(
                    "SELECT * FROM canonical_jobs WHERE id IN (?,?)",
                    (survivor_job_id, absorbed_job_id),
                )
            }
            if len(jobs) != 2 or any(jobs[job_id].get("merged_into_job_id") for job_id in pair):
                raise JobhuntError("A duplicate job already changed merge state", status=409, code="duplicate_candidate_stale")
            active_conflict = connection.execute(
                """SELECT id FROM canonical_job_merges WHERE state='active' AND (
                       survivor_job_id IN (?,?) OR absorbed_job_id IN (?,?)
                   ) LIMIT 1""",
                (survivor_job_id, absorbed_job_id, survivor_job_id, absorbed_job_id),
            ).fetchone()
            if active_conflict:
                raise JobhuntError("A Canonical Job is already involved in an active merge", status=409, code="merge_conflict")
            listings = [dict(row) for row in connection.execute(
                "SELECT * FROM source_listings WHERE canonical_job_id IN (?,?) ORDER BY id",
                (survivor_job_id, absorbed_job_id),
            )]
            tracks = [dict(row) for row in connection.execute(
                "SELECT * FROM track_job_assignments WHERE job_id IN (?,?) ORDER BY track_id,job_id",
                (survivor_job_id, absorbed_job_id),
            )]
            overrides = [dict(row) for row in connection.execute(
                "SELECT * FROM human_overrides WHERE job_id IN (?,?) AND state='active' ORDER BY field_name,id",
                (survivor_job_id, absorbed_job_id),
            )]
            before_state = {
                "jobs": jobs,
                "listingOwnership": {item["id"]: item["canonical_job_id"] for item in listings},
                "trackAssignments": tracks,
                "activeOverrideIds": [item["id"] for item in overrides],
            }
            moved_listing_ids = [
                item["id"] for item in listings if item["canonical_job_id"] == absorbed_job_id
            ]
            connection.execute(
                "UPDATE source_listings SET canonical_job_id=?,updated_at=? WHERE canonical_job_id=?",
                (survivor_job_id, now, absorbed_job_id),
            )
            survivor_tracks = {
                item["track_id"]: item for item in tracks if item["job_id"] == survivor_job_id
            }
            unioned_assignments: list[dict[str, Any]] = []
            for assignment in tracks:
                if assignment["job_id"] != absorbed_job_id or not assignment["active"]:
                    continue
                existing = survivor_tracks.get(assignment["track_id"])
                if existing and existing["active"]:
                    continue
                unioned_assignments.append({
                    "trackId": assignment["track_id"],
                    "survivorStateBefore": None if existing is None else {
                        "active": bool(existing["active"]),
                        "origin": existing["origin"], "note": existing.get("note"),
                    },
                    "sourceJobId": absorbed_job_id,
                })
                connection.execute(
                    """INSERT INTO track_job_assignments(
                           track_id,job_id,origin,note,active,created_at,updated_at
                       ) VALUES(?,?,?,?,1,?,?)
                       ON CONFLICT(track_id,job_id) DO UPDATE SET
                           active=1,origin=excluded.origin,note=excluded.note,updated_at=excluded.updated_at""",
                    (
                        assignment["track_id"], survivor_job_id, assignment["origin"],
                        assignment.get("note") or f"Unioned from {absorbed_job_id} by Pack H merge",
                        assignment["created_at"], now,
                    ),
                )
            track_handling = {
                **track_handling,
                "unionedAssignments": unioned_assignments,
            }
            connection.execute(
                "UPDATE canonical_jobs SET merged_into_job_id=?,merged_at=?,updated_at=? WHERE id=?",
                (survivor_job_id, now, now, absorbed_job_id),
            )
            merge_id = _id("merge")
            connection.execute(
                """INSERT INTO canonical_job_merges(
                       id,candidate_id,survivor_job_id,absorbed_job_id,origin,rule_version,
                       evidence_fingerprint,state,affected_listing_ids_json,before_state_json,
                       application_handling_json,track_handling_json,override_handling_json,
                       reason,note,merged_at
                   ) VALUES(?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?)""",
                (
                    merge_id, candidate_id, survivor_job_id, absorbed_job_id, origin,
                    rule_version, evidence_fingerprint, _json(moved_listing_ids),
                    _json(before_state), _json(application_handling), _json(track_handling),
                    _json(override_handling), reason, note, now,
                ),
            )
            connection.execute(
                "INSERT INTO canonical_job_merge_events(id,merge_id,event_type,origin,payload_json,created_at) VALUES(?,?,'merged',?,?,?)",
                (_id("merge_event"), merge_id, origin, _json({
                    "candidateId": candidate_id, "survivorJobId": survivor_job_id,
                    "absorbedJobId": absorbed_job_id,
                }), now),
            )
            connection.execute(
                "UPDATE duplicate_candidates SET state='merged',reviewed_at=?,resolution=?,reviewer=?,updated_at=? WHERE id=?",
                (now, reason, "local_user" if origin == "manual_user" else "deterministic_policy", now, candidate_id),
            )
            connection.execute(
                "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,'merged',?,?,?)",
                (_id("duplicate_event"), candidate_id, "manual_user" if origin == "manual_user" else "deterministic_policy", _json({"mergeId": merge_id}), now),
            )
            stale_candidates = connection.execute(
                """SELECT id FROM duplicate_candidates
                   WHERE id!=? AND state='open' AND (
                       left_job_id IN (?,?) OR right_job_id IN (?,?)
                   )""",
                (candidate_id, survivor_job_id, absorbed_job_id, survivor_job_id, absorbed_job_id),
            ).fetchall()
            for stale in stale_candidates:
                connection.execute(
                    "UPDATE duplicate_candidates SET state='stale',updated_at=? WHERE id=?",
                    (now, stale["id"]),
                )
                connection.execute(
                    "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,'stale','system',?,?)",
                    (_id("duplicate_event"), stale["id"], _json({"mergeId": merge_id}), now),
                )
            saved = connection.execute(
                "SELECT * FROM canonical_job_merges WHERE id=?", (merge_id,)
            ).fetchone()
        return self._decode_merge(saved)

    def list_canonical_job_merges(
        self, *, state: str | None = None, limit: int = 200,
    ) -> list[dict[str, Any]]:
        where = "" if state is None else "WHERE m.state=?"
        parameters: list[Any] = [] if state is None else [state]
        parameters.append(max(1, min(500, int(limit))))
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT m.*,s.company AS survivor_company,s.role_title AS survivor_title,
                           a.company AS absorbed_company,a.role_title AS absorbed_title
                    FROM canonical_job_merges m
                    JOIN canonical_jobs s ON s.id=m.survivor_job_id
                    JOIN canonical_jobs a ON a.id=m.absorbed_job_id
                    {where} ORDER BY m.merged_at DESC,m.id LIMIT ?""", parameters,
            ).fetchall()
        return [self._decode_merge(row) for row in rows]

    def get_canonical_job_merge(self, merge_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM canonical_job_merges WHERE id=?", (merge_id,)
            ).fetchone()
            if not row:
                return None
            result = self._decode_merge(row)
            result["events"] = []
            for event in connection.execute(
                "SELECT * FROM canonical_job_merge_events WHERE merge_id=? ORDER BY created_at,id",
                (merge_id,),
            ):
                item = dict(event)
                item["payload"] = _loads(item.pop("payload_json", "{}"), {})
                result["events"].append(item)
        return result

    def unmerge_canonical_jobs(self, merge_id: str, *, note: str | None, now: str) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM canonical_job_merges WHERE id=?", (merge_id,)
            ).fetchone()
            if not row:
                raise JobhuntError("Canonical Job merge not found", status=404, code="merge_not_found")
            if row["state"] != "active":
                raise JobhuntError("Canonical Job merge is not active", status=409, code="merge_not_active")
            survivor_job_id = str(row["survivor_job_id"])
            absorbed_job_id = str(row["absorbed_job_id"])
            absorbed = connection.execute(
                "SELECT merged_into_job_id FROM canonical_jobs WHERE id=?", (absorbed_job_id,)
            ).fetchone()
            if not absorbed or absorbed["merged_into_job_id"] != survivor_job_id:
                raise JobhuntError("Canonical Job merge state changed", status=409, code="merge_stale")
            before = _loads(row["before_state_json"], {})
            ownership = before.get("listingOwnership") or {}
            for listing_id, owner_id in ownership.items():
                connection.execute(
                    "UPDATE source_listings SET canonical_job_id=?,updated_at=? WHERE id=?",
                    (owner_id, now, listing_id),
                )
            connection.execute(
                "UPDATE canonical_jobs SET merged_into_job_id=NULL,merged_at=NULL,updated_at=? WHERE id=?",
                (now, absorbed_job_id),
            )
            snapshot_assignments = before.get("trackAssignments") or []
            snapshot_keys = {(item["track_id"], item["job_id"]) for item in snapshot_assignments}
            merge_track_handling = _loads(row["track_handling_json"], {})
            for item in merge_track_handling.get("unionedAssignments") or []:
                key = (item.get("trackId"), survivor_job_id)
                if key not in snapshot_keys:
                    connection.execute(
                        "UPDATE track_job_assignments SET active=0,updated_at=? WHERE track_id=? AND job_id=?",
                        (now, item.get("trackId"), survivor_job_id),
                    )
            for item in snapshot_assignments:
                connection.execute(
                    """INSERT INTO track_job_assignments(
                           track_id,job_id,origin,note,active,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(track_id,job_id) DO UPDATE SET
                           origin=excluded.origin,note=excluded.note,active=excluded.active,
                           updated_at=excluded.updated_at""",
                    (
                        item["track_id"], item["job_id"], item["origin"], item.get("note"),
                        item["active"], item["created_at"], now,
                    ),
                )
            restore_columns = (
                "company", "role_title", "seniority", "location_city", "location_country",
                "work_mode", "hybrid_details", "contract_type", "contract_details",
                "salary_min", "salary_max", "salary_currency", "salary_period",
                "salary_tax_type", "salary_is_known", "source_name", "source_url",
                "source_captured_at", "expires_at", "requirements_json",
            )
            for job_id in (survivor_job_id, absorbed_job_id):
                snapshot = (before.get("jobs") or {}).get(job_id)
                if not snapshot:
                    continue
                assignments = ",".join(f"{column}=?" for column in restore_columns)
                connection.execute(
                    f"UPDATE canonical_jobs SET {assignments},updated_at=? WHERE id=?",
                    [snapshot.get(column) for column in restore_columns] + [now, job_id],
                )
            connection.execute(
                "UPDATE canonical_job_merges SET state='reverted',reverted_at=?,note=COALESCE(?,note) WHERE id=?",
                (now, note, merge_id),
            )
            connection.execute(
                "INSERT INTO canonical_job_merge_events(id,merge_id,event_type,origin,payload_json,created_at) VALUES(?,?,'reverted','manual_user',?,?)",
                (_id("merge_event"), merge_id, _json({"note": note}), now),
            )
            candidate_id = row["candidate_id"]
            if candidate_id:
                connection.execute(
                    "UPDATE duplicate_candidates SET state='not_duplicate',reviewed_at=?,resolution='unmerged_by_local_user',reviewer='local_user',updated_at=? WHERE id=?",
                    (now, now, candidate_id),
                )
                connection.execute(
                    "INSERT INTO duplicate_candidate_events(id,candidate_id,event_type,origin,payload_json,created_at) VALUES(?,?,'unmerged','manual_user',?,?)",
                    (_id("duplicate_event"), candidate_id, _json({"mergeId": merge_id}), now),
                )
        return self.get_canonical_job_merge(merge_id)  # type: ignore[return-value]

    def dedupe_summary(self) -> dict[str, int]:
        with self.read_connection() as connection:
            return {
                "openCandidates": int(connection.execute(
                    "SELECT COUNT(*) FROM duplicate_candidates WHERE state='open'"
                ).fetchone()[0]),
                "activeMerges": int(connection.execute(
                    "SELECT COUNT(*) FROM canonical_job_merges WHERE state='active'"
                ).fetchone()[0]),
                "notDuplicatePairs": int(connection.execute(
                    "SELECT COUNT(*) FROM duplicate_candidates WHERE state='not_duplicate'"
                ).fetchone()[0]),
                "dismissedPairs": int(connection.execute(
                    "SELECT COUNT(*) FROM duplicate_candidates WHERE state='dismissed'"
                ).fetchone()[0]),
                "mergedCanonicalJobs": int(connection.execute(
                    "SELECT COUNT(*) FROM canonical_jobs WHERE merged_into_job_id IS NOT NULL"
                ).fetchone()[0]),
                "sourceListings": int(connection.execute("SELECT COUNT(*) FROM source_listings").fetchone()[0]),
                "canonicalJobs": int(connection.execute(
                    "SELECT COUNT(*) FROM canonical_jobs WHERE deleted_at IS NULL AND merged_into_job_id IS NULL"
                ).fetchone()[0]),
                "rawCaptures": int(connection.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0]),
            }

    def _seed_tracks(self, connection: sqlite3.Connection, now: str) -> None:
        for seed in TRACK_SEEDS:
            connection.execute(
                """INSERT OR IGNORE INTO career_tracks(
                       id,slug,name,purpose,status,countries_json,regions_cities_json,
                       remote_allowed,relocation_relevant,primary_currency,
                       evaluation_policy_version,rationale,notes,seed_key,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    seed["id"], seed["slug"], seed["name"], seed["purpose"], "exploring",
                    _json(seed["countries"]), _json(seed["regions_cities"]),
                    seed["remote_allowed"], seed["relocation_relevant"], seed["primary_currency"],
                    None, None, None, seed["seed_key"], now, now,
                ),
            )
            for profile_key, name, keywords, role_intent in seed["profiles"]:
                seed_key = f"{seed['seed_key']}:{profile_key}"
                schedule_hints = ["weekend"] if seed["seed_key"] == "krakow-weekend" else []
                connection.execute(
                    """INSERT OR IGNORE INTO track_search_profiles(
                           id,track_id,name,status,include_keywords_json,exclude_keywords_json,
                           role_intent,countries_json,regions_cities_json,work_models_json,
                           schedule_hints_json,contract_hints_json,language_hints_json,
                           seniority_hints_json,planned_source_keys_json,notes,seed_key,
                           created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"search_seed_{seed['seed_key']}_{profile_key}", seed["id"], name,
                        "enabled", _json(keywords), "[]", role_intent,
                        _json(seed["countries"]), _json(seed["regions_cities"]), "[]",
                        _json(schedule_hints), "[]", "[]", "[]", _json(seed["sources"]),
                        None, seed_key, now, now,
                    ),
                )

    def _seed_evaluation_policies(
        self, connection: sqlite3.Connection, now: str, *, track_id: str | None = None,
    ) -> None:
        policy = default_policy()
        encoded = _json(policy)
        policy_fingerprint = evaluation_fingerprint(policy)
        where = "WHERE id=?" if track_id else ""
        parameters: tuple[Any, ...] = (track_id,) if track_id else ()
        tracks = connection.execute(
            f"SELECT id,evaluation_policy_version FROM career_tracks {where} ORDER BY id",
            parameters,
        ).fetchall()
        for track in tracks:
            existing = connection.execute(
                "SELECT id,policy_version FROM track_evaluation_policies WHERE track_id=? ORDER BY policy_version DESC LIMIT 1",
                (track["id"],),
            ).fetchone()
            if existing:
                if track["evaluation_policy_version"] is None:
                    connection.execute(
                        "UPDATE career_tracks SET evaluation_policy_version=?,updated_at=? WHERE id=?",
                        (str(existing["policy_version"]), now, track["id"]),
                    )
                continue
            policy_id = _id("evaluation_policy")
            connection.execute(
                """INSERT INTO track_evaluation_policies(
                       id,track_id,schema_version,policy_version,fingerprint,policy_json,origin,created_at
                   ) VALUES(?,?,?,1,?,?,'seed',?)""",
                (policy_id, track["id"], policy["schemaVersion"], policy_fingerprint, encoded, now),
            )
            connection.execute(
                "UPDATE career_tracks SET evaluation_policy_version='1',updated_at=? WHERE id=?",
                (now, track["id"]),
            )

    @staticmethod
    def _decode_track(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["countries"] = _loads(result.pop("countries_json", "[]"), [])
        result["regions_cities"] = _loads(result.pop("regions_cities_json", "[]"), [])
        if result.get("remote_allowed") is not None:
            result["remote_allowed"] = bool(result["remote_allowed"])
        if result.get("relocation_relevant") is not None:
            result["relocation_relevant"] = bool(result["relocation_relevant"])
        return result

    @staticmethod
    def _decode_search_profile(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for column in (
            "include_keywords_json", "exclude_keywords_json", "countries_json",
            "regions_cities_json", "work_models_json", "schedule_hints_json",
            "contract_hints_json", "language_hints_json", "seniority_hints_json",
            "planned_source_keys_json",
        ):
            result[column.removesuffix("_json")] = _loads(result.pop(column, "[]"), [])
        return result

    def list_tracks(self) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT t.*,
                          (SELECT COUNT(*) FROM track_search_profiles p WHERE p.track_id=t.id) AS search_profile_count,
                          (SELECT COUNT(*) FROM track_job_assignments a
                           WHERE a.track_id=t.id AND a.active=1 AND a.origin='manual') AS assigned_job_count
                   FROM career_tracks t
                   ORDER BY CASE t.status WHEN 'active' THEN 0 WHEN 'exploring' THEN 1
                            WHEN 'paused' THEN 2 ELSE 3 END, t.updated_at DESC, t.id"""
            ).fetchall()
        return [self._decode_track(row) for row in rows]

    def get_track(self, track_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT t.*,
                          (SELECT COUNT(*) FROM track_search_profiles p WHERE p.track_id=t.id) AS search_profile_count,
                          (SELECT COUNT(*) FROM track_job_assignments a
                           WHERE a.track_id=t.id AND a.active=1 AND a.origin='manual') AS assigned_job_count
                   FROM career_tracks t WHERE t.id=?""",
                (track_id,),
            ).fetchone()
        return self._decode_track(row) if row else None

    def create_track(self, values: dict[str, Any], *, now: str) -> str:
        track_id = _id("track")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO career_tracks(
                       id,slug,name,purpose,status,countries_json,regions_cities_json,
                       remote_allowed,relocation_relevant,primary_currency,
                       evaluation_policy_version,rationale,notes,seed_key,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)""",
                (
                    track_id, values["slug"], values["name"], values["purpose"], values["status"],
                    _json(values["countries"]), _json(values["regions_cities"]),
                    values["remote_allowed"], values["relocation_relevant"],
                    values["primary_currency"], values["evaluation_policy_version"],
                    values["rationale"], values["notes"], now, now,
                ),
            )
            self._seed_evaluation_policies(connection, now, track_id=track_id)
        return track_id

    def update_track(self, track_id: str, changes: dict[str, Any], *, now: str) -> None:
        encoded = dict(changes)
        for key in ("countries", "regions_cities"):
            if key in encoded:
                encoded[f"{key}_json"] = _json(encoded.pop(key))
        with self.transaction() as connection:
            if not encoded:
                exists = connection.execute("SELECT 1 FROM career_tracks WHERE id=?", (track_id,)).fetchone()
                if not exists:
                    raise JobhuntError("Track not found", status=404, code="track_not_found")
                return
            assignments = ",".join(f"{column}=?" for column in encoded)
            cursor = connection.execute(
                f"UPDATE career_tracks SET {assignments},updated_at=? WHERE id=?",
                (*encoded.values(), now, track_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Track not found", status=404, code="track_not_found")

    def list_search_profiles(self, track_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT * FROM track_search_profiles WHERE track_id=?
                   ORDER BY CASE status WHEN 'enabled' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                            updated_at DESC,id""",
                (track_id,),
            ).fetchall()
        return [self._decode_search_profile(row) for row in rows]

    def get_search_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM track_search_profiles WHERE id=?", (profile_id,)
            ).fetchone()
        return self._decode_search_profile(row) if row else None

    def save_search_profile(
        self,
        track_id: str,
        values: dict[str, Any],
        *,
        profile_id: str | None = None,
        now: str,
    ) -> str:
        json_fields = {
            "include_keywords", "exclude_keywords", "countries", "regions_cities",
            "work_models", "schedule_hints", "contract_hints", "language_hints",
            "seniority_hints", "planned_source_keys",
        }
        encoded = {
            (f"{key}_json" if key in json_fields else key): (_json(value) if key in json_fields else value)
            for key, value in values.items()
        }
        identifier = profile_id or _id("search")
        with self.transaction() as connection:
            track = connection.execute("SELECT 1 FROM career_tracks WHERE id=?", (track_id,)).fetchone()
            if not track:
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            if profile_id:
                owner = connection.execute(
                    "SELECT track_id FROM track_search_profiles WHERE id=?", (profile_id,)
                ).fetchone()
                if not owner:
                    raise JobhuntError("Search Profile not found", status=404, code="search_profile_not_found")
                if owner["track_id"] != track_id:
                    raise JobhuntError(
                        "Search Profile belongs to another Track",
                        status=409,
                        code="search_profile_track_mismatch",
                    )
                assignments = ",".join(f"{column}=?" for column in encoded)
                connection.execute(
                    f"UPDATE track_search_profiles SET {assignments},updated_at=? WHERE id=?",
                    (*encoded.values(), now, profile_id),
                )
            else:
                columns = ["id", "track_id", *encoded.keys(), "seed_key", "created_at", "updated_at"]
                values_list = [identifier, track_id, *encoded.values(), None, now, now]
                connection.execute(
                    f"INSERT INTO track_search_profiles({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                    values_list,
                )
            connection.execute(
                "DELETE FROM search_profile_sources WHERE search_profile_id=?", (identifier,)
            )
            source_ids = {
                row["source_key"]: row["id"]
                for row in connection.execute("SELECT id,source_key FROM source_definitions")
            }
            planned_keys = values.get("planned_source_keys", [])
            for key in planned_keys:
                source_id = source_ids.get(str(key))
                if source_id:
                    connection.execute(
                        """INSERT INTO search_profile_sources(
                               search_profile_id,source_id,legacy_source_key,resolved_at
                           ) VALUES(?,?,?,?)""",
                        (identifier, source_id, str(key), now),
                    )
        return identifier

    def assigned_jobs_for_track(self, track_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT a.track_id,a.job_id,a.origin,a.note,a.active,a.created_at,a.updated_at,
                          j.company,j.role_title,j.location_city,j.location_country,
                          ap.current_status AS application_status
                   FROM track_job_assignments a
                   JOIN canonical_jobs j ON j.id=a.job_id
                   JOIN applications ap ON ap.job_id=j.id
                   WHERE a.track_id=? AND a.active=1 AND j.deleted_at IS NULL
                   ORDER BY a.updated_at DESC,a.job_id""",
                (track_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def job_track_assignments(self, job_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT t.id,t.slug,t.name,t.status,a.origin,a.note,a.active,
                          a.created_at,a.updated_at
                   FROM career_tracks t
                   LEFT JOIN track_job_assignments a ON a.track_id=t.id AND a.job_id=?
                   ORDER BY CASE t.status WHEN 'active' THEN 0 WHEN 'exploring' THEN 1
                            WHEN 'paused' THEN 2 ELSE 3 END,t.name COLLATE NOCASE,t.id""",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def sync_job_tracks(
        self,
        job_id: str,
        track_ids: list[str],
        *,
        origin: str,
        note: str | None,
        now: str,
    ) -> None:
        selected = set(track_ids)
        with self.transaction() as connection:
            job = connection.execute(
                "SELECT 1 FROM canonical_jobs WHERE id=? AND deleted_at IS NULL", (job_id,)
            ).fetchone()
            if not job:
                raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
            if selected:
                placeholders = ",".join("?" for _ in selected)
                rows = connection.execute(
                    f"SELECT id,status FROM career_tracks WHERE id IN ({placeholders})", tuple(selected)
                ).fetchall()
                found = {row["id"]: row["status"] for row in rows}
                missing = sorted(selected - set(found))
                if missing:
                    raise JobhuntError("Track not found", status=404, code="track_not_found", details=missing)
                already_active = {
                    row["track_id"] for row in connection.execute(
                        "SELECT track_id FROM track_job_assignments WHERE job_id=? AND active=1",
                        (job_id,),
                    ).fetchall()
                }
                archived = sorted(
                    key for key, status in found.items()
                    if status == "archived" and key not in already_active
                )
                if archived:
                    raise JobhuntError(
                        "Archived Tracks cannot receive new assignments",
                        status=409,
                        code="track_archived",
                        details=archived,
                    )
            connection.execute(
                "UPDATE track_job_assignments SET active=0,updated_at=? WHERE job_id=? AND active=1",
                (now, job_id),
            )
            for track_id in sorted(selected):
                connection.execute(
                    """INSERT INTO track_job_assignments(
                           track_id,job_id,origin,note,active,created_at,updated_at
                       ) VALUES(?,?,?,?,1,?,?)
                       ON CONFLICT(track_id,job_id) DO UPDATE SET
                           origin=excluded.origin,note=excluded.note,active=1,updated_at=excluded.updated_at""",
                    (track_id, job_id, origin, note, now, now),
                )

    @staticmethod
    def _decode_evaluation_policy(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["policy"] = _loads(result.pop("policy_json", "{}"), {})
        return result

    def get_track_evaluation_policy(
        self, track_id: str, *, version: int | None = None,
    ) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            if version is None:
                row = connection.execute(
                    """SELECT p.* FROM track_evaluation_policies p
                       JOIN career_tracks t ON t.id=p.track_id
                       WHERE p.track_id=? AND CAST(t.evaluation_policy_version AS INTEGER)=p.policy_version""",
                    (track_id,),
                ).fetchone()
                if not row:
                    row = connection.execute(
                        "SELECT * FROM track_evaluation_policies WHERE track_id=? ORDER BY policy_version DESC LIMIT 1",
                        (track_id,),
                    ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM track_evaluation_policies WHERE track_id=? AND policy_version=?",
                    (track_id, int(version)),
                ).fetchone()
        return self._decode_evaluation_policy(row) if row else None

    def list_track_evaluation_policies(self, track_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM track_evaluation_policies WHERE track_id=? ORDER BY policy_version DESC",
                (track_id,),
            ).fetchall()
        return [self._decode_evaluation_policy(row) for row in rows]

    def save_track_evaluation_policy(
        self, track_id: str, policy: dict[str, Any], *, origin: str, now: str,
    ) -> tuple[dict[str, Any], bool]:
        policy_fingerprint = evaluation_fingerprint(policy)
        with self.transaction() as connection:
            track = connection.execute(
                "SELECT id FROM career_tracks WHERE id=?", (track_id,),
            ).fetchone()
            if not track:
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            existing = connection.execute(
                "SELECT * FROM track_evaluation_policies WHERE track_id=? AND fingerprint=?",
                (track_id, policy_fingerprint),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE career_tracks SET evaluation_policy_version=?,updated_at=? WHERE id=?",
                    (str(existing["policy_version"]), now, track_id),
                )
                return self._decode_evaluation_policy(existing), True
            version = int(connection.execute(
                "SELECT COALESCE(MAX(policy_version),0)+1 FROM track_evaluation_policies WHERE track_id=?",
                (track_id,),
            ).fetchone()[0])
            policy_id = _id("evaluation_policy")
            connection.execute(
                """INSERT INTO track_evaluation_policies(
                       id,track_id,schema_version,policy_version,fingerprint,policy_json,origin,created_at
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    policy_id, track_id, policy["schemaVersion"], version,
                    policy_fingerprint, _json(policy), origin, now,
                ),
            )
            connection.execute(
                "UPDATE career_tracks SET evaluation_policy_version=?,updated_at=? WHERE id=?",
                (str(version), now, track_id),
            )
            row = connection.execute(
                "SELECT * FROM track_evaluation_policies WHERE id=?", (policy_id,),
            ).fetchone()
        return self._decode_evaluation_policy(row), False

    def resolve_evaluation_job_id(self, job_id: str) -> str | None:
        with self.read_connection() as connection:
            current = job_id
            seen: set[str] = set()
            while current and current not in seen:
                seen.add(current)
                row = connection.execute(
                    "SELECT id,merged_into_job_id,deleted_at FROM canonical_jobs WHERE id=?",
                    (current,),
                ).fetchone()
                if not row or row["deleted_at"] is not None:
                    return None
                if not row["merged_into_job_id"]:
                    return str(row["id"])
                current = str(row["merged_into_job_id"])
        return None

    @staticmethod
    def _projection_fallback(job: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "company", "role_title", "seniority", "location_city", "location_country",
            "work_mode", "contract_type", "salary_min", "salary_max", "salary_currency",
            "salary_period", "salary_tax_type", "salary_is_known", "requirements_json",
        )
        return {key: job.get(key) for key in fields}

    def evaluation_context(self, job_id: str, track_id: str) -> dict[str, Any]:
        resolved_job_id = self.resolve_evaluation_job_id(job_id)
        if not resolved_job_id:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        with self.read_connection() as connection:
            job_row = connection.execute(
                """SELECT * FROM canonical_jobs
                   WHERE id=? AND deleted_at IS NULL AND merged_into_job_id IS NULL""",
                (resolved_job_id,),
            ).fetchone()
            track_row = connection.execute(
                "SELECT * FROM career_tracks WHERE id=?", (track_id,),
            ).fetchone()
            profile_row = connection.execute(
                "SELECT * FROM career_profile WHERE id='default'",
            ).fetchone()
            if not job_row:
                raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
            if not track_row:
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            if not profile_row:
                raise JobhuntError("Career Profile is unavailable", status=500, code="career_profile_missing")
            job = dict(job_row)
            track = self._decode_track(track_row)
            profile = self._profile_snapshot(connection)
            revision = connection.execute(
                "SELECT changed_at FROM career_profile_revisions WHERE revision=?",
                (profile_row["revision"],),
            ).fetchone()
            projection_row = connection.execute(
                """SELECT * FROM canonical_job_projections WHERE job_id=?
                   ORDER BY projection_version DESC LIMIT 1""",
                (resolved_job_id,),
            ).fetchone()
            projection = None
            selected_ids: list[str] = []
            if projection_row:
                projection = dict(projection_row)
                selected_ids = _loads(projection["selected_fact_ids_json"], [])
                projection["selected_fact_ids"] = selected_ids
                projection["applied_override_ids"] = _loads(
                    projection["applied_override_ids_json"], [],
                )
                projection["snapshot"] = _loads(projection["snapshot_json"], {})
                projection_fingerprint = str(projection["snapshot_fingerprint"])
                conditions = []
                parameters: list[Any] = []
                if selected_ids:
                    placeholders = ",".join("?" for _ in selected_ids)
                    conditions.append(f"f.id IN ({placeholders})")
                    parameters.extend(selected_ids)
                conditions.append(
                    "(f.capture_id=? AND f.fact_type IN "
                    "('skill','tool','language','experience','work_model','contract_type',"
                    "'schedule','shift_work','employment_fraction','country','location_text',"
                    "'salary_min','salary_max','salary_exact','salary_currency','salary_period','salary_tax_type'))"
                )
                parameters.append(projection["capture_id"])
                rows = connection.execute(
                    self._fact_query(
                        "(" + " OR ".join(conditions) + ") "
                        "AND f.validation_state='valid' "
                        "AND r.status IN ('completed','completed_with_warnings')"
                    ),
                    parameters,
                ).fetchall()
                facts = [self._decode_fact(row) for row in rows]
            else:
                projection_fingerprint = evaluation_fingerprint({
                    "schemaVersion": "canonical-job-row@1",
                    "job": self._projection_fallback(job),
                })
                facts = []
            pointer = track.get("evaluation_policy_version")
            policy_row = connection.execute(
                """SELECT * FROM track_evaluation_policies
                   WHERE track_id=? AND policy_version=CAST(? AS INTEGER)""",
                (track_id, pointer),
            ).fetchone()
            if not policy_row:
                policy_row = connection.execute(
                    "SELECT * FROM track_evaluation_policies WHERE track_id=? ORDER BY policy_version DESC LIMIT 1",
                    (track_id,),
                ).fetchone()
            if not policy_row:
                raise JobhuntError(
                    "Track Evaluation Policy is unavailable", status=500,
                    code="evaluation_policy_missing",
                )
            policy_record = self._decode_evaluation_policy(policy_row)
        context_value = track_context(track)
        context_fingerprint = evaluation_fingerprint(context_value)
        current_input = make_evaluation_input_fingerprint(
            profile_fingerprint=str(profile_row["fingerprint"]),
            projection_fingerprint=projection_fingerprint,
            policy_fingerprint=policy_record["fingerprint"],
            track_context_fingerprint=context_fingerprint,
        )
        return {
            "requested_job_id": job_id,
            "job": job,
            "track": track,
            "profile": profile,
            "profile_revision": int(profile_row["revision"]),
            "profile_fingerprint": str(profile_row["fingerprint"]),
            "profile_changed_at": revision["changed_at"] if revision else profile_row["updated_at"],
            "projection": projection,
            "projection_fingerprint": projection_fingerprint,
            "facts": facts,
            "policy_record": policy_record,
            "policy": policy_record["policy"],
            "track_context": context_value,
            "track_context_fingerprint": context_fingerprint,
            "input_fingerprint": current_input,
        }

    def evaluation_basis(
        self, job_id: str, track_id: str, *, explicit: bool = False,
    ) -> dict[str, Any]:
        resolved_job_id = self.resolve_evaluation_job_id(job_id)
        if not resolved_job_id:
            raise JobhuntError("Job not found", status=404, code="jobhunt_job_not_found")
        sources: list[dict[str, Any]] = []
        with self.read_connection() as connection:
            assignment = connection.execute(
                "SELECT origin,note FROM track_job_assignments WHERE job_id=? AND track_id=? AND active=1",
                (resolved_job_id, track_id),
            ).fetchone()
            if assignment:
                sources.append({"type": "track_assignment", "origin": assignment["origin"]})
            listing_rows = connection.execute(
                """SELECT DISTINCT l.id FROM source_listings l
                   JOIN source_listing_tracks x ON x.listing_id=l.id
                   WHERE l.canonical_job_id=? AND x.track_id=? ORDER BY l.id""",
                (resolved_job_id, track_id),
            ).fetchall()
            if listing_rows:
                sources.append({
                    "type": "source_listing_track", "listingIds": [row["id"] for row in listing_rows],
                })
            profile_rows = connection.execute(
                """SELECT DISTINCT l.id,p.id AS profile_id FROM source_listings l
                   JOIN source_listing_search_profiles x ON x.listing_id=l.id
                   JOIN track_search_profiles p ON p.id=x.search_profile_id
                   WHERE l.canonical_job_id=? AND p.track_id=? ORDER BY l.id,p.id""",
                (resolved_job_id, track_id),
            ).fetchall()
            if profile_rows:
                sources.append({
                    "type": "search_profile_discovery",
                    "listingIds": sorted({row["id"] for row in profile_rows}),
                    "searchProfileIds": sorted({row["profile_id"] for row in profile_rows}),
                })
            current = connection.execute(
                "SELECT evaluation_basis_json FROM evaluation_current WHERE job_id=? AND track_id=?",
                (resolved_job_id, track_id),
            ).fetchone()
            prior = _loads(current["evaluation_basis_json"], {}) if current else {}
            if any(item.get("type") == "explicit_request" for item in prior.get("sources") or []):
                sources.append({"type": "explicit_request", "persisted": True})
        if explicit and not any(item.get("type") == "explicit_request" for item in sources):
            sources.append({"type": "explicit_request"})
        return {
            "requestedJobId": job_id,
            "resolvedJobId": resolved_job_id,
            "trackId": track_id,
            "sources": sources,
        }

    def eligible_evaluation_pairs(
        self, *, scope: str = "profile", job_id: str | None = None,
        track_id: str | None = None, after: str | None = None,
        limit: int = 50, automatic: bool = True,
    ) -> list[dict[str, Any]]:
        if job_id:
            job_id = self.resolve_evaluation_job_id(job_id)
            if not job_id:
                return []
        pairs: set[tuple[str, str]] = set()
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT a.job_id,a.track_id FROM track_job_assignments a
                   JOIN canonical_jobs j ON j.id=a.job_id
                   WHERE a.active=1 AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                   UNION
                   SELECT l.canonical_job_id,x.track_id FROM source_listings l
                   JOIN source_listing_tracks x ON x.listing_id=l.id
                   JOIN canonical_jobs j ON j.id=l.canonical_job_id
                   WHERE l.canonical_job_id IS NOT NULL AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                   UNION
                   SELECT l.canonical_job_id,p.track_id FROM source_listings l
                   JOIN source_listing_search_profiles x ON x.listing_id=l.id
                   JOIN track_search_profiles p ON p.id=x.search_profile_id
                   JOIN canonical_jobs j ON j.id=l.canonical_job_id
                   WHERE l.canonical_job_id IS NOT NULL AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL"""
            ).fetchall()
            pairs.update((str(row[0]), str(row[1])) for row in rows)
            current_rows = connection.execute(
                "SELECT job_id,track_id,evaluation_basis_json FROM evaluation_current",
            ).fetchall()
            for row in current_rows:
                basis = _loads(row["evaluation_basis_json"], {})
                if any(item.get("type") == "explicit_request" for item in basis.get("sources") or []):
                    pairs.add((str(row["job_id"]), str(row["track_id"])))
            statuses = {
                str(row["id"]): str(row["status"])
                for row in connection.execute("SELECT id,status FROM career_tracks")
            }
        selected = []
        for pair_job, pair_track in sorted(pairs):
            if job_id and pair_job != job_id:
                continue
            if track_id and pair_track != track_id:
                continue
            if scope == "pair" and (pair_job != job_id or pair_track != track_id):
                continue
            if automatic and statuses.get(pair_track) not in {"active", "exploring"}:
                continue
            cursor = f"{pair_job}|{pair_track}"
            if after and cursor <= after:
                continue
            basis = self.evaluation_basis(pair_job, pair_track)
            if not basis["sources"]:
                continue
            selected.append({"job_id": pair_job, "track_id": pair_track, "cursor": cursor, "basis": basis})
            if len(selected) >= max(1, min(200, int(limit))):
                break
        return selected

    def prune_ineligible_evaluation_current(self, job_ids: Iterable[str]) -> int:
        """Remove only current pointers for pairs that lost every eligibility basis."""
        identifiers = sorted({str(item) for item in job_ids if item})
        if not identifiers:
            return 0
        placeholders = ",".join("?" for _ in identifiers)
        removed = 0
        with self.transaction() as connection:
            rows = connection.execute(
                f"SELECT job_id,track_id,evaluation_basis_json FROM evaluation_current WHERE job_id IN ({placeholders})",
                identifiers,
            ).fetchall()
            for row in rows:
                basis = _loads(row["evaluation_basis_json"], {})
                if any(
                    item.get("type") == "explicit_request"
                    for item in basis.get("sources") or []
                ):
                    continue
                eligible = connection.execute(
                    """SELECT EXISTS(
                           SELECT 1 FROM track_job_assignments a
                           WHERE a.job_id=? AND a.track_id=? AND a.active=1
                       ) OR EXISTS(
                           SELECT 1 FROM source_listings l
                           JOIN source_listing_tracks x ON x.listing_id=l.id
                           WHERE l.canonical_job_id=? AND x.track_id=?
                       ) OR EXISTS(
                           SELECT 1 FROM source_listings l
                           JOIN source_listing_search_profiles x ON x.listing_id=l.id
                           JOIN track_search_profiles p ON p.id=x.search_profile_id
                           WHERE l.canonical_job_id=? AND p.track_id=?
                       )""",
                    (
                        row["job_id"], row["track_id"],
                        row["job_id"], row["track_id"],
                        row["job_id"], row["track_id"],
                    ),
                ).fetchone()[0]
                if not eligible:
                    removed += connection.execute(
                        "DELETE FROM evaluation_current WHERE job_id=? AND track_id=?",
                        (row["job_id"], row["track_id"]),
                    ).rowcount
        return removed

    @staticmethod
    def _decode_evaluation_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["evaluation_basis"] = _loads(result.pop("evaluation_basis_json", "{}"), {})
        return result

    def save_evaluation(
        self, context: dict[str, Any], result: dict[str, Any], *, basis: dict[str, Any], now: str,
    ) -> tuple[dict[str, Any], bool]:
        job_id = context["job"]["id"]
        track_id = context["track"]["id"]
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT * FROM evaluations
                   WHERE job_id=? AND track_id=? AND input_fingerprint=? AND status='completed'""",
                (job_id, track_id, context["input_fingerprint"]),
            ).fetchone()
            if existing:
                connection.execute(
                    """INSERT INTO evaluation_current(
                           job_id,track_id,evaluation_id,evaluation_basis_json,updated_at
                       ) VALUES(?,?,?,?,?)
                       ON CONFLICT(job_id,track_id) DO UPDATE SET
                           evaluation_id=excluded.evaluation_id,
                           evaluation_basis_json=excluded.evaluation_basis_json,
                           updated_at=excluded.updated_at""",
                    (job_id, track_id, existing["id"], _json(basis), now),
                )
                return self._decode_evaluation_row(existing), True
            evaluation_id = _id("evaluation")
            projection = context.get("projection") or {}
            policy = context["policy_record"]
            counts = result["counts"]
            connection.execute(
                """INSERT INTO evaluations(
                       id,job_id,track_id,profile_revision,profile_fingerprint,
                       projection_id,projection_version,projection_fingerprint,
                       policy_id,policy_version,policy_fingerprint,track_context_fingerprint,
                       evaluator_version,evaluation_schema_version,input_fingerprint,status,
                       evaluation_basis_json,blocker_count,gap_count,unknown_count,
                       required_gap_count,supported_required_count,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'building',?,?,?,?,?,?,?)""",
                (
                    evaluation_id, job_id, track_id, context["profile_revision"],
                    context["profile_fingerprint"], projection.get("id"),
                    int(projection.get("projection_version") or 0), context["projection_fingerprint"],
                    policy["id"], policy["policy_version"], policy["fingerprint"],
                    context["track_context_fingerprint"], EVALUATOR_VERSION,
                    EVALUATION_SCHEMA_VERSION, context["input_fingerprint"], _json(basis),
                    counts["blocker_count"], counts["gap_count"], counts["unknown_count"],
                    counts["required_gap_count"], counts["supported_required_count"], now,
                ),
            )
            for item in result["dimensions"]:
                connection.execute(
                    """INSERT INTO evaluation_dimensions(
                           evaluation_id,dimension,state,importance,finding_count,
                           explanation_code,display_params_json
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        evaluation_id, item["dimension"], item["state"], item["importance"],
                        item["finding_count"], item["explanation_code"], _json(item["display_params"]),
                    ),
                )
            for item in result["findings"]:
                connection.execute(
                    """INSERT INTO evaluation_findings(
                           id,evaluation_id,dimension,finding_type,status,importance,
                           requirement_class,concept_key,job_fact_ids_json,job_evidence_json,
                           profile_evidence_json,policy_evidence_json,explanation_code,
                           display_params_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _id("evaluation_finding"), evaluation_id, item["dimension"],
                        item["finding_type"], item["status"], item["importance"],
                        item["requirement_class"], item.get("concept_key"),
                        _json(item["job_fact_ids"]), _json(item["job_evidence"]),
                        _json(item["profile_evidence"]), _json(item["policy_evidence"]),
                        item["explanation_code"], _json(item["display_params"]), now,
                    ),
                )
            connection.execute(
                "UPDATE evaluations SET status='completed',completed_at=? WHERE id=?",
                (now, evaluation_id),
            )
            connection.execute(
                """INSERT INTO evaluation_current(
                       job_id,track_id,evaluation_id,evaluation_basis_json,updated_at
                   ) VALUES(?,?,?,?,?)
                   ON CONFLICT(job_id,track_id) DO UPDATE SET
                       evaluation_id=excluded.evaluation_id,
                       evaluation_basis_json=excluded.evaluation_basis_json,
                       updated_at=excluded.updated_at""",
                (job_id, track_id, evaluation_id, _json(basis), now),
            )
            saved = connection.execute(
                "SELECT * FROM evaluations WHERE id=?", (evaluation_id,),
            ).fetchone()
        return self._decode_evaluation_row(saved), False

    @staticmethod
    def _decode_evaluation_dimension(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["display_params"] = _loads(result.pop("display_params_json", "{}"), {})
        return result

    @staticmethod
    def _decode_evaluation_finding(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for column, fallback in (
            ("job_fact_ids_json", []), ("job_evidence_json", []),
            ("profile_evidence_json", []), ("policy_evidence_json", {}),
            ("display_params_json", {}),
        ):
            result[column.removesuffix("_json")] = _loads(result.pop(column, None), fallback)
        return result

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT e.*,j.company,j.role_title,t.name AS track_name,
                          CASE WHEN c.evaluation_id=e.id THEN 1 ELSE 0 END AS is_pointer
                   FROM evaluations e
                   JOIN canonical_jobs j ON j.id=e.job_id
                   JOIN career_tracks t ON t.id=e.track_id
                   LEFT JOIN evaluation_current c ON c.job_id=e.job_id AND c.track_id=e.track_id
                   WHERE e.id=?""",
                (evaluation_id,),
            ).fetchone()
            if not row:
                return None
            result = self._decode_evaluation_row(row)
            result["dimensions"] = [
                self._decode_evaluation_dimension(item) for item in connection.execute(
                    "SELECT * FROM evaluation_dimensions WHERE evaluation_id=? ORDER BY rowid",
                    (evaluation_id,),
                )
            ]
            result["findings"] = [
                self._decode_evaluation_finding(item) for item in connection.execute(
                    "SELECT * FROM evaluation_findings WHERE evaluation_id=? ORDER BY rowid",
                    (evaluation_id,),
                )
            ]
        return result

    def list_evaluation_rows(
        self, *, job_id: str | None = None, track_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if job_id:
            resolved = self.resolve_evaluation_job_id(job_id)
            if not resolved:
                return []
            clauses.append("e.job_id=?")
            parameters.append(resolved)
        if track_id:
            clauses.append("e.track_id=?")
            parameters.append(track_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT e.*,j.company,j.role_title,t.name AS track_name,
                           CASE WHEN c.evaluation_id=e.id THEN 1 ELSE 0 END AS is_pointer
                    FROM evaluations e
                    JOIN canonical_jobs j ON j.id=e.job_id
                    JOIN career_tracks t ON t.id=e.track_id
                    LEFT JOIN evaluation_current c ON c.job_id=e.job_id AND c.track_id=e.track_id
                    {where} ORDER BY e.created_at DESC,e.id""",
                parameters,
            ).fetchall()
        return [self._decode_evaluation_row(row) for row in rows]

    def current_evaluation_rows_for_job(self, job_id: str) -> list[dict[str, Any]]:
        resolved = self.resolve_evaluation_job_id(job_id)
        if not resolved:
            return []
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT e.*,j.company,j.role_title,t.name AS track_name,t.status AS track_status,
                          1 AS is_pointer
                   FROM evaluation_current c
                   JOIN evaluations e ON e.id=c.evaluation_id
                   JOIN canonical_jobs j ON j.id=e.job_id
                   JOIN career_tracks t ON t.id=e.track_id
                   WHERE c.job_id=? ORDER BY t.name COLLATE NOCASE,t.id""",
                (resolved,),
            ).fetchall()
        return [self._decode_evaluation_row(row) for row in rows]

    def current_evaluation_rows_for_track(self, track_id: str) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """SELECT e.*,j.company,j.role_title,t.name AS track_name,t.status AS track_status,
                          1 AS is_pointer
                   FROM evaluation_current c
                   JOIN evaluations e ON e.id=c.evaluation_id
                   JOIN canonical_jobs j ON j.id=e.job_id
                   JOIN career_tracks t ON t.id=e.track_id
                   WHERE c.track_id=? AND j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                   ORDER BY e.created_at DESC,e.id""",
                (track_id,),
            ).fetchall()
        return [self._decode_evaluation_row(row) for row in rows]

    @staticmethod
    def _decode_profile_row(kind: str, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for column in PROFILE_COLLECTIONS[kind]["json"]:
            result[column] = _loads(result.get(column), [] if column == "domains_json" else None)
        return result

    def _profile_snapshot(self, connection: sqlite3.Connection) -> dict[str, Any]:
        profile = connection.execute(
            "SELECT current_role_title,headline,professional_summary FROM career_profile WHERE id='default'"
        ).fetchone()
        result: dict[str, Any] = {
            "profile": dict(profile) if profile else {
                "current_role_title": None, "headline": None, "professional_summary": None,
            }
        }
        for kind, definition in PROFILE_COLLECTIONS.items():
            rows = connection.execute(
                f"SELECT * FROM {definition['table']} ORDER BY created_at,id"
            ).fetchall()
            result[kind] = [self._decode_profile_row(kind, row) for row in rows]
            for item in result[kind]:
                item.pop("created_at", None)
                item.pop("updated_at", None)
        return result

    @staticmethod
    def _snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
        encoded = _json(snapshot).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _ensure_profile(self, connection: sqlite3.Connection, now: str) -> None:
        existing = connection.execute("SELECT 1 FROM career_profile WHERE id='default'").fetchone()
        if existing:
            return
        empty_snapshot = {
            "profile": {"current_role_title": None, "headline": None, "professional_summary": None},
            **{kind: [] for kind in PROFILE_COLLECTIONS},
        }
        fingerprint = self._snapshot_fingerprint(empty_snapshot)
        connection.execute(
            """INSERT INTO career_profile(
                   id,current_role_title,headline,professional_summary,revision,fingerprint,created_at,updated_at
               ) VALUES('default',NULL,NULL,NULL,0,?,?,?)""",
            (fingerprint, now, now),
        )
        connection.execute(
            "INSERT OR IGNORE INTO career_profile_revisions(revision,fingerprint,snapshot_json,changed_at) VALUES(0,?,?,?)",
            (fingerprint, _json(empty_snapshot), now),
        )

    def _record_profile_revision(self, connection: sqlite3.Connection, now: str) -> dict[str, Any]:
        snapshot = self._profile_snapshot(connection)
        fingerprint = self._snapshot_fingerprint(snapshot)
        current = connection.execute(
            "SELECT revision,fingerprint FROM career_profile WHERE id='default'"
        ).fetchone()
        if current and current["fingerprint"] == fingerprint:
            return {"revision": int(current["revision"]), "fingerprint": fingerprint}
        revision = int(current["revision"] if current else 0) + 1
        connection.execute(
            "UPDATE career_profile SET revision=?,fingerprint=?,updated_at=? WHERE id='default'",
            (revision, fingerprint, now),
        )
        connection.execute(
            "INSERT INTO career_profile_revisions(revision,fingerprint,snapshot_json,changed_at) VALUES(?,?,?,?)",
            (revision, fingerprint, _json(snapshot), now),
        )
        return {"revision": revision, "fingerprint": fingerprint}

    def get_profile(self) -> dict[str, Any]:
        with self.read_connection() as connection:
            profile = connection.execute("SELECT * FROM career_profile WHERE id='default'").fetchone()
            if not profile:
                raise JobhuntError("Career Profile is unavailable", status=500, code="career_profile_missing")
            result = dict(profile)
            for kind, definition in PROFILE_COLLECTIONS.items():
                rows = connection.execute(
                    f"SELECT * FROM {definition['table']} ORDER BY created_at DESC,id"
                ).fetchall()
                result[kind] = [self._decode_profile_row(kind, row) for row in rows]
        return result

    def update_profile(self, changes: dict[str, Any], *, now: str) -> dict[str, Any]:
        allowed = {"current_role_title", "headline", "professional_summary"}
        if set(changes) - allowed:
            raise ValueError("Unsupported career profile field")
        with self.transaction() as connection:
            self._ensure_profile(connection, now)
            if changes:
                assignments = ",".join(f"{column}=?" for column in changes)
                connection.execute(
                    f"UPDATE career_profile SET {assignments},updated_at=? WHERE id='default'",
                    (*changes.values(), now),
                )
            self._record_profile_revision(connection, now)
        return self.get_profile()

    def save_profile_record(
        self, kind: str, values: dict[str, Any], *, record_id: str | None = None, now: str
    ) -> str:
        definition = PROFILE_COLLECTIONS.get(kind)
        if not definition:
            raise ValueError("Unsupported Career Profile collection")
        columns = definition["columns"]
        if set(values) - set(columns):
            raise ValueError("Unsupported Career Profile record field")
        identifier = record_id or _id(definition["prefix"])
        encoded = {
            key: (_json(value) if key in definition["json"] else value)
            for key, value in values.items()
        }
        with self.transaction() as connection:
            current = connection.execute(
                f"SELECT * FROM {definition['table']} WHERE id=?", (identifier,)
            ).fetchone()
            if record_id and not current:
                raise JobhuntError("Career Profile record not found", status=404, code="profile_record_not_found")
            if current:
                assignments = ",".join(f"{column}=?" for column in encoded)
                timestamp_sql = "" if definition.get("created_only") else ",updated_at=?"
                parameters = [*encoded.values()]
                if not definition.get("created_only"):
                    parameters.append(now)
                parameters.append(identifier)
                connection.execute(
                    f"UPDATE {definition['table']} SET {assignments}{timestamp_sql} WHERE id=?",
                    parameters,
                )
            else:
                insert_columns = ["id", *encoded.keys(), "created_at"]
                insert_values = [identifier, *encoded.values(), now]
                if not definition.get("created_only"):
                    insert_columns.append("updated_at")
                    insert_values.append(now)
                placeholders = ",".join("?" for _ in insert_columns)
                connection.execute(
                    f"INSERT INTO {definition['table']}({','.join(insert_columns)}) VALUES({placeholders})",
                    insert_values,
                )
            self._record_profile_revision(connection, now)
        return identifier

    def delete_profile_record(self, kind: str, record_id: str, *, now: str) -> None:
        definition = PROFILE_COLLECTIONS.get(kind)
        if not definition:
            raise ValueError("Unsupported Career Profile collection")
        with self.transaction() as connection:
            cursor = connection.execute(
                f"DELETE FROM {definition['table']} WHERE id=?", (record_id,)
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Career Profile record not found", status=404, code="profile_record_not_found")
            self._record_profile_revision(connection, now)

    def profile_revision(self, revision: int) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT revision,fingerprint,snapshot_json,changed_at FROM career_profile_revisions WHERE revision=?",
                (revision,),
            ).fetchone()
        if not row:
            return None
        return {
            "revision": int(row["revision"]), "fingerprint": row["fingerprint"],
            "snapshot": _loads(row["snapshot_json"], {}), "changedAt": row["changed_at"],
        }

    def create_assessment_run(self, values: dict[str, Any]) -> str:
        run_id = values.get("id") or _id("assessment")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO assessment_runs(
                       id,instrument_id,instrument_version,definition_hash,status,scoring_version,
                       started_at,completed_at,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, values["instrument_id"], values["instrument_version"],
                    values["definition_hash"], "draft", values["scoring_version"],
                    values["started_at"], None, values["created_at"], values["updated_at"],
                ),
            )
        return run_id

    @staticmethod
    def _assessment_run_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        responses = connection.execute(
            "SELECT item_id,raw_answer_json,answered_at FROM assessment_responses WHERE run_id=? ORDER BY item_id",
            (row["id"],),
        ).fetchall()
        scores = connection.execute(
            """SELECT dimension,raw_score,normalized_score,interpretation_band,scoring_version
               FROM assessment_scores WHERE run_id=? ORDER BY dimension""",
            (row["id"],),
        ).fetchall()
        result["responses"] = {
            item["item_id"]: _loads(item["raw_answer_json"], None) for item in responses
        }
        result["response_timestamps"] = {
            item["item_id"]: item["answered_at"] for item in responses
        }
        result["scores"] = [dict(item) for item in scores]
        return result

    def get_assessment_run(self, run_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute("SELECT * FROM assessment_runs WHERE id=?", (run_id,)).fetchone()
            return self._assessment_run_payload(connection, row) if row else None

    def list_assessment_runs(self, instrument_id: str | None = None) -> list[dict[str, Any]]:
        clause = "WHERE instrument_id=?" if instrument_id else ""
        parameters = (instrument_id,) if instrument_id else ()
        with self.read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM assessment_runs {clause} ORDER BY created_at DESC,id DESC",
                parameters,
            ).fetchall()
            return [self._assessment_run_payload(connection, row) for row in rows]

    def save_assessment_responses(
        self, run_id: str, responses: dict[str, Any], *, answered_at: str
    ) -> None:
        with self.transaction() as connection:
            run = connection.execute("SELECT status FROM assessment_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise JobhuntError("Assessment run not found", status=404, code="assessment_run_not_found")
            if run["status"] != "draft":
                raise JobhuntError(
                    "Completed or abandoned assessment responses are immutable",
                    status=409, code="assessment_run_immutable",
                )
            for item_id, answer in responses.items():
                connection.execute(
                    """INSERT INTO assessment_responses(run_id,item_id,raw_answer_json,answered_at)
                       VALUES(?,?,?,?) ON CONFLICT(run_id,item_id) DO UPDATE SET
                       raw_answer_json=excluded.raw_answer_json,answered_at=excluded.answered_at""",
                    (run_id, item_id, _json(answer), answered_at),
                )
            connection.execute(
                "UPDATE assessment_runs SET updated_at=? WHERE id=?", (answered_at, run_id)
            )

    def complete_assessment_run(
        self, run_id: str, scores: list[dict[str, Any]], *, completed_at: str
    ) -> None:
        with self.transaction() as connection:
            run = connection.execute("SELECT status FROM assessment_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise JobhuntError("Assessment run not found", status=404, code="assessment_run_not_found")
            if run["status"] != "draft":
                raise JobhuntError("Assessment run is immutable", status=409, code="assessment_run_immutable")
            for score in scores:
                connection.execute(
                    """INSERT INTO assessment_scores(
                           run_id,dimension,raw_score,normalized_score,interpretation_band,scoring_version
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        run_id, score["dimension"], score["rawScore"], score.get("normalizedScore"),
                        score.get("interpretationBand"), score["scoringVersion"],
                    ),
                )
            connection.execute(
                """UPDATE assessment_runs SET status='completed',completed_at=?,updated_at=?
                   WHERE id=?""",
                (completed_at, completed_at, run_id),
            )

    def abandon_assessment_run(self, run_id: str, *, now: str) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE assessment_runs SET status='abandoned',updated_at=?
                   WHERE id=? AND status='draft'""",
                (now, run_id),
            )
            if cursor.rowcount != 1:
                raise JobhuntError("Assessment draft not found", status=404, code="assessment_draft_not_found")

    @staticmethod
    def _decode_economic_scenario(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": item["id"], "trackId": item["track_id"],
            "schemaVersion": item["schema_version"], "version": int(item["scenario_version"]),
            "fingerprint": item["fingerprint"], "name": item["name"],
            "currency": item["currency"], "assumptions": _loads(item["assumptions_json"], {}),
            "origin": item["origin"], "createdAt": item["created_at"],
        }

    def get_current_economic_scenario(self, track_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """SELECT s.* FROM economic_scenario_current c
                    JOIN economic_scenarios s ON s.id=c.scenario_id WHERE c.track_id=?""",
                (track_id,),
            ).fetchone()
        return self._decode_economic_scenario(row) if row else None

    def list_economic_scenarios(self, track_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE track_id=?" if track_id else ""
        parameters = (track_id,) if track_id else ()
        with self.read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM economic_scenarios {where} ORDER BY track_id,scenario_version DESC,id",
                parameters,
            ).fetchall()
        return [self._decode_economic_scenario(row) for row in rows]

    def save_economic_scenario(
        self, track_id: str, *, name: str, currency: str, assumptions: dict[str, Any], now: str
    ) -> dict[str, Any]:
        payload = {
            "schemaVersion": "economic-scenario@1", "trackId": track_id,
            "name": name, "currency": currency, "assumptions": assumptions,
        }
        fingerprint = "sha256:" + hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
        with self.transaction() as connection:
            if not connection.execute("SELECT 1 FROM career_tracks WHERE id=?", (track_id,)).fetchone():
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            existing = connection.execute(
                "SELECT * FROM economic_scenarios WHERE track_id=? AND fingerprint=?",
                (track_id, fingerprint),
            ).fetchone()
            if existing:
                scenario_id = existing["id"]
            else:
                version = int(connection.execute(
                    "SELECT COALESCE(MAX(scenario_version),0)+1 FROM economic_scenarios WHERE track_id=?",
                    (track_id,),
                ).fetchone()[0])
                scenario_id = _id("scenario")
                connection.execute(
                    """INSERT INTO economic_scenarios(
                           id,track_id,schema_version,scenario_version,fingerprint,name,currency,
                           assumptions_json,origin,created_at
                       ) VALUES(?,?,'economic-scenario@1',?,?,?,?,?,'manual_user',?)""",
                    (scenario_id, track_id, version, fingerprint, name, currency, _json(assumptions), now),
                )
            connection.execute(
                """INSERT INTO economic_scenario_current(track_id,scenario_id,updated_at)
                   VALUES(?,?,?) ON CONFLICT(track_id) DO UPDATE SET
                   scenario_id=excluded.scenario_id,updated_at=excluded.updated_at""",
                (track_id, scenario_id, now),
            )
            row = connection.execute("SELECT * FROM economic_scenarios WHERE id=?", (scenario_id,)).fetchone()
        return self._decode_economic_scenario(row)

    @staticmethod
    def _decode_track_proposal(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": item["id"], "proposalKey": item["proposal_key"],
            "methodVersion": item["method_version"], "roleFamily": item["role_family"],
            "proposedName": item["proposed_name"], "state": item["state"],
            "evidence": _loads(item["evidence_json"], {}),
            "evidenceFingerprint": item["evidence_fingerprint"],
            "acceptedTrackId": item.get("accepted_track_id"),
            "createdAt": item["created_at"], "updatedAt": item["updated_at"],
            "decidedAt": item.get("decided_at"),
        }

    def list_track_proposals(self) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM career_track_proposals ORDER BY updated_at DESC,id"
            ).fetchall()
        return [self._decode_track_proposal(row) for row in rows]

    def get_track_proposal(self, proposal_key: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM career_track_proposals WHERE proposal_key=?", (proposal_key,)
            ).fetchone()
        return self._decode_track_proposal(row) if row else None

    def save_track_proposal(
        self,
        *,
        proposal_key: str,
        role_family: str,
        proposed_name: str,
        state: str,
        evidence: dict[str, Any],
        evidence_fingerprint: str,
        accepted_track_id: str | None,
        now: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM career_track_proposals WHERE proposal_key=?", (proposal_key,)
            ).fetchone()
            if row and row["state"] == state and row["evidence_fingerprint"] == evidence_fingerprint and row["accepted_track_id"] == accepted_track_id:
                return self._decode_track_proposal(row)
            if row:
                proposal_id = row["id"]
                connection.execute(
                    """UPDATE career_track_proposals SET role_family=?,proposed_name=?,state=?,
                           evidence_json=?,evidence_fingerprint=?,accepted_track_id=?,updated_at=?,decided_at=?
                       WHERE id=?""",
                    (
                        role_family, proposed_name, state, _json(evidence), evidence_fingerprint,
                        accepted_track_id, now, now if state in {"accepted", "dismissed"} else None,
                        proposal_id,
                    ),
                )
            else:
                proposal_id = _id("proposal")
                connection.execute(
                    """INSERT INTO career_track_proposals(
                           id,proposal_key,method_version,role_family,proposed_name,state,
                           evidence_json,evidence_fingerprint,accepted_track_id,created_at,updated_at,decided_at
                       ) VALUES(?,?,'career-intelligence@1',?,?,?,?,?,?,?,?,?)""",
                    (
                        proposal_id, proposal_key, role_family, proposed_name, state,
                        _json(evidence), evidence_fingerprint, accepted_track_id, now, now,
                        now if state in {"accepted", "dismissed"} else None,
                    ),
                )
            connection.execute(
                """INSERT INTO career_track_proposal_events(id,proposal_id,event_type,payload_json,occurred_at)
                   VALUES(?,?,?,?,?)""",
                (_id("proposal_event"), proposal_id, state, _json({"evidenceFingerprint": evidence_fingerprint, "acceptedTrackId": accepted_track_id}), now),
            )
            saved = connection.execute("SELECT * FROM career_track_proposals WHERE id=?", (proposal_id,)).fetchone()
        return self._decode_track_proposal(saved)

    @staticmethod
    def _decode_experiment(row: sqlite3.Row | dict[str, Any], events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": item["id"], "trackId": item.get("track_id"), "proposalId": item.get("proposal_id"),
            "skillReference": item.get("skill_reference"), "hypothesis": item["hypothesis"],
            "title": item["title"], "taskDefinition": item["task_definition"],
            "taskDefinitionVersion": item["task_definition_version"], "templateId": item.get("template_id"),
            "status": item["status"], "plannedMinutes": item.get("planned_minutes"),
            "actualMinutes": item.get("actual_minutes"), "startedAt": item.get("started_at"),
            "completedAt": item.get("completed_at"), "abandonedAt": item.get("abandoned_at"),
            "interestRating": item.get("interest_rating"), "difficultyRating": item.get("difficulty_rating"),
            "frustrationRating": item.get("frustration_rating"),
            "confidenceChangeRating": item.get("confidence_change_rating"),
            "desireToContinue": None if item.get("desire_to_continue") is None else bool(item["desire_to_continue"]),
            "notes": item.get("notes") or "", "evidence": _loads(item.get("evidence_json"), {}),
            "createdAt": item["created_at"], "updatedAt": item["updated_at"],
            "events": events or [],
        }

    def _experiment_events(self, connection: sqlite3.Connection, experiment_id: str) -> list[dict[str, Any]]:
        return [{
            "id": row["id"], "type": row["event_type"],
            "payload": _loads(row["payload_json"], {}), "occurredAt": row["occurred_at"],
        } for row in connection.execute(
            "SELECT * FROM career_experiment_events WHERE experiment_id=? ORDER BY occurred_at,rowid",
            (experiment_id,),
        )]

    def list_experiments(
        self, *, status: str | None = None, track_id: str | None = None, proposal_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if status:
            clauses.append("status=?")
            parameters.append(status)
        if track_id:
            clauses.append("track_id=?")
            parameters.append(track_id)
        if proposal_id:
            clauses.append("proposal_id=?")
            parameters.append(proposal_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM career_experiments {where} ORDER BY updated_at DESC,id LIMIT 500",
                parameters,
            ).fetchall()
            return [
                self._decode_experiment(row, self._experiment_events(connection, row["id"]))
                for row in rows
            ]

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM career_experiments WHERE id=?", (experiment_id,)
            ).fetchone()
            if not row:
                return None
            return self._decode_experiment(row, self._experiment_events(connection, experiment_id))

    def create_experiment(self, values: dict[str, Any], *, now: str) -> dict[str, Any]:
        experiment_id = _id("experiment")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO career_experiments(
                       id,track_id,proposal_id,skill_reference,hypothesis,title,task_definition,
                       task_definition_version,template_id,status,planned_minutes,actual_minutes,
                       started_at,completed_at,abandoned_at,interest_rating,difficulty_rating,
                       frustration_rating,confidence_change_rating,desire_to_continue,notes,
                       evidence_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,'planned',?,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,?,?,?)""",
                (
                    experiment_id, values.get("track_id"), values.get("proposal_id"),
                    values.get("skill_reference"), values["hypothesis"], values["title"],
                    values["task_definition"], values["task_definition_version"], values.get("template_id"),
                    values.get("planned_minutes"), values.get("notes") or "",
                    _json(values.get("evidence") or {}), now, now,
                ),
            )
            connection.execute(
                "INSERT INTO career_experiment_events(id,experiment_id,event_type,payload_json,occurred_at) VALUES(?,?,\'created\',?,?)",
                (_id("experiment_event"), experiment_id, _json({"snapshot": values}), now),
            )
        return self.get_experiment(experiment_id) or {}

    def update_experiment(self, experiment_id: str, changes: dict[str, Any], *, now: str) -> dict[str, Any]:
        allowed = {
            "track_id", "proposal_id", "skill_reference", "hypothesis", "title",
            "task_definition", "task_definition_version", "planned_minutes", "notes", "evidence_json",
        }
        if set(changes) - allowed:
            raise ValueError("Unsupported Career Experiment field")
        with self.transaction() as connection:
            row = connection.execute("SELECT status FROM career_experiments WHERE id=?", (experiment_id,)).fetchone()
            if not row:
                raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
            if row["status"] == "completed":
                raise JobhuntError("Completed Career Experiment observations are immutable", status=409, code="experiment_immutable")
            encoded = dict(changes)
            if "evidence_json" in encoded:
                encoded["evidence_json"] = _json(encoded["evidence_json"])
            if encoded:
                assignments = ",".join(f"{key}=?" for key in encoded)
                connection.execute(
                    f"UPDATE career_experiments SET {assignments},updated_at=? WHERE id=?",
                    (*encoded.values(), now, experiment_id),
                )
            connection.execute(
                "INSERT INTO career_experiment_events(id,experiment_id,event_type,payload_json,occurred_at) VALUES(?,?,\'updated\',?,?)",
                (_id("experiment_event"), experiment_id, _json({"changes": changes}), now),
            )
        return self.get_experiment(experiment_id) or {}

    def transition_experiment(
        self, experiment_id: str, *, status: str, values: dict[str, Any], now: str
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            current = connection.execute("SELECT * FROM career_experiments WHERE id=?", (experiment_id,)).fetchone()
            if not current:
                raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
            if current["status"] == "completed":
                raise JobhuntError("Completed Career Experiment observations are immutable", status=409, code="experiment_immutable")
            updates = {**values, "status": status, "updated_at": now}
            if status == "active":
                updates["started_at"] = current["started_at"] or now
            elif status == "completed":
                updates["started_at"] = current["started_at"] or now
                updates["completed_at"] = now
            elif status == "abandoned":
                updates["abandoned_at"] = now
            if "desire_to_continue" in updates and updates["desire_to_continue"] is not None:
                updates["desire_to_continue"] = int(bool(updates["desire_to_continue"]))
            assignments = ",".join(f"{key}=?" for key in updates)
            connection.execute(
                f"UPDATE career_experiments SET {assignments} WHERE id=?",
                (*updates.values(), experiment_id),
            )
            snapshot = dict(connection.execute("SELECT * FROM career_experiments WHERE id=?", (experiment_id,)).fetchone())
            connection.execute(
                "INSERT INTO career_experiment_events(id,experiment_id,event_type,payload_json,occurred_at) VALUES(?,?,?,?,?)",
                (_id("experiment_event"), experiment_id, status if status != "active" else "started", _json({"snapshot": snapshot}), now),
            )
        return self.get_experiment(experiment_id) or {}

    def append_experiment_event(
        self, experiment_id: str, *, event_type: str, payload: dict[str, Any], now: str
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            if not connection.execute("SELECT 1 FROM career_experiments WHERE id=?", (experiment_id,)).fetchone():
                raise JobhuntError("Career Experiment not found", status=404, code="experiment_not_found")
            connection.execute(
                "INSERT INTO career_experiment_events(id,experiment_id,event_type,payload_json,occurred_at) VALUES(?,?,?,?,?)",
                (_id("experiment_event"), experiment_id, event_type, _json(payload), now),
            )
        return self.get_experiment(experiment_id) or {}

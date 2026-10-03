"""Local persistence, queue, and API-facing orchestration for Journal HTR."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import queue
import re
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path

from journal_htr_core import (
    JOB_STATUSES,
    LINE_STATUSES,
    PAGE_STATUSES,
    HtrValidationError,
    calculate_next_step,
    character_statistics,
    filter_review_lines,
    line_eligible_for_training,
    split_pages,
    validate_status,
)
from journal_htr_provider import (
    EscriptoriumProvider,
    FakeHtrProvider,
    HtrProviderError,
    provider_from_environment,
)


ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tiff",
    "application/pdf": ".pdf",
}
DATE_PRECISIONS = {"exact", "approximate", "unknown"}
LANGUAGES = {"pl", "en", "mixed", "unknown"}
MODEL_TYPES = {"recognition", "segmentation"}
SAFE_ID = re.compile(r"^[a-f0-9]{32}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_geometry(value: dict) -> dict:
    if not isinstance(value, dict):
        raise JournalHtrError("Geometry must be an object", code="invalid_geometry")
    result = dict(value)
    for key in ("mask", "baseline"):
        raw = value.get(key)
        if raw is None:
            continue
        if not isinstance(raw, list) or len(raw) > 4096:
            raise JournalHtrError(f"Invalid {key}", code="invalid_geometry")
        points = []
        for point in raw:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise JournalHtrError(f"Invalid {key} point", code="invalid_geometry")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0:
                raise JournalHtrError(f"Invalid {key} coordinates", code="invalid_geometry")
            points.append([round(x, 3), round(y, 3)])
        result[key] = points
    if len(result.get("mask") or []) < 3 and len(result.get("baseline") or []) < 2:
        raise JournalHtrError(
            "Geometry needs a polygon or baseline", code="invalid_geometry"
        )
    return result


def convex_hull(points: list[list[float]]) -> list[list[float]]:
    unique = sorted({(float(point[0]), float(point[1])) for point in points})
    if len(unique) <= 2:
        return [list(point) for point in unique]

    def cross(origin, first, second):
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return [list(point) for point in lower[:-1] + upper[:-1]]


def rotate_geometry(geometry: dict, width: int, height: int, angle: int) -> dict:
    normalized = angle % 360

    def rotate(point):
        x, y = float(point[0]), float(point[1])
        if normalized == 90:
            return [height - y, x]
        if normalized == 180:
            return [width - x, height - y]
        if normalized == 270:
            return [y, width - x]
        return [x, y]

    result = dict(geometry or {})
    for key in ("mask", "baseline"):
        if isinstance(result.get(key), list):
            result[key] = [rotate(point) for point in result[key]]
    coordinate_space = dict(result.get("coordinateSpace") or {})
    coordinate_space.update(
        {
            "width": height if normalized in {90, 270} else width,
            "height": width if normalized in {90, 270} else height,
            "variant": "working",
        }
    )
    result["coordinateSpace"] = coordinate_space
    return result


class JournalHtrError(ValueError):
    def __init__(self, message: str, *, status: int = 400, code: str = "htr_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict:
        return {"error": str(self), "code": self.code}


@dataclass
class UploadedPart:
    field_name: str
    filename: str
    content_type: str
    data: bytes


def parse_multipart(content_type: str, raw: bytes) -> tuple[dict[str, str], list[UploadedPart]]:
    if "multipart/form-data" not in str(content_type or "").lower():
        raise JournalHtrError(
            "Content-Type must be multipart/form-data", code="invalid_content_type"
        )
    message = BytesParser(policy=email_policy).parsebytes(
        (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("ascii", errors="ignore")
        + raw
    )
    fields: dict[str, str] = {}
    files: list[UploadedPart] = []
    if not message.is_multipart():
        raise JournalHtrError("Malformed multipart body", code="invalid_multipart")
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if filename:
            files.append(
                UploadedPart(
                    field_name=name,
                    filename=Path(filename).name,
                    content_type=str(part.get_content_type() or ""),
                    data=data,
                )
            )
        elif name:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = data.decode(charset, errors="replace")
    return fields, files


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


class JournalHtrStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS htr_projects (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        external_document_id TEXT,
                        transcription_id TEXT,
                        entry_date TEXT,
                        date_precision TEXT NOT NULL DEFAULT 'unknown',
                        language TEXT NOT NULL DEFAULT 'unknown',
                        notes TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS htr_pages (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES htr_projects(id) ON DELETE CASCADE,
                        external_page_id TEXT,
                        original_filename TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        original_path TEXT NOT NULL,
                        working_path TEXT NOT NULL,
                        thumbnail_path TEXT,
                        page_number INTEGER,
                        page_order INTEGER NOT NULL,
                        language TEXT NOT NULL DEFAULT 'unknown',
                        entry_date TEXT,
                        date_precision TEXT NOT NULL DEFAULT 'unknown',
                        notes TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'uploaded',
                        segmentation_issue INTEGER NOT NULL DEFAULT 0,
                        processing_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_htr_pages_project_order
                    ON htr_pages(project_id, page_order);
                    CREATE INDEX IF NOT EXISTS idx_htr_pages_status
                    ON htr_pages(status, project_id);

                    CREATE TABLE IF NOT EXISTS htr_lines (
                        id TEXT PRIMARY KEY,
                        page_id TEXT NOT NULL REFERENCES htr_pages(id) ON DELETE CASCADE,
                        external_line_id TEXT,
                        external_transcription_id TEXT,
                        line_order INTEGER NOT NULL,
                        geometry_json TEXT NOT NULL DEFAULT '{}',
                        line_image_reference TEXT,
                        model_id TEXT,
                        model_version TEXT,
                        predicted_text TEXT NOT NULL DEFAULT '',
                        confidence REAL,
                        corrected_text TEXT,
                        normalized_text TEXT,
                        review_status TEXT NOT NULL DEFAULT 'unreviewed',
                        use_for_training INTEGER NOT NULL DEFAULT 0,
                        language TEXT NOT NULL DEFAULT 'unknown',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        reviewed_at TEXT,
                        UNIQUE(page_id, external_line_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_htr_lines_review
                    ON htr_lines(review_status, confidence);
                    CREATE INDEX IF NOT EXISTS idx_htr_lines_training
                    ON htr_lines(use_for_training, review_status);

                    CREATE TABLE IF NOT EXISTS htr_line_revisions (
                        id TEXT PRIMARY KEY,
                        line_id TEXT NOT NULL REFERENCES htr_lines(id) ON DELETE CASCADE,
                        previous_text TEXT,
                        new_text TEXT,
                        previous_status TEXT,
                        new_status TEXT NOT NULL,
                        use_for_training INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_htr_revisions_line
                    ON htr_line_revisions(line_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS htr_datasets (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        ratios_json TEXT NOT NULL,
                        split_json TEXT NOT NULL,
                        line_count INTEGER NOT NULL,
                        character_count INTEGER NOT NULL,
                        fixed_test INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        UNIQUE(name, version)
                    );

                    CREATE TABLE IF NOT EXISTS htr_models (
                        id TEXT PRIMARY KEY,
                        external_model_id TEXT,
                        name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        type TEXT NOT NULL,
                        base_model_id TEXT,
                        training_dataset_version TEXT,
                        created_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        cer REAL,
                        wer REAL,
                        validation_cer REAL,
                        test_cer REAL,
                        test_wer REAL,
                        is_active INTEGER NOT NULL DEFAULT 0,
                        notes TEXT NOT NULL DEFAULT '',
                        artifact_path TEXT,
                        provider_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_htr_models_active
                    ON htr_models(type, is_active);

                    CREATE TABLE IF NOT EXISTS htr_jobs (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL DEFAULT 0,
                        stage TEXT NOT NULL DEFAULT 'queued',
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        safe_log_json TEXT NOT NULL DEFAULT '[]',
                        error TEXT,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        provider_task_id TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_htr_jobs_status
                    ON htr_jobs(status, created_at);
                    """
                )
                line_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(htr_lines)")
                }
                if "line_image_reference" not in line_columns:
                    connection.execute(
                        "ALTER TABLE htr_lines ADD COLUMN line_image_reference TEXT"
                    )
                job_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(htr_jobs)")
                }
                if "provider_task_id" not in job_columns:
                    connection.execute(
                        "ALTER TABLE htr_jobs ADD COLUMN provider_task_id TEXT"
                    )
            self._initialized = True

    @staticmethod
    def _json(value, fallback):
        try:
            return json.loads(value or "")
        except (TypeError, json.JSONDecodeError):
            return fallback

    @classmethod
    def project_dict(cls, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "externalDocumentId": row["external_document_id"],
            "transcriptionId": row["transcription_id"],
            "entryDate": row["entry_date"],
            "datePrecision": row["date_precision"],
            "language": row["language"],
            "notes": row["notes"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @classmethod
    def page_dict(cls, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "externalPageId": row["external_page_id"],
            "originalFilename": row["original_filename"],
            "mimeType": row["mime_type"],
            "pageNumber": row["page_number"],
            "pageOrder": row["page_order"],
            "language": row["language"],
            "entryDate": row["entry_date"],
            "datePrecision": row["date_precision"],
            "notes": row["notes"],
            "status": row["status"],
            "segmentationIssue": bool(row["segmentation_issue"]),
            "processing": cls._json(row["processing_json"], {}),
            "hasThumbnail": bool(row["thumbnail_path"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @classmethod
    def line_dict(cls, row: sqlite3.Row) -> dict:
        text = row["corrected_text"]
        return {
            "id": row["id"],
            "pageId": row["page_id"],
            "externalLineId": row["external_line_id"],
            "externalTranscriptionId": row["external_transcription_id"],
            "lineOrder": row["line_order"],
            "geometry": cls._json(row["geometry_json"], {}),
            "lineImageReference": row["line_image_reference"],
            "modelId": row["model_id"],
            "modelVersion": row["model_version"],
            "predictedText": row["predicted_text"],
            "confidence": row["confidence"],
            "correctedText": text,
            "displayText": text if text is not None else row["predicted_text"],
            "normalizedText": row["normalized_text"],
            "reviewStatus": row["review_status"],
            "useForTraining": bool(row["use_for_training"]),
            "language": row["language"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "reviewedAt": row["reviewed_at"],
        }

    @classmethod
    def model_dict(cls, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "externalModelId": row["external_model_id"],
            "name": row["name"],
            "version": row["version"],
            "type": row["type"],
            "baseModelId": row["base_model_id"],
            "trainingDatasetVersion": row["training_dataset_version"],
            "createdAt": row["created_at"],
            "status": row["status"],
            "cer": row["cer"],
            "wer": row["wer"],
            "validationCer": row["validation_cer"],
            "testCer": row["test_cer"],
            "testWer": row["test_wer"],
            "isActive": bool(row["is_active"]),
            "notes": row["notes"],
            "artifactPath": row["artifact_path"],
            "provider": cls._json(row["provider_json"], {}),
        }

    @classmethod
    def job_dict(cls, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "type": row["type"],
            "status": row["status"],
            "progress": row["progress"],
            "stage": row["stage"],
            "safeLog": cls._json(row["safe_log_json"], []),
            "error": row["error"],
            "createdAt": row["created_at"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "cancelRequested": bool(row["cancel_requested"]),
            "providerTaskId": row["provider_task_id"],
        }

    def create_project(self, payload: dict) -> dict:
        self.initialize()
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 160:
            raise JournalHtrError("Notebook name is required (max 160 characters)")
        date_precision = str(payload.get("datePrecision") or "unknown")
        language = str(payload.get("language") or "unknown")
        if date_precision not in DATE_PRECISIONS:
            raise JournalHtrError("Invalid date precision")
        if language not in LANGUAGES:
            raise JournalHtrError("Invalid language")
        project_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO htr_projects (
                    id, name, entry_date, date_precision, language, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name,
                    str(payload.get("entryDate") or "").strip() or None,
                    date_precision,
                    language,
                    str(payload.get("notes") or "")[:2000],
                    now,
                    now,
                ),
            )
        return self.get_project(project_id)

    def list_projects(self) -> list[dict]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM htr_projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self.project_dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM htr_projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not row:
            raise JournalHtrError("HTR project not found", status=404, code="not_found")
        return self.project_dict(row)

    def update_project_remote(
        self, project_id: str, external_document_id: str, transcription_id: str | None = None
    ):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE htr_projects
                SET external_document_id = ?, transcription_id = COALESCE(?, transcription_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (external_document_id, transcription_id, utc_now(), project_id),
            )

    def next_page_order(self, project_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(page_order), -1) + 1 FROM htr_pages WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return int(row[0])

    def create_page(self, payload: dict) -> dict:
        page_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO htr_pages (
                    id, project_id, original_filename, mime_type, original_path,
                    working_path, thumbnail_path, page_number, page_order, language,
                    entry_date, date_precision, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    payload["projectId"],
                    payload["originalFilename"],
                    payload["mimeType"],
                    payload["originalPath"],
                    payload["workingPath"],
                    payload.get("thumbnailPath"),
                    payload.get("pageNumber"),
                    payload["pageOrder"],
                    payload.get("language", "unknown"),
                    payload.get("entryDate"),
                    payload.get("datePrecision", "unknown"),
                    payload.get("notes", ""),
                    now,
                    now,
                ),
            )
        return self.get_page(page_id)

    def get_page(self, page_id: str, *, include_paths: bool = False) -> dict:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM htr_pages WHERE id = ?", (page_id,)
            ).fetchone()
        if not row:
            raise JournalHtrError("HTR page not found", status=404, code="not_found")
        result = self.page_dict(row)
        if include_paths:
            result.update(
                {
                    "originalPath": row["original_path"],
                    "workingPath": row["working_path"],
                    "thumbnailPath": row["thumbnail_path"],
                }
            )
        return result

    def list_pages(self, project_id: str | None = None) -> list[dict]:
        self.initialize()
        sql = (
            "SELECT p.*, pr.name AS project_name FROM htr_pages p "
            "JOIN htr_projects pr ON pr.id = p.project_id"
        )
        params: tuple = ()
        if project_id:
            sql += " WHERE p.project_id = ?"
            params = (project_id,)
        sql += " ORDER BY pr.updated_at DESC, p.page_order"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = self.page_dict(row)
            item["projectName"] = row["project_name"]
            result.append(item)
        return result

    def update_page(self, page_id: str, **changes):
        allowed = {
            "external_page_id",
            "status",
            "page_order",
            "segmentation_issue",
            "working_path",
            "thumbnail_path",
            "processing_json",
        }
        clean = {key: value for key, value in changes.items() if key in allowed}
        if not clean:
            return
        if "status" in clean:
            clean["status"] = validate_status(clean["status"], PAGE_STATUSES, "page status")
        clean["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE htr_pages SET {assignments} WHERE id = ?",
                (*clean.values(), page_id),
            )

    def delete_page(self, page_id: str) -> dict:
        page = self.get_page(page_id, include_paths=True)
        with self._connect() as connection:
            connection.execute("DELETE FROM htr_pages WHERE id = ?", (page_id,))
        return page

    def reorder_pages(self, page_ids: list[str]) -> list[dict]:
        if not page_ids:
            raise JournalHtrError("pageIds are required")
        pages = [self.get_page(page_id) for page_id in page_ids]
        if len({page["projectId"] for page in pages}) != 1:
            raise JournalHtrError("Pages must belong to one notebook")
        with self._connect() as connection:
            for order, page_id in enumerate(page_ids):
                connection.execute(
                    "UPDATE htr_pages SET page_order = ?, updated_at = ? WHERE id = ?",
                    (order, utc_now(), page_id),
                )
        return self.list_pages(pages[0]["projectId"])

    def upsert_lines(
        self,
        page_id: str,
        provider_lines: list[dict],
        *,
        model_id: str | None = None,
        model_version: str | None = None,
        replace: bool = False,
    ) -> list[dict]:
        now = utc_now()
        page = self.get_page(page_id)
        with self._connect() as connection:
            existing_rows = connection.execute(
                "SELECT external_line_id, geometry_json FROM htr_lines WHERE page_id = ?",
                (page_id,),
            ).fetchall()
            merged_source_ids = {
                str(source_id)
                for row in existing_rows
                for source_id in (
                    self._json(row["geometry_json"], {}).get("sourceExternalLineIds") or []
                )
            }
            incoming_ids = {
                str(item.get("externalLineId") or "").strip()
                for item in provider_lines
                if str(item.get("externalLineId") or "").strip()
            }
            if replace:
                connection.execute(
                    """
                    DELETE FROM htr_lines
                    WHERE page_id = ?
                      AND external_line_id NOT LIKE 'manual-%'
                      AND external_line_id NOT IN (
                        SELECT value FROM json_each(?)
                      )
                    """,
                    (page_id, json.dumps(sorted(incoming_ids))),
                )
            for item in provider_lines:
                external_id = str(item.get("externalLineId") or "").strip()
                if not external_id or external_id in merged_source_ids:
                    continue
                line_id = uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO htr_lines (
                        id, page_id, external_line_id, external_transcription_id,
                        line_order, geometry_json, line_image_reference, model_id, model_version,
                        predicted_text, confidence, language, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(page_id, external_line_id) DO UPDATE SET
                        external_transcription_id = excluded.external_transcription_id,
                        line_order = excluded.line_order,
                        geometry_json = excluded.geometry_json,
                        line_image_reference = excluded.line_image_reference,
                        model_id = excluded.model_id,
                        model_version = excluded.model_version,
                        predicted_text = excluded.predicted_text,
                        confidence = excluded.confidence,
                        updated_at = excluded.updated_at
                    """,
                    (
                        line_id,
                        page_id,
                        external_id,
                        item.get("externalTranscriptionId"),
                        int(item.get("lineOrder") or 0),
                        json.dumps(item.get("geometry") or {}),
                        f"/api/journal-htr/pages/{page_id}/file?variant=working",
                        model_id,
                        model_version,
                        str(item.get("predictedText") or ""),
                        item.get("confidence"),
                        page["language"],
                        now,
                        now,
                    ),
                )
        return self.list_lines(page_id=page_id)

    def update_line_geometry(self, line_id: str, geometry: dict) -> dict:
        current = self.get_line(line_id)
        normalized = normalize_geometry(geometry)
        normalized["manuallyEdited"] = True
        with self._connect() as connection:
            connection.execute(
                "UPDATE htr_lines SET geometry_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(normalized), utc_now(), line_id),
            )
            connection.execute(
                "UPDATE htr_pages SET segmentation_issue = 1, updated_at = ? WHERE id = ?",
                (utc_now(), current["pageId"]),
            )
        return self.get_line(line_id)

    def rotate_page_geometries(
        self, page_id: str, width: int, height: int, angle: int
    ) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, geometry_json FROM htr_lines WHERE page_id = ?",
                (page_id,),
            ).fetchall()
            now = utc_now()
            for row in rows:
                geometry = rotate_geometry(
                    self._json(row["geometry_json"], {}), width, height, angle
                )
                connection.execute(
                    "UPDATE htr_lines SET geometry_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(geometry), now, row["id"]),
                )

    def clear_page_lines(self, page_id: str) -> None:
        self.get_page(page_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM htr_lines WHERE page_id = ?", (page_id,))

    def merge_lines(self, line_id: str, other_line_id: str) -> dict:
        first = self.get_line(line_id)
        second = self.get_line(other_line_id)
        if first["pageId"] != second["pageId"] or first["id"] == second["id"]:
            raise JournalHtrError(
                "Lines must be different and belong to one page",
                code="invalid_line_merge",
            )
        ordered = sorted([first, second], key=lambda line: line["lineOrder"])
        masks = [
            point
            for line in ordered
            for point in (line["geometry"].get("mask") or line["geometry"].get("baseline") or [])
        ]
        hull = convex_hull(masks)
        if len(hull) < 3:
            raise JournalHtrError("Lines have no usable polygons", code="invalid_geometry")
        baselines = [
            point
            for line in ordered
            for point in (line["geometry"].get("baseline") or [])
        ]
        source_external_ids = []
        for line in ordered:
            inherited = line["geometry"].get("sourceExternalLineIds") or []
            if inherited:
                source_external_ids.extend(str(value) for value in inherited)
            elif line.get("externalLineId"):
                source_external_ids.append(str(line["externalLineId"]))
        source_external_ids = list(dict.fromkeys(source_external_ids))
        coordinate_space = next(
            (
                line["geometry"].get("coordinateSpace")
                for line in ordered
                if line["geometry"].get("coordinateSpace")
            ),
            {},
        )
        geometry = {
            "mask": hull,
            "baseline": sorted(baselines, key=lambda point: (point[0], point[1])),
            "coordinateSpace": coordinate_space,
            "manuallyEdited": True,
            "merged": True,
            "sourceLineIds": [line["id"] for line in ordered],
            "sourceExternalLineIds": source_external_ids,
        }
        merged_text = " ".join(
            str(line.get("displayText") or "").strip() for line in ordered
        ).strip()
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE htr_lines SET
                    external_line_id = ?,
                    external_transcription_id = NULL,
                    line_order = ?,
                    geometry_json = ?,
                    predicted_text = ?,
                    corrected_text = ?,
                    confidence = NULL,
                    review_status = 'unreviewed',
                    use_for_training = 0,
                    updated_at = ?,
                    reviewed_at = NULL
                WHERE id = ?
                """,
                (
                    f"manual-{line_id}",
                    min(first["lineOrder"], second["lineOrder"]),
                    json.dumps(geometry),
                    merged_text,
                    merged_text or None,
                    now,
                    line_id,
                ),
            )
            connection.execute(
                """
                UPDATE htr_lines SET review_status = 'excluded',
                    use_for_training = 0, updated_at = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (now, now, other_line_id),
            )
            connection.execute(
                "UPDATE htr_pages SET segmentation_issue = 1, updated_at = ? WHERE id = ?",
                (now, first["pageId"]),
            )
        return self.get_line(line_id)

    def list_lines(
        self,
        *,
        page_id: str | None = None,
        filters: dict | None = None,
    ) -> list[dict]:
        self.initialize()
        sql = (
            "SELECT l.*, p.project_id, p.original_filename, p.segmentation_issue, p.entry_date "
            "FROM htr_lines l JOIN htr_pages p ON p.id = l.page_id"
        )
        params: tuple = ()
        if page_id:
            sql += " WHERE l.page_id = ?"
            params = (page_id,)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        items = []
        for row in rows:
            item = self.line_dict(row)
            item["projectId"] = row["project_id"]
            item["pageFilename"] = row["original_filename"]
            item["segmentationIssue"] = bool(row["segmentation_issue"])
            item["entryDate"] = row["entry_date"]
            items.append(item)
        return filter_review_lines(items, filters)

    def get_line(self, line_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM htr_lines WHERE id = ?", (line_id,)
            ).fetchone()
        if not row:
            raise JournalHtrError("HTR line not found", status=404, code="not_found")
        return self.line_dict(row)

    def update_line(self, line_id: str, payload: dict) -> dict:
        current = self.get_line(line_id)
        status = validate_status(
            payload.get("reviewStatus", current["reviewStatus"]),
            LINE_STATUSES,
            "reviewStatus",
        )
        corrected_text = payload.get("correctedText", current["correctedText"])
        if corrected_text is not None:
            corrected_text = str(corrected_text)
            if len(corrected_text) > 10000:
                raise JournalHtrError("Line transcription is too long", status=413)
        default_training = line_eligible_for_training(
            status, corrected_text, current["predictedText"], True
        )
        use_for_training = bool(payload.get("useForTraining", default_training))
        if status in {"uncertain", "illegible", "excluded"} and "useForTraining" not in payload:
            use_for_training = False
        now = utc_now()
        reviewed_at = now if status != "unreviewed" else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO htr_line_revisions (
                    id, line_id, previous_text, new_text, previous_status,
                    new_status, use_for_training, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    line_id,
                    current["correctedText"],
                    corrected_text,
                    current["reviewStatus"],
                    status,
                    int(use_for_training),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE htr_lines SET corrected_text = ?, review_status = ?,
                    use_for_training = ?, updated_at = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (
                    corrected_text,
                    status,
                    int(use_for_training),
                    now,
                    reviewed_at,
                    line_id,
                ),
            )
            page_id = current["pageId"]
            remaining = connection.execute(
                """
                SELECT COUNT(*) FROM htr_lines
                WHERE page_id = ? AND review_status = 'unreviewed'
                """,
                (page_id,),
            ).fetchone()[0]
            total = connection.execute(
                "SELECT COUNT(*) FROM htr_lines WHERE page_id = ?", (page_id,)
            ).fetchone()[0]
            if total and not remaining:
                connection.execute(
                    "UPDATE htr_pages SET status = 'reviewed', updated_at = ? WHERE id = ?",
                    (now, page_id),
                )
        return self.get_line(line_id)

    def line_revisions(self, line_id: str) -> list[dict]:
        self.get_line(line_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM htr_line_revisions
                WHERE line_id = ? ORDER BY created_at DESC
                """,
                (line_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "previousText": row["previous_text"],
                "newText": row["new_text"],
                "previousStatus": row["previous_status"],
                "newStatus": row["new_status"],
                "useForTraining": bool(row["use_for_training"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def dataset_stats(self) -> dict:
        lines = self.list_lines()
        eligible = [
            line
            for line in lines
            if line_eligible_for_training(
                line["reviewStatus"],
                line["correctedText"],
                line["predictedText"],
                line["useForTraining"],
            )
        ]
        texts = [line["displayText"] for line in eligible]
        language_counts: dict[str, int] = {}
        for line in eligible:
            language_counts[line["language"]] = language_counts.get(line["language"], 0) + 1
        chars = character_statistics(texts)
        low_chars = [
            {"character": character, "count": count}
            for character, count in chars["polishCharacters"].items()
            if count < 10
        ]
        return {
            "approvedPages": len({line["pageId"] for line in eligible}),
            "lines": len(eligible),
            **chars,
            "languages": language_counts,
            "excluded": sum(line["reviewStatus"] == "excluded" for line in lines),
            "uncertain": sum(line["reviewStatus"] == "uncertain" for line in lines),
            "newLinesSinceTraining": len(eligible),
            "lowFrequencyWarnings": low_chars,
        }

    def create_dataset(self, payload: dict) -> dict:
        stats = self.dataset_stats()
        eligible = [
            line
            for line in self.list_lines()
            if line_eligible_for_training(
                line["reviewStatus"],
                line["correctedText"],
                line["predictedText"],
                line["useForTraining"],
            )
        ]
        if not eligible:
            raise JournalHtrError(
                "There are no approved training lines", code="empty_training_data"
            )
        ratios = payload.get("ratios") or {"train": 0.8, "validation": 0.1, "test": 0.1}
        name = str(payload.get("name") or "journal-ground-truth").strip()[:120]
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT * FROM htr_datasets WHERE name = ? ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
        fixed_test = []
        if previous:
            fixed_test = self._json(previous["split_json"], {}).get("test", [])
        split = split_pages(
            [line["pageId"] for line in eligible],
            train_ratio=float(ratios.get("train", 0.8)),
            validation_ratio=float(ratios.get("validation", 0.1)),
            test_ratio=float(ratios.get("test", 0.1)),
            fixed_test_pages=fixed_test,
        )
        version = int(previous["version"]) + 1 if previous else 1
        dataset_id = uuid.uuid4().hex
        created_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO htr_datasets (
                    id, name, version, ratios_json, split_json, line_count,
                    character_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    name,
                    version,
                    json.dumps(ratios),
                    json.dumps(split),
                    stats["lines"],
                    stats["characters"],
                    created_at,
                ),
            )
        return {
            "id": dataset_id,
            "name": name,
            "version": version,
            "ratios": ratios,
            "split": split,
            "lineCount": stats["lines"],
            "characterCount": stats["characters"],
            "createdAt": created_at,
        }

    def list_datasets(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM htr_datasets ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "version": row["version"],
                "ratios": self._json(row["ratios_json"], {}),
                "split": self._json(row["split_json"], {}),
                "lineCount": row["line_count"],
                "characterCount": row["character_count"],
                "fixedTest": bool(row["fixed_test"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def get_dataset(self, dataset_id: str) -> dict:
        match = next(
            (item for item in self.list_datasets() if item["id"] == dataset_id), None
        )
        if not match:
            raise JournalHtrError("Dataset not found", status=404, code="not_found")
        return match

    def upsert_provider_model(self, item: dict) -> dict:
        external_id = str(item.get("pk") or item.get("id") or "")
        if not external_id:
            raise JournalHtrError("Provider model has no id")
        job = str(item.get("job") or "").lower()
        model_type = "segmentation" if "segment" in job else "recognition"
        model_id = f"external-{external_id}"
        now = utc_now()
        version = str(item.get("version") or item.get("versions") or "provider")
        status = "training" if item.get("training") else "ready"
        with self._connect() as connection:
            has_active = connection.execute(
                "SELECT 1 FROM htr_models WHERE type = ? AND is_active = 1 LIMIT 1",
                (model_type,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO htr_models (
                    id, external_model_id, name, version, type, created_at,
                    status, provider_json, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name, version = excluded.version,
                    type = excluded.type, status = excluded.status,
                    provider_json = excluded.provider_json
                """,
                (
                    model_id,
                    external_id,
                    str(item.get("name") or external_id),
                    version,
                    model_type,
                    now,
                    status,
                    json.dumps(item),
                    int(not has_active and status == "ready"),
                ),
            )
        return self.get_model(model_id)

    def create_candidate_model(self, payload: dict, dataset: dict) -> dict:
        model_id = uuid.uuid4().hex
        now = utc_now()
        model_type = str(payload.get("type") or "recognition")
        if model_type not in MODEL_TYPES:
            raise JournalHtrError("Model type must be recognition or segmentation")
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM htr_models WHERE type = ?", (model_type,)
            ).fetchone()[0]
            version = f"v{count + 1}"
            connection.execute(
                """
                INSERT INTO htr_models (
                    id, name, version, type, base_model_id,
                    training_dataset_version, created_at, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'training', ?)
                """,
                (
                    model_id,
                    str(payload.get("name") or f"Journal HTR {version}")[:160],
                    version,
                    model_type,
                    payload.get("baseModelId"),
                    f"{dataset['name']}@{dataset['version']}",
                    now,
                    str(payload.get("description") or "")[:2000],
                ),
            )
        return self.get_model(model_id)

    def get_model(self, model_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM htr_models WHERE id = ?", (model_id,)
            ).fetchone()
        if not row:
            raise JournalHtrError("Model not found", status=404, code="not_found")
        return self.model_dict(row)

    def list_models(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM htr_models ORDER BY created_at DESC"
            ).fetchall()
        return [self.model_dict(row) for row in rows]

    def update_model(self, model_id: str, **changes) -> dict:
        allowed = {
            "external_model_id",
            "status",
            "cer",
            "wer",
            "validation_cer",
            "test_cer",
            "test_wer",
            "notes",
            "artifact_path",
            "provider_json",
        }
        clean = {key: value for key, value in changes.items() if key in allowed}
        if clean:
            assignments = ", ".join(f"{key} = ?" for key in clean)
            with self._connect() as connection:
                connection.execute(
                    f"UPDATE htr_models SET {assignments} WHERE id = ?",
                    (*clean.values(), model_id),
                )
        return self.get_model(model_id)

    def activate_model(self, model_id: str) -> dict:
        model = self.get_model(model_id)
        if model["status"] not in {"ready", "evaluated", "active"}:
            raise JournalHtrError(
                "Only a ready or evaluated model can be activated",
                code="model_not_ready",
            )
        with self._connect() as connection:
            connection.execute(
                "UPDATE htr_models SET is_active = 0 WHERE type = ?", (model["type"],)
            )
            connection.execute(
                "UPDATE htr_models SET is_active = 1, status = 'active' WHERE id = ?",
                (model_id,),
            )
        return self.get_model(model_id)

    def archive_model(self, model_id: str) -> dict:
        model = self.get_model(model_id)
        if model["isActive"]:
            raise JournalHtrError("Activate another model before archiving this one")
        if model["status"] in {"queued", "training"}:
            raise JournalHtrError(
                "Cancel the training before archiving this model",
                status=409,
                code="model_training",
            )
        return self.update_model(model_id, status="archived")

    def delete_model(self, model_id: str) -> dict:
        model = self.get_model(model_id)
        if model["isActive"]:
            raise JournalHtrError(
                "Activate another model before deleting this one",
                status=409,
                code="active_model",
            )
        with self._connect() as connection:
            jobs = connection.execute(
                "SELECT id, payload_json FROM htr_jobs WHERE type = 'training'"
            ).fetchall()
            job_ids = [
                row["id"]
                for row in jobs
                if self._json(row["payload_json"], {}).get("modelId") == model_id
            ]
            if job_ids:
                placeholders = ", ".join("?" for _ in job_ids)
                connection.execute(
                    f"DELETE FROM htr_jobs WHERE id IN ({placeholders})", job_ids
                )
            connection.execute("DELETE FROM htr_models WHERE id = ?", (model_id,))
        return {"ok": True, "deletedModelId": model_id}

    def create_job(self, job_type: str, payload: dict) -> dict:
        job_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO htr_jobs (
                    id, type, status, payload_json, safe_log_json, created_at
                ) VALUES (?, ?, 'pending', ?, '[]', ?)
                """,
                (job_id, job_type, json.dumps(payload), now),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str, *, include_payload: bool = False) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM htr_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not row:
            raise JournalHtrError("Job not found", status=404, code="not_found")
        result = self.job_dict(row)
        if include_payload:
            result["payload"] = self._json(row["payload_json"], {})
        return result

    def list_jobs(self, limit: int = 30) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM htr_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.job_dict(row) for row in rows]

    def update_job(self, job_id: str, **changes) -> dict:
        allowed = {
            "status",
            "progress",
            "stage",
            "safe_log_json",
            "error",
            "started_at",
            "finished_at",
            "cancel_requested",
            "provider_task_id",
        }
        clean = {key: value for key, value in changes.items() if key in allowed}
        if "status" in clean:
            clean["status"] = validate_status(clean["status"], JOB_STATUSES, "job status")
        if "progress" in clean:
            clean["progress"] = min(100, max(0, int(clean["progress"])))
        if clean:
            assignments = ", ".join(f"{key} = ?" for key in clean)
            with self._connect() as connection:
                connection.execute(
                    f"UPDATE htr_jobs SET {assignments} WHERE id = ?",
                    (*clean.values(), job_id),
                )
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> dict:
        job = self.get_job(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        return self.update_job(job_id, cancel_requested=1, stage="cancelling")

    def summary_counts(self) -> dict:
        with self._connect() as connection:
            page_counts = dict(
                connection.execute(
                    "SELECT status, COUNT(*) FROM htr_pages GROUP BY status"
                ).fetchall()
            )
            line_counts = dict(
                connection.execute(
                    "SELECT review_status, COUNT(*) FROM htr_lines GROUP BY review_status"
                ).fetchall()
            )
            training_lines = connection.execute(
                """
                SELECT COUNT(*) FROM htr_lines
                WHERE use_for_training = 1 AND review_status IN ('approved', 'corrected')
                """
            ).fetchone()[0]
            segmentation_issues = connection.execute(
                "SELECT COUNT(*) FROM htr_pages WHERE segmentation_issue = 1"
            ).fetchone()[0]
            total_pages = connection.execute(
                "SELECT COUNT(*) FROM htr_pages"
            ).fetchone()[0]
            exportable = connection.execute(
                "SELECT COUNT(*) FROM htr_pages WHERE status = 'reviewed'"
            ).fetchone()[0]
            active_model = connection.execute(
                "SELECT * FROM htr_models WHERE type = 'recognition' AND is_active = 1 LIMIT 1"
            ).fetchone()
            active_segmentation_model = connection.execute(
                "SELECT * FROM htr_models WHERE type = 'segmentation' AND is_active = 1 LIMIT 1"
            ).fetchone()
            custom_models = connection.execute(
                "SELECT COUNT(*) FROM htr_models WHERE id NOT LIKE 'external-%'"
            ).fetchone()[0]
            unevaluated = connection.execute(
                """
                SELECT COUNT(*) FROM htr_models
                WHERE type = 'recognition' AND status IN ('ready', 'training')
                    AND test_cer IS NULL
                """
            ).fetchone()[0]
        return {
            "totalPages": total_pages,
            "pendingSegmentation": page_counts.get("uploaded", 0),
            "segmentingPages": page_counts.get("segmenting", 0),
            "pendingTranscription": page_counts.get("segmented", 0),
            "transcribingPages": page_counts.get("transcribing", 0),
            "segmentationIssues": segmentation_issues,
            "unreviewedLines": line_counts.get("unreviewed", 0),
            "approvedTrainingLines": training_lines,
            "exportablePages": exportable,
            "activeModel": self.model_dict(active_model) if active_model else None,
            "activeSegmentationModel": (
                self.model_dict(active_segmentation_model)
                if active_segmentation_model
                else None
            ),
            "hasCustomModel": bool(custom_models),
            "unevaluatedModels": unevaluated,
        }


class JournalHtrService:
    def __init__(self, root: Path, *, provider=None, storage_path: Path | None = None):
        self.root = Path(root).resolve()
        self._explicit_provider = provider
        self.provider = provider
        self.storage_path = Path(storage_path).resolve() if storage_path else None
        self.store: JournalHtrStore | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._runtime_lock = threading.Lock()
        self._health_cache: tuple[float, dict] | None = None

    @property
    def enabled(self) -> bool:
        if self._explicit_provider is not None:
            return True
        return env_bool("HTR_ENABLED", False)

    @property
    def max_upload_bytes(self) -> int:
        try:
            mb = int(os.environ.get("HTR_MAX_UPLOAD_MB", "25"))
        except ValueError:
            mb = 25
        return max(1, min(mb, 500)) * 1024 * 1024

    @property
    def max_multipart_bytes(self) -> int:
        return self.max_upload_bytes * 20 + 1024 * 1024

    def initialize(self, *, start_worker: bool = True):
        if not self.storage_path:
            configured = os.environ.get("HTR_STORAGE_PATH", "").strip()
            self.storage_path = (
                Path(configured).expanduser().resolve()
                if configured
                else (self.root / "data" / "journal-htr").resolve()
            )
        if self.store is None:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            (self.storage_path / "originals").mkdir(exist_ok=True)
            (self.storage_path / "working").mkdir(exist_ok=True)
            (self.storage_path / "thumbnails").mkdir(exist_ok=True)
            self.store = JournalHtrStore(self.storage_path / "journal-htr.sqlite")
            self.store.initialize()
        if start_worker:
            self.start_runtime()

    def start_runtime(self):
        self.initialize(start_worker=False)
        with self._runtime_lock:
            if self._thread and self._thread.is_alive():
                return
            if self.provider is None and self._explicit_provider is not None:
                self.provider = self._explicit_provider
            if self.provider is None:
                try:
                    self.provider = provider_from_environment()
                except HtrProviderError:
                    self.provider = None
            self._queue = queue.Queue()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_jobs, name="journal-htr-worker", daemon=True
            )
            self._thread.start()
        assert self.store is not None
        persisted_jobs = self.store.list_jobs(1000)
        pending_types = {
            job["type"] for job in persisted_jobs if job["status"] == "pending"
        }
        for job in persisted_jobs:
            if job["status"] == "pending":
                self._queue.put(job["id"])
        if self._provider_configured() and "provider-upload" not in pending_types:
            unsynced_by_project: dict[str, list[str]] = {}
            pages = self.store.list_pages()
            for page in pages:
                if not page.get("externalPageId"):
                    unsynced_by_project.setdefault(page["projectId"], []).append(page["id"])
            for project_id, page_ids in unsynced_by_project.items():
                self.submit_job(
                    "provider-upload",
                    {"projectId": project_id, "pageIds": page_ids},
                )
            if "sync" not in pending_types and (not self.store.list_models() or any(
                page["status"] in {"segmenting", "transcribing"} for page in pages
            )):
                self.submit_job("sync", {})

    def stop_runtime(self):
        with self._runtime_lock:
            thread = self._thread
            if not thread:
                self.provider = self._explicit_provider
                self._health_cache = None
                return
            self._stop.set()
            self._queue.put(None)
        thread.join(timeout=5)
        with self._runtime_lock:
            if not thread.is_alive():
                self._thread = None
                self.provider = self._explicit_provider
            self._health_cache = None

    def stop(self):
        self.stop_runtime()

    def _require_store(self) -> JournalHtrStore:
        if not self.store:
            self.initialize(start_worker=False)
        assert self.store is not None
        return self.store

    def _provider_configured(self) -> bool:
        if isinstance(self.provider, FakeHtrProvider):
            return True
        return bool(
            isinstance(self.provider, EscriptoriumProvider) and self.provider.configured
        )

    def _provider_health(self, force: bool = False) -> dict:
        if not self.enabled:
            return {"online": False, "error": "HTR module is disabled"}
        if not self.provider or not self._provider_configured():
            return {"online": False, "error": "eScriptorium configuration is incomplete"}
        if not force and self._health_cache and time.monotonic() - self._health_cache[0] < 10:
            return self._health_cache[1]
        try:
            result = self.provider.health_check()
        except HtrProviderError as exc:
            result = {"online": False, "error": str(exc), "code": exc.code}
        self._health_cache = (time.monotonic(), result)
        return result

    def status(
        self,
        *,
        force_health: bool = False,
        health_override: dict | None = None,
    ) -> dict:
        store = self._require_store()
        counts = store.summary_counts()
        health = (
            dict(health_override)
            if health_override is not None
            else self._provider_health(force=force_health)
        )
        bootstrap: dict = {}
        bootstrap_path = self.root / "htr" / "bootstrap-state.json"
        try:
            bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bootstrap = {}
        if (
            bootstrap.get("status") == "waiting_for_virtualization"
            and not health.get("online")
        ):
            health = {
                "online": False,
                "error": bootstrap.get("detail")
                or "Wirtualizacja procesora jest wyłączona w UEFI/BIOS.",
                "code": "virtualization_disabled",
            }
        try:
            free_bytes = shutil.disk_usage(self.storage_path).free
            storage_ok = free_bytes > self.max_upload_bytes
        except OSError:
            free_bytes = None
            storage_ok = False
        active = counts.get("activeModel")
        state = {
            **counts,
            "enabled": self.enabled,
            "providerConfigured": self._provider_configured(),
            "providerOnline": bool(health.get("online")),
            "providerError": health.get("error"),
            "trainingMinimum": int(os.environ.get("HTR_TRAINING_MIN_LINES", "200")),
            "retrainAfterLines": int(
                os.environ.get("HTR_RETRAIN_AFTER_NEW_LINES", "300")
            ),
            "newLinesSinceTraining": store.dataset_stats()["newLinesSinceTraining"],
            "betterCandidate": False,
            "bootstrapState": bootstrap.get("status"),
        }
        return {
            "enabled": self.enabled,
            "provider": os.environ.get("HTR_PROVIDER", "escriptorium"),
            "services": {
                "dashboardBackend": {"online": True},
                "escriptorium": health,
                "krakenWorker": {
                    "online": bool(health.get("online")),
                    "version": health.get("krakenVersion"),
                },
                "database": {"online": True, "path": str(store.db_path)},
                "storage": {
                    "online": storage_ok,
                    "freeBytes": free_bytes,
                    "path": str(self.storage_path),
                },
            },
            "stats": {
                **counts,
                "activeModelVersion": active["version"] if active else None,
                "activeRecognitionModel": active,
                "activeSegmentationModel": counts.get("activeSegmentationModel"),
                "lastCer": active["testCer"] if active else None,
                "runningJobs": sum(
                    job["status"] in {"pending", "running"} for job in store.list_jobs()
                ),
            },
            "nextStep": calculate_next_step(state),
            "bootstrap": bootstrap,
            "capabilities": {
                "upload": True,
                "rotation": self._pillow_available(),
                "crop": True,
                "perspectiveCorrection": self._pillow_available(),
                "deskew": self._pillow_available(),
                "shadowReduction": False,
                "segmentationEditing": True,
                "providerTraining": True,
            },
        }

    @staticmethod
    def _pillow_available() -> bool:
        try:
            import PIL  # noqa: F401
        except ImportError:
            return False
        return True

    def create_project(self, payload: dict) -> dict:
        return self._require_store().create_project(payload)

    def _prepare_working_copy(
        self, source: Path, target: Path, thumbnail: Path, mime_type: str
    ) -> str | None:
        if mime_type == "application/pdf":
            shutil.copy2(source, target)
            return None
        try:
            from PIL import Image, ImageOps

            with Image.open(source) as image:
                clean = ImageOps.exif_transpose(image)
                if clean.mode not in {"RGB", "L"}:
                    clean = clean.convert("RGB")
                save_format = {
                    "image/jpeg": "JPEG",
                    "image/png": "PNG",
                    "image/tiff": "TIFF",
                }[mime_type]
                clean.save(target, format=save_format)
                preview = clean.copy()
                preview.thumbnail((480, 480))
                if preview.mode != "RGB":
                    preview = preview.convert("RGB")
                preview.save(thumbnail, format="JPEG", quality=82, optimize=True)
            return str(thumbnail)
        except ImportError:
            source.unlink(missing_ok=True)
            raise JournalHtrError(
                "Pillow is required to create a metadata-free working copy",
                status=503,
                code="image_dependency_missing",
            )
        except Exception as exc:
            source.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            thumbnail.unlink(missing_ok=True)
            raise JournalHtrError(
                f"Image could not be decoded: {exc}", code="invalid_image"
            ) from exc

    def upload(self, content_type: str, raw: bytes) -> dict:
        store = self._require_store()
        if not self.enabled:
            raise JournalHtrError(
                "HTR module is disabled", status=503, code="htr_disabled"
            )
        fields, files = parse_multipart(content_type, raw)
        if not files:
            raise JournalHtrError("Select at least one file", code="empty_upload")
        project_id = fields.get("projectId", "").strip()
        if project_id:
            project = store.get_project(project_id)
        else:
            project = store.create_project(
                {
                    "name": fields.get("notebookName") or "Dziennik",
                    "entryDate": fields.get("entryDate"),
                    "datePrecision": fields.get("datePrecision") or "unknown",
                    "language": fields.get("language") or "unknown",
                    "notes": fields.get("notes") or "",
                }
            )
        language = fields.get("language") or project["language"]
        date_precision = fields.get("datePrecision") or project["datePrecision"]
        if language not in LANGUAGES or date_precision not in DATE_PRECISIONS:
            raise JournalHtrError("Invalid language or date precision")
        order = store.next_page_order(project["id"])
        created = []
        for index, upload in enumerate(files):
            if len(upload.data) > self.max_upload_bytes:
                raise JournalHtrError(
                    f"{upload.filename}: file exceeds configured upload limit",
                    status=413,
                    code="payload_too_large",
                )
            detected = sniff_mime(upload.data)
            if detected not in ALLOWED_MIME_TYPES:
                raise JournalHtrError(
                    f"{upload.filename}: unsupported or invalid file type",
                    code="unsupported_file_type",
                )
            extension = ALLOWED_MIME_TYPES[detected]
            storage_id = uuid.uuid4().hex
            original = self.storage_path / "originals" / f"{storage_id}{extension}"
            working = self.storage_path / "working" / f"{storage_id}{extension}"
            thumbnail = self.storage_path / "thumbnails" / f"{storage_id}.jpg"
            original.write_bytes(upload.data)
            thumbnail_path = self._prepare_working_copy(
                original, working, thumbnail, detected
            )
            try:
                page_number = int(fields.get("pageNumber") or 0) + index or None
            except ValueError:
                page_number = None
            created.append(
                store.create_page(
                    {
                        "projectId": project["id"],
                        "originalFilename": Path(upload.filename).name[:255],
                        "mimeType": detected,
                        "originalPath": str(original),
                        "workingPath": str(working),
                        "thumbnailPath": thumbnail_path,
                        "pageNumber": page_number,
                        "pageOrder": order + index,
                        "language": language,
                        "entryDate": fields.get("entryDate") or project["entryDate"],
                        "datePrecision": date_precision,
                        "notes": fields.get("notes") or "",
                    }
                )
            )
        job = None
        if self._provider_configured():
            job = self.submit_job(
                "provider-upload",
                {
                    "projectId": project["id"],
                    "pageIds": [page["id"] for page in created],
                },
            )
        return {"project": project, "pages": created, "job": job}

    def image_file(self, page_id: str, variant: str = "working") -> tuple[Path, str]:
        page = self._require_store().get_page(page_id, include_paths=True)
        if variant == "thumbnail" and page.get("thumbnailPath"):
            path = Path(page["thumbnailPath"])
            mime = "image/jpeg"
        elif variant == "original":
            path = Path(page["originalPath"])
            mime = page["mimeType"]
        else:
            path = Path(page["workingPath"])
            mime = page["mimeType"]
        resolved = path.resolve()
        if self.storage_path not in resolved.parents or not resolved.is_file():
            raise JournalHtrError("Stored file is missing", status=404, code="file_missing")
        return resolved, mime

    @staticmethod
    def _image_dimensions(path: str | Path | None) -> dict | None:
        if not path:
            return None
        try:
            from PIL import Image

            with Image.open(path) as image:
                return {"width": image.width, "height": image.height}
        except (ImportError, OSError):
            return None

    def list_pages(self, project_id: str | None = None) -> list[dict]:
        store = self._require_store()
        result = []
        for page in store.list_pages(project_id):
            stored = store.get_page(page["id"], include_paths=True)
            working = self._image_dimensions(stored.get("workingPath"))
            original = self._image_dimensions(stored.get("originalPath"))
            segmentation = (
                page.get("processing", {}).get("segmentationImage") or working
            )
            page["imageInfo"] = {
                "original": original,
                "working": working,
                "segmentation": segmentation,
            }
            result.append(page)
        return result

    def _lines_in_working_space(self, page: dict, lines: list[dict]) -> list[dict]:
        stored = self._require_store().get_page(page["id"], include_paths=True)
        dimensions = self._image_dimensions(stored.get("workingPath")) or {}
        coordinate_space = {
            "width": dimensions.get("width"),
            "height": dimensions.get("height"),
            "variant": "working",
        }
        for item in lines:
            geometry = dict(item.get("geometry") or {})
            geometry.setdefault("coordinateSpace", coordinate_space)
            item["geometry"] = geometry
        if dimensions:
            processing = dict(page.get("processing") or {})
            processing["segmentationImage"] = coordinate_space
            self._require_store().update_page(
                page["id"], processing_json=json.dumps(processing)
            )
        return lines

    def rotate_page(self, page_id: str, angle: int) -> dict:
        if angle not in {-270, -180, -90, 90, 180, 270}:
            raise JournalHtrError("Rotation angle must be a multiple of 90")
        page = self._require_store().get_page(page_id, include_paths=True)
        if page["mimeType"] == "application/pdf":
            raise JournalHtrError(
                "PDF rotation is unavailable; rotate individual pages after import",
                status=409,
                code="capability_unavailable",
            )
        try:
            from PIL import Image
        except ImportError as exc:
            raise JournalHtrError(
                "Install Pillow to enable local image rotation",
                status=501,
                code="capability_unavailable",
            ) from exc
        working = Path(page["workingPath"])
        with Image.open(working) as image:
            old_width, old_height = image.size
            rotated = image.rotate(-angle, expand=True)
            rotated.save(working)
            thumb_path = Path(page["thumbnailPath"]) if page.get("thumbnailPath") else None
            if thumb_path:
                preview = rotated.copy()
                preview.thumbnail((480, 480))
                if preview.mode != "RGB":
                    preview = preview.convert("RGB")
                preview.save(thumb_path, "JPEG", quality=82)
        self._require_store().rotate_page_geometries(
            page_id, old_width, old_height, angle
        )
        processing = page["processing"]
        processing["rotation"] = (int(processing.get("rotation") or 0) + angle) % 360
        processing["transformRevision"] = int(processing.get("transformRevision") or 0) + 1
        processing["segmentationImage"] = {
            "width": rotated.width,
            "height": rotated.height,
            "variant": "working",
        }
        self._require_store().update_page(
            page_id, processing_json=json.dumps(processing)
        )
        project = self._require_store().get_project(page["projectId"])
        if (
            page["externalPageId"]
            and project["externalDocumentId"]
            and self.provider
            and self._provider_configured()
        ):
            try:
                self.provider.rotate_page(
                    project["externalDocumentId"], page["externalPageId"], angle
                )
            except HtrProviderError as exc:
                result = self._require_store().get_page(page_id)
                result["providerSync"] = {
                    "ok": False,
                    "error": str(exc)[:500],
                    "retryAction": "Rotate the page in eScriptorium",
                }
                return result
        return self._require_store().get_page(page_id)

    def preprocess_page(self, page_id: str, payload: dict) -> dict:
        page = self._require_store().get_page(page_id, include_paths=True)
        if page["mimeType"] == "application/pdf":
            raise JournalHtrError(
                "Image preprocessing is unavailable for PDF pages",
                code="capability_unavailable",
            )
        if not self.provider or not self._provider_configured():
            raise JournalHtrError(
                "eScriptorium must be online before replacing a working image",
                status=503,
                code="provider_not_configured",
            )
        deskew_angle = float(payload.get("deskewAngle") or 0)
        if not math.isfinite(deskew_angle) or abs(deskew_angle) > 20:
            raise JournalHtrError("Deskew angle must be between -20 and 20 degrees")
        corners = payload.get("perspectiveCorners")
        if corners is not None:
            if not isinstance(corners, list) or len(corners) != 4:
                raise JournalHtrError(
                    "Perspective correction needs four corners",
                    code="invalid_perspective",
                )
            corners = normalize_geometry(
                {"mask": corners, "baseline": [corners[0], corners[1]]}
            )["mask"]
        if not deskew_angle and not corners:
            raise JournalHtrError("Choose deskew or perspective correction")
        try:
            from PIL import Image
        except ImportError as exc:
            raise JournalHtrError(
                "Pillow is required for image preprocessing",
                status=501,
                code="capability_unavailable",
            ) from exc

        working = Path(page["workingPath"])
        temporary = working.with_name(f".tmp-{uuid.uuid4().hex}{working.suffix}")
        processed = None
        try:
            with Image.open(working) as source:
                processed = source.convert("RGB") if source.mode not in {"RGB", "L"} else source.copy()
            if corners:
                upper_left, upper_right, lower_right, lower_left = corners
                target_width = max(
                    1,
                    round(
                        max(
                            math.dist(upper_left, upper_right),
                            math.dist(lower_left, lower_right),
                        )
                    ),
                )
                target_height = max(
                    1,
                    round(
                        max(
                            math.dist(upper_left, lower_left),
                            math.dist(upper_right, lower_right),
                        )
                    ),
                )
                processed = processed.transform(
                    (target_width, target_height),
                    Image.Transform.QUAD,
                    (
                        *upper_left,
                        *lower_left,
                        *lower_right,
                        *upper_right,
                    ),
                    resample=Image.Resampling.BICUBIC,
                )
            if deskew_angle:
                processed = processed.rotate(
                    -deskew_angle,
                    expand=True,
                    resample=Image.Resampling.BICUBIC,
                    fillcolor="white",
                )
            save_format = {
                "image/jpeg": "JPEG",
                "image/png": "PNG",
                "image/tiff": "TIFF",
            }[page["mimeType"]]
            save_options = {"quality": 95} if save_format == "JPEG" else {}
            processed.save(temporary, format=save_format, **save_options)

            project = self._require_store().get_project(page["projectId"])
            uploaded = self.provider.upload_page(
                project["externalDocumentId"], temporary, page["mimeType"]
            )
            new_external_id = str(uploaded.get("pk") or uploaded.get("id") or "")
            if not new_external_id:
                raise JournalHtrError(
                    "eScriptorium did not return the replacement page id",
                    code="provider_page_missing",
                )
            try:
                if page.get("externalPageId"):
                    self.provider.delete_page(
                        project["externalDocumentId"], page["externalPageId"]
                    )
            except Exception:
                try:
                    self.provider.delete_page(
                        project["externalDocumentId"], new_external_id
                    )
                except Exception:
                    pass
                raise

            os.replace(temporary, working)
            thumb_path = Path(page["thumbnailPath"]) if page.get("thumbnailPath") else None
            if thumb_path:
                preview = processed.copy()
                preview.thumbnail((480, 480))
                if preview.mode != "RGB":
                    preview = preview.convert("RGB")
                preview.save(thumb_path, "JPEG", quality=82, optimize=True)
            processing = dict(page.get("processing") or {})
            processing.update(
                {
                    "deskewAngle": deskew_angle,
                    "perspectiveCorners": corners,
                    "transformRevision": int(processing.get("transformRevision") or 0) + 1,
                    "segmentationImage": {
                        "width": processed.width,
                        "height": processed.height,
                        "variant": "working",
                    },
                }
            )
            self._require_store().clear_page_lines(page_id)
            self._require_store().update_page(
                page_id,
                external_page_id=new_external_id,
                status="uploaded",
                segmentation_issue=0,
                processing_json=json.dumps(processing),
            )
            job = self.start_segmentation([page_id], replace_existing=True)
            return {"page": self._require_store().get_page(page_id), "job": job}
        except HtrProviderError as exc:
            raise JournalHtrError(
                str(exc), status=exc.status, code=exc.code
            ) from exc
        finally:
            if processed is not None:
                processed.close()
            temporary.unlink(missing_ok=True)

    def reorder_pages(self, page_ids: list[str]) -> dict:
        return {"pages": self._require_store().reorder_pages(page_ids)}

    def delete_page(self, page_id: str) -> dict:
        page = self._require_store().delete_page(page_id)
        removed = []
        for key in ("originalPath", "workingPath", "thumbnailPath"):
            value = page.get(key)
            if value:
                path = Path(value).resolve()
                if self.storage_path in path.parents and path.exists():
                    path.unlink()
                    removed.append(path.name)
        return {"ok": True, "removedFiles": removed}

    def submit_job(self, job_type: str, payload: dict) -> dict:
        job = self._require_store().create_job(job_type, payload)
        self._queue.put(job["id"])
        return job

    def cancel_job(self, job_id: str) -> dict:
        return self._require_store().cancel_job(job_id)

    def _run_jobs(self):
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._execute_job(job_id)
            except Exception:
                # _execute_job converts all failures into safe persisted messages.
                pass

    def _job_log(self, job: dict, message: str) -> str:
        log = list(job.get("safeLog") or [])
        log.append({"at": utc_now(), "message": str(message)[:500]})
        return json.dumps(log[-100:])

    def _execute_job(self, job_id: str):
        store = self._require_store()
        job = store.get_job(job_id, include_payload=True)
        if job["cancelRequested"]:
            store.update_job(
                job_id,
                status="cancelled",
                stage="cancelled",
                finished_at=utc_now(),
            )
            return
        job = store.update_job(
            job_id,
            status="running",
            stage="starting",
            progress=1,
            started_at=utc_now(),
        )
        try:
            if not self.provider or not self._provider_configured():
                raise HtrProviderError(
                    "eScriptorium is not configured",
                    code="provider_not_configured",
                    status=503,
                )
            payload = store.get_job(job_id, include_payload=True)["payload"]
            handlers = {
                "provider-upload": self._job_provider_upload,
                "segment": self._job_segment,
                "transcribe": self._job_transcribe,
                "sync": self._job_sync,
                "training": self._job_training,
            }
            if job["type"] not in handlers:
                raise JournalHtrError(f"Unsupported job type: {job['type']}")
            completed_now = handlers[job["type"]](job_id, payload)
            if completed_now is False:
                return
            latest = store.get_job(job_id)
            if latest["cancelRequested"]:
                store.update_job(
                    job_id,
                    status="cancelled",
                    stage="cancelled",
                    finished_at=utc_now(),
                )
            else:
                store.update_job(
                    job_id,
                    status="completed",
                    stage="completed",
                    progress=100,
                    finished_at=utc_now(),
                )
        except (JournalHtrError, HtrProviderError, HtrValidationError) as exc:
            # Never persist request bodies, tokens, or transcription content in errors.
            safe = str(exc)
            token = os.environ.get("ESCRIPTORIUM_API_TOKEN", "")
            if token:
                safe = safe.replace(token, "[redacted]")
            safe = safe[:1000]
            store.update_job(
                job_id,
                status="failed",
                stage="failed",
                error=safe,
                finished_at=utc_now(),
            )
        except Exception as exc:
            store.update_job(
                job_id,
                status="failed",
                stage="failed",
                error=f"Unexpected local worker error: {type(exc).__name__}",
                finished_at=utc_now(),
            )

    def _ensure_remote_project(self, project_id: str) -> dict:
        store = self._require_store()
        project = store.get_project(project_id)
        if project["externalDocumentId"]:
            return project
        remote = self.provider.create_document(project["name"])
        external_id = str(remote.get("pk") or remote.get("id") or "")
        if not external_id:
            raise HtrProviderError("eScriptorium did not return a document id")
        transcription_id = None
        if hasattr(self.provider, "ensure_transcription"):
            transcription = self.provider.ensure_transcription(external_id)
            transcription_id = str(
                transcription.get("pk") or transcription.get("id") or ""
            )
        store.update_project_remote(project_id, external_id, transcription_id)
        return store.get_project(project_id)

    def _job_provider_upload(self, job_id: str, payload: dict):
        store = self._require_store()
        project = self._ensure_remote_project(payload["projectId"])
        page_ids = payload["pageIds"]
        for index, page_id in enumerate(page_ids, start=1):
            if store.get_job(job_id)["cancelRequested"]:
                return
            page = store.get_page(page_id, include_paths=True)
            result = self.provider.upload_page(
                project["externalDocumentId"],
                Path(page["workingPath"]),
                page["mimeType"],
            )
            external_id = result.get("pk") or result.get("id")
            if page["mimeType"] != "application/pdf" and not external_id:
                raise HtrProviderError("eScriptorium did not return a page id")
            if external_id:
                store.update_page(page_id, external_page_id=str(external_id))
            store.update_job(
                job_id,
                progress=round(index / len(page_ids) * 100),
                stage=f"uploaded {index}/{len(page_ids)}",
            )

    def _provider_task_group_ids(self, document_id: str) -> set[str]:
        if not self.provider:
            return set()
        return {
            str(group.get("pk"))
            for group in self.provider.list_task_groups(document_id)
            if group.get("pk") is not None
        }

    def _wait_for_provider_process(
        self,
        job_id: str,
        document_id: str,
        method: str,
        *,
        previous_group_ids: set[str] | None = None,
    ) -> dict:
        if isinstance(self.provider, FakeHtrProvider):
            return {"workflowState": "Finished", "progress": 100}
        try:
            timeout = int(os.environ.get("HTR_PROVIDER_JOB_TIMEOUT_SECONDS", "7200"))
        except ValueError:
            timeout = 7200
        deadline = time.monotonic() + max(60, timeout)
        selected_id: str | None = None
        expected = method.lower()
        while time.monotonic() < deadline:
            job = self._require_store().get_job(job_id)
            if job["cancelRequested"]:
                return {"workflowState": "Canceled", "progress": job["progress"]}
            groups = self.provider.list_task_groups(document_id)
            candidates = []
            for group in groups:
                group_id = str(group.get("pk") or "")
                group_method = str(group.get("method") or "").lower()
                if selected_id and group_id != selected_id:
                    continue
                if previous_group_ids is not None and group_id in previous_group_ids:
                    continue
                if group_method and expected not in group_method:
                    continue
                candidates.append(group)
            if previous_group_ids is None:
                matching = [
                    group
                    for group in groups
                    if expected in str(group.get("method") or "").lower()
                ]
                if matching:
                    candidates = matching
            if candidates:
                candidates.sort(
                    key=lambda item: int(item.get("pk") or 0), reverse=True
                )
                group = candidates[0]
                selected_id = str(group.get("pk") or selected_id or "")
                states = {
                    str(item.get("workflow_state") or "").lower(): int(
                        item.get("count") or 0
                    )
                    for item in group.get("tasks") or []
                }
                total = max(
                    int(group.get("page_count") or 0),
                    sum(states.values()),
                )
                finished = states.get("finished", 0)
                failed = states.get("crashed", 0)
                cancelled = states.get("canceled", 0)
                if failed or cancelled:
                    raise HtrProviderError(
                        f"eScriptorium {method} failed: "
                        f"{failed} crashed, {cancelled} canceled",
                        code="provider_task_failed",
                    )
                progress = (
                    min(95, max(5, round(finished / total * 95))) if total else 5
                )
                self._require_store().update_job(
                    job_id,
                    progress=progress,
                    stage=(
                        f"eScriptorium {method}: {finished}/{total}"
                        if total
                        else f"eScriptorium {method}: queued"
                    ),
                )
                if total and finished >= total:
                    return {
                        "workflowState": "Finished",
                        "progress": 100,
                        "taskGroupId": selected_id,
                    }
            else:
                self._require_store().update_job(
                    job_id,
                    progress=3,
                    stage=f"eScriptorium {method}: waiting for task group",
                )
            time.sleep(2)
        raise HtrProviderError(
            f"Timed out waiting for eScriptorium {method}",
            code="provider_task_timeout",
        )

    def start_segmentation(
        self,
        page_ids: list[str],
        model_id: str | None = None,
        *,
        replace_existing: bool = False,
    ) -> dict:
        if not page_ids:
            raise JournalHtrError("Select at least one page")
        for page_id in page_ids:
            self._require_store().get_page(page_id)
        return self.submit_job(
            "segment",
            {
                "pageIds": page_ids,
                "modelId": model_id,
                "replaceExisting": bool(replace_existing),
            },
        )

    def _job_segment(self, job_id: str, payload: dict):
        store = self._require_store()
        pages = [store.get_page(page_id) for page_id in payload["pageIds"]]
        projects = {page["projectId"] for page in pages}
        if len(projects) != 1:
            raise JournalHtrError("Batch segmentation must contain one notebook")
        project = self._ensure_remote_project(projects.pop())
        remote_ids = [page["externalPageId"] for page in pages]
        if any(not value for value in remote_ids):
            raise JournalHtrError(
                "Some pages are not uploaded to eScriptorium yet",
                code="remote_page_missing",
            )
        for page in pages:
            store.update_page(page["id"], status="segmenting")
        model = store.get_model(payload["modelId"]) if payload.get("modelId") else None
        external_model = model["externalModelId"] if model else None
        previous_groups = self._provider_task_group_ids(
            project["externalDocumentId"]
        )
        self.provider.segment_page(
            project["externalDocumentId"],
            remote_ids,
            external_model,
            override=bool(payload.get("replaceExisting")),
        )
        if isinstance(self.provider, FakeHtrProvider):
            for page in pages:
                store.update_page(page["id"], status="segmented")
        else:
            self._wait_for_provider_process(
                job_id,
                project["externalDocumentId"],
                "segment",
                previous_group_ids=previous_groups,
            )
            for page in pages:
                lines = self.provider.get_page_lines(
                    project["externalDocumentId"],
                    page["externalPageId"],
                )
                lines = self._lines_in_working_space(page, lines)
                store.upsert_lines(
                    page["id"],
                    lines,
                    replace=bool(payload.get("replaceExisting")),
                )
                store.update_page(page["id"], status="segmented")
        store.update_job(job_id, progress=99, stage="segmentacja gotowa")

    def start_transcription(self, page_ids: list[str], model_id: str) -> dict:
        if not page_ids or not model_id:
            raise JournalHtrError("Select pages and a recognition model")
        self.reconcile_provider_models()
        model = self._require_store().get_model(model_id)
        if (
            model["type"] != "recognition"
            or not model["externalModelId"]
            or model["status"] not in {"ready", "evaluated", "active"}
            or model.get("provider", {}).get("training")
        ):
            raise JournalHtrError(
                "Wybrany model nadal się trenuje albo nie został jeszcze zsynchronizowany z eScriptorium.",
                status=409,
                code="model_not_ready",
            )
        return self.submit_job(
            "transcribe", {"pageIds": page_ids, "modelId": model_id}
        )

    def _job_transcribe(self, job_id: str, payload: dict):
        store = self._require_store()
        model = store.get_model(payload["modelId"])
        if model["type"] != "recognition" or not model["externalModelId"]:
            raise JournalHtrError(
                "Choose a provider recognition model", code="invalid_model"
            )
        pages = [store.get_page(page_id) for page_id in payload["pageIds"]]
        projects = {page["projectId"] for page in pages}
        if len(projects) != 1:
            raise JournalHtrError("Batch transcription must contain one notebook")
        project = self._ensure_remote_project(projects.pop())
        if not project["transcriptionId"] and hasattr(
            self.provider, "ensure_transcription"
        ):
            transcription = self.provider.ensure_transcription(
                project["externalDocumentId"]
            )
            project = store.get_project(project["id"])
            store.update_project_remote(
                project["id"],
                project["externalDocumentId"],
                str(transcription.get("pk")),
            )
            project = store.get_project(project["id"])
        remote_ids = [page["externalPageId"] for page in pages]
        if any(not value for value in remote_ids):
            raise JournalHtrError("Some pages have no eScriptorium id")
        for page in pages:
            store.update_page(page["id"], status="transcribing")
        previous_groups = self._provider_task_group_ids(
            project["externalDocumentId"]
        )
        self.provider.transcribe_page(
            project["externalDocumentId"],
            remote_ids,
            model["externalModelId"],
            project["transcriptionId"],
        )
        if isinstance(self.provider, FakeHtrProvider):
            for page in pages:
                lines = self.provider.get_page_lines(
                    project["externalDocumentId"],
                    page["externalPageId"],
                    project["transcriptionId"],
                )
                lines = self._lines_in_working_space(page, lines)
                store.upsert_lines(
                    page["id"],
                    lines,
                    model_id=model["id"],
                    model_version=model["version"],
                )
                store.update_page(page["id"], status="transcribed")
        else:
            self._wait_for_provider_process(
                job_id,
                project["externalDocumentId"],
                "transcribe",
                previous_group_ids=previous_groups,
            )
            for page in pages:
                lines = self.provider.get_page_lines(
                    project["externalDocumentId"],
                    page["externalPageId"],
                    project["transcriptionId"],
                )
                lines = self._lines_in_working_space(page, lines)
                store.upsert_lines(
                    page["id"],
                    lines,
                    model_id=model["id"],
                    model_version=model["version"],
                )
                store.update_page(page["id"], status="transcribed")
        store.update_job(job_id, progress=99, stage="transkrypcja gotowa")

    def reconcile_provider_models(self) -> list[dict]:
        store = self._require_store()
        if not self.provider or not self._provider_configured():
            return store.list_models()
        try:
            remote_models = self.provider.list_models()
            remote_training_jobs = self.provider.list_training_jobs()
        except HtrProviderError:
            return store.list_models()
        training_jobs_by_id = {
            job["taskId"]: job for job in remote_training_jobs if job.get("taskId")
        }
        assigned_task_ids = {
            job["providerTaskId"]
            for job in store.list_jobs(100)
            if job.get("providerTaskId")
        }

        def parse_timestamp(value):
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None

        def job_for_model(model_id):
            for item in store.list_jobs(100):
                if item["type"] != "training":
                    continue
                detail = store.get_job(item["id"], include_payload=True)
                if detail["payload"].get("modelId") == model_id:
                    return detail
            return None

        def attach_provider_task(job):
            if not job or job.get("providerTaskId"):
                return job
            local_time = parse_timestamp(job.get("createdAt"))
            matches = []
            for remote_job in remote_training_jobs:
                task_id = remote_job.get("taskId")
                remote_time = parse_timestamp(remote_job.get("queuedAt"))
                if (
                    not task_id
                    or task_id in assigned_task_ids
                    or not local_time
                    or not remote_time
                ):
                    continue
                distance = abs((remote_time - local_time).total_seconds())
                if distance <= 120:
                    matches.append((distance, task_id))
            if not matches:
                return job
            _, task_id = min(matches)
            assigned_task_ids.add(task_id)
            return store.update_job(job["id"], provider_task_id=task_id)
        local_models = store.list_models()
        local_candidates = [
            model for model in local_models if not model["id"].startswith("external-")
        ]
        matched_candidate_ids = set()
        for remote in remote_models:
            external_id = str(remote.get("pk") or remote.get("id") or "")
            remote_name = str(remote.get("name") or "")
            remote_job = str(remote.get("job") or "").lower()
            remote_type = "segmentation" if "segment" in remote_job else "recognition"
            candidate = next(
                (
                    model for model in local_candidates
                    if model["id"] not in matched_candidate_ids
                    and model.get("externalModelId") == external_id
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (
                        model for model in local_candidates
                        if model["id"] not in matched_candidate_ids
                        and model["name"] == remote_name
                        and model["type"] == remote_type
                    ),
                    None,
                )
            is_training = bool(remote.get("training"))
            if candidate:
                matched_candidate_ids.add(candidate["id"])
                job = attach_provider_task(job_for_model(candidate["id"]))
                provider_job = (
                    training_jobs_by_id.get(job.get("providerTaskId")) if job else None
                )
                workflow_state = int(provider_job["workflowState"]) if provider_job else None
                if candidate["status"] == "archived":
                    next_status = "archived"
                elif workflow_state == 0:
                    next_status = "queued"
                elif workflow_state == 1 or is_training:
                    next_status = "training"
                elif workflow_state == 2:
                    next_status = "failed"
                elif workflow_state == 4:
                    next_status = "cancelled"
                elif workflow_state == 3:
                    next_status = "active" if candidate["isActive"] else "ready"
                elif job and job["status"] in {"pending", "running"}:
                    next_status = "queued"
                else:
                    next_status = "active" if candidate["isActive"] else "ready"
                store.update_model(
                    candidate["id"],
                    external_model_id=external_id,
                    status=next_status,
                    provider_json=json.dumps(remote),
                )
                if job and workflow_state == 0:
                    store.update_job(
                        job["id"], status="pending",
                        stage="eScriptorium: trening czeka w kolejce",
                        progress=min(9, job["progress"] or 1),
                        finished_at=None, error=None,
                    )
                elif job and (workflow_state == 1 or is_training):
                    store.update_job(
                        job["id"], status="running",
                        stage="eScriptorium: trening modelu trwa",
                        progress=max(10, min(95, job["progress"] or 10)),
                        finished_at=None, error=None,
                    )
                elif job and workflow_state == 2:
                    message = "; ".join(provider_job.get("messages") or [])
                    store.update_job(
                        job["id"], status="failed",
                        stage="trening zakończony błędem",
                        finished_at=provider_job.get("doneAt") or utc_now(),
                        error=message[:1000] or "eScriptorium training task failed",
                    )
                elif job and workflow_state == 4:
                    store.update_job(
                        job["id"], status="cancelled", stage="trening anulowany",
                        finished_at=provider_job.get("doneAt") or utc_now(),
                    )
                elif job and workflow_state == 3:
                    store.update_job(
                        job["id"], status="completed",
                        stage="trening zakończony — model gotowy",
                        progress=100,
                        finished_at=provider_job.get("doneAt") or utc_now(),
                        error=None,
                    )
                continue
                for job in store.list_jobs(100):
                    if job["type"] != "training" or job["status"] == "cancelled":
                        continue
                    detail = store.get_job(job["id"], include_payload=True)
                    if detail["payload"].get("modelId") != candidate["id"]:
                        continue
                    if is_training:
                        if (
                            job["status"] != "running"
                            or job["stage"] != "eScriptorium: trening modelu trwa"
                        ):
                            store.update_job(
                                job["id"],
                                status="running",
                                stage="eScriptorium: trening modelu trwa",
                                progress=max(10, min(95, job["progress"] or 10)),
                                finished_at=None,
                                error=None,
                            )
                    else:
                        if (
                            job["status"] != "completed"
                            or job["stage"] != "trening zakończony — model gotowy"
                        ):
                            store.update_job(
                                job["id"],
                                status="completed",
                                stage="trening zakończony — model gotowy",
                                progress=100,
                                finished_at=utc_now(),
                                error=None,
                            )
            else:
                store.upsert_provider_model(remote)
        return store.list_models()

    def list_models(self) -> list[dict]:
        return self.reconcile_provider_models()

    def sync(self, project_id: str | None = None) -> dict:
        return self.submit_job("sync", {"projectId": project_id})

    def _job_sync(self, job_id: str, payload: dict):
        store = self._require_store()
        self.reconcile_provider_models()
        projects = (
            [store.get_project(payload["projectId"])]
            if payload.get("projectId")
            else store.list_projects()
        )
        pages = store.list_pages(payload.get("projectId"))
        if not isinstance(self.provider, FakeHtrProvider):
            for project in projects:
                project_pages = [
                    page for page in pages if page["projectId"] == project["id"]
                ]
                if any(page["status"] == "segmenting" for page in project_pages):
                    self._wait_for_provider_process(
                        job_id,
                        project["externalDocumentId"],
                        "segment",
                    )
                if any(page["status"] == "transcribing" for page in project_pages):
                    self._wait_for_provider_process(
                        job_id,
                        project["externalDocumentId"],
                        "transcribe",
                    )
        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            project = next(
                (item for item in projects if item["id"] == page["projectId"]), None
            )
            if not project or not project["externalDocumentId"] or not page["externalPageId"]:
                continue
            lines = self.provider.get_page_lines(
                project["externalDocumentId"],
                page["externalPageId"],
                project["transcriptionId"],
            )
            if lines:
                lines = self._lines_in_working_space(page, lines)
                store.upsert_lines(page["id"], lines)
                has_text = any(item.get("predictedText") for item in lines)
                store.update_page(
                    page["id"], status="transcribed" if has_text else "segmented"
                )
            store.update_job(
                job_id,
                progress=round(index / total * 100),
                stage=f"synced {index}/{total}",
            )

    def update_line(self, line_id: str, payload: dict) -> dict:
        store = self._require_store()
        if "geometry" in payload:
            updated = store.update_line_geometry(line_id, payload["geometry"])
            text_keys = {"reviewStatus", "correctedText", "useForTraining"}
            if text_keys.intersection(payload):
                updated = store.update_line(line_id, payload)
        else:
            updated = store.update_line(line_id, payload)
        page = store.get_page(updated["pageId"])
        project = store.get_project(page["projectId"])
        if (
            updated["externalTranscriptionId"]
            and page["externalPageId"]
            and project["externalDocumentId"]
            and self.provider
            and self._provider_configured()
        ):
            try:
                self.provider.update_line_transcription(
                    project["externalDocumentId"],
                    page["externalPageId"],
                    updated["externalTranscriptionId"],
                    updated["displayText"],
                )
                updated["providerSync"] = {"ok": True}
            except HtrProviderError as exc:
                updated["providerSync"] = {
                    "ok": False,
                    "error": str(exc)[:500],
                    "retryAction": "Use Synchronizuj after restoring eScriptorium",
                }
        return updated

    def merge_lines(self, line_id: str, other_line_id: str) -> dict:
        return self._require_store().merge_lines(line_id, other_line_id)

    def start_training(self, payload: dict) -> dict:
        dataset = self._require_store().get_dataset(str(payload.get("datasetId") or ""))
        model = self._require_store().create_candidate_model(payload, dataset)
        job = self.submit_job(
            "training",
            {
                "modelId": model["id"],
                "datasetId": dataset["id"],
                "baseModelId": payload.get("baseModelId"),
            },
        )
        return {"model": model, "job": job}

    def _job_training(self, job_id: str, payload: dict):
        store = self._require_store()
        model = store.get_model(payload["modelId"])
        dataset = store.get_dataset(payload["datasetId"])
        pages_by_id = {page["id"]: page for page in store.list_pages()}
        project_ids = {
            pages_by_id[page_id]["projectId"]
            for subset in dataset["split"].values()
            for page_id in subset
            if page_id in pages_by_id
        }
        if len(project_ids) != 1:
            raise JournalHtrError(
                "eScriptorium document training currently requires one notebook",
                code="multi_document_training_unavailable",
            )
        project = self._ensure_remote_project(project_ids.pop())
        part_ids = [
            pages_by_id[page_id]["externalPageId"]
            for subset in dataset["split"].values()
            for page_id in subset
            if page_id in pages_by_id and pages_by_id[page_id]["externalPageId"]
        ]
        if not part_ids:
            raise JournalHtrError("Dataset pages are not synchronized with eScriptorium")
        base = store.get_model(payload["baseModelId"]) if payload.get("baseModelId") else None
        request_payload = {
            "parts": part_ids,
            "transcription": project["transcriptionId"],
            "modelName": model["name"],
            "baseModelId": base["externalModelId"] if base else None,
        }
        if model["type"] == "recognition":
            result = self.provider.start_recognition_training(
                project["externalDocumentId"], request_payload
            )
        else:
            result = self.provider.start_segmentation_training(
                project["externalDocumentId"], request_payload
            )
        if isinstance(self.provider, FakeHtrProvider) and result.get("model"):
            remote = result["model"]
            store.update_model(
                model["id"],
                external_model_id=str(remote["pk"]),
                status="ready",
                provider_json=json.dumps(remote),
            )
            store.update_job(job_id, progress=100, stage="training completed")
            return True
        else:
            store.update_model(model["id"], status="training")
            latest_report = self.provider.get_training_job(
                project["externalDocumentId"]
            )
            task_match = re.search(
                r"celery task ([a-f0-9-]{36})",
                str(latest_report.get("label") or ""),
                re.IGNORECASE,
            )
            store.update_job(
                job_id,
                status="pending",
                progress=5,
                stage="eScriptorium: trening przyjęty",
                finished_at=None,
                provider_task_id=task_match.group(1) if task_match else None,
            )
            for _ in range(10):
                self.reconcile_provider_models()
                linked = store.get_model(model["id"])
                if linked["externalModelId"]:
                    break
                time.sleep(1)
            return False

    def activate_model(self, model_id: str) -> dict:
        store = self._require_store()
        model = store.get_model(model_id)
        if model["externalModelId"] and self.provider:
            self.provider.activate_model(model["externalModelId"])
        return store.activate_model(model_id)

    def archive_model(self, model_id: str) -> dict:
        return self._require_store().archive_model(model_id)

    def delete_model(self, model_id: str) -> dict:
        store = self._require_store()
        model = store.get_model(model_id)
        if model["isActive"]:
            raise JournalHtrError(
                "Activate another model before deleting this one",
                status=409,
                code="active_model",
            )
        matching_jobs = []
        for job in store.list_jobs(100):
            if job["type"] != "training":
                continue
            detail = store.get_job(job["id"], include_payload=True)
            if detail["payload"].get("modelId") == model_id:
                matching_jobs.append(detail)
        if model["externalModelId"] and self.provider:
            if any(job["status"] in {"pending", "running"} for job in matching_jobs):
                self.provider.cancel_training(model["externalModelId"])
            self.provider.delete_model(model["externalModelId"])
        return store.delete_model(model_id)

    def cancel_model_training(self, model_id: str) -> dict:
        store = self._require_store()
        model = store.get_model(model_id)
        if model["status"] not in {"queued", "training"}:
            raise JournalHtrError("This model is not training", code="model_not_training")
        if not model["externalModelId"]:
            raise JournalHtrError(
                "Synchronize first to obtain the provider model id",
                code="provider_model_not_linked",
            )
        self.provider.cancel_training(model["externalModelId"])
        for job in store.list_jobs(100):
            if job["type"] != "training":
                continue
            detail = store.get_job(job["id"], include_payload=True)
            if detail["payload"].get("modelId") == model_id:
                store.update_job(
                    job["id"],
                    status="cancelled",
                    stage="trening anulowany",
                    finished_at=utc_now(),
                )
        return store.update_model(model_id, status="cancelled")

    def export_to_journal(self, payload: dict) -> dict:
        page_ids = [str(value) for value in payload.get("pageIds") or []]
        if not page_ids:
            raise JournalHtrError("Select at least one reviewed page")
        pages = [self._require_store().get_page(page_id) for page_id in page_ids]
        if any(page["status"] != "reviewed" for page in pages):
            raise JournalHtrError(
                "Every exported page must be fully reviewed", code="page_not_reviewed"
            )
        lines = []
        for page in sorted(pages, key=lambda item: item["pageOrder"]):
            page_lines = self._require_store().list_lines(page_id=page["id"])
            lines.extend(sorted(page_lines, key=lambda item: item["lineOrder"]))
        faithful = "\n".join(line["displayText"] for line in lines).strip()
        structured = str(payload.get("structuredText") or faithful).strip()
        if not faithful:
            raise JournalHtrError("Reviewed pages contain no transcription")
        source_metadata = {
            "htrPageIds": page_ids,
            "faithfulTranscription": faithful,
            "sourceImages": [
                f"/api/journal-htr/pages/{page_id}/file?variant=original"
                for page_id in page_ids
            ],
        }
        from journal_store import JOURNAL_STORE

        return JOURNAL_STORE.publish_htr_entry(
            {
                "title": payload.get("title") or pages[0].get("projectName") or "OCR dziennika",
                "content": structured,
                "entryDate": payload.get("entryDate") or pages[0]["entryDate"],
                "tags": payload.get("tags") or ["OCR dziennika"],
                "sourceMetadata": source_metadata,
            }
        )


JOURNAL_HTR_SERVICE: JournalHtrService | None = None


def get_journal_htr_service(root: Path) -> JournalHtrService:
    global JOURNAL_HTR_SERVICE
    if JOURNAL_HTR_SERVICE is None:
        JOURNAL_HTR_SERVICE = JournalHtrService(root)
    return JOURNAL_HTR_SERVICE

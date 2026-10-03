"""Rights-aware authentic content intake, transcripts, and sentence alignment."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .errors import LanguageConflictError, LanguageNotFoundError, LanguageValidationError
from .store import canonical_json, new_id, utc_now


RIGHTS_POLICY_VERSION = "language.content-rights/v1"
INGESTION_POLICY_VERSION = "language.content-ingestion/v1"
TRANSCRIPT_SEGMENTATION_VERSION = "language.transcript-segmentation/v1"
TRANSCRIPT_ALIGNMENT_VERSION = "language.transcript-alignment/v1"
AUTHENTIC_LISTENING_EXPOSURE_POLICY_VERSION = "language.listening-exposure/v2"
MAX_MEDIA_BYTES = 64 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MAX_CUES = 20_000
MAX_MEDIA_DURATION_MS = 24 * 60 * 60 * 1000

REFERENCE_TYPES = {"ARTICLE_REFERENCE", "PODCAST_REFERENCE", "VIDEO_REFERENCE", "NRK_REFERENCE"}
LOCAL_TYPES = {"PASTED_TEXT", "LOCAL_AUDIO", "LOCAL_TRANSCRIPT", "LOCAL_AUDIO_PLUS_TRANSCRIPT", "SRT", "VTT"}
CONTENT_TYPES = REFERENCE_TYPES | LOCAL_TYPES
TRANSCRIPT_FORMATS = {"PLAIN", "SRT", "VTT"}
SUPPORTED_AUDIO = {
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
}


@dataclass(frozen=True)
class ParsedCue:
    order: int
    start_ms: int
    end_ms: int
    text: str
    source_identifier: str | None
    text_start: int = 0
    text_end: int = 0


def _timestamp_ms(value: str) -> int:
    parts = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{3})", value.strip())
    if not parts:
        raise LanguageValidationError("Transcript timestamp is malformed", code="malformed_transcript_timestamp")
    hours = int(parts.group(1) or 0)
    minutes, seconds, millis = (int(item) for item in parts.groups()[1:])
    if minutes > 59 or seconds > 59:
        raise LanguageValidationError("Transcript timestamp is out of range", code="malformed_transcript_timestamp")
    result = ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
    if result > MAX_MEDIA_DURATION_MS:
        raise LanguageValidationError("Transcript timestamp exceeds 24 hours", code="transcript_timestamp_out_of_range")
    return result


def _with_offsets(cues: list[ParsedCue]) -> tuple[str, list[ParsedCue]]:
    chunks: list[str] = []
    mapped: list[ParsedCue] = []
    offset = 0
    for cue in cues:
        if chunks:
            chunks.append("\n")
            offset += 1
        start = offset
        chunks.append(cue.text)
        offset += len(cue.text)
        mapped.append(ParsedCue(
            cue.order, cue.start_ms, cue.end_ms, cue.text, cue.source_identifier, start, offset,
        ))
    return "".join(chunks), mapped


def parse_srt(value: str) -> tuple[str, list[ParsedCue]]:
    text = value.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = re.split(r"\n{2,}", text.strip()) if text.strip() else []
    cues: list[ParsedCue] = []
    previous_start = -1
    for order, block in enumerate(blocks):
        lines = block.split("\n")
        identifier = None
        timing_index = 0
        if lines and "-->" not in lines[0]:
            identifier = lines[0].strip() or None
            timing_index = 1
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            raise LanguageValidationError("SRT cue is missing a timestamp", code="malformed_transcript")
        parts = [item.strip() for item in lines[timing_index].split("-->")]
        if len(parts) != 2:
            raise LanguageValidationError("SRT cue timestamp is malformed", code="malformed_transcript_timestamp")
        start_ms, end_ms = _timestamp_ms(parts[0]), _timestamp_ms(parts[1].split()[0])
        cue_text = "\n".join(lines[timing_index + 1:]).strip()
        if not cue_text or end_ms <= start_ms:
            raise LanguageValidationError("SRT cue is empty or has an invalid range", code="malformed_transcript")
        if start_ms < previous_start:
            raise LanguageValidationError("Transcript cues are out of source order", code="transcript_cues_out_of_order")
        previous_start = start_ms
        cues.append(ParsedCue(order, start_ms, end_ms, cue_text, identifier))
        if len(cues) > MAX_CUES:
            raise LanguageValidationError("Transcript has too many cues", code="transcript_too_large")
    if not cues:
        raise LanguageValidationError("Transcript contains no cues", code="empty_transcript")
    return _with_offsets(cues)


def parse_vtt(value: str) -> tuple[str, list[ParsedCue]]:
    text = value.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = text.split("\n")
    if not lines or not lines[0].strip().startswith("WEBVTT"):
        raise LanguageValidationError("VTT must start with WEBVTT", code="malformed_transcript")
    body = "\n".join(lines[1:]).strip()
    blocks = re.split(r"\n{2,}", body) if body else []
    cues: list[ParsedCue] = []
    previous_start = -1
    for block in blocks:
        rows = block.split("\n")
        if rows[0].strip().startswith(("NOTE", "STYLE", "REGION")):
            continue
        identifier = None
        timing_index = 0
        if "-->" not in rows[0]:
            identifier = rows[0].strip() or None
            timing_index = 1
        if timing_index >= len(rows) or "-->" not in rows[timing_index]:
            raise LanguageValidationError("VTT cue is missing a timestamp", code="malformed_transcript")
        parts = [item.strip() for item in rows[timing_index].split("-->")]
        if len(parts) != 2:
            raise LanguageValidationError("VTT cue timestamp is malformed", code="malformed_transcript_timestamp")
        start_ms, end_ms = _timestamp_ms(parts[0]), _timestamp_ms(parts[1].split()[0])
        cue_text = "\n".join(rows[timing_index + 1:]).strip()
        if not cue_text or end_ms <= start_ms:
            raise LanguageValidationError("VTT cue is empty or has an invalid range", code="malformed_transcript")
        if start_ms < previous_start:
            raise LanguageValidationError("Transcript cues are out of source order", code="transcript_cues_out_of_order")
        previous_start = start_ms
        cues.append(ParsedCue(len(cues), start_ms, end_ms, cue_text, identifier))
        if len(cues) > MAX_CUES:
            raise LanguageValidationError("Transcript has too many cues", code="transcript_too_large")
    if not cues:
        raise LanguageValidationError("Transcript contains no cues", code="empty_transcript")
    return _with_offsets(cues)


def parse_transcript(value: str, transcript_format: str) -> tuple[str, list[ParsedCue]]:
    if not isinstance(value, str) or not value.strip():
        raise LanguageValidationError("Transcript text is required", details=["transcriptText"])
    if len(value.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
        raise LanguageValidationError("Transcript is too large", code="transcript_too_large")
    kind = str(transcript_format or "PLAIN").upper()
    if kind == "SRT":
        return parse_srt(value)
    if kind == "VTT":
        return parse_vtt(value)
    if kind != "PLAIN":
        raise LanguageValidationError("Unsupported transcript format", code="unsupported_transcript_format")
    return value, []


def canonical_external_url(value: Any, source_type: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LanguageValidationError("sourceUri is required", details=["sourceUri"])
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise LanguageValidationError("External reference URL is invalid", code="invalid_external_reference")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise LanguageValidationError("Local/private destinations are not accepted", code="unsafe_external_reference")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
        if not address.is_global:
            raise LanguageValidationError("Local/private destinations are not accepted", code="unsafe_external_reference")
    except ValueError:
        pass
    if source_type == "NRK_REFERENCE" and host not in {"nrk.no", "www.nrk.no", "radio.nrk.no", "tv.nrk.no"}:
        raise LanguageValidationError("NRK references must use an official NRK host", code="invalid_nrk_reference")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def sniff_audio(data: bytes, declared_mime: str, original_name: str) -> tuple[str, str]:
    mime = str(declared_mime or "").split(";", 1)[0].strip().lower()
    suffix = Path(str(original_name or "")).suffix.lower()
    detected = None
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        detected = "audio/mpeg"
    elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        detected = "audio/wav"
    elif data.startswith(b"OggS"):
        detected = "audio/ogg"
    elif len(data) >= 12 and data[4:8] == b"ftyp":
        detected = "audio/mp4"
    if detected is None:
        raise LanguageValidationError("Audio content is unsupported or does not match its type", code="unsupported_media")
    aliases = {"audio/x-wav": "audio/wav", "audio/x-m4a": "audio/mp4"}
    if mime and aliases.get(mime, mime) != detected:
        raise LanguageValidationError("Declared MIME type does not match audio content", code="media_mime_mismatch")
    expected_suffix = SUPPORTED_AUDIO[detected]
    allowed_suffixes = {expected_suffix}
    if detected == "audio/mpeg":
        allowed_suffixes.add(".mp3")
    if suffix and suffix not in allowed_suffixes:
        raise LanguageValidationError("File extension does not match audio content", code="media_mime_mismatch")
    return detected, expected_suffix


def map_cues_to_sentences(sentences: list[Any], cues: list[Any]) -> list[dict[str, Any]]:
    """Map source cue character spans to canonical sentence spans deterministically."""
    mapped: list[dict[str, Any]] = []
    for sentence in sentences:
        sentence_start, sentence_end = int(sentence["source_start"]), int(sentence["source_end"])
        overlaps = [cue for cue in cues if int(cue["text_end"]) > sentence_start and int(cue["text_start"]) < sentence_end]
        if not overlaps:
            continue
        starts: list[int] = []
        ends: list[int] = []
        cue_ids: list[str] = []
        for cue in overlaps:
            cue_span = max(1, int(cue["text_end"]) - int(cue["text_start"]))
            duration = int(cue["end_ms"]) - int(cue["start_ms"])
            relative_start = max(0, sentence_start - int(cue["text_start"])) / cue_span
            relative_end = min(cue_span, sentence_end - int(cue["text_start"])) / cue_span
            starts.append(int(cue["start_ms"]) + round(duration * relative_start))
            ends.append(int(cue["start_ms"]) + round(duration * max(relative_start, relative_end)))
            cue_ids.append(str(cue["id"]))
        start_ms, end_ms = min(starts), max(ends)
        if end_ms > start_ms:
            mapped.append({
                "sentence_id": str(sentence["id"]), "start_ms": start_ms, "end_ms": end_ms,
                "source_cue_ids": cue_ids,
            })
    return mapped


class ContentInboxService:
    def __init__(self, language_service: Any, media_root: str | Path):
        self.language_service = language_service
        self.store = language_service.store
        self.media_root = Path(media_root).resolve()

    @staticmethod
    def _digest(value: bytes) -> str:
        return "sha256:" + hashlib.sha256(value).hexdigest()

    def _row(self, connection: Any, content_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
        if row is None:
            raise LanguageNotFoundError("Content item was not found", code="content_item_not_found")
        return dict(row)

    def create(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        source_type = str(payload.get("sourceType") or "").upper()
        if source_type not in CONTENT_TYPES:
            raise LanguageValidationError("Unsupported content source type", code="unsupported_content_source")
        title = str(payload.get("title") or "Untitled content").strip()[:500]
        if not title:
            raise LanguageValidationError("title is required", details=["title"])
        now = utc_now()
        if source_type in REFERENCE_TYPES:
            uri = canonical_external_url(payload.get("sourceUri"), source_type)
            fingerprint = self._digest(uri.encode("utf-8"))
            with self.store.connection() as connection:
                existing = connection.execute(
                    "SELECT * FROM content_items WHERE language_profile_id=? AND source_type=? AND content_fingerprint=?",
                    (profile_id, source_type, fingerprint),
                ).fetchone()
                if existing:
                    return self.detail(str(existing["id"]))
                content_id = new_id()
                connection.execute(
                    "INSERT INTO content_items(id,language_profile_id,content_type,title,source_type,source_uri,"
                    "source_name,author_publisher,language_code,rights_status,license,attribution,retention_policy,"
                    "rights_policy_version,ingestion_policy_version,content_fingerprint,status,user_notes,created_at,added_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (content_id, profile_id, source_type, title, source_type, uri,
                     str(payload.get("sourceName") or source_type.replace("_REFERENCE", "")).strip()[:300],
                     str(payload.get("authorPublisher") or "").strip()[:500] or None, "nb",
                     "STORAGE_NOT_AUTHORIZED", None, None, "REFERENCE_ONLY", RIGHTS_POLICY_VERSION,
                     INGESTION_POLICY_VERSION, fingerprint, "REFERENCE_ONLY",
                     str(payload.get("notes") or "").strip()[:5000] or None, now, now, now),
                )
            return self.detail(content_id)
        if source_type == "PASTED_TEXT":
            raw_text = payload.get("text")
            if not isinstance(raw_text, str) or not raw_text:
                raise LanguageValidationError("text is required", details=["text"])
            fingerprint = self._digest(raw_text.encode("utf-8"))
            with self.store.connection() as connection:
                existing = connection.execute(
                    "SELECT * FROM content_items WHERE language_profile_id=? AND source_type=? AND content_fingerprint=?",
                    (profile_id, source_type, fingerprint),
                ).fetchone()
                if existing:
                    return self.detail(str(existing["id"]))
            text_result = self.language_service.create_text_draft({
                "languageProfileId": profile_id, "title": title, "rawText": raw_text,
                "sourceType": "CONTENT_PASTED_TEXT", "sourceReference": None,
            })["data"]["text"]
            fingerprint = str(text_result["contentFingerprint"])
            with self.store.connection() as connection:
                content_id = new_id()
                connection.execute(
                    "INSERT INTO content_items(id,language_profile_id,content_type,title,source_type,source_name,language_code,"
                    "rights_status,retention_policy,rights_policy_version,ingestion_policy_version,content_fingerprint,status,"
                    "text_document_id,created_at,added_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (content_id, profile_id, source_type, title, source_type, "User-provided text", "nb",
                     "USER_PROVIDED_STORAGE_ALLOWED", "KEEP_UNTIL_USER_DELETES", RIGHTS_POLICY_VERSION,
                     INGESTION_POLICY_VERSION, fingerprint, "ANALYZING", text_result["id"], now, now, now),
                )
            self.language_service.enqueue_analysis(str(text_result["id"]), {})
            return self.detail(content_id)
        if source_type in {"LOCAL_TRANSCRIPT", "SRT", "VTT"}:
            transcript_format = source_type if source_type in {"SRT", "VTT"} else str(payload.get("format") or "PLAIN").upper()
            transcript_text = payload.get("transcriptText")
            if not isinstance(transcript_text, str) or not transcript_text.strip():
                raise LanguageValidationError("transcriptText is required", details=["transcriptText"])
            fingerprint = self._digest(transcript_text.encode("utf-8"))
            with self.store.connection() as connection:
                existing = connection.execute(
                    "SELECT * FROM content_items WHERE language_profile_id=? AND source_type=? AND content_fingerprint=?",
                    (profile_id, source_type, fingerprint),
                ).fetchone()
                if existing:
                    return self.detail(str(existing["id"]))
                content_id = new_id()
                connection.execute(
                    "INSERT INTO content_items(id,language_profile_id,content_type,title,source_type,source_name,language_code,"
                    "rights_status,retention_policy,rights_policy_version,ingestion_policy_version,content_fingerprint,status,"
                    "created_at,added_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (content_id, profile_id, "LOCAL_TRANSCRIPT", title, source_type, "User-provided transcript", "nb",
                     "USER_PROVIDED_STORAGE_ALLOWED", "KEEP_UNTIL_USER_DELETES", RIGHTS_POLICY_VERSION,
                     INGESTION_POLICY_VERSION, fingerprint, "IMPORTED", now, now, now),
                )
            return self.add_transcript(content_id, {
                "format": transcript_format, "transcriptText": transcript_text,
                "attribution": payload.get("attribution"),
            })
        raise LanguageValidationError("This source type requires a media or transcript upload", code="content_upload_required")

    def import_audio(self, profile_id: str, *, data: bytes, title: str, original_name: str, mime_type: str) -> dict[str, Any]:
        if not data:
            raise LanguageValidationError("Audio file is empty", code="empty_media")
        if len(data) > MAX_MEDIA_BYTES:
            raise LanguageValidationError("Audio file exceeds the 64 MiB limit", code="media_too_large")
        detected_mime, suffix = sniff_audio(data, mime_type, original_name)
        checksum = self._digest(data)
        with self.store.connection() as connection:
            existing = connection.execute(
                "SELECT ci.id FROM content_artifacts ca JOIN content_items ci ON ci.id=ca.content_id "
                "WHERE ci.language_profile_id=? AND ca.checksum=? AND ca.artifact_type='AUDIO'",
                (profile_id, checksum),
            ).fetchone()
            if existing:
                return self.detail(str(existing["id"]))
        content_id, artifact_id = new_id(), new_id()
        self.media_root.mkdir(parents=True, exist_ok=True)
        target = (self.media_root / f"{artifact_id}{suffix}").resolve()
        if target.parent != self.media_root:
            raise LanguageConflictError("Managed media path is invalid", code="unsafe_media_path")
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
        now = utc_now()
        safe_display = Path(str(original_name or f"audio{suffix}")).name[:255]
        try:
            with self.store.connection() as connection:
                connection.execute(
                    "INSERT INTO content_items(id,language_profile_id,content_type,title,source_type,source_name,language_code,"
                    "rights_status,retention_policy,rights_policy_version,ingestion_policy_version,content_fingerprint,status,"
                    "media_artifact_id,created_at,added_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (content_id, profile_id, "LOCAL_AUDIO", str(title or safe_display).strip()[:500], "LOCAL_AUDIO",
                     "User-owned upload", "nb", "USER_OWNED_STORAGE_ALLOWED", "KEEP_UNTIL_USER_DELETES",
                     RIGHTS_POLICY_VERSION, INGESTION_POLICY_VERSION, checksum, "NEEDS_TRANSCRIPT", artifact_id,
                     now, now, now),
                )
                connection.execute(
                    "INSERT INTO content_artifacts(id,content_id,artifact_type,original_display_name,managed_relpath,mime_type,"
                    "byte_size,checksum,storage_policy,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (artifact_id, content_id, "AUDIO", safe_display, target.name, detected_mime, len(data), checksum,
                     "MANAGED_PRIVATE_FILESYSTEM", now),
                )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return self.detail(content_id)

    def add_transcript(self, content_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        transcript_format = str(payload.get("format") or "PLAIN").upper()
        if transcript_format not in TRANSCRIPT_FORMATS:
            raise LanguageValidationError("Unsupported transcript format", code="unsupported_transcript_format")
        projection, cues = parse_transcript(payload.get("transcriptText"), transcript_format)
        checksum = self._digest(str(payload.get("transcriptText")).encode("utf-8"))
        with self.store.connection() as connection:
            content = self._row(connection, content_id)
            if content["rights_status"] == "STORAGE_NOT_AUTHORIZED":
                raise LanguageConflictError("This reference does not authorize storing transcript text", code="storage_not_authorized")
            existing = connection.execute(
                "SELECT * FROM transcripts WHERE content_id=? AND source_fingerprint=?", (content_id, checksum),
            ).fetchone()
            if existing:
                return self.detail(content_id)
            next_version = int(connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM transcripts WHERE content_id=?", (content_id,),
            ).fetchone()[0])
        text = self.language_service.create_text_draft({
            "languageProfileId": content["language_profile_id"], "title": content["title"], "rawText": projection,
            "sourceType": "CONTENT_TRANSCRIPT", "sourceReference": f"content:{content_id}:transcript:v{next_version}",
        })["data"]["text"]
        transcript_id = new_id()
        now = utc_now()
        source_type = {"SRT": "SRT", "VTT": "VTT"}.get(transcript_format, "USER_PROVIDED_TEXT")
        method = {"SRT": "IMPORTED_SRT", "VTT": "IMPORTED_VTT"}.get(transcript_format, "USER_PROVIDED_TEXT")
        with self.store.connection() as connection:
            connection.execute("UPDATE transcripts SET is_current=0 WHERE content_id=?", (content_id,))
            connection.execute(
                "INSERT INTO transcripts(id,content_id,text_document_id,version,source_type,format,source_fingerprint,method,"
                "confidence_basis,edit_state,attribution,segmentation_version,is_current,created_at,imported_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (transcript_id, content_id, text["id"], next_version, source_type, transcript_format, checksum, method,
                 "CONFIDENCE_NOT_REPORTED", "ORIGINAL", str(payload.get("attribution") or "").strip()[:1000] or None,
                 TRANSCRIPT_SEGMENTATION_VERSION, 1, now, now),
            )
            for cue in cues:
                connection.execute(
                    "INSERT INTO transcript_cues(id,transcript_id,cue_order,start_ms,end_ms,cue_text,source_identifier,"
                    "text_start,text_end,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), transcript_id, cue.order, cue.start_ms, cue.end_ms, cue.text,
                     cue.source_identifier, cue.text_start, cue.text_end, now),
                )
            status = "ANALYZING"
            connection.execute(
                "UPDATE content_items SET text_document_id=?,current_transcript_id=?,content_type=?,status=?,updated_at=? WHERE id=?",
                (text["id"], transcript_id, "LOCAL_AUDIO_PLUS_TRANSCRIPT" if content.get("media_artifact_id") else "LOCAL_TRANSCRIPT",
                 status, now, content_id),
            )
        self.language_service.enqueue_analysis(str(text["id"]), {})
        return self.detail(content_id)

    def refresh_alignment_for_text(self, text_document_id: str) -> None:
        with self.store.connection() as connection:
            # A completed analysis can be observed just before the worker's refresh returns.
            # Serialize that worker refresh with any detail-triggered recovery refresh.
            connection.execute("BEGIN IMMEDIATE")
            transcript = connection.execute(
                "SELECT * FROM transcripts WHERE text_document_id=? AND is_current=1", (text_document_id,),
            ).fetchone()
            if transcript is None:
                connection.execute(
                    "UPDATE content_items SET status='READY_READER',updated_at=? "
                    "WHERE text_document_id=? AND current_transcript_id IS NULL",
                    (utc_now(), text_document_id),
                )
                return
            content = self._row(connection, str(transcript["content_id"]))
            sentences = connection.execute(
                "SELECT * FROM text_sentences WHERE text_document_id=? ORDER BY sentence_order", (text_document_id,),
            ).fetchall()
            cues = connection.execute(
                "SELECT * FROM transcript_cues WHERE transcript_id=? ORDER BY cue_order", (transcript["id"],),
            ).fetchall()
            now = utc_now()
            if not cues:
                connection.execute(
                    "UPDATE content_items SET status=?,updated_at=? WHERE id=?",
                    ("NEEDS_ALIGNMENT" if content.get("media_artifact_id") else "READY_READER", now, content["id"]),
                )
                return
            mapped_windows = {item["sentence_id"]: item for item in map_cues_to_sentences(sentences, cues)}
            for sentence in sentences:
                current_alignment = connection.execute(
                    "SELECT * FROM sentence_alignments WHERE transcript_id=? AND sentence_id=? AND is_current=1",
                    (transcript["id"], sentence["id"]),
                ).fetchone()
                if current_alignment and current_alignment["method"] in {"MANUAL", "USER_CORRECTED"}:
                    continue
                window = mapped_windows.get(str(sentence["id"]))
                if window is None:
                    continue
                start_ms, end_ms = window["start_ms"], window["end_ms"]
                source_cue_ids_json = canonical_json(window["source_cue_ids"])
                if (
                    current_alignment
                    and int(current_alignment["start_ms"]) == start_ms
                    and int(current_alignment["end_ms"]) == end_ms
                    and current_alignment["method"] == transcript["method"]
                    and current_alignment["source_cue_ids_json"] == source_cue_ids_json
                ):
                    continue
                version = int(connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM sentence_alignments "
                    "WHERE transcript_id=? AND sentence_id=?",
                    (transcript["id"], sentence["id"]),
                ).fetchone()[0])
                connection.execute(
                    "UPDATE sentence_alignments SET is_current=0 WHERE transcript_id=? AND sentence_id=? AND is_current=1",
                    (transcript["id"], sentence["id"]),
                )
                connection.execute(
                    "INSERT INTO sentence_alignments(id,content_id,transcript_id,text_document_id,sentence_id,version,start_ms,end_ms,"
                    "source_start_ms,source_end_ms,method,policy_version,confidence,confidence_basis,exposure_eligible,"
                    "source_cue_ids_json,is_current,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), content["id"], transcript["id"], text_document_id, sentence["id"], version, start_ms, end_ms,
                     start_ms, end_ms, transcript["method"], TRANSCRIPT_ALIGNMENT_VERSION, None,
                     "CONFIDENCE_NOT_REPORTED", 1, source_cue_ids_json, 1, now, now),
                )
            aligned = int(connection.execute(
                "SELECT COUNT(*) FROM sentence_alignments WHERE transcript_id=? AND is_current=1", (transcript["id"],),
            ).fetchone()[0])
            status = "READY_LISTENING" if content.get("media_artifact_id") and aligned else "READY_READER"
            connection.execute("UPDATE content_items SET status=?,updated_at=? WHERE id=?", (status, now, content["id"]))

    def correct_alignment(self, alignment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        start_ms, end_ms = payload.get("startMs"), payload.get("endMs")
        if isinstance(start_ms, bool) or isinstance(end_ms, bool) or not isinstance(start_ms, int) or not isinstance(end_ms, int):
            raise LanguageValidationError("Alignment times must be integers", details=["startMs", "endMs"])
        if start_ms < 0 or end_ms <= start_ms or end_ms > MAX_MEDIA_DURATION_MS:
            raise LanguageValidationError("Alignment range is invalid", code="invalid_alignment_range")
        with self.store.connection() as connection:
            current = connection.execute("SELECT * FROM sentence_alignments WHERE id=?", (alignment_id,)).fetchone()
            if current is None:
                raise LanguageNotFoundError("Alignment was not found", code="alignment_not_found")
            version = int(connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM sentence_alignments WHERE transcript_id=? AND sentence_id=?",
                (current["transcript_id"], current["sentence_id"]),
            ).fetchone()[0])
            now = utc_now()
            connection.execute(
                "UPDATE sentence_alignments SET is_current=0,updated_at=? WHERE transcript_id=? AND sentence_id=? AND is_current=1",
                (now, current["transcript_id"], current["sentence_id"]),
            )
            new_alignment_id = new_id()
            connection.execute(
                "INSERT INTO sentence_alignments(id,content_id,transcript_id,text_document_id,sentence_id,version,start_ms,end_ms,"
                "source_start_ms,source_end_ms,method,policy_version,confidence,confidence_basis,exposure_eligible,"
                "source_cue_ids_json,supersedes_alignment_id,is_current,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_alignment_id, current["content_id"], current["transcript_id"], current["text_document_id"],
                 current["sentence_id"], version, start_ms, end_ms, current["source_start_ms"], current["source_end_ms"],
                 "USER_CORRECTED", TRANSCRIPT_ALIGNMENT_VERSION, None, "USER_PROVIDED", 1,
                 current["source_cue_ids_json"], alignment_id, 1, now, now),
            )
        return self.detail(str(current["content_id"]))

    def list(self, profile_id: str, limit: int = 100) -> dict[str, Any]:
        with self.store.connection() as connection:
            rows = connection.execute(
                "SELECT ci.*,ca.mime_type,ca.byte_size,t.version AS transcript_version,t.format AS transcript_format,"
                "d.processing_state FROM content_items ci LEFT JOIN content_artifacts ca ON ca.id=ci.media_artifact_id "
                "LEFT JOIN transcripts t ON t.id=ci.current_transcript_id LEFT JOIN text_documents d ON d.id=ci.text_document_id "
                "WHERE ci.language_profile_id=? ORDER BY ci.added_at DESC,ci.id LIMIT ?",
                (profile_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return {"items": [self.store.api_row(dict(row)) for row in rows], "total": len(rows),
                "rightsPolicyVersion": RIGHTS_POLICY_VERSION, "ingestionPolicyVersion": INGESTION_POLICY_VERSION}

    def detail(self, content_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            item = self._row(connection, content_id)
            artifact = connection.execute("SELECT * FROM content_artifacts WHERE id=?", (item.get("media_artifact_id"),)).fetchone()
            transcripts = connection.execute(
                "SELECT * FROM transcripts WHERE content_id=? ORDER BY version DESC", (content_id,),
            ).fetchall()
            alignments = connection.execute(
                "SELECT a.*,s.sentence_order,s.exact_text FROM sentence_alignments a JOIN text_sentences s ON s.id=a.sentence_id "
                "WHERE a.content_id=? AND a.is_current=1 ORDER BY s.sentence_order LIMIT 5000", (content_id,),
            ).fetchall()
            current_transcript = next((dict(row) for row in transcripts if row["is_current"]), None)
            document = connection.execute("SELECT * FROM text_documents WHERE id=?", (item.get("text_document_id"),)).fetchone()
            latest_job = connection.execute(
                "SELECT * FROM language_jobs WHERE text_document_id=? AND analysis_domain='TEXT' ORDER BY created_at DESC,id DESC LIMIT 1",
                (item.get("text_document_id"),),
            ).fetchone() if item.get("text_document_id") else None
        if document and document["processing_state"] == "ANALYZED" and (not current_transcript or not alignments):
            self.refresh_alignment_for_text(str(document["id"]))
            with self.store.connection() as connection:
                item = self._row(connection, content_id)
                alignments = connection.execute(
                    "SELECT a.*,s.sentence_order,s.exact_text FROM sentence_alignments a JOIN text_sentences s ON s.id=a.sentence_id "
                    "WHERE a.content_id=? AND a.is_current=1 ORDER BY s.sentence_order LIMIT 5000", (content_id,),
                ).fetchall()
        elif latest_job and latest_job["state"] in {"FAILED", "CANCELLED"} and item["status"] == "ANALYZING":
            with self.store.connection() as connection:
                connection.execute(
                    "UPDATE content_items SET status=?,updated_at=? WHERE id=?",
                    ("FAILED", utc_now(), content_id),
                )
                item = self._row(connection, content_id)
        coverage = None
        reference_profile = None
        if document and document["processing_state"] == "ANALYZED":
            text_payload = self.language_service.get_text(str(document["id"]))["data"]
            coverage = text_payload.get("coverage")
            reference_profile = text_payload.get("referenceProfile")
        media = self.store.api_row(dict(artifact)) if artifact else None
        if media:
            media["url"] = f"/api/language/content/media/{artifact['id']}"
        return {
            "item": self.store.api_row(item), "media": media,
            "transcripts": [self.store.api_row(dict(row)) for row in transcripts],
            "currentTranscript": self.store.api_row(current_transcript),
            "alignments": [self.store.api_row(dict(row)) for row in alignments],
            "document": self.store.api_row(dict(document)) if document else None,
            "latestJob": self.store.api_row(dict(latest_job)) if latest_job else None,
            "coverage": coverage, "referenceProfile": reference_profile,
            "forcedAlignment": {"state": "DEFERRED", "reason": "NO_DEFENSIBLE_LOCAL_PROVIDER_SELECTED"},
            "rightsPolicyVersion": RIGHTS_POLICY_VERSION, "ingestionPolicyVersion": INGESTION_POLICY_VERSION,
            "alignmentPolicyVersion": TRANSCRIPT_ALIGNMENT_VERSION,
        }

    def media_file(self, artifact_id: str) -> tuple[Path, str]:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM content_artifacts WHERE id=? AND artifact_type='AUDIO'", (artifact_id,),
            ).fetchone()
        if row is None:
            raise LanguageNotFoundError("Managed media was not found", code="managed_media_not_found")
        path = (self.media_root / str(row["managed_relpath"])).resolve()
        if path.parent != self.media_root or not path.is_file():
            raise LanguageNotFoundError("Managed media was not found", code="managed_media_not_found")
        return path, str(row["mime_type"])

    def alignment_for_event(self, text_id: str, sentence_id: str, alignment_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT a.* FROM sentence_alignments a JOIN content_items ci ON ci.id=a.content_id "
                "WHERE a.id=? AND a.text_document_id=? AND a.sentence_id=? AND a.is_current=1 "
                "AND ci.media_artifact_id IS NOT NULL",
                (alignment_id, text_id, sentence_id),
            ).fetchone()
        if row is None:
            raise LanguageConflictError("Authentic listening requires a current managed alignment", code="invalid_authentic_alignment")
        return dict(row)


__all__ = [
    "AUTHENTIC_LISTENING_EXPOSURE_POLICY_VERSION", "ContentInboxService", "INGESTION_POLICY_VERSION",
    "MAX_MEDIA_BYTES", "MAX_TRANSCRIPT_BYTES", "RIGHTS_POLICY_VERSION", "TRANSCRIPT_ALIGNMENT_VERSION",
    "TRANSCRIPT_SEGMENTATION_VERSION", "canonical_external_url", "parse_srt", "parse_transcript", "parse_vtt",
    "map_cues_to_sentences", "sniff_audio",
]

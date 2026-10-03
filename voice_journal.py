"""Local-only audio validation and Whisper transcription for the voice journal."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path

from voice_journal_options import transcription_options_capabilities
from voice_journal_engines import DEFAULT_ENGINE, OPENAI_ENGINE, faster_whisper_health


RECOMMENDED_MODEL = "small"
SUPPORTED_MODELS = ("small", "medium", "turbo")
SUPPORTED_TASKS = {"transcribe", "translate"}
SUPPORTED_DEVICES = {"auto", "cpu", "cuda"}
MAX_AUDIO_BYTES = 250 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_AUDIO_BYTES + 9 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 90 * 60

ALLOWED_AUDIO_TYPES = {
    # Windows commonly identifies ADTS AAC files as audio/vnd.dlna.adts.
    ".aac": {"audio/aac", "audio/x-aac", "audio/vnd.dlna.adts"},
    ".flac": {"audio/flac", "audio/x-flac"},
    ".m4a": {"audio/mp4", "audio/x-m4a"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".mp4": {"audio/mp4", "video/mp4"},
    ".oga": {"audio/ogg", "application/ogg"},
    ".ogg": {"audio/ogg", "application/ogg"},
    ".opus": {"audio/opus", "audio/ogg"},
    ".wav": {"audio/wav", "audio/wave", "audio/x-wav"},
    ".webm": {"audio/webm", "video/webm"},
}


class VoiceJournalError(Exception):
    def __init__(self, message: str, *, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict:
        return {"error": str(self), "code": self.code}


_MODEL_LOCK = threading.RLock()
_LOADED_MODEL = None
_LOADED_MODEL_KEY = None
_VERIFIED_CHECKPOINTS: set[tuple[str, int, int]] = set()


def whisper_cache_dir() -> Path:
    default_cache = Path.home() / ".cache"
    return Path(os.environ.get("XDG_CACHE_HOME", default_cache)) / "whisper"


def _whisper_module():
    import whisper

    return whisper


def _torch_module():
    import torch

    return torch


def _binary_details(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        return {"available": False, "path": None, "version": None}
    try:
        completed = subprocess.run(
            [path, "-version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        first_line = (completed.stdout or completed.stderr or "").splitlines()
        version = first_line[0].strip() if first_line else None
        return {
            "available": completed.returncode == 0,
            "path": str(Path(path).resolve()),
            "version": version,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "path": str(path), "version": None, "error": str(exc)}


def _checkpoint_filename(whisper_module, model_name: str) -> str | None:
    url = getattr(whisper_module, "_MODELS", {}).get(model_name)
    if not url:
        return None
    return Path(urllib.parse.urlparse(url).path).name


def _model_download_marker(model_name: str) -> Path:
    return whisper_cache_dir().resolve() / f".{model_name}.download-pending"


def _cached_models(whisper_module, cache_dir: Path) -> list[str]:
    cached = []
    for model_name in SUPPORTED_MODELS:
        filename = _checkpoint_filename(whisper_module, model_name)
        if filename and (cache_dir / filename).is_file() and not _model_download_marker(model_name).is_file():
            cached.append(model_name)
    return cached


def voice_journal_health() -> dict:
    ffmpeg = _binary_details("ffmpeg")
    ffprobe = _binary_details("ffprobe")
    cache_dir = whisper_cache_dir().resolve()
    errors = []

    try:
        whisper_module = _whisper_module()
        whisper_version = importlib.metadata.version("openai-whisper")
        available_models = list(whisper_module.available_models())
        cached_models = _cached_models(whisper_module, cache_dir)
        transcription_options = transcription_options_capabilities(whisper_module)
    except Exception as exc:
        whisper_version = None
        available_models = []
        cached_models = []
        transcription_options = {"supported": [], "specs": {}, "presets": {}, "recommendedPreset": "balanced"}
        errors.append(f"Whisper unavailable: {exc}")

    try:
        torch = _torch_module()
        cuda_available = bool(torch.cuda.is_available())
        gpu = {
            "available": cuda_available,
            "name": torch.cuda.get_device_name(0) if cuda_available else None,
            "deviceCount": int(torch.cuda.device_count()) if cuda_available else 0,
            "cudaVersion": torch.version.cuda,
        }
        pytorch = {"version": str(torch.__version__), "cudaAvailable": cuda_available}
    except Exception as exc:
        gpu = {"available": False, "name": None, "deviceCount": 0, "cudaVersion": None}
        pytorch = {"version": None, "cudaAvailable": False}
        errors.append(f"PyTorch unavailable: {exc}")

    if not ffmpeg["available"]:
        errors.append("FFmpeg unavailable")
    if not ffprobe["available"]:
        errors.append("ffprobe unavailable")

    cpu_name = platform.processor().strip() or os.environ.get("PROCESSOR_IDENTIFIER", "").strip()
    openai_engine = {
        "id": OPENAI_ENGINE,
        "label": "OpenAI Whisper (dotychczasowy)",
        "available": whisper_version is not None,
        "version": whisper_version,
        "error": next((error for error in errors if error.startswith("Whisper unavailable")), None),
        "supportedModels": list(SUPPORTED_MODELS),
        "cachedModels": cached_models,
        "recommendedModel": RECOMMENDED_MODEL,
        "supportedLanguages": ["auto", "pl"],
        "supportedTasks": sorted(SUPPORTED_TASKS),
        "computeTypes": [],
        "transcriptionOptions": transcription_options,
    }
    faster_engine = faster_whisper_health()
    return {
        "status": "ok" if not errors else "degraded",
        "whisperVersion": whisper_version,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "pytorch": pytorch,
        "cpu": {
            "name": cpu_name or platform.machine(),
            "logicalCores": os.cpu_count(),
        },
        "gpu": gpu,
        "availableModels": available_models,
        "supportedModels": list(SUPPORTED_MODELS),
        "cachedModels": cached_models,
        "supportedLanguages": ["auto", "pl"],
        "supportedTasks": sorted(SUPPORTED_TASKS),
        "supportedDevices": ["auto", "cpu"] + (["cuda"] if gpu["available"] else []),
        "maxUploadBytes": MAX_AUDIO_BYTES,
        "maxDurationSeconds": MAX_AUDIO_DURATION_SECONDS,
        "cacheDirectory": str(cache_dir),
        "recommendedModel": RECOMMENDED_MODEL,
        "transcriptionOptions": transcription_options,
        "defaultEngine": DEFAULT_ENGINE,
        "engines": [openai_engine, faster_engine],
        "errors": errors,
    }


def parse_multipart_form(
    content_type: str,
    body: bytes,
    *,
    allowed_fields: set[str],
    max_field_bytes: int = 64,
) -> tuple[dict, dict[str, str]]:
    if not content_type or not content_type.lower().startswith("multipart/form-data"):
        raise VoiceJournalError(
            "Content-Type must be multipart/form-data",
            status=415,
            code="unsupported_media_type",
        )
    if len(body) > MAX_MULTIPART_BYTES:
        raise VoiceJournalError("Upload is too large", status=413, code="payload_too_large")
    try:
        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
    except UnicodeEncodeError as exc:
        raise VoiceJournalError("Invalid multipart Content-Type") from exc

    message = BytesParser(policy=policy.default).parsebytes(header + body)
    if not message.is_multipart():
        raise VoiceJournalError("Invalid multipart body")

    audio_part = None
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            if field_name not in {"file", "audio"}:
                raise VoiceJournalError("The audio file field must be named 'file' or 'audio'")
            if audio_part is not None:
                raise VoiceJournalError("Exactly one audio file is allowed")
            audio_part = {
                "filename": filename,
                "mime": part.get_content_type().lower(),
                "content": payload,
            }
            continue
        if field_name not in allowed_fields:
            raise VoiceJournalError(f"Unknown form field: {field_name or '<empty>'}")
        if field_name in fields:
            raise VoiceJournalError(f"Duplicate form field: {field_name}")
        if len(payload) > max_field_bytes:
            raise VoiceJournalError(f"Form field is too long: {field_name}")
        try:
            fields[field_name] = payload.decode(part.get_content_charset() or "utf-8").strip()
        except UnicodeDecodeError as exc:
            raise VoiceJournalError(f"Invalid text encoding for field: {field_name}") from exc

    if audio_part is None:
        raise VoiceJournalError("A single audio file is required")
    return audio_part, fields


def _parse_multipart(content_type: str, body: bytes) -> tuple[dict, dict[str, str]]:
    return parse_multipart_form(
        content_type,
        body,
        allowed_fields={"model", "language", "task", "device"},
    )


def validate_audio_part(audio_part: dict) -> str:
    filename = str(audio_part.get("filename") or "")
    if not filename or "\x00" in filename or "/" in filename or "\\" in filename:
        raise VoiceJournalError("Unsafe audio filename", code="unsafe_filename")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_TYPES:
        raise VoiceJournalError("Unsupported audio extension", status=415, code="unsupported_extension")
    mime = str(audio_part.get("mime") or "").lower()
    # Browsers on Windows derive AAC MIME from local file associations. Depending
    # on the installed player this can be audio/vnd.dlna.adts, another audio/*
    # subtype, or the generic application/octet-stream. The extension remains
    # whitelisted and ffprobe still verifies the actual audio stream afterwards.
    flexible_aac_mime = suffix == ".aac" and (
        mime.startswith("audio/") or mime == "application/octet-stream"
    )
    if mime not in ALLOWED_AUDIO_TYPES[suffix] and not flexible_aac_mime:
        raise VoiceJournalError(
            f"Audio MIME type '{mime or '<empty>'}' does not match the {suffix} file extension",
            status=415,
            code="mime_mismatch",
        )
    size = len(audio_part.get("content") or b"")
    if size == 0:
        raise VoiceJournalError("Audio file is empty")
    if size > MAX_AUDIO_BYTES:
        raise VoiceJournalError("Audio file is too large", status=413, code="payload_too_large")
    return suffix


_validate_audio_part = validate_audio_part


def _validate_options(fields: dict[str, str]) -> tuple[str, str | None, str, str]:
    model_name = fields.get("model", "").lower()
    if not model_name:
        raise VoiceJournalError("Model is required")
    if model_name not in SUPPORTED_MODELS:
        raise VoiceJournalError(
            f"Unsupported model. Allowed models: {', '.join(SUPPORTED_MODELS)}",
            code="unsupported_model",
        )

    requested_language = (fields.get("language") or "pl").lower()
    if requested_language == "auto":
        language = None
    else:
        language = requested_language
        try:
            from whisper.tokenizer import LANGUAGES

            valid_language = language in LANGUAGES
        except Exception:
            valid_language = language == "pl"
        if not valid_language:
            raise VoiceJournalError("Unsupported language", code="unsupported_language")

    task = (fields.get("task") or "transcribe").lower()
    if task not in SUPPORTED_TASKS:
        raise VoiceJournalError("Task must be 'transcribe' or 'translate'", code="unsupported_task")

    requested_device = (fields.get("device") or "auto").lower()
    if requested_device not in SUPPORTED_DEVICES:
        raise VoiceJournalError("Device must be auto, cpu or cuda", code="unsupported_device")
    return model_name, language, task, requested_device


def resolve_device(requested_device: str) -> str:
    torch = _torch_module()
    cuda_available = bool(torch.cuda.is_available())
    if requested_device == "cuda" and not cuda_available:
        raise VoiceJournalError("CUDA is not available in the installed PyTorch", code="cuda_unavailable")
    if requested_device == "auto":
        return "cuda" if cuda_available else "cpu"
    return requested_device


def probe_audio(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise VoiceJournalError("ffprobe is not available", status=503, code="ffprobe_unavailable")
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name,sample_rate,channels:format=format_name,duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise VoiceJournalError("ffprobe timed out", status=422, code="invalid_audio") from exc
    except OSError as exc:
        raise VoiceJournalError("ffprobe could not inspect the file", status=503, code="ffprobe_unavailable") from exc
    if completed.returncode != 0:
        raise VoiceJournalError("File is not valid audio", status=422, code="invalid_audio")
    try:
        payload = json.loads(completed.stdout)
        stream = (payload.get("streams") or [])[0]
        format_data = payload.get("format") or {}
        duration = float(format_data.get("duration"))
        sample_rate = int(stream.get("sample_rate"))
        channels = int(stream.get("channels"))
        codec = str(stream.get("codec_name") or "").strip()
        format_name = str(format_data.get("format_name") or "").strip()
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise VoiceJournalError("File has no valid audio stream", status=422, code="invalid_audio") from exc
    if not codec or not format_name or not math.isfinite(duration) or duration <= 0 or sample_rate <= 0 or channels <= 0:
        raise VoiceJournalError("File has invalid audio metadata", status=422, code="invalid_audio")
    if duration > MAX_AUDIO_DURATION_SECONDS:
        raise VoiceJournalError("Audio duration exceeds 90 minutes", status=413, code="audio_too_long")
    return {
        "durationSeconds": duration,
        "format": format_name,
        "codec": codec,
        "sampleRate": sample_rate,
        "channels": channels,
    }


def _checkpoint_path(whisper_module, model_name: str) -> tuple[Path, str]:
    url = getattr(whisper_module, "_MODELS", {}).get(model_name)
    filename = _checkpoint_filename(whisper_module, model_name)
    if not url or not filename:
        raise VoiceJournalError("Whisper model metadata is unavailable", status=500, code="model_metadata_error")
    checkpoint = (whisper_cache_dir().resolve() / filename).resolve()
    cache_root = whisper_cache_dir().resolve()
    if checkpoint.parent != cache_root:
        raise VoiceJournalError("Unsafe model cache path", status=500, code="unsafe_model_path")
    expected_hash = Path(urllib.parse.urlparse(url).path).parent.name.lower()
    return checkpoint, expected_hash


def _verify_cached_checkpoint(path: Path, expected_hash: str) -> None:
    if not path.is_file():
        raise VoiceJournalError(
            f"Model is not present in the local Whisper cache: {path.name}",
            status=409,
            code="model_not_cached",
        )
    stat = path.stat()
    cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
    if cache_key in _VERIFIED_CHECKPOINTS:
        return
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if expected_hash and digest.hexdigest().lower() != expected_hash:
        raise VoiceJournalError(
            "Cached Whisper model has an invalid checksum",
            status=409,
            code="invalid_model_cache",
        )
    _VERIFIED_CHECKPOINTS.add(cache_key)


def _get_model(model_name: str, device: str, *, allow_download: bool = False):
    global _LOADED_MODEL, _LOADED_MODEL_KEY

    key = (model_name, device)
    if _LOADED_MODEL is not None and _LOADED_MODEL_KEY == key:
        return _LOADED_MODEL
    whisper_module = _whisper_module()
    checkpoint, expected_hash = _checkpoint_path(whisper_module, model_name)
    marker = _model_download_marker(model_name)
    if allow_download and (not checkpoint.is_file() or marker.is_file()):
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.is_file() and checkpoint.is_file():
            checkpoint.unlink(missing_ok=True)
        marker.write_text("download pending", encoding="utf-8")
        try:
            loaded_model = whisper_module.load_model(
                model_name,
                device=device,
                download_root=str(whisper_cache_dir().resolve()),
            )
            _verify_cached_checkpoint(checkpoint, expected_hash)
        except Exception:
            raise
        else:
            marker.unlink(missing_ok=True)
            _LOADED_MODEL = loaded_model
            _LOADED_MODEL_KEY = key
            return _LOADED_MODEL
    _verify_cached_checkpoint(checkpoint, expected_hash)
    # Passing the verified checkpoint path guarantees that Whisper cannot
    # download a missing model as a side effect of this local-only endpoint.
    _LOADED_MODEL = whisper_module.load_model(str(checkpoint), device=device)
    _LOADED_MODEL_KEY = key
    return _LOADED_MODEL


def transcribe_multipart(content_type: str, body: bytes) -> dict:
    audio_part, fields = _parse_multipart(content_type, body)
    suffix = _validate_audio_part(audio_part)
    model_name, language, task, requested_device = _validate_options(fields)
    device = resolve_device(requested_device)

    with tempfile.TemporaryDirectory(prefix="voice-journal-") as temp_directory:
        temp_root = Path(temp_directory).resolve()
        audio_path = (temp_root / f"{uuid.uuid4().hex}{suffix}").resolve()
        if audio_path.parent != temp_root:
            raise VoiceJournalError("Unsafe temporary path", status=500, code="unsafe_temporary_path")
        audio_path.write_bytes(audio_part["content"])
        metadata = probe_audio(audio_path)

        started = time.perf_counter()
        with _MODEL_LOCK:
            model = _get_model(model_name, device)
            result = model.transcribe(
                str(audio_path),
                language=language,
                task=task,
                fp16=device == "cuda",
            )
        elapsed = time.perf_counter() - started

    transcript = str((result or {}).get("text") or "").strip()
    duration = metadata["durationSeconds"]
    return {
        "transcript": transcript,
        "transcriptSegments": normalize_transcript_segments(result),
        **metadata,
        "sizeBytes": len(audio_part["content"]),
        "model": model_name,
        "device": device,
        "transcriptionDurationSeconds": round(elapsed, 3),
        "realTimeFactor": round(elapsed / duration, 4),
    }


def normalize_transcription_data_segments(result) -> list[dict]:
    """Return additive, correction-safe OpenAI Whisper segment data."""
    raw_segments = (result or {}).get("segments") if isinstance(result, dict) else None
    if not isinstance(raw_segments, list):
        return []
    segments = []
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            continue
        try:
            start = float(raw.get("start"))
            end = float(raw.get("end"))
        except (TypeError, ValueError):
            continue
        text = str(raw.get("text") or "").strip()
        if not text or not math.isfinite(start) or not math.isfinite(end) or start < 0:
            continue
        segment_id = f"segment-{index + 1}"
        words = []
        raw_words = raw.get("words") if isinstance(raw.get("words"), list) else []
        for word_index, raw_word in enumerate(raw_words):
            if not isinstance(raw_word, dict):
                continue
            word_text = str(raw_word.get("word") or raw_word.get("text") or "")
            probability = raw_word.get("probability")
            try:
                probability = float(probability) if probability is not None else None
            except (TypeError, ValueError):
                probability = None
            try:
                word_start = float(raw_word.get("start"))
                word_end = float(raw_word.get("end"))
                valid_time = math.isfinite(word_start) and math.isfinite(word_end) and word_start >= 0 and word_end >= word_start
            except (TypeError, ValueError):
                valid_time = False
                word_start = word_end = None
            words.append({
                "id": f"{segment_id}-word-{word_index + 1}",
                "text": word_text,
                "originalText": word_text,
                "correctedText": word_text,
                "start": round(word_start, 3) if valid_time else None,
                "end": round(word_end, 3) if valid_time else None,
                "probability": round(probability, 6) if probability is not None and math.isfinite(probability) else None,
                "correctionStatus": "original",
                "manuallyChanged": False,
            })
        avg_logprob = raw.get("avg_logprob")
        no_speech_prob = raw.get("no_speech_prob")
        try:
            avg_logprob = float(avg_logprob) if avg_logprob is not None else None
        except (TypeError, ValueError):
            avg_logprob = None
        try:
            no_speech_prob = float(no_speech_prob) if no_speech_prob is not None else None
        except (TypeError, ValueError):
            no_speech_prob = None
        segments.append({
            "id": segment_id,
            "start": round(start, 3),
            "end": round(max(start, end), 3),
            "text": text,
            "originalText": text,
            "correctedText": text,
            "avgLogprob": avg_logprob if avg_logprob is None or math.isfinite(avg_logprob) else None,
            "noSpeechProbability": no_speech_prob if no_speech_prob is None or math.isfinite(no_speech_prob) else None,
            "correctionStatus": "original",
            "words": words,
        })
    return segments


def normalize_transcript_segments(result) -> list[dict]:
    """Preserve the original public segment schema for backwards compatibility."""
    return [
        {"start": segment["start"], "end": segment["end"], "text": segment["text"]}
        for segment in normalize_transcription_data_segments(result)
    ]

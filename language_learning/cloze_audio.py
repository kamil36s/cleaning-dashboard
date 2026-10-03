"""Server-side Google Chirp 3 HD audio generation for frozen Cloze sentences."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid
from typing import Any, Mapping

from .errors import LanguageError, LanguageNotFoundError, LanguageStorageError, LanguageValidationError
from .store import LanguageStore, canonical_json, utc_now


TTS_LANGUAGE = "nb-NO"
TTS_PROVIDER = "GOOGLE_CLOUD_TTS"
TTS_AUDIO_ENCODING = "MP3"
TTS_CONFIG_VERSION = "language.cloze-audio-google/v1"
DEFAULT_TTS_VOICE = "nb-NO-Chirp3-HD-Kore"
GOOGLE_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
VOICE_RE = re.compile(r"nb-NO-Chirp3-HD-[A-Za-z0-9-]+")
CACHE_KEY_RE = re.compile(r"[a-f0-9]{64}")


class ClozeAudioError(LanguageError):
    pass


class GoogleCloudChirpProvider:
    """Small REST adapter using Application Default Credentials."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 45,
        credentials_loader: Any | None = None,
        session_factory: Any | None = None,
    ):
        self.environment = environment if environment is not None else os.environ
        self.timeout_seconds = timeout_seconds
        self.credentials_loader = credentials_loader
        self.session_factory = session_factory

    def synthesize(self, *, text: str, language_code: str, voice_id: str, audio_encoding: str) -> bytes:
        if self.credentials_loader is None or self.session_factory is None:
            try:
                import google.auth
                from google.auth.exceptions import DefaultCredentialsError
                from google.auth.transport.requests import AuthorizedSession
            except ImportError as exc:
                raise ClozeAudioError(
                    "Google Cloud authentication support is not installed",
                    code="cloze_audio_dependency_missing",
                    status=503,
                ) from exc
            credentials_loader = google.auth.default
            session_factory = AuthorizedSession
            credential_errors = (DefaultCredentialsError,)
        else:
            credentials_loader = self.credentials_loader
            session_factory = self.session_factory
            credential_errors = ()

        project = str(self.environment.get("GOOGLE_CLOUD_PROJECT") or "").strip() or None
        try:
            credentials, _ = credentials_loader(
                scopes=[GOOGLE_CLOUD_SCOPE], quota_project_id=project,
            )
        except credential_errors as exc:
            raise ClozeAudioError(
                "Google Cloud TTS credentials are not configured",
                code="cloze_audio_credentials_missing",
                status=503,
            ) from exc

        session = session_factory(credentials)
        try:
            response = session.post(
                GOOGLE_TTS_ENDPOINT,
                json={
                    "input": {"text": text},
                    "voice": {"languageCode": language_code, "name": voice_id},
                    "audioConfig": {"audioEncoding": audio_encoding},
                },
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise ClozeAudioError(
                "Google Cloud TTS request failed",
                code="cloze_audio_provider_unavailable",
                status=502,
            ) from exc
        finally:
            session.close()

        if not response.ok:
            if response.status_code == 429:
                raise ClozeAudioError(
                    "Google Cloud TTS quota or rate limit was reached",
                    code="cloze_audio_quota_limit",
                    status=429,
                )
            if response.status_code in {401, 403}:
                raise ClozeAudioError(
                    "Google Cloud TTS authentication failed",
                    code="cloze_audio_credentials_invalid",
                    status=503,
                )
            raise ClozeAudioError(
                f"Google Cloud TTS returned HTTP {response.status_code}",
                code="cloze_audio_provider_error",
                status=502,
            )
        try:
            encoded = response.json()["audioContent"]
            audio = base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise ClozeAudioError(
                "Google Cloud TTS returned invalid audio",
                code="cloze_audio_invalid_provider_response",
                status=502,
            ) from exc
        if len(audio) < 16:
            raise ClozeAudioError(
                "Google Cloud TTS returned empty audio",
                code="cloze_audio_invalid_provider_response",
                status=502,
            )
        return audio


class ClozeAudioService:
    def __init__(
        self,
        store: LanguageStore,
        audio_root: str | Path,
        *,
        provider: Any | None = None,
        environment: Mapping[str, str] | None = None,
    ):
        self.store = store
        self.audio_root = Path(audio_root)
        self.environment = environment if environment is not None else os.environ
        self.provider = provider or GoogleCloudChirpProvider(environment=self.environment)
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @property
    def voice_id(self) -> str:
        voice = str(self.environment.get("NORWEGIAN_TTS_VOICE") or DEFAULT_TTS_VOICE).strip()
        if not VOICE_RE.fullmatch(voice):
            raise ClozeAudioError(
                "NORWEGIAN_TTS_VOICE must be an nb-NO Chirp 3 HD voice",
                code="cloze_audio_voice_invalid",
                status=503,
            )
        return voice

    @staticmethod
    def _text_hash(sentence_text: str) -> str:
        return hashlib.sha256(sentence_text.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_key(sentence_text: str, voice_id: str) -> str:
        identity = {
            "audioEncoding": TTS_AUDIO_ENCODING,
            "configVersion": TTS_CONFIG_VERSION,
            "language": TTS_LANGUAGE,
            "provider": TTS_PROVIDER,
            "sentenceText": sentence_text,
            "voiceId": voice_id,
        }
        return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()

    def _lock(self, cache_key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(cache_key, threading.Lock())

    def _relative_path(self, sentence_id: str, cache_key: str, *, category: str = "cloze") -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", sentence_id).strip("-._")[:80] or "sentence"
        safe_category = category if category in {"cloze", "generated", "word"} else "cloze"
        return Path(TTS_LANGUAGE) / safe_category / f"{safe_id}_{cache_key}.mp3"

    def _absolute_path(self, relative_path: str | Path) -> Path:
        root = self.audio_root.resolve()
        candidate = (self.audio_root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            raise LanguageStorageError("Cloze audio cache path is invalid")
        return candidate

    def _existing_file(self, cache_key: str) -> tuple[dict[str, Any], Path] | None:
        metadata = self.store.get_cloze_sentence_audio(cache_key)
        if metadata is None:
            return None
        path = self._absolute_path(metadata["audio_path"])
        if path.is_file() and path.stat().st_size > 0:
            return metadata, path
        return None

    @staticmethod
    def _audio_url(cache_key: str) -> str:
        return f"/api/language/cloze/audio/{cache_key}.mp3"

    def _metadata(
        self,
        *,
        item: dict[str, Any],
        sentence_text: str,
        voice_id: str,
        cache_key: str,
        relative_path: Path,
    ) -> dict[str, Any]:
        source = item.get("source") or {}
        return {
            "cache_key": cache_key,
            "reference_sentence_source": str(source.get("sourceId") or "unknown"),
            "reference_sentence_id": str(source.get("sentenceId") or "unknown"),
            "sentence_text": sentence_text,
            "audio_path": relative_path.as_posix(),
            "language_code": TTS_LANGUAGE,
            "provider": TTS_PROVIDER,
            "voice_id": voice_id,
            "audio_encoding": TTS_AUDIO_ENCODING,
            "text_hash": self._text_hash(sentence_text),
            "settings": {"configVersion": TTS_CONFIG_VERSION},
            "created_at": utc_now(),
        }

    def generate(self, session_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        unknown = sorted(set(payload) - {"itemIndex", "itemFingerprint"})
        if unknown:
            raise LanguageValidationError("Cloze audio request contains unsupported fields", details=unknown)
        try:
            item_index = int(payload.get("itemIndex"))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("itemIndex is invalid", details=["itemIndex"]) from exc
        if isinstance(payload.get("itemIndex"), bool) or item_index < 0:
            raise LanguageValidationError("itemIndex is invalid", details=["itemIndex"])

        detail = self.store.get_cloze_session(session_id)
        try:
            items = json.loads(detail["session"]["items_json"])
            item = items[item_index]
        except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
            raise LanguageNotFoundError("Cloze sentence was not found", code="cloze_audio_sentence_not_found") from exc
        if str(payload.get("itemFingerprint") or "") != str(item.get("fingerprint") or ""):
            raise LanguageValidationError(
                "Cloze item fingerprint is stale", code="cloze_audio_item_stale", details=["itemFingerprint"],
            )
        sentence_text = str(item.get("sentenceText") or "").strip()
        if not sentence_text or len(sentence_text) > 5000:
            raise LanguageValidationError("Cloze sentence text is invalid", code="cloze_audio_sentence_invalid")

        source = item.get("source") or {}
        return self.synthesize_sentence(
            sentence_text=sentence_text,
            source_id=str(source.get("sourceId") or "unknown"),
            sentence_id=str(source.get("sentenceId") or "sentence"),
            category="cloze",
        )

    def synthesize_sentence(
        self,
        *,
        sentence_text: str,
        source_id: str,
        sentence_id: str,
        category: str = "generated",
    ) -> dict[str, Any]:
        sentence_text = str(sentence_text or "").strip()
        if not sentence_text or len(sentence_text) > 5000:
            raise LanguageValidationError("Sentence text is invalid", code="sentence_audio_text_invalid")
        voice_id = self.voice_id
        cache_key = self._cache_key(sentence_text, voice_id)
        relative_path = self._relative_path(sentence_id, cache_key, category=category)
        target = self._absolute_path(relative_path)

        existing = self._existing_file(cache_key)
        if existing:
            return self._result(existing[0], cached=True)

        with self._lock(cache_key):
            existing = self._existing_file(cache_key)
            if existing:
                return self._result(existing[0], cached=True)
            metadata = self._metadata(
                item={"source": {"sourceId": source_id, "sentenceId": sentence_id}},
                sentence_text=sentence_text, voice_id=voice_id,
                cache_key=cache_key, relative_path=relative_path,
            )
            if target.is_file() and target.stat().st_size > 0:
                try:
                    stored = self.store.upsert_cloze_sentence_audio(metadata)
                except Exception as exc:
                    raise LanguageStorageError("Cloze audio metadata could not be persisted") from exc
                return self._result(stored, cached=True)

            audio = self.provider.synthesize(
                text=sentence_text,
                language_code=TTS_LANGUAGE,
                voice_id=voice_id,
                audio_encoding=TTS_AUDIO_ENCODING,
            )
            if not isinstance(audio, bytes) or len(audio) < 16:
                raise ClozeAudioError(
                    "TTS provider returned invalid audio",
                    code="cloze_audio_invalid_provider_response",
                    status=502,
                )
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with temporary.open("xb") as handle:
                    handle.write(audio)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            except OSError as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise ClozeAudioError(
                    "Cloze audio file could not be written",
                    code="cloze_audio_write_failed",
                    status=500,
                ) from exc
            try:
                stored = self.store.upsert_cloze_sentence_audio(metadata)
            except Exception as exc:
                raise LanguageStorageError("Cloze audio metadata could not be persisted") from exc
            return self._result(stored, cached=False)

    def _result(self, metadata: dict[str, Any], *, cached: bool) -> dict[str, Any]:
        return {
            "audioUrl": self._audio_url(str(metadata["cache_key"])),
            "cached": cached,
            "language": metadata["language_code"],
            "provider": metadata["provider"],
            "voiceId": metadata["voice_id"],
            "cacheKey": metadata["cache_key"],
        }

    def audio_file(self, cache_key: str) -> tuple[Path, str]:
        if not CACHE_KEY_RE.fullmatch(str(cache_key or "")):
            raise LanguageNotFoundError("Cloze audio was not found", code="cloze_audio_not_found")
        existing = self._existing_file(cache_key)
        if not existing:
            raise LanguageNotFoundError("Cloze audio was not found", code="cloze_audio_not_found")
        return existing[1], "audio/mpeg"


__all__ = [
    "CACHE_KEY_RE", "DEFAULT_TTS_VOICE", "TTS_AUDIO_ENCODING", "TTS_CONFIG_VERSION",
    "TTS_LANGUAGE", "TTS_PROVIDER", "ClozeAudioError", "ClozeAudioService",
    "GoogleCloudChirpProvider",
]

"""On-demand Norwegian sentence translation through configured Google Cloud credentials."""

from __future__ import annotations

import os
import time
import json
import html
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from ..errors import LanguageError


class GoogleCloudTranslationProvider:
    provider_id = "GOOGLE_CLOUD_TRANSLATION_NMT"

    def __init__(self, *, environment: Mapping[str, str] | None = None,
                 credentials_loader: Any | None = None, session_factory: Any | None = None):
        self.environment = environment if environment is not None else os.environ
        self.credentials_loader = credentials_loader
        self.session_factory = session_factory

    def translate(self, text: str, target_language: str) -> str:
        if self.credentials_loader is None or self.session_factory is None:
            try:
                import google.auth
                from google.auth.transport.requests import AuthorizedSession
            except ImportError as exc:
                raise LanguageError("Google Cloud translation support is not installed",
                                    code="reader_translation_dependency_missing", status=503) from exc
            loader = google.auth.default
            session_factory = AuthorizedSession
        else:
            loader = self.credentials_loader
            session_factory = self.session_factory
        configured_project = str(self.environment.get("GOOGLE_CLOUD_PROJECT") or "").strip() or None
        try:
            credentials, detected_project = loader(
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
                quota_project_id=configured_project,
            )
        except Exception as exc:
            raise LanguageError("Google Cloud translation credentials are unavailable",
                                code="reader_translation_not_configured", status=503) from exc
        project = configured_project or detected_project
        if not project:
            raise LanguageError("GOOGLE_CLOUD_PROJECT is required for sentence translation",
                                code="reader_translation_not_configured", status=503)
        session = session_factory(credentials)
        try:
            response = session.post(
                f"https://translate.googleapis.com/v3/projects/{project}/locations/global:translateText",
                json={"contents": [text], "mimeType": "text/plain",
                      "sourceLanguageCode": "no", "targetLanguageCode": target_language,
                      "model": f"projects/{project}/locations/global/models/general/nmt"},
                timeout=20,
            )
        except Exception as exc:
            raise LanguageError("Sentence translation request failed",
                                code="reader_translation_unavailable", status=502) from exc
        finally:
            session.close()
        if not response.ok:
            status = 503 if response.status_code in {401, 403, 404} else 429 if response.status_code == 429 else 502
            raise LanguageError(f"Sentence translation is unavailable (HTTP {response.status_code})",
                                code="reader_translation_unavailable", status=status)
        try:
            translated = response.json()["translations"][0]["translatedText"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LanguageError("Translation provider returned an invalid sentence",
                                code="reader_translation_invalid_response", status=502) from exc
        if not isinstance(translated, str) or not translated.strip() or len(translated) > 5000:
            raise LanguageError("Translation provider returned an invalid sentence",
                                code="reader_translation_invalid_response", status=502)
        return translated.strip()


class MyMemoryTranslationProvider:
    """Bounded public translation fallback for a single Reader sentence."""

    provider_id = "MYMEMORY_PUBLIC"

    def translate(self, text: str, target_language: str, *, timeout_seconds: float = 12) -> str:
        if len(text.encode("utf-8")) > 500:
            raise LanguageError("Sentence exceeds the public translator's 500-byte limit",
                                code="reader_translation_too_long", status=422)
        query = urllib.parse.urlencode({"q": text, "langpair": f"no|{target_language}"})
        request = urllib.request.Request(
            f"https://api.mymemory.translated.net/get?{query}",
            headers={"Accept": "application/json", "User-Agent": "CleaningDashboard/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(64 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LanguageError("Public sentence translator is unavailable",
                                code="reader_translation_unavailable", status=502) from exc
        if len(body) > 64 * 1024:
            raise LanguageError("Translation response is too large",
                                code="reader_translation_invalid_response", status=502)
        try:
            parsed = json.loads(body.decode("utf-8"))
            translation = parsed["responseData"]["translatedText"]
            status = int(parsed["responseStatus"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise LanguageError("Translation provider returned an invalid response",
                                code="reader_translation_invalid_response", status=502) from exc
        if status != 200 or not isinstance(translation, str) or not translation.strip():
            raise LanguageError("Public sentence translation quota or service is unavailable",
                                code="reader_translation_unavailable", status=503)
        return html.unescape(translation.strip())


class GooglePublicTranslationProvider:
    """Bounded best-effort fallback when configured and public providers are unavailable."""

    provider_id = "GOOGLE_TRANSLATE_PUBLIC"

    def translate(self, text: str, target_language: str, *, timeout_seconds: float = 12) -> str:
        if len(text.encode("utf-8")) > 500:
            raise LanguageError("Sentence exceeds the public translator's 500-byte limit",
                                code="reader_translation_too_long", status=422)
        query = urllib.parse.urlencode({"client": "gtx", "sl": "no", "tl": target_language,
                                        "dt": "t", "q": text})
        request = urllib.request.Request(
            f"https://translate.googleapis.com/translate_a/single?{query}",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(64 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LanguageError("Public sentence translator is unavailable",
                                code="reader_translation_unavailable", status=502) from exc
        if len(body) > 64 * 1024:
            raise LanguageError("Translation response is too large",
                                code="reader_translation_invalid_response", status=502)
        try:
            segments = json.loads(body.decode("utf-8"))[0]
            translation = "".join(segment[0] for segment in segments if segment and segment[0])
        except (UnicodeDecodeError, json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise LanguageError("Translation provider returned an invalid response",
                                code="reader_translation_invalid_response", status=502) from exc
        if not translation.strip() or len(translation) > 5000:
            raise LanguageError("Translation provider returned an invalid sentence",
                                code="reader_translation_invalid_response", status=502)
        return translation.strip()


class ReaderTranslationProvider:
    """Use configured Cloud Translation, then a bounded public fallback."""

    provider_id = "READER_TRANSLATION"

    def __init__(self, *, cloud: Any | None = None, public: Any | None = None,
                 public_fallback: Any | None = None):
        self.cloud = cloud or GoogleCloudTranslationProvider()
        self.public = public or MyMemoryTranslationProvider()
        self.public_fallback = public_fallback or GooglePublicTranslationProvider()
        self._cloud_unavailable_until = 0.0
        self._public_unavailable_until = 0.0

    def translate(self, text: str, target_language: str) -> tuple[str, str]:
        if time.monotonic() >= self._cloud_unavailable_until:
            try:
                return self.cloud.translate(text, target_language), self.cloud.provider_id
            except LanguageError as cloud_error:
                if cloud_error.status not in {503, 502}:
                    raise
                self._cloud_unavailable_until = time.monotonic() + 300
        if time.monotonic() >= self._public_unavailable_until:
            try:
                return self.public.translate(text, target_language), self.public.provider_id
            except LanguageError as public_error:
                if public_error.status not in {502, 503}:
                    raise
                self._public_unavailable_until = time.monotonic() + 300
        return self.public_fallback.translate(text, target_language), self.public_fallback.provider_id


__all__ = ["GoogleCloudTranslationProvider", "MyMemoryTranslationProvider",
           "GooglePublicTranslationProvider", "ReaderTranslationProvider"]

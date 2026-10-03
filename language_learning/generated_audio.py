"""Authorized Reader audio for accepted generated TextDocuments."""

from __future__ import annotations

from typing import Any

from .cloze_audio import (
    TTS_AUDIO_ENCODING,
    TTS_CONFIG_VERSION,
    TTS_LANGUAGE,
    TTS_PROVIDER,
    ClozeAudioError,
    ClozeAudioService,
)
from .errors import LanguageConflictError, LanguageValidationError
from .store import LanguageStore


GENERATED_AUDIO_VERSION = "language.generated-reader-audio/v1"


class GeneratedTextAudioService:
    def __init__(self, store: LanguageStore, sentence_audio: ClozeAudioService):
        self.store = store
        self.sentence_audio = sentence_audio

    def health(self) -> dict[str, Any]:
        try:
            voice = self.sentence_audio.voice_id
        except ClozeAudioError as exc:
            return {
                "state": "PROVIDER_UNAVAILABLE", "provider": TTS_PROVIDER,
                "language": TTS_LANGUAGE, "voiceId": None, "reason": exc.code,
            }
        return {
            "state": "CONFIGURED", "provider": TTS_PROVIDER, "language": TTS_LANGUAGE,
            "voiceId": voice, "audioEncoding": TTS_AUDIO_ENCODING,
            "synthesisConfigVersion": TTS_CONFIG_VERSION,
            "generatedAudioVersion": GENERATED_AUDIO_VERSION,
        }

    def generate(self, text_id: str, sentence_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        if payload:
            raise LanguageValidationError(
                "Generated sentence audio does not accept text or synthesis options",
                code="generated_audio_options_forbidden",
            )
        sentence = self.store.generated_text_sentence(text_id, sentence_id)
        source_type = str(sentence["source_type"] or "")
        if not source_type.startswith("GENERATED_"):
            raise LanguageConflictError(
                "Audio synthesis is limited to accepted generated Reader texts",
                code="generated_audio_source_not_allowed",
            )
        if sentence["processing_state"] != "ANALYZED":
            raise LanguageConflictError(
                "Generated Reader text must finish analysis before audio is available",
                code="generated_audio_text_not_ready",
            )
        exact_text = str(sentence.get("exact_text") or "").strip()
        if not exact_text:
            raise LanguageConflictError(
                "Generated Reader sentence has no authoritative text",
                code="generated_audio_sentence_not_ready",
            )
        result = self.sentence_audio.synthesize_sentence(
            sentence_text=exact_text,
            source_id=source_type,
            sentence_id=sentence_id,
            category="generated",
        )
        self.store.link_generated_text_sentence_audio(
            text_document_id=text_id,
            sentence_id=sentence_id,
            cache_key=result["cacheKey"],
            source_type=source_type,
        )
        return {
            **result,
            "audioUrl": f"/api/language/audio/{result['cacheKey']}.mp3",
            "textDocumentId": text_id,
            "sentenceId": sentence_id,
            "sourceType": source_type,
            "provenanceVersion": GENERATED_AUDIO_VERSION,
        }

    def audio_file(self, cache_key: str):
        return self.sentence_audio.audio_file(cache_key)


__all__ = ["GENERATED_AUDIO_VERSION", "GeneratedTextAudioService"]

"""Queued Google Cloud pronunciation audio for vocabulary and Reader words."""

from __future__ import annotations

from typing import Any

from .cloze_audio import ClozeAudioService
from .errors import LanguageConflictError, LanguageNotFoundError
from .store import LanguageStore


class WordAudioService:
    def __init__(self, store: LanguageStore, sentence_audio: ClozeAudioService):
        self.store = store
        self.sentence_audio = sentence_audio
        self.job_manager: Any | None = None

    def attach_job_manager(self, manager: Any) -> None:
        self.job_manager = manager

    def _entry(self, value: str) -> tuple[str, str, str] | None:
        word = str(value or "").strip()
        if not word or len(word) > 120 or any(char.isspace() for char in word) or not any(char.isalpha() for char in word):
            return None
        voice = self.sentence_audio.voice_id
        return self.sentence_audio._cache_key(word, voice), word, voice

    def enqueue_all(self) -> int:
        entries = [entry for word in self.store.word_audio_candidates()
                   if (entry := self._entry(word)) is not None]
        added = self.store.queue_word_audio_jobs(entries)
        if added and self.job_manager:
            self.job_manager.notify()
        return added

    def enqueue_for_text(self, text_id: str) -> int:
        entries = [entry for word in self.store.word_audio_candidates(text_id)
                   if (entry := self._entry(word)) is not None]
        added = self.store.queue_word_audio_jobs(entries)
        if added and self.job_manager:
            self.job_manager.notify()
        return added

    def enqueue_word(self, word: str) -> int:
        entry = self._entry(word)
        if not entry:
            return 0
        added = self.store.queue_word_audio_jobs([entry])
        if added and self.job_manager:
            self.job_manager.notify()
        return added

    def enqueue_forms_for_lemma(self, lemma_id: str) -> int:
        entries = [entry for word in self.store.word_audio_forms_for_lemma(lemma_id)
                   if (entry := self._entry(word)) is not None]
        added = self.store.queue_word_audio_jobs(entries)
        if added and self.job_manager:
            self.job_manager.notify()
        return added

    def status(self, *, lemma_id: str | None = None, token_id: str | None = None, retry: bool = False) -> dict[str, Any]:
        word = self.store.word_audio_source(lemma_id=lemma_id, token_id=token_id)
        entry = self._entry(word)
        if not entry:
            return {"state": "UNAVAILABLE", "reason": "single_word_required", "word": word}
        cache_key, _, _ = entry
        added = self.store.queue_word_audio_jobs([entry])
        job = self.store.get_word_audio_job(cache_key)
        if retry and job["state"] == "FAILED":
            self.store.retry_word_audio_job(cache_key)
            job = self.store.get_word_audio_job(cache_key)
            added = 1
        if retry and job["state"] == "QUEUED":
            self.store.prioritize_word_audio_job(cache_key)
        if job["state"] == "READY":
            try:
                self.sentence_audio.audio_file(cache_key)
            except LanguageNotFoundError:
                self.store.retry_word_audio_job(cache_key)
                job = self.store.get_word_audio_job(cache_key)
                added = 1
        if added and self.job_manager:
            self.job_manager.notify()
        result = {"state": job["state"], "word": word, "attempts": job["attempts"]}
        if job["state"] == "READY":
            result["audioUrl"] = f"/api/language/audio/{cache_key}.mp3"
        if job["state"] == "FAILED":
            result["errorCode"] = job["error_code"]
        return result

    def process(self, job: dict[str, Any]) -> None:
        if job["voice_id"] != self.sentence_audio.voice_id:
            raise LanguageConflictError("Audio voice changed", code="word_audio_voice_changed")
        result = self.sentence_audio.synthesize_sentence(
            sentence_text=job["word_text"], source_id="WORD_AUDIO",
            sentence_id=job["cache_key"][:16], category="word",
        )
        if result["cacheKey"] != job["cache_key"]:
            raise LanguageConflictError("Audio cache key changed", code="word_audio_cache_changed")
        self.store.finish_word_audio_job(job["cache_key"])


__all__ = ["WordAudioService"]

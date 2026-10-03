"""Previewable, staged Anki cards from an accepted Reader story."""

from __future__ import annotations

import base64
import hashlib
import html
import re
import threading
import time
from typing import Any

from .errors import LanguageConflictError, LanguageValidationError
from .providers.anki import AnkiAdapterError
from .store import LanguageStore, canonical_json


STORY_POLICY_VERSION = "language.reader-story-anki/v1"
MAX_WORDS = 50
MAX_PHRASES = 10
WORD_PARTS_OF_SPEECH = frozenset({"NOUN", "VERB", "ADJ", "ADV"})
_WORD = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)


class StoryAnkiService:
    def __init__(self, language_service: Any):
        self.service = language_service
        self.store: LanguageStore = language_service.store
        self._lock = threading.Lock()
        self._plans: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _phrase_candidates(sentences: list[dict[str, Any]]) -> list[tuple[str, str]]:
        phrases: list[tuple[str, str]] = []
        seen: set[str] = set()
        for sentence in sentences:
            text = str(sentence["exact_text"] or "").strip()
            for segment in re.split(r"[,;:!?]", text)[:-1]:
                phrase = segment.strip(" .–—")
                words = _WORD.findall(phrase)
                if 3 <= len(words) <= 9 and phrase.casefold() not in seen:
                    seen.add(phrase.casefold())
                    phrases.append((phrase, sentence["id"]))
                    break
            if len(phrases) >= MAX_PHRASES:
                break
        return phrases

    def _translate(self, source: str) -> tuple[str, str]:
        result = self.service.translation_provider.translate(source, "en")
        if isinstance(result, tuple):
            return result
        return result, self.service.translation_provider.provider_id

    def preview(self, text_id: str) -> dict[str, Any]:
        text = self.store.get_text(text_id)
        document = text["document"]
        if not str(document["source_type"] or "").startswith("GENERATED_") or document["processing_state"] != "ANALYZED":
            raise LanguageConflictError("Analyze a generated Reader text before creating a story deck",
                                        code="story_anki_text_not_ready")
        profile_id = document["language_profile_id"]
        config = self.service.anki_sync_service._config(profile_id)
        if not config["enabled"]:
            raise LanguageValidationError("Enable local AnkiConnect before creating a deck",
                                          code="anki_not_configured")
        sentences = [item for item in text["sentences"] if item.get("exact_text")]
        words: list[tuple[str, str]] = []
        seen: set[str] = set()
        for token in text["tokens"]:
            if token["token_kind"] != "WORD" or not token["selected_lemma_id"]:
                continue
            if token.get("selected_lemma_pos") not in WORD_PARTS_OF_SPEECH:
                continue
            if token.get("knowledge_status") in {"KNOWN", "MASTERED"}:
                continue
            source = str(token.get("selected_lemma_display") or token["surface"]).strip()
            key = source.casefold()
            if not source or key in seen:
                continue
            seen.add(key)
            words.append((source, token["sentence_id"]))
            if len(words) >= MAX_WORDS:
                break
        candidates = ([{"stage": "words", "source": word, "sentenceId": sentence_id} for word, sentence_id in words]
                      + [{"stage": "phrases", "source": phrase, "sentenceId": sentence_id}
                         for phrase, sentence_id in self._phrase_candidates(sentences)]
                      + [{"stage": "sentences", "source": str(item["exact_text"]).strip(),
                          "sentenceId": item["id"]} for item in sentences])
        if not candidates:
            raise LanguageConflictError("This Reader text has no cards to export", code="story_anki_empty")
        for item in candidates:
            item["english"], item["translationProvider"] = self._translate(item["source"])
        context_sources = {sentence["id"]: str(sentence["exact_text"]).strip() for sentence in sentences}
        context_english = {item["sentenceId"]: item["english"] for item in candidates
                           if item["stage"] == "sentences"}
        for item in candidates:
            if item["stage"] != "sentences":
                item["context"] = context_sources.get(item["sentenceId"], "")
                item["contextEnglish"] = context_english.get(item["sentenceId"], "")
        title = str(document["title"]).strip().replace("::", " - ")[:80]
        root_name = f"Reader Stories::{title} [{text_id[:8]}]"
        plan = {"policyVersion": STORY_POLICY_VERSION, "textId": text_id,
                "profileId": profile_id, "title": title, "deckName": root_name,
                "contentFingerprint": document["content_fingerprint"],
                "cards": candidates, "audioSentences": len(sentences),
                "order": ["01 Words", "02 Phrases", "03 Sentences"],
                "note": "Study the three subdecks in order. Anki owns scheduling; English translations are machine generated and should be checked."}
        token = hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()
        with self._lock:
            self._plans[token] = (time.monotonic(), plan)
            self._plans = {key: value for key, value in self._plans.items()
                           if time.monotonic() - value[0] < 1800}
        return {**plan, "previewToken": token}

    def create(self, text_id: str, preview_token: str,
               translation_overrides: dict[str, str] | None = None,
               source_overrides: dict[str, str] | None = None) -> dict[str, Any]:
        with self._lock:
            cached = self._plans.get(preview_token)
        if cached is None or time.monotonic() - cached[0] >= 1800 or cached[1]["textId"] != text_id:
            raise LanguageConflictError("Story deck preview expired; preview it again",
                                        code="story_anki_preview_expired")
        plan = cached[1]
        overrides = translation_overrides or {}
        source_changes = source_overrides or {}
        for changes in (overrides, source_changes):
            for key, value in changes.items():
                if not key.isdecimal() or int(key) >= len(plan["cards"]):
                    raise LanguageValidationError("Story card override has an invalid index",
                                                  code="story_anki_invalid_card")
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1000:
                    raise LanguageValidationError("Story card override must be 1–1000 characters",
                                                  code="story_anki_invalid_card")
        if any(plan["cards"][int(key)]["stage"] == "sentences" for key in source_changes):
            raise LanguageValidationError("A sentence card cannot differ from its audio source",
                                          code="story_anki_sentence_audio_mismatch")
        current = self.store.get_text(text_id)["document"]
        if (current["processing_state"] != "ANALYZED" or current["language_profile_id"] != plan["profileId"]
                or current["content_fingerprint"] != plan["contentFingerprint"]):
            raise LanguageConflictError("Reader text changed; preview it again", code="story_anki_text_changed")
        try:
            adapter = self.service.anki_sync_service._adapter(plan["profileId"], timeout_seconds=30.0)
            if adapter.capabilities().version < 6:
                raise LanguageValidationError("AnkiConnect version 6 or newer is required", code="anki_version_unsupported")
            for suffix in plan["order"]:
                adapter.create_deck(f"{plan['deckName']}::{suffix}")
            tag = f"dashboard_story_{text_id}"
            decks = {"words": "01 Words", "phrases": "02 Phrases", "sentences": "03 Sentences"}
            notes = []
            for index, card in enumerate(plan["cards"]):
                source = html.escape(source_changes.get(str(index), card["source"]).strip())
                english = html.escape(overrides.get(str(index), card["english"]).strip())
                context = (f"<br><small>{html.escape(card.get('context') or '')}"
                           f"<br>{html.escape(card.get('contextEnglish') or '')}</small>") if (
                               card["stage"] != "sentences" and card.get("context")) else ""
                notes.append({"deckName": f"{plan['deckName']}::{decks[card['stage']]}",
                              "modelName": "Basic", "fields": {"Front": source, "Back": english + context},
                              "options": {"allowDuplicate": False},
                              "tags": [tag, f"dashboard_stage_{card['stage']}"]})
            accepted = adapter.can_add_notes(notes)
            media: dict[str, str] = {}
            for card, note, allowed in zip(plan["cards"], notes, accepted):
                if not allowed or card["stage"] != "sentences":
                    continue
                sentence_id = card["sentenceId"]
                audio = self.service._require_generated_audio().generate(text_id, sentence_id, {})
                path, _ = self.service.generated_audio_file(audio["cacheKey"])
                filename = f"dashboard_story_{text_id[:12]}_{sentence_id[:12]}.mp3"
                media[sentence_id] = adapter.store_media_file(
                    filename, base64.b64encode(path.read_bytes()).decode("ascii"))
                note["fields"]["Back"] += f"<br>[sound:{media[sentence_id]}]"
            created = 0
            for start in range(0, len(notes), 25):
                batch = [note for note, allowed in zip(notes[start:start + 25], accepted[start:start + 25]) if allowed]
                if batch:
                    created += sum(note_id is not None for note_id in adapter.add_notes(batch))
            skipped = len(notes) - created
            sync_error = None
            try:
                adapter.sync_web()
            except AnkiAdapterError as exc:
                sync_error = str(exc)
            self.service.anki_sync_service._insights_cache = None
            self.service.anki_sync_service._card_catalog_cache = None
            return {"deckName": plan["deckName"], "created": created, "skippedDuplicates": skipped,
                    "audioFiles": len(media), "ankiWebSyncError": sync_error,
                    "studyOrder": plan["order"], "policyVersion": STORY_POLICY_VERSION}
        except AnkiAdapterError as exc:
            raise LanguageValidationError(str(exc), code=exc.code) from exc


__all__ = ["StoryAnkiService", "STORY_POLICY_VERSION"]

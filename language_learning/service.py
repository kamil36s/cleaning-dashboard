"""Domain boundary for the canonical Language Learning backend."""

from __future__ import annotations

import re
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .analysis.base import normalize_lookup
from .analysis.registry import AnalyzerRegistry, build_default_registry
from .analysis.norwegian_bokmal import (
    ANALYZER_ID as CANONICAL_ANALYZER_ID,
    IMPLEMENTATION_VERSION as CANONICAL_ANALYZER_VERSION,
    PROCESSOR_PACKAGES as CANONICAL_PROCESSOR_PACKAGES,
)
from .coverage import COVERAGE_POLICY_VERSION, CoverageService
from .content_inbox import ContentInboxService
from .grammar import GrammarService
from .assessment import AssessmentService
from .curricula import CurriculumService
from .anki_sync import AnkiSyncService
from .errors import LanguageConflictError, LanguageError, LanguageValidationError
from .providers.frequency import WordfreqFrequencyProvider
from .providers.dictionary import DictionaryProviderError, OrdbokeneDictionaryProvider
from .providers.generation import GeminiGenerationProvider
from .providers.translation import GooglePublicTranslationProvider, MyMemoryTranslationProvider, ReaderTranslationProvider
from .learning_plan import LearningPlanService
from .listening import (
    LISTENING_ACTIVITY_POLICY_VERSION,
    LISTENING_COMPLETION_POLICY_VERSION,
    LISTENING_EXPOSURE_POLICY_VERSION,
    LISTENING_MODES,
    LISTENING_OUTCOMES,
    LISTENING_PLAYBACK_SOURCES,
    LISTENING_QUALIFICATION_THRESHOLD,
    qualifies_sentence_event,
    validate_playback_timing,
)
from .mistakes import MistakeIntelligenceService
from .generation import GenerationService
from .gamification import (
    ACHIEVEMENT_POLICY_VERSION,
    CAMPAIGN_POLICY_VERSION,
    COLLECTION_POLICY_VERSION,
    GamificationService,
    level_from_xp,
    LEVEL_POLICY_VERSION,
    LISTENING_XP_POLICY_VERSION,
    QUEST_POLICY_VERSION,
    XP_POLICY_VERSION,
)
from .schemas import ANALYSIS_CONTRACT_VERSION, AnalysisDocument, text_fingerprint
from .statistics import (
    DEFAULT_TIMEZONE,
    GOAL_RULE_VERSION,
    StatisticsService,
)
from .store import EXPORT_VERSION, LanguageStore, OFFSET_UNIT, SCHEMA_VERSION, canonical_json, utc_now


CANONICAL_MODEL_VERSION = "stanza-resources-1.14.0"
CANONICAL_PROCESSORS = tuple(CANONICAL_PROCESSOR_PACKAGES)
ANALYSIS_JOB_VERSION = "language.analysis-job/v1"
ANALYSIS_POLICY_VERSION = "language.analysis-policy/v1"
MAX_ANALYSIS_TEXT_BYTES = 2 * 1024 * 1024

KNOWLEDGE_STATUSES = {"NEW", "LEARNING", "KNOWN", "MASTERED"}
DISPOSITIONS = {"TRACKED", "IGNORED", "EXCLUDED"}
PROFILE_STATUSES = {"ACTIVE", "INACTIVE"}
SOURCE_KINDS = {"MANUAL", "ANALYZER", "IMPORT"}
AMBIGUITY_STATES = {"NOT_REPORTED", "UNAMBIGUOUS", "AMBIGUOUS"}
LEXICAL_STATUSES = {"NOT_ASSESSED", "KNOWN", "UNKNOWN"}
SESSION_TYPES = {"READER", "GENERATED_READER", "LISTENING", "CLOZE", "MANUAL", "ANKI_IMPORTED"}
SESSION_STATUSES = {"ACTIVE", "COMPLETED", "CANCELLED"}
READER_SESSION_ACTIONS = {"HEARTBEAT", "PAUSE", "RESUME", "COMPLETE"}
READING_STATUSES = {"IN_PROGRESS", "COMPLETED"}
TOPIC_PROVENANCE = {"MANUAL", "IMPORT"}
TOPIC_MEMBERSHIP_STATES = {"MANUAL", "IMPORTED"}
GOAL_METRIC_UNITS = {
    "NEW_WORDS": "WORDS",
    "ACTIVE_READING_MINUTES": "MINUTES",
    "TEXTS_COMPLETED": "TEXTS",
    "READER_EXPOSURES": "EXPOSURES",
    "LISTENING_ACTIVE_MINUTES": "MINUTES",
    "LISTENING_SESSIONS": "SESSIONS",
    "LISTENING_TEXTS_COMPLETED": "TEXTS",
}
GOAL_PERIODS = {"WEEK"}
ID_RE = re.compile(r"^[a-f0-9]{32}$")


class LanguageService:
    def __init__(
        self,
        store: LanguageStore,
        *,
        analyzer_registry: AnalyzerRegistry | None = None,
        frequency_provider: Any | None = None,
        coverage_service: CoverageService | None = None,
        statistics_service: StatisticsService | None = None,
        learning_plan_service: LearningPlanService | None = None,
        mistake_intelligence_service: MistakeIntelligenceService | None = None,
        anki_sync_service: AnkiSyncService | None = None,
        cloze_service: Any | None = None,
        cloze_audio_service: Any | None = None,
        generated_audio_service: Any | None = None,
        reference_lexicon_service: Any | None = None,
        dictionary_provider: Any | None = None,
        curriculum_service: CurriculumService | None = None,
        gamification_service: GamificationService | None = None,
        generation_provider: Any | None = None,
        translation_provider: Any | None = None,
        grammar_parser: Any | None = None,
    ):
        self.store = store
        self.analyzer_registry = analyzer_registry or build_default_registry()
        self.frequency_provider = frequency_provider or WordfreqFrequencyProvider()
        self.coverage_service = coverage_service or CoverageService()
        self.statistics_service = statistics_service or StatisticsService(store)
        self.mistake_intelligence_service = mistake_intelligence_service or MistakeIntelligenceService(store)
        self.learning_plan_service = learning_plan_service or LearningPlanService(
            store, self.statistics_service, self.mistake_intelligence_service
        )
        self.anki_sync_service = anki_sync_service or AnkiSyncService(store)
        self.cloze_service = cloze_service
        self.cloze_audio_service = cloze_audio_service
        self.generated_audio_service = generated_audio_service
        self.word_audio_service: Any | None = None
        self.reference_lexicon_service = reference_lexicon_service
        self.dictionary_provider = dictionary_provider or OrdbokeneDictionaryProvider()
        self.curriculum_service = curriculum_service or CurriculumService(
            store,
            reference_service=reference_lexicon_service,
            dictionary_provider=self.dictionary_provider,
        )
        self.gamification_service = gamification_service or GamificationService(
            store, self.statistics_service, cloze_service=cloze_service,
            curriculum_service=self.curriculum_service,
        )
        self.gamification_service.attach_curriculum_service(self.curriculum_service)
        self.generation_provider = generation_provider or GeminiGenerationProvider()
        self.translation_provider = translation_provider or ReaderTranslationProvider()
        self._word_translation_cache: dict[tuple[str, str], dict[str, str]] = {}
        from .story_anki import StoryAnkiService
        self.story_anki_service = StoryAnkiService(self)
        self.generation_service = GenerationService(self)
        self.content_inbox = ContentInboxService(
            self, store.database_path.parent / "language-learning" / "media"
        )
        self.job_manager: Any | None = None
        self.grammar = GrammarService(self, grammar_parser)
        self.assessment = AssessmentService(store, self.curriculum_service)

    def study_session(self, profile_id: str, minutes: int) -> dict[str, Any]:
        from .study_session import StudySessionBuilder
        return self._response(StudySessionBuilder(self).build(profile_id, minutes))

    def benchmark_runs(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.assessment.list_runs(profile_id))

    def start_benchmark(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.assessment.start(profile_id))

    def benchmark_run(self, profile_id: str, run_id: str) -> dict[str, Any]:
        return self._response(self.assessment.get(profile_id, run_id))

    def benchmark_response(self, profile_id: str, run_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.assessment.respond(profile_id, run_id, payload))

    def complete_benchmark(self, profile_id: str, run_id: str) -> dict[str, Any]:
        return self._response(self.assessment.complete(profile_id, run_id))

    def norway_preparation(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.assessment.norway_preparation(profile_id))

    def grammar_summary(self, profile_id, pattern_id=None):
        return self._response(self.grammar.summary(profile_id, pattern_id))

    def text_grammar(self, text_id, profile_id):
        return self._response(self.grammar.text_status(text_id, profile_id))

    def enqueue_grammar(self, text_id, payload):
        return self.grammar.enqueue(text_id, payload)

    def review_grammar(self, occurrence_id, payload):
        return self._response(self.grammar.review(occurrence_id, payload))

    def attach_job_manager(self, manager: Any) -> None:
        self.job_manager = manager
        if self.word_audio_service:
            self.word_audio_service.attach_job_manager(manager)

    def attach_cloze_service(self, service: Any) -> None:
        self.cloze_service = service
        self.gamification_service.attach_cloze_service(service)

    def attach_cloze_audio_service(self, service: Any) -> None:
        self.cloze_audio_service = service

    def attach_generated_audio_service(self, service: Any) -> None:
        self.generated_audio_service = service

    def attach_word_audio_service(self, service: Any) -> None:
        self.word_audio_service = service
        if self.job_manager:
            service.attach_job_manager(self.job_manager)

    def attach_reference_lexicon_service(self, service: Any) -> None:
        self.reference_lexicon_service = service
        self.mistake_intelligence_service.attach_reference_service(service)
        self.curriculum_service.attach_reference_service(service)

    def reference_health(self) -> dict[str, Any]:
        if self.reference_lexicon_service is None:
            return self._response({
                "configured": False, "available": False, "schemaVersion": None,
                "referenceFingerprint": None, "reason": "REFERENCE_SERVICE_NOT_CONFIGURED",
            })
        return self._response(self.reference_lexicon_service.health())

    def _require_cloze(self) -> Any:
        if self.cloze_service is None:
            raise LanguageConflictError(
                "Cloze reference data is not configured", code="cloze_reference_unavailable"
            )
        return self.cloze_service

    def _require_cloze_audio(self) -> Any:
        if self.cloze_audio_service is None:
            raise LanguageConflictError(
                "Cloze sentence audio is not configured", code="cloze_audio_unavailable"
            )
        return self.cloze_audio_service

    def _require_generated_audio(self) -> Any:
        if self.generated_audio_service is None:
            raise LanguageConflictError(
                "Generated Reader audio is not configured", code="generated_audio_unavailable"
            )
        return self.generated_audio_service

    @staticmethod
    def _object(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        return payload

    @staticmethod
    def _text(value: Any, field: str, *, maximum: int = 500) -> str:
        if not isinstance(value, str) or not value.strip():
            raise LanguageValidationError(f"{field} must be a non-empty string", details=[field])
        result = value.strip()
        if len(result) > maximum:
            raise LanguageValidationError(f"{field} is too long", details=[field])
        return result

    @staticmethod
    def _optional_text(value: Any, field: str, *, maximum: int = 4000) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise LanguageValidationError(f"{field} must be a string or null", details=[field])
        if len(value) > maximum:
            raise LanguageValidationError(f"{field} is too long", details=[field])
        return value

    @staticmethod
    def _id(value: Any, field: str = "id") -> str:
        if not isinstance(value, str) or not ID_RE.fullmatch(value):
            raise LanguageValidationError(f"{field} is invalid", code="invalid_language_id", details=[field])
        return value

    @staticmethod
    def _enum(value: Any, field: str, allowed: set[str]) -> str:
        result = str(value or "").upper()
        if result not in allowed:
            raise LanguageValidationError(f"{field} is invalid", details=[field])
        return result

    @staticmethod
    def _score(value: Any, field: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
            raise LanguageValidationError(f"{field} must be an integer from 0 to 5 or null", details=[field])
        return value

    @staticmethod
    def _response(data: Any) -> dict[str, Any]:
        return {"ok": True, "data": data}

    def initialize(self) -> None:
        self.store.initialize()

    def ensure_bokmal_profile(self) -> dict[str, Any]:
        row, created = self.store.create_profile({
            "language_code": "nb",
            "locale": "nb-NO",
            "display_name": "Norwegian Bokmål",
            "translation_locales": ["pl-PL", "en-GB"],
            "analyzer_id": CANONICAL_ANALYZER_ID,
            "analyzer_version": CANONICAL_ANALYZER_VERSION,
            "analyzer_settings": {
                "modelVersion": CANONICAL_MODEL_VERSION,
                "processors": list(CANONICAL_PROCESSORS),
                "runtimeNetworkPolicy": "OFFLINE_ONLY",
            },
            "reference_provider_config": {
                "frequencyRank": "UNSELECTED",
                "dictionary": "UNSELECTED",
                "translations": "UNSELECTED",
                "cefr": "UNSELECTED",
            },
        })
        self.gamification_service.reconcile_profile(str(row["id"]))
        return {"profile": self.store.api_row(row), "created": created}

    def create_profile(self, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        language_code = self._text(payload.get("languageCode"), "languageCode", maximum=16).casefold()
        locale = self._text(payload.get("locale"), "locale", maximum=35)
        display_name = self._text(payload.get("displayName"), "displayName", maximum=120)
        locales = payload.get("translationLocales", [])
        if not isinstance(locales, list) or len(locales) > 10 or any(not isinstance(item, str) or not item.strip() for item in locales):
            raise LanguageValidationError("translationLocales must be a list of locale strings", details=["translationLocales"])
        row, created = self.store.create_profile({
            "language_code": language_code,
            "locale": locale,
            "display_name": display_name,
            "translation_locales": [item.strip() for item in locales],
            "analyzer_id": self._optional_text(payload.get("analyzerId"), "analyzerId", maximum=120),
            "analyzer_version": self._optional_text(payload.get("analyzerVersion"), "analyzerVersion", maximum=120),
            "analyzer_settings": {},
            "reference_provider_config": {},
            "status": self._enum(payload.get("status", "ACTIVE"), "status", PROFILE_STATUSES),
        })
        self.gamification_service.reconcile_profile(str(row["id"]))
        return self._response({"profile": self.store.api_row(row), "created": created})

    def list_profiles(self) -> dict[str, Any]:
        return self._response({"items": [self.store.api_row(row) for row in self.store.list_profiles()]})

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        return self._response({"profile": self.store.api_row(self.store.get_profile(self._id(profile_id, "profileId")))})

    def update_profile(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        payload = self._object(payload)
        changes: dict[str, Any] = {}
        allowed = {"displayName", "translationLocales", "status"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError("Profile update contains unsupported fields", details=unknown)
        if "displayName" in payload:
            changes["display_name"] = self._text(payload["displayName"], "displayName", maximum=120)
        if "translationLocales" in payload:
            locales = payload["translationLocales"]
            if not isinstance(locales, list) or len(locales) > 10 or any(not isinstance(item, str) or not item.strip() for item in locales):
                raise LanguageValidationError("translationLocales must be a list of locale strings", details=["translationLocales"])
            changes["translation_locales_json"] = canonical_json([item.strip() for item in locales])
        if "status" in payload:
            changes["status"] = self._enum(payload["status"], "status", PROFILE_STATUSES)
        return self._response({"profile": self.store.api_row(self.store.update_profile(profile_id, changes))})

    def upsert_lemma(
        self,
        profile_id: str,
        lemma_display: str,
        *,
        part_of_speech: str | None = None,
        source_kind: str = "MANUAL",
        source_id: str | None = None,
        source_version: str | None = None,
        user_notes: str | None = None,
    ) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        display = self._text(lemma_display, "lemmaDisplay", maximum=300)
        normalized = normalize_lookup(display)
        pos = self._optional_text(part_of_speech, "partOfSpeech", maximum=40)
        if pos:
            pos = pos.upper()
        kind = self._enum(source_kind, "sourceKind", SOURCE_KINDS)
        canonical_key = f"{normalized}|{pos or ''}"
        row, created = self.store.upsert_lemma({
            "language_profile_id": profile_id,
            "lemma_display": display,
            "lemma_normalized": normalized,
            "part_of_speech": pos,
            "canonical_key": canonical_key,
            "source_kind": kind,
            "source_id": source_id,
            "source_version": source_version,
            "user_notes": user_notes,
        })
        if created and self.word_audio_service:
            try:
                self.word_audio_service.enqueue_word(display)
            except LanguageError:
                pass
        return {"lemma": self.store.api_row(row), "created": created}

    def upsert_surface_form(self, profile_id: str, form_display: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        display = self._text(form_display, "formDisplay", maximum=300)
        row, created = self.store.upsert_surface_form({
            "language_profile_id": profile_id,
            "form_display": display,
            "form_normalized": normalize_lookup(display),
        })
        return {"form": self.store.api_row(row), "created": created}

    def upsert_form_lemma_mapping(
        self,
        profile_id: str,
        form_id: str,
        lemma_id: str,
        *,
        provider_id: str | None = None,
        provider_version: str | None = None,
        morphology: dict[str, str] | None = None,
        confidence: float | None = None,
        ambiguity_state: str = "NOT_REPORTED",
        lexical_status: str = "NOT_ASSESSED",
        provenance: str = "ANALYZER",
        manual_locked: bool = False,
        manual_provenance: str | None = None,
    ) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        form_id = self._id(form_id, "formId")
        lemma_id = self._id(lemma_id, "lemmaId")
        provenance = self._enum(provenance, "provenance", SOURCE_KINDS)
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            raise LanguageValidationError("confidence must be between 0 and 1 or null", details=["confidence"])
        if not isinstance(morphology or {}, dict):
            raise LanguageValidationError("morphology must be an object", details=["morphology"])
        if manual_locked and provenance != "MANUAL":
            raise LanguageValidationError("A manual lock requires MANUAL provenance", details=["manualLocked"])
        if manual_locked:
            manual_provenance = self._text(manual_provenance, "manualProvenance", maximum=300)
        row, created, protected = self.store.upsert_form_lemma_link({
            "language_profile_id": profile_id,
            "form_id": form_id,
            "lemma_id": lemma_id,
            "provider_id": provider_id,
            "provider_version": provider_version,
            "morphology": morphology or {},
            "confidence": confidence,
            "ambiguity_state": self._enum(ambiguity_state, "ambiguityState", AMBIGUITY_STATES),
            "lexical_status": self._enum(lexical_status, "lexicalStatus", LEXICAL_STATUSES),
            "mapping_provenance": provenance,
            "manual_locked": manual_locked,
            "manual_provenance": manual_provenance,
        })
        return {"mapping": self.store.api_row(row), "created": created, "protected": protected}

    def lock_form_lemma_mapping(self, profile_id: str, form_id: str, lemma_id: str, *, source: str) -> dict[str, Any]:
        return self.upsert_form_lemma_mapping(
            profile_id,
            form_id,
            lemma_id,
            provenance="MANUAL",
            manual_locked=True,
            manual_provenance=self._text(source, "source", maximum=300),
            ambiguity_state="UNAMBIGUOUS",
        )

    def update_knowledge(self, lemma_id: str, payload: Any, *, source: str = "USER") -> dict[str, Any]:
        lemma_id = self._id(lemma_id, "lemmaId")
        payload = self._object(payload)
        allowed = {"knowledgeStatus", "disposition", "recognition", "recall", "production"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError("Knowledge update contains unsupported fields", details=unknown)
        changes: dict[str, Any] = {}
        if "knowledgeStatus" in payload:
            changes["knowledge_status"] = self._enum(payload["knowledgeStatus"], "knowledgeStatus", KNOWLEDGE_STATUSES)
        if "disposition" in payload:
            changes["disposition"] = self._enum(payload["disposition"], "disposition", DISPOSITIONS)
        for public, internal in (("recognition", "recognition"), ("recall", "recall"), ("production", "production")):
            if public in payload:
                changes[internal] = self._score(payload[public], public)
        if not changes:
            raise LanguageValidationError("Knowledge update is empty", code="empty_language_update")
        row = self.store.update_knowledge(lemma_id, changes, source=source, manual=True)
        if self.word_audio_service and row["knowledge_status"] == "NEW":
            try:
                self.word_audio_service.enqueue_forms_for_lemma(lemma_id)
            except LanguageError:
                pass
        profile_id = str(self.store.get_lemma_detail(lemma_id)["lemma"]["language_profile_id"])
        self.gamification_service.reconcile_profile(profile_id)
        reflection = None
        if "knowledge_status" in changes or "disposition" in changes:
            status = "IGNORED" if row["disposition"] == "IGNORED" else row["knowledge_status"]
            reflection = self.anki_sync_service.reflect_manual_knowledge(lemma_id, status=status)
        return self._response({"knowledge": self.store.api_row(row), "ankiReflection": reflection})

    def apply_automated_knowledge(self, lemma_id: str, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
        """Internal Phase 1 hook used to prove manual evidence precedence."""
        lemma_id = self._id(lemma_id, "lemmaId")
        changes: dict[str, Any] = {}
        if "knowledgeStatus" in payload:
            changes["knowledge_status"] = self._enum(payload["knowledgeStatus"], "knowledgeStatus", KNOWLEDGE_STATUSES)
        if "disposition" in payload:
            changes["disposition"] = self._enum(payload["disposition"], "disposition", DISPOSITIONS)
        for field in ("recognition", "recall", "production"):
            if field in payload:
                changes[field] = self._score(payload[field], field)
        row = self.store.update_knowledge(lemma_id, changes, source=source, manual=False)
        if self.word_audio_service and row["knowledge_status"] == "NEW":
            try:
                self.word_audio_service.enqueue_forms_for_lemma(lemma_id)
            except LanguageError:
                pass
        profile_id = str(self.store.get_lemma_detail(lemma_id)["lemma"]["language_profile_id"])
        self.gamification_service.reconcile_profile(profile_id)
        return {"knowledge": self.store.api_row(row)}

    def get_lemma(self, lemma_id: str) -> dict[str, Any]:
        detail = self.store.get_lemma_detail(self._id(lemma_id, "lemmaId"))
        forms = []
        for row in detail["forms"]:
            form = self.store.api_row(row)
            form["candidateMappings"] = [
                self.store.api_row(candidate)
                for candidate in detail["candidates_by_form"].get(str(row["id"]), [])
            ]
            forms.append(form)
        return self._response({
            "lemma": self.store.api_row(detail["lemma"]),
            "knowledge": self.store.api_row(detail["knowledge"]),
            "forms": forms,
            "frequencies": [self.store.api_row(row) for row in detail["frequencies"]],
            "events": [self.store.api_row(row) for row in detail["events"]],
        })

    def get_lemma_reference(self, lemma_id: str) -> dict[str, Any]:
        from .reference_core.models import VocabularyLemmaIdentity

        detail = self.store.get_lemma_detail(self._id(lemma_id, "lemmaId"))
        lemma = detail["lemma"]
        knowledge = detail["knowledge"]
        profile = self.store.get_profile(str(lemma["language_profile_id"]))
        user = {
            "lemma": self.store.api_row(lemma),
            "knowledge": self.store.api_row(knowledge),
        }
        if self.reference_lexicon_service is None:
            return self._response({
                "user": user,
                "reference": {"available": False},
                "resolution": {"status": "UNAVAILABLE", "ruleVersion": "reference-resolver/v1", "candidates": []},
            })
        try:
            result = self.reference_lexicon_service.get_reference_profile(
                VocabularyLemmaIdentity(
                    str(profile["language_code"]), str(lemma["lemma_normalized"]),
                    lemma.get("part_of_speech"), str(lemma["id"]),
                )
            )
        except (OSError, sqlite3.Error):
            result = {
                "reference": {"available": False},
                "resolution": {"status": "UNAVAILABLE", "ruleVersion": "reference-resolver/v1", "candidates": []},
            }
        return self._response({"user": user, **result})

    def get_lemma_lexical_detail(self, lemma_id: str) -> dict[str, Any]:
        lemma_id = self._id(lemma_id, "lemmaId")
        detail = self.store.get_lemma_detail(lemma_id)
        lemma = detail["lemma"]
        profile = self.store.api_row(self.store.get_profile(str(lemma["language_profile_id"])))
        user_translations = self.store.lemma_user_translations(lemma_id)
        try:
            dictionary = self.dictionary_provider.lookup_lemma(
                str(lemma["lemma_display"]), lemma.get("part_of_speech")
            )
        except DictionaryProviderError as exc:
            dictionary = {
                "available": False,
                "lookupStatus": "PROVIDER_UNAVAILABLE",
                "reason": str(exc),
                "provider": self.dictionary_provider.health(),
                "articles": [],
            }
        learner_glosses: list[dict[str, Any]] = []
        if self.reference_lexicon_service is not None:
            try:
                learner_glosses = self.reference_lexicon_service.get_learner_glosses(
                    language_code=str(profile["languageCode"]),
                    lemma_normalized=str(lemma["lemma_normalized"]),
                    part_of_speech=lemma.get("part_of_speech"),
                    user_lemma_id=lemma_id,
                )
            except (OSError, sqlite3.Error):
                learner_glosses = []
        return self._response({
            "lemmaId": lemma_id,
            "preferredTranslationLocales": profile.get("translationLocales") or [],
            "dictionary": dictionary,
            "translations": {
                "user": user_translations,
                "learnerGlosses": learner_glosses,
                "polish": {
                    "available": False,
                    "status": "NOT_CONFIGURED",
                    "reason": "NO_ACCEPTED_OPEN_POLISH_TRANSLATION_SOURCE",
                },
            },
        })

    def get_lemma_preview(self, lemma_id: str) -> dict[str, Any]:
        """Read-only hover data; never calls a network dictionary provider."""
        lemma_id = self._id(lemma_id, "lemmaId")
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT l.language_profile_id,l.lemma_display,l.lemma_normalized,l.part_of_speech,"
                "k.knowledge_status,k.disposition FROM vocabulary_lemmas l "
                "JOIN lemma_knowledge k ON k.lemma_id=l.id WHERE l.id=? AND l.merged_into_id IS NULL",
                (lemma_id,),
            ).fetchone()
            forms = [item[0] for item in connection.execute(
                "SELECT f.form_display FROM form_lemma_links m JOIN surface_forms f ON f.id=m.form_id "
                "WHERE m.lemma_id=? ORDER BY m.manual_locked DESC,f.form_display LIMIT 5",
                (lemma_id,),
            ).fetchall()]
        if row is None:
            from .errors import LanguageNotFoundError
            raise LanguageNotFoundError("Lemma was not found", code="language_lemma_not_found")
        row = dict(row)
        profile = self.store.api_row(self.store.get_profile(row["language_profile_id"]))
        user = self.store.lemma_user_translations(lemma_id)
        glosses = []
        if self.reference_lexicon_service is not None:
            try:
                glosses = self.reference_lexicon_service.get_learner_glosses(
                    language_code=str(profile["languageCode"]),
                    lemma_normalized=row["lemma_normalized"],
                    part_of_speech=row["part_of_speech"], user_lemma_id=lemma_id,
                )[:5]
            except (OSError, sqlite3.Error):
                pass
        return self._response({
            "lemmaId": lemma_id, "lemmaDisplay": row["lemma_display"],
            "partOfSpeech": row["part_of_speech"], "knowledgeStatus": row["knowledge_status"],
            "disposition": row["disposition"], "preferredTranslationLocales": profile.get("translationLocales") or [],
            "forms": forms, "translations": {"user": user[:10], "learnerGlosses": glosses},
        })

    def lookup_surface_preview(self, profile_id: str, surface: str) -> dict[str, Any]:
        """Inspect a visible word without creating a vocabulary lemma or evidence."""
        profile_id = self._id(profile_id, "profileId")
        surface = self._text(surface, "surface", maximum=100)
        profile = self.store.api_row(self.store.get_profile(profile_id))
        normalized = normalize_lookup(surface)
        with self.store.connection() as connection:
            matches = connection.execute(
                "SELECT l.id FROM surface_forms f JOIN form_lemma_links m ON m.form_id=f.id "
                "JOIN vocabulary_lemmas l ON l.id=m.lemma_id "
                "WHERE f.language_profile_id=? AND f.form_normalized=? AND l.merged_into_id IS NULL "
                "ORDER BY m.manual_locked DESC,m.confidence DESC,l.id LIMIT 3",
                (profile_id, normalized),
            ).fetchall()
        if matches:
            result = self.get_lemma_preview(str(matches[0][0]))["data"]
            result["multipleMeanings"] = len(matches) > 1
            return self._response(result)
        glosses = []
        if self.reference_lexicon_service is not None:
            try:
                glosses = self.reference_lexicon_service.get_learner_glosses(
                    language_code=str(profile["languageCode"]), lemma_normalized=normalized,
                    part_of_speech=None, user_lemma_id=None,
                )[:5]
            except (OSError, sqlite3.Error):
                pass
        return self._response({
            "lemmaId": None, "lemmaDisplay": surface, "partOfSpeech": None,
            "knowledgeStatus": None, "disposition": None, "multipleMeanings": False,
            "translations": {"user": [], "learnerGlosses": glosses},
        })

    def _translate_surface_word(self, surface: str, locale: str) -> dict[str, str] | None:
        key = (surface.casefold(), locale)
        if key in self._word_translation_cache:
            return self._word_translation_cache[key]
        for provider in (GooglePublicTranslationProvider(), MyMemoryTranslationProvider()):
            try:
                value = provider.translate(surface, locale, timeout_seconds=4).strip()
                if value and value.casefold() != surface.casefold():
                    result = {"targetLocale": locale, "value": value, "source": provider.provider_id}
                    if len(self._word_translation_cache) >= 512:
                        self._word_translation_cache.pop(next(iter(self._word_translation_cache)))
                    self._word_translation_cache[key] = result
                    return result
            except LanguageError:
                continue
        return None

    def lookup_surface_meanings(self, profile_id: str, surface: str) -> dict[str, Any]:
        """On-demand translation fallback; stored user meanings and KELLY glosses stay first."""
        profile_id = self._id(profile_id, "profileId")
        surface = self._text(surface, "surface", maximum=100)
        preview = self.lookup_surface_preview(profile_id, surface)["data"]
        translations = preview["translations"]
        local = {str(row.get("targetLocale") or "")[:2].lower()
                 for row in translations.get("user", []) if row.get("translationText")}
        if any(row.get("value") for row in translations.get("learnerGlosses", [])):
            local.add("en")
        missing = [locale for locale in ("en", "pl") if locale not in local]
        if missing:
            with ThreadPoolExecutor(max_workers=len(missing)) as pool:
                machine = [item for item in pool.map(lambda locale: self._translate_surface_word(surface, locale), missing)
                           if item]
        else:
            machine = []
        preview["translations"]["machine"] = machine
        return self._response(preview)

    def upsert_lemma_translation(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        lemma_id = self._id(lemma_id, "lemmaId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"targetLocale", "translation"})
        if unknown:
            raise LanguageValidationError("Translation update contains unsupported fields", details=unknown)
        target_locale = self._text(payload.get("targetLocale"), "targetLocale", maximum=35)
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", target_locale):
            raise LanguageValidationError("targetLocale is invalid", details=["targetLocale"])
        translation = self._text(payload.get("translation"), "translation", maximum=2000)
        detail = self.store.get_lemma_detail(lemma_id)
        row = self.store.upsert_lemma_user_translation(
            lemma_id, str(detail["lemma"]["language_profile_id"]), target_locale, translation,
        )
        return self._response({"translation": row})

    def delete_lemma_translation(self, lemma_id: str, target_locale: Any) -> dict[str, Any]:
        lemma_id = self._id(lemma_id, "lemmaId")
        locale = self._text(target_locale, "targetLocale", maximum=35)
        return self._response({
            "deleted": self.store.delete_lemma_user_translation(lemma_id, locale),
            "lemmaId": lemma_id,
            "targetLocale": locale,
        })

    @staticmethod
    def _phrasebook_fingerprint(source: dict[str, Any], context: str | None) -> str:
        identity = {"source": source, "context": context}
        return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()

    def create_phrasebook_entry(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        self.store.get_profile(profile_id)
        payload = self._object(payload)
        allowed = {"expression", "sourceType", "sourceEntityId", "sourceContext", "sourceProvenance", "note", "userTranslation", "links"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError("Phrasebook entry contains unsupported fields", details=unknown)
        expression = self._text(payload.get("expression"), "expression", maximum=2000)
        source_type = self._enum(payload.get("sourceType", "MANUAL"), "sourceType", {"READER", "CLOZE", "GENERATED", "AUTHENTIC_MEDIA", "MANUAL"})
        entity_id = self._optional_text(payload.get("sourceEntityId"), "sourceEntityId", maximum=500)
        context = self._optional_text(payload.get("sourceContext"), "sourceContext", maximum=8000)
        note = self._optional_text(payload.get("note"), "note", maximum=5000)
        user_translation = self._optional_text(payload.get("userTranslation"), "userTranslation", maximum=5000)
        provenance = payload.get("sourceProvenance") or {}
        if not isinstance(provenance, dict) or len(canonical_json(provenance).encode("utf-8")) > 16 * 1024:
            raise LanguageValidationError("sourceProvenance is invalid", details=["sourceProvenance"])
        links_payload = payload.get("links") or []
        if not isinstance(links_payload, list) or len(links_payload) > 24:
            raise LanguageValidationError("links is invalid", details=["links"])
        links = []
        for item in links_payload:
            if not isinstance(item, dict) or set(item) - {"type", "value", "metadata"}:
                raise LanguageValidationError("Phrasebook link is invalid", details=["links"])
            link_type = self._enum(item.get("type"), "links.type", {"LEMMA", "REFERENCE_UNIT", "TOKEN_SPAN"})
            link_value = self._text(item.get("value"), "links.value", maximum=500)
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, dict) or len(canonical_json(metadata).encode("utf-8")) > 4096:
                raise LanguageValidationError("Phrasebook link metadata is invalid", details=["links.metadata"])
            links.append({"link_type": link_type, "link_value": link_value, "metadata": metadata})
        source_identity = {"type": source_type, "entityId": entity_id, "provenance": provenance}
        entry, created = self.store.create_phrasebook_entry({
            "language_profile_id": profile_id,
            "expression_text": expression,
            "expression_normalized": normalize_lookup(expression),
            "source_type": source_type,
            "source_entity_id": entity_id,
            "source_context": context,
            "source_provenance": provenance,
            "source_fingerprint": self._phrasebook_fingerprint(source_identity, context),
            "note": note,
            "user_translation": user_translation,
        }, links)
        return self._response({"entry": entry, "created": created, "reused": not created})

    def list_phrasebook_entries(
        self, profile_id: str, *, query: Any = "", source_type: Any = None,
        limit: Any = 50, cursor: Any = None,
    ) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        if not isinstance(query, str) or len(query) > 300:
            raise LanguageValidationError("q is invalid", details=["q"])
        try:
            parsed_limit, offset = int(limit), int(cursor or 0)
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("Pagination is invalid") from exc
        if not 1 <= parsed_limit <= 100 or offset < 0:
            raise LanguageValidationError("Pagination is invalid")
        source = self._enum(source_type, "sourceType", {"READER", "CLOZE", "GENERATED", "AUTHENTIC_MEDIA", "MANUAL"}) if source_type else None
        result = self.store.list_phrasebook_entries(
            profile_id, query=normalize_lookup(query.strip()) if query.strip() else "",
            source_type=source, limit=parsed_limit, offset=offset,
        )
        next_cursor = str(offset + parsed_limit) if offset + parsed_limit < result["total"] else None
        return self._response({
            "items": result["items"],
            "pagination": {"limit": parsed_limit, "cursor": str(offset), "nextCursor": next_cursor, "total": result["total"]},
        })

    def get_phrasebook_entry(self, entry_id: str) -> dict[str, Any]:
        return self._response({"entry": self.store.get_phrasebook_entry(self._id(entry_id, "entryId"))})

    def update_phrasebook_entry(self, entry_id: str, payload: Any) -> dict[str, Any]:
        entry_id = self._id(entry_id, "entryId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"note", "userTranslation"})
        if unknown:
            raise LanguageValidationError("Phrasebook update contains unsupported fields", details=unknown)
        changes = {}
        if "note" in payload:
            changes["note"] = self._optional_text(payload["note"], "note", maximum=5000)
        if "userTranslation" in payload:
            changes["user_translation"] = self._optional_text(payload["userTranslation"], "userTranslation", maximum=5000)
        return self._response({"entry": self.store.update_phrasebook_entry(entry_id, changes)})

    def delete_phrasebook_entry(self, entry_id: str) -> dict[str, Any]:
        entry_id = self._id(entry_id, "entryId")
        return self._response({"deleted": self.store.delete_phrasebook_entry(entry_id), "entryId": entry_id})

    def get_form_mapping(self, form_id: str) -> dict[str, Any]:
        detail = self.store.get_form_mapping_detail(self._id(form_id, "formId"))
        return self._response({
            "form": self.store.api_row(detail["form"]),
            "mappings": [self.store.api_row(row) for row in detail["mappings"]],
        })

    def lock_form_mapping(self, form_id: str, payload: Any) -> dict[str, Any]:
        form_id = self._id(form_id, "formId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"lemmaId"})
        if unknown:
            raise LanguageValidationError(
                "Form mapping update contains unsupported fields", details=unknown
            )
        detail = self.store.get_form_mapping_detail(form_id)
        lemma_id = self._id(payload.get("lemmaId"), "lemmaId")
        self.lock_form_lemma_mapping(
            str(detail["form"]["language_profile_id"]),
            form_id,
            lemma_id,
            source="LANGUAGE_PHASE3_UI",
        )
        return self.get_form_mapping(form_id)

    def search_lemmas(
        self,
        profile_id: str,
        *,
        query: str = "",
        status: str | None = None,
        disposition: str | None = None,
        limit: Any = 50,
        cursor: Any = None,
    ) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        if not isinstance(query, str) or len(query) > 300:
            raise LanguageValidationError("q is invalid", details=["q"])
        try:
            limit_value = int(limit)
            offset = int(cursor or 0)
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("Pagination is invalid", code="invalid_language_pagination") from exc
        if not 1 <= limit_value <= 100 or offset < 0:
            raise LanguageValidationError("Pagination is invalid", code="invalid_language_pagination")
        normalized_query = normalize_lookup(query.strip()) if query.strip() else ""
        status_value = self._enum(status, "status", KNOWLEDGE_STATUSES) if status else None
        disposition_value = self._enum(disposition, "disposition", DISPOSITIONS) if disposition else None
        result = self.store.search_lemmas(
            profile_id,
            query=normalized_query,
            status=status_value,
            disposition=disposition_value,
            limit=limit_value,
            offset=offset,
        )
        next_cursor = str(offset + limit_value) if offset + limit_value < result["total"] else None
        return self._response({
            "items": [self.store.api_row(row) for row in result["items"]],
            "pagination": {"limit": limit_value, "cursor": str(offset), "nextCursor": next_cursor, "total": result["total"]},
        })

    def update_lemma(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        lemma_id = self._id(lemma_id, "lemmaId")
        payload = self._object(payload)
        lemma_fields = {"lemmaDisplay", "partOfSpeech", "userNotes"}
        knowledge_fields = {"knowledgeStatus", "disposition", "recognition", "recall", "production"}
        unknown = sorted(set(payload) - lemma_fields - knowledge_fields)
        if unknown:
            raise LanguageValidationError("Lemma update contains unsupported fields", details=unknown)
        if lemma_fields.intersection(payload):
            current = self.store.get_lemma_detail(lemma_id)["lemma"]
            display = self._text(payload.get("lemmaDisplay", current["lemma_display"]), "lemmaDisplay", maximum=300)
            pos = payload.get("partOfSpeech", current["part_of_speech"])
            pos = self._optional_text(pos, "partOfSpeech", maximum=40)
            if pos:
                pos = pos.upper()
            changes = {
                "lemma_display": display,
                "lemma_normalized": normalize_lookup(display),
                "part_of_speech": pos,
                "canonical_key": f"{normalize_lookup(display)}|{pos or ''}",
            }
            if "userNotes" in payload:
                changes["user_notes"] = self._optional_text(payload["userNotes"], "userNotes", maximum=10000)
            self.store.update_lemma(lemma_id, changes, source="USER")
        if knowledge_fields.intersection(payload):
            self.update_knowledge(lemma_id, {key: payload[key] for key in knowledge_fields if key in payload})
        detail = self.get_lemma(lemma_id)
        if self.word_audio_service and lemma_fields.intersection(payload):
            try:
                self.word_audio_service.enqueue_word(detail["data"]["lemma"]["lemmaDisplay"])
            except LanguageError:
                pass
        return detail

    def merge_lemmas(self, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        source_id = self._id(payload.get("sourceLemmaId"), "sourceLemmaId")
        target_id = self._id(payload.get("targetLemmaId"), "targetLemmaId")
        note = self._optional_text(payload.get("note"), "note", maximum=2000)
        result = self.store.merge_lemmas(source_id, target_id, source="USER", note=note)
        return self._response(result)

    def create_text_draft(self, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        profile_id = self._id(payload.get("languageProfileId"), "languageProfileId")
        raw_text = payload.get("rawText")
        if not isinstance(raw_text, str) or not raw_text:
            raise LanguageValidationError("rawText must be a non-empty string", details=["rawText"])
        if len(raw_text.encode("utf-8")) > MAX_ANALYSIS_TEXT_BYTES:
            raise LanguageValidationError("rawText is too large", code="language_text_too_large", details=["rawText"])
        title = self._text(payload.get("title", "Untitled text"), "title", maximum=500)
        source_type = self._text(payload.get("sourceType", "PASTED"), "sourceType", maximum=80).upper()
        source_reference = self._optional_text(payload.get("sourceReference"), "sourceReference", maximum=2000)
        row = self.store.create_text_draft({
            "language_profile_id": profile_id,
            "title": title,
            "raw_text": raw_text,
            "source_type": source_type,
            "source_reference": source_reference,
            "content_fingerprint": text_fingerprint(raw_text),
        })
        return self._response({"text": self.store.api_row(row)})

    def get_text(self, text_id: str) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        result = self.store.get_text(text_id)
        document = self.store.api_row(result["document"])
        membership = self.store.get_text_series_membership(text_id)
        if membership:
            document.update(self.store.api_row(membership))
        coverage = self.coverage_service.calculate(self.store.coverage_rows(text_id))
        sentences = [self.store.api_row(row) for row in result["sentences"]]
        tokens = [self.store.api_row(row) for row in result["tokens"]]
        reference_profile = self._text_reference_profile(result, sentences, tokens)
        return self._response({
            "document": document,
            "sentences": sentences,
            "tokens": tokens,
            "analysisRuns": [self.store.api_row(row) for row in result["analysisRuns"]],
            "frequencies": [self.store.api_row(row) for row in result["frequencies"]],
            "coverage": coverage,
            "latestJob": self._public_job(result["latestJob"]) if result["latestJob"] else None,
            "readingProgress": self.store.api_row(result["readingProgress"]),
            "studySessions": [self.store.api_row(row) for row in result["studySessions"]],
            "referenceProfile": reference_profile,
        })

    def translate_reader_sentence(self, text_id: str, sentence_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        sentence_id = self._id(sentence_id, "sentenceId")
        payload = self._object(payload)
        if set(payload) - {"targetLanguage"}:
            raise LanguageValidationError("Sentence translation accepts only targetLanguage")
        target = payload.get("targetLanguage", "en")
        if target not in {"en", "pl"}:
            raise LanguageValidationError("targetLanguage must be en or pl", details=["targetLanguage"])
        record = self.store.reader_sentence_translation(text_id, sentence_id, target)
        sentence = record["sentence"]
        if sentence["processing_state"] != "ANALYZED":
            raise LanguageConflictError("Analyze the Reader text before translating",
                                        code="reader_text_not_analyzed")
        source = str(sentence["exact_text"] or "").strip()
        if not source or len(source) > 1024:
            raise LanguageValidationError("Reader sentence is empty or too long to translate")
        source_hash = text_fingerprint(source)
        cached = record["translation"]
        if cached and cached["source_hash"] == source_hash:
            return self._response({"sentenceId": sentence_id, "source": source,
                                   "targetLanguage": target, "translation": cached["translation_text"],
                                   "provider": cached["provider"], "cached": True})
        translated_result = self.translation_provider.translate(source, target)
        translated, provider_id = (translated_result if isinstance(translated_result, tuple)
                                   else (translated_result, self.translation_provider.provider_id))
        saved = self.store.save_reader_sentence_translation(
            text_id, sentence_id, target_language=target, source_hash=source_hash,
            translation=translated, provider=provider_id,
        )
        return self._response({"sentenceId": sentence_id, "source": source,
                               "targetLanguage": target, "translation": saved["translation_text"],
                               "provider": saved["provider"], "cached": False})

    def reader_study_notes(self, text_id: str) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        self.store.get_text(text_id)
        return self._response({"items": self.store.reader_study_notes(text_id)})

    def import_reader_study_notes(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        if set(payload) != {"sentences"} or not isinstance(payload["sentences"], list):
            raise LanguageValidationError("Study notes must contain a sentences list")
        supplied = payload["sentences"]
        if not supplied or len(supplied) > 500:
            raise LanguageValidationError("Study notes must contain 1 to 500 sentences")
        snapshot = self.store.get_text(text_id)
        if snapshot["document"]["processing_state"] != "ANALYZED":
            raise LanguageConflictError("Analyze the Reader text before importing study notes")
        current = {row["id"]: row["exact_text"] for row in snapshot["sentences"]}
        tokens_by_sentence: dict[str, dict[str, dict[str, Any]]] = {}
        for token in snapshot["tokens"]:
            if token["token_kind"] == "WORD":
                tokens_by_sentence.setdefault(token["sentence_id"], {})[token["id"]] = token
        if len(supplied) != len(current):
            raise LanguageValidationError("Include every sentence from this text exactly once")
        items = []
        seen = set()
        for index, value in enumerate(supplied, start=1):
            if not isinstance(value, dict) or set(value) != {"sentenceId", "source", "english", "glosses", "grammarHint"}:
                raise LanguageValidationError(f"Sentence {index} must include sentenceId, source, english, glosses and grammarHint")
            sentence_id = self._id(value["sentenceId"], "sentenceId")
            if sentence_id in seen or sentence_id not in current or value["source"] != current[sentence_id]:
                raise LanguageValidationError(f"Sentence {index} does not match this text")
            english = value["english"]
            grammar_hint = value["grammarHint"]
            if not isinstance(english, str) or not english.strip() or len(english) > 2000:
                raise LanguageValidationError(f"Sentence {index} needs a short English translation")
            if not isinstance(grammar_hint, str) or not grammar_hint.strip() or len(grammar_hint) > 2000:
                raise LanguageValidationError(f"Sentence {index} needs a short grammar hint")
            supplied_glosses = value["glosses"]
            if not isinstance(supplied_glosses, list) or len(supplied_glosses) > 100:
                raise LanguageValidationError(f"Sentence {index} needs a glosses list of at most 100 entries")
            sentence_tokens = tokens_by_sentence.get(sentence_id, {})
            required = {token_id for token_id, token in sentence_tokens.items()
                        if token["selected_lemma_id"] and token["resolution_state"] not in {"AMBIGUOUS", "UNRESOLVED"}
                        and token["disposition"] not in {"IGNORED", "EXCLUDED"}
                        and (token["knowledge_status"] or "NEW") in {"NEW", "LEARNING"}}
            covered: set[str] = set()
            glosses = []
            for gloss_index, gloss in enumerate(supplied_glosses, start=1):
                if not isinstance(gloss, dict) or set(gloss) != {"source", "english", "tokenIds"}:
                    raise LanguageValidationError(f"Sentence {index}, gloss {gloss_index} needs source, english and tokenIds")
                token_ids = gloss["tokenIds"]
                if (not isinstance(token_ids, list) or not token_ids or len(token_ids) > 20
                        or any(not isinstance(token_id, str) or token_id not in sentence_tokens for token_id in token_ids)
                        or len(set(token_ids)) != len(token_ids)):
                    raise LanguageValidationError(f"Sentence {index}, gloss {gloss_index} has invalid tokenIds")
                selected = [sentence_tokens[token_id] for token_id in token_ids]
                if selected != sorted(selected, key=lambda token: token["source_start"]):
                    raise LanguageValidationError(f"Sentence {index}, gloss {gloss_index} tokenIds must follow text order")
                source = gloss["source"]
                english_gloss = gloss["english"]
                expected_source = snapshot["document"]["raw_text"][selected[0]["source_start"]:selected[-1]["source_end"]]
                if not isinstance(source, str) or source != expected_source or len(source) > 500:
                    raise LanguageValidationError(f"Sentence {index}, gloss {gloss_index} source must match the exact text span")
                if not isinstance(english_gloss, str) or not english_gloss.strip() or len(english_gloss) > 500:
                    raise LanguageValidationError(f"Sentence {index}, gloss {gloss_index} needs a short English meaning")
                covered.update(token_ids)
                glosses.append({"source": source, "english": english_gloss.strip(), "tokenIds": token_ids})
            if required - covered:
                raise LanguageValidationError(f"Sentence {index} is missing contextual meanings for New or Learning words")
            seen.add(sentence_id)
            items.append({"sentenceId": sentence_id, "source": current[sentence_id],
                          "english": english.strip(), "glosses": glosses, "grammarHint": grammar_hint.strip()})
        self.store.import_reader_study_notes(text_id, items)
        return self.reader_study_notes(text_id)

    def preview_reader_story_anki(self, text_id: str) -> dict[str, Any]:
        return self._response(self.story_anki_service.preview(self._id(text_id, "textId")))

    def create_reader_story_anki(self, text_id: str, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        if "previewToken" not in payload or set(payload) - {"previewToken", "translationOverrides", "sourceOverrides"}:
            raise LanguageValidationError("Story deck creation requires previewToken")
        token = self._text(payload["previewToken"], "previewToken", maximum=64)
        overrides = payload.get("translationOverrides", {})
        sources = payload.get("sourceOverrides", {})
        if not isinstance(overrides, dict) or len(overrides) > 200 or not isinstance(sources, dict) or len(sources) > 200:
            raise LanguageValidationError("Story card overrides must be small objects")
        return self._response(self.story_anki_service.create(self._id(text_id, "textId"), token, overrides, sources))

    def _text_reference_profile(
        self, result: dict[str, Any], sentences: list[dict[str, Any]], tokens: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if self.reference_lexicon_service is None:
            return {"available": False, "profileVersion": "language.reference-text-profile/v1",
                    "health": {"configured": False, "available": False}, "expressions": []}
        document = result["document"]
        profile = self.store.get_profile(str(document["language_profile_id"]))
        try:
            return self.reference_lexicon_service.text_reference_profile(
                language_code=str(profile["language_code"]), raw_text=str(document["raw_text"]),
                sentences=sentences, tokens=tokens,
            )
        except (OSError, sqlite3.Error):
            return {"available": False, "profileVersion": "language.reference-text-profile/v1",
                    "health": {"configured": True, "available": False, "reason": "REFERENCE_DATABASE_UNAVAILABLE"},
                    "expressions": []}

    def get_text_reference_profile(self, text_id: str) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        result = self.store.get_text(text_id)
        sentences = [self.store.api_row(row) for row in result["sentences"]]
        tokens = [self.store.api_row(row) for row in result["tokens"]]
        return self._response({"referenceProfile": self._text_reference_profile(result, sentences, tokens)})

    def list_texts(
        self,
        profile_id: str,
        *,
        limit: Any = 50,
        cursor: Any = None,
    ) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        try:
            limit_value = int(limit)
            offset = int(cursor or 0)
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError(
                "Pagination is invalid", code="invalid_language_pagination"
            ) from exc
        if not 1 <= limit_value <= 100 or offset < 0:
            raise LanguageValidationError(
                "Pagination is invalid", code="invalid_language_pagination"
            )
        result = self.store.list_texts(profile_id, limit=limit_value, offset=offset)
        next_cursor = str(offset + limit_value) if offset + limit_value < result["total"] else None
        items = []
        coverage_rows = self.store.coverage_rows_batch([
            row["id"] for row in result["items"] if row.get("processing_state") == "ANALYZED"
        ])
        for row in result["items"]:
            item = self.store.api_row(row)
            if row.get("processing_state") == "ANALYZED":
                item["coverage"] = self.coverage_service.calculate(
                    coverage_rows[row["id"]]
                )
            else:
                item["coverage"] = None
            items.append(item)
        return self._response({
            "items": items,
            "pagination": {
                "limit": limit_value,
                "cursor": str(offset),
                "nextCursor": next_cursor,
                "total": result["total"],
            },
        })

    def list_reading_series(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        self.store.get_profile(profile_id)
        items = [self.store.api_row(row) for row in self.store.list_reading_series(profile_id)]
        by_id = {item["id"]: item for item in items}
        for item in items:
            item["episodes"] = []
        for row in self.store.list_reading_series_episodes(profile_id):
            by_id[row["series_id"]]["episodes"].append(self.store.api_row(row))
        return self._response({"items": items})

    def create_reading_series(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        payload = self._object(payload)
        if set(payload) - {"title", "premise", "continuityNotes"}:
            raise LanguageValidationError("Series contains unsupported fields")
        self.store.get_profile(profile_id)
        title = self._text(payload.get("title"), "title", maximum=200)
        premise = self._optional_text(payload.get("premise"), "premise", maximum=2000) or ""
        notes = self._optional_text(payload.get("continuityNotes"), "continuityNotes", maximum=4000) or ""
        return self._response({"series": self.store.api_row(self.store.create_reading_series(profile_id, title, premise, notes))})

    def update_reading_series(self, series_id: str, payload: Any) -> dict[str, Any]:
        series_id = self._id(series_id, "seriesId")
        payload = self._object(payload)
        if set(payload) - {"title", "premise", "continuityNotes"}:
            raise LanguageValidationError("Series contains unsupported fields")
        current = self.store.get_reading_series(series_id)
        title = self._text(payload.get("title", current["title"]), "title", maximum=200)
        premise = self._optional_text(payload.get("premise", current["premise"]), "premise", maximum=2000) or ""
        notes = self._optional_text(payload.get("continuityNotes", current["continuity_notes"]), "continuityNotes", maximum=4000) or ""
        return self._response({"series": self.store.api_row(self.store.update_reading_series(series_id, title, premise, notes))})

    def assign_text_to_series(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        if set(payload) != {"seriesId"}:
            raise LanguageValidationError("seriesId is required")
        series_id = self._id(payload["seriesId"], "seriesId") if payload["seriesId"] is not None else None
        document = self.store.get_text(text_id)["document"]
        assignment = self.store.assign_text_to_series(document["language_profile_id"], text_id, series_id)
        return self._response({"assignment": assignment})

    def _analysis_job_values(
        self,
        text_id: str,
        *,
        job_type: str,
        request: dict[str, Any] | None = None,
        fingerprint_suffix: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self.store.analysis_snapshot(text_id)
        document = snapshot["document"]
        raw_text = document["raw_text"]
        if not raw_text.strip():
            raise LanguageValidationError(
                "Text must contain non-whitespace content before analysis",
                code="empty_language_text",
                details=["rawText"],
            )
        if len(raw_text.encode("utf-8")) > MAX_ANALYSIS_TEXT_BYTES:
            raise LanguageValidationError(
                "rawText is too large", code="language_text_too_large", details=["rawText"]
            )
        profile = self.store.get_profile(document["language_profile_id"])
        analyzer_id = str(profile.get("analyzer_id") or "")
        analyzer_version = str(profile.get("analyzer_version") or "")
        registration = self.analyzer_registry.describe(analyzer_id)
        if analyzer_version != registration["implementationVersion"]:
            raise LanguageConflictError(
                "Language profile analyzer version is not registered",
                code="language_analyzer_version_mismatch",
            )
        manual_lock_fingerprint = self._manual_lock_fingerprint(snapshot)
        try:
            analyzer_settings = json.loads(profile.get("analyzer_settings_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            analyzer_settings = {}
        fingerprint_inputs = {
            "contentFingerprint": document["content_fingerprint"],
            "languageProfileId": document["language_profile_id"],
            "analyzerId": analyzer_id,
            "analyzerVersion": analyzer_version,
            "analyzerSettings": analyzer_settings,
            "contractVersion": ANALYSIS_CONTRACT_VERSION,
            "analysisPolicyVersion": ANALYSIS_POLICY_VERSION,
            "frequencyProviderId": self.frequency_provider.provider_id,
            "frequencyProviderVersion": self.frequency_provider.provider_version,
            "coveragePolicyVersion": self.coverage_service.policy_version,
            "manualLockFingerprint": manual_lock_fingerprint,
            "suffix": fingerprint_suffix,
        }
        analysis_fingerprint = "sha256:" + hashlib.sha256(
            canonical_json(fingerprint_inputs).encode("utf-8")
        ).hexdigest()
        return {
            "language_profile_id": document["language_profile_id"],
            "text_document_id": document["id"],
            "job_type": job_type,
            "job_version": ANALYSIS_JOB_VERSION,
            "analyzer_id": analyzer_id,
            "analyzer_version": analyzer_version,
            "contract_version": ANALYSIS_CONTRACT_VERSION,
            "analysis_policy_version": ANALYSIS_POLICY_VERSION,
            "frequency_provider_id": self.frequency_provider.provider_id,
            "frequency_provider_version": self.frequency_provider.provider_version,
            "coverage_policy_version": self.coverage_service.policy_version,
            "content_fingerprint": document["content_fingerprint"],
            "analysis_fingerprint": analysis_fingerprint,
            "request": request or {},
        }

    @staticmethod
    def _manual_lock_fingerprint(snapshot: dict[str, Any]) -> str:
        locks = [
            {
                "form": row["form_normalized"],
                "lemmaId": row["lemma_id"],
                "mappingId": row.get("mapping_id"),
                "updatedAt": row.get("mapping_updated_at"),
            }
            for row in snapshot.get("manualLocks", [])
        ]
        encoded = canonical_json(locks).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _require_job_manager(self) -> Any:
        if self.job_manager is None:
            raise LanguageError(
                "Language analysis worker is unavailable",
                code="language_job_manager_unavailable",
                status=503,
            )
        return self.job_manager

    def _enqueue_job(self, values: dict[str, Any]) -> dict[str, Any]:
        manager = self._require_job_manager()
        row, created = self.store.create_analysis_job(
            values, max_pending=manager.max_pending_jobs
        )
        if created or row["state"] in {"QUEUED", "RUNNING"}:
            manager.start()
            manager.notify()
        return self._response({
            "job": self._public_job(row),
            "created": created,
            "reused": not created,
        })

    def enqueue_analysis(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        if payload:
            raise LanguageValidationError(
                "Analysis request does not accept options", details=sorted(payload)
            )
        return self._enqueue_job(self._analysis_job_values(text_id, job_type="ANALYZE"))

    def enqueue_reanalysis_preview(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        if payload:
            raise LanguageValidationError(
                "Reanalysis preview does not accept options", details=sorted(payload)
            )
        if self.store.analysis_snapshot(text_id)["analysisRun"] is None:
            raise LanguageConflictError(
                "Text has no committed analysis to preview against",
                code="language_text_not_analyzed",
            )
        return self._enqueue_job(
            self._analysis_job_values(text_id, job_type="REANALYSIS_PREVIEW")
        )

    def enqueue_reanalysis_commit(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"previewJobId"})
        if unknown:
            raise LanguageValidationError(
                "Reanalysis commit contains unsupported fields", details=unknown
            )
        preview_job_id = self._id(payload.get("previewJobId"), "previewJobId")
        if self.store.text_has_study_evidence(text_id):
            raise LanguageConflictError(
                "Committed reanalysis is blocked after Reader study evidence exists",
                code="studied_text_reanalysis_blocked",
            )
        preview = self.store.get_analysis_job(preview_job_id)
        if (
            preview["job_type"] != "REANALYSIS_PREVIEW"
            or preview["state"] != "COMPLETED"
            or preview["text_document_id"] != text_id
        ):
            raise LanguageConflictError(
                "A completed preview for this text is required",
                code="invalid_reanalysis_preview",
            )
        preview_result = json.loads(preview.get("result_json") or "{}")
        snapshot = self.store.analysis_snapshot(text_id)
        if (
            preview_result.get("baseAnalysisRunId")
            != (snapshot["analysisRun"] or {}).get("id")
            or preview_result.get("manualLockFingerprint")
            != self._manual_lock_fingerprint(snapshot)
        ):
            raise LanguageConflictError(
                "Reanalysis preview is stale", code="stale_reanalysis_preview"
            )
        values = self._analysis_job_values(
            text_id,
            job_type="REANALYSIS_COMMIT",
            request={"previewJobId": preview_job_id},
            fingerprint_suffix=preview_job_id,
        )
        return self._enqueue_job(values)

    def _public_job(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self.store.api_row(row) or {}
        result.pop("request", None)
        preview_result = result.get("result")
        if isinstance(preview_result, dict):
            preview_result = dict(preview_result)
            preview_result.pop("analysisDocument", None)
            result["result"] = preview_result
        return result

    def get_analysis_job(self, job_id: str) -> dict[str, Any]:
        return self._response({
            "job": self._public_job(self.store.get_analysis_job(self._id(job_id, "jobId")))
        })

    def cancel_analysis_job(self, job_id: str) -> dict[str, Any]:
        row = self.store.request_analysis_job_cancellation(self._id(job_id, "jobId"))
        manager = self.job_manager
        if manager is not None:
            manager.notify()
        return self._response({"job": self._public_job(row)})

    def analyze_for_job(self, job: dict[str, Any]) -> AnalysisDocument:
        request = json.loads(job.get("request_json") or "{}")
        candidate_id = request.get("generationCandidateId")
        if candidate_id:
            candidate = self.store.get_generation_candidate(candidate_id)
            if candidate.get("accepted_text_document_id") != job["text_document_id"] or not candidate.get("analysis_json"):
                raise LanguageConflictError(
                    "Accepted generation analysis is missing or stale",
                    code="stale_generation_candidate_analysis",
                )
            analysis = AnalysisDocument.from_dict(
                json.loads(candidate["analysis_json"])["analysisDocument"]
            )
            if analysis.original_text_fingerprint != job["content_fingerprint"]:
                raise LanguageConflictError(
                    "Accepted generation analysis does not match the text",
                    code="stale_generation_candidate_analysis",
                )
            return analysis
        snapshot = self.store.analysis_snapshot(job["text_document_id"])
        document = snapshot["document"]
        profile = self.store.get_profile(job["language_profile_id"])
        if document["content_fingerprint"] != job["content_fingerprint"]:
            raise LanguageConflictError(
                "Text changed after analysis was queued", code="stale_language_analysis"
            )
        if profile["analyzer_id"] != job["analyzer_id"]:
            raise LanguageConflictError(
                "Language profile analyzer changed after analysis was queued",
                code="stale_language_analysis",
            )
        analyzer = self.analyzer_registry.get(job["analyzer_id"])
        analysis = analyzer.analyze(
            document["raw_text"], language_code=profile["language_code"]
        )
        analysis.validate()
        if (
            analysis.language_code != profile["language_code"]
            or analysis.analyzer.analyzer_id != job["analyzer_id"]
            or analysis.analyzer.implementation_version != job["analyzer_version"]
            or analysis.contract_version != job["contract_version"]
        ):
            raise LanguageConflictError(
                "Analyzer output provenance does not match the queued job",
                code="invalid_analyzer_provenance",
            )
        if analysis.original_text_fingerprint != job["content_fingerprint"]:
            raise LanguageConflictError(
                "Analyzer output does not match the queued text", code="stale_language_analysis"
            )
        return analysis

    def frequency_rows_for_analysis(
        self, analysis: AnalysisDocument
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for sentence in analysis.sentences:
            for token in sentence.tokens:
                for candidate in token.lemma_candidates:
                    key = f"{candidate.normalized_lemma}|{candidate.pos or ''}"
                    if key in result:
                        continue
                    frequency = self.frequency_provider.lookup(
                        candidate.normalized_lemma,
                        language_code=analysis.language_code,
                    )
                    match_kind = "LEMMA"
                    if frequency is None or frequency.score is None or frequency.score <= 0:
                        frequency = self.frequency_provider.lookup(
                            token.normalized_lookup or token.surface,
                            language_code=analysis.language_code,
                        )
                        match_kind = "SURFACE"
                    if frequency is None or frequency.score is None:
                        continue
                    if frequency.rank is not None:
                        raise LanguageConflictError(
                            "Phase 2 frequency provider returned a forbidden exact rank",
                            code="invalid_frequency_provider_result",
                        )
                    result[key] = {
                        "metric": frequency.metric,
                        "score": frequency.score,
                        "lookup_value": frequency.lookup,
                        "match_kind": match_kind,
                        "provider_id": frequency.source.source_id,
                        "provider_version": frequency.source.source_version,
                        "retrieval_version": frequency.source.retrieval_or_import_version,
                        "observed_at": utc_now(),
                    }
        return result

    @staticmethod
    def _token_preview_value(token: Any) -> dict[str, Any]:
        selected = None
        if token.selected_lemma is not None:
            selected = next(
                (
                    {
                        "lemma": item.lemma,
                        "normalizedLemma": item.normalized_lemma,
                        "partOfSpeech": item.pos,
                    }
                    for item in token.lemma_candidates
                    if item.lemma == token.selected_lemma
                ),
                {"lemma": token.selected_lemma, "normalizedLemma": normalize_lookup(token.selected_lemma), "partOfSpeech": token.pos},
            )
        return {
            "surface": token.surface,
            "start": token.start,
            "end": token.end,
            "kind": token.kind.value,
            "selected": selected,
            "partOfSpeech": token.pos,
            "morphology": dict(token.morphology),
            "resolutionState": token.resolution_state.value,
        }

    def build_reanalysis_preview(
        self, job: dict[str, Any], analysis: AnalysisDocument
    ) -> dict[str, Any]:
        snapshot = self.store.analysis_snapshot(job["text_document_id"])
        current = snapshot["tokens"]
        proposed = [token for sentence in analysis.sentences for token in sentence.tokens]
        locks: dict[str, list[dict[str, Any]]] = {}
        for row in snapshot["manualLocks"]:
            locks.setdefault(row["form_normalized"], []).append(row)

        differences: list[dict[str, Any]] = []
        summary = {
            "tokenizationChanges": 0,
            "lemmaChanges": 0,
            "partOfSpeechChanges": 0,
            "morphologyChanges": 0,
            "unresolvedChanges": 0,
            "manualLockConflictsProtected": 0,
        }
        for index in range(max(len(current), len(proposed))):
            before = current[index] if index < len(current) else None
            after_token = proposed[index] if index < len(proposed) else None
            after = self._token_preview_value(after_token) if after_token is not None else None
            change_types: list[str] = []
            if before is None or after is None or (
                before["surface"], before["source_start"], before["source_end"], before["token_kind"]
            ) != (
                after["surface"], after["start"], after["end"], after["kind"]
            ):
                change_types.append("TOKENIZATION")
                summary["tokenizationChanges"] += 1

            before_lemma = (
                before.get("selected_lemma_normalized"), before.get("selected_lemma_pos")
            ) if before else (None, None)
            after_selected = after.get("selected") if after else None
            after_lemma = (
                after_selected.get("normalizedLemma"), after_selected.get("partOfSpeech")
            ) if after_selected else (None, None)
            if before_lemma != after_lemma:
                change_types.append("LEMMA")
                summary["lemmaChanges"] += 1
            before_pos = before.get("part_of_speech") if before else None
            after_pos = after.get("partOfSpeech") if after else None
            if before_pos != after_pos:
                change_types.append("PART_OF_SPEECH")
                summary["partOfSpeechChanges"] += 1
            before_morphology = json.loads(before.get("morphology_json") or "{}") if before else {}
            after_morphology = after.get("morphology") if after else {}
            if before_morphology != after_morphology:
                change_types.append("MORPHOLOGY")
                summary["morphologyChanges"] += 1
            before_unresolved = not before or not before.get("selected_lemma_id")
            after_unresolved = not after_selected
            if before_unresolved != after_unresolved:
                change_types.append("RESOLUTION")
                summary["unresolvedChanges"] += 1

            protected = False
            if after_token is not None and after_token.normalized_lookup:
                form_locks = locks.get(after_token.normalized_lookup, [])
                proposed_keys = {
                    (item.normalized_lemma, item.pos) for item in after_token.lemma_candidates
                }
                locked_keys = {
                    (item["lemma_normalized"], item["part_of_speech"]) for item in form_locks
                }
                if len(form_locks) > 1 or (
                    form_locks and proposed_keys.isdisjoint(locked_keys)
                ):
                    protected = True
                    change_types.append("MANUAL_LOCK_CONFLICT")
                    summary["manualLockConflictsProtected"] += 1

            if change_types:
                differences.append({
                    "tokenIndex": index,
                    "changeTypes": change_types,
                    "before": {
                        "surface": before.get("surface"),
                        "start": before.get("source_start"),
                        "end": before.get("source_end"),
                        "selectedLemma": before.get("selected_lemma_display"),
                        "partOfSpeech": before_pos,
                        "morphology": before_morphology,
                    } if before else None,
                    "after": after,
                    "manualLockProtected": protected,
                })

        return {
            "textDocumentId": job["text_document_id"],
            "baseAnalysisRunId": (
                snapshot["analysisRun"]["id"] if snapshot["analysisRun"] else None
            ),
            "manualLockFingerprint": self._manual_lock_fingerprint(snapshot),
            "summary": summary,
            "differences": differences,
            "analysisDocument": analysis.to_dict(),
        }

    def analysis_from_preview_job(self, job: dict[str, Any]) -> AnalysisDocument:
        request = json.loads(job.get("request_json") or "{}")
        preview_id = request.get("previewJobId")
        preview = self.store.get_analysis_job(str(preview_id or ""))
        if (
            preview["job_type"] != "REANALYSIS_PREVIEW"
            or preview["state"] != "COMPLETED"
            or preview["text_document_id"] != job["text_document_id"]
        ):
            raise LanguageConflictError(
                "Reanalysis preview is no longer valid", code="invalid_reanalysis_preview"
            )
        result = json.loads(preview.get("result_json") or "{}")
        analysis_payload = result.get("analysisDocument")
        if not isinstance(analysis_payload, dict):
            raise LanguageConflictError(
                "Reanalysis preview has no commit payload", code="invalid_reanalysis_preview"
            )
        analysis = AnalysisDocument.from_dict(analysis_payload)
        if analysis.original_text_fingerprint != job["content_fingerprint"]:
            raise LanguageConflictError(
                "Reanalysis preview is stale", code="stale_language_analysis"
            )
        return analysis

    def commit_analysis_for_job(
        self, job: dict[str, Any], analysis: AnalysisDocument
    ) -> dict[str, Any]:
        if (
            job.get("job_type") == "REANALYSIS_COMMIT"
            and self.store.text_has_study_evidence(job["text_document_id"])
        ):
            raise LanguageConflictError(
                "Committed reanalysis is blocked after Reader study evidence exists",
                code="studied_text_reanalysis_blocked",
            )
        frequencies = self.frequency_rows_for_analysis(analysis)
        return self.store.commit_analysis_job(job["id"], analysis, frequencies=frequencies)

    def create_study_session(self, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        values = {
            "language_profile_id": self._id(payload.get("languageProfileId"), "languageProfileId"),
            "text_document_id": self._id(payload["textDocumentId"], "textDocumentId") if payload.get("textDocumentId") else None,
            "session_type": self._enum(payload.get("sessionType"), "sessionType", SESSION_TYPES),
            "status": self._enum(payload.get("status", "ACTIVE"), "status", SESSION_STATUSES),
            "client_session_id": self._optional_text(payload.get("clientSessionId"), "clientSessionId", maximum=200),
            "started_at": self._optional_text(payload.get("startedAt"), "startedAt", maximum=80),
            "ended_at": self._optional_text(payload.get("endedAt"), "endedAt", maximum=80),
            "active_seconds": payload.get("activeSeconds", 0),
        }
        if isinstance(values["active_seconds"], bool) or not isinstance(values["active_seconds"], int) or values["active_seconds"] < 0:
            raise LanguageValidationError("activeSeconds must be a non-negative integer", details=["activeSeconds"])
        row, created = self.store.create_session(values)
        return self._response({"session": self.store.api_row(row), "created": created})

    def start_reader_session(self, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        unknown = sorted(
            set(payload) - {"languageProfileId", "textDocumentId", "clientSessionId"}
        )
        if unknown:
            raise LanguageValidationError(
                "Reader session contains unsupported fields", details=unknown
            )
        profile_id = self._id(payload.get("languageProfileId"), "languageProfileId")
        text_id = self._id(payload.get("textDocumentId"), "textDocumentId")
        client_id = self._text(
            payload.get("clientSessionId"), "clientSessionId", maximum=200
        )
        text = self.store.get_text(text_id)
        document = text["document"]
        if document["language_profile_id"] != profile_id:
            raise LanguageConflictError(
                "Reader text belongs to another profile", code="cross_profile_relationship"
            )
        if document["processing_state"] != "ANALYZED" or not text["analysisRuns"]:
            raise LanguageConflictError(
                "Reader sessions require an analyzed text",
                code="language_text_not_analyzed",
            )
        row, created = self.store.create_session(
            {
                "language_profile_id": profile_id,
                "text_document_id": text_id,
                "session_type": "READER",
                "status": "ACTIVE",
                "activity_state": "ACTIVE",
                "client_session_id": client_id,
            }
        )
        if (
            row["language_profile_id"] != profile_id
            or row["text_document_id"] != text_id
            or row["session_type"] != "READER"
        ):
            raise LanguageConflictError(
                "Reader session idempotency key belongs to another session",
                code="reader_session_idempotency_conflict",
            )
        return self._response(
            {"session": self.store.api_row(row), "created": created, "reused": not created}
        )

    def update_reader_session(self, session_id: str, payload: Any) -> dict[str, Any]:
        session_id = self._id(session_id, "studySessionId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"action", "commandId"})
        if unknown:
            raise LanguageValidationError(
                "Reader session command contains unsupported fields", details=unknown
            )
        action = self._enum(payload.get("action"), "action", READER_SESSION_ACTIONS)
        command_id = self._text(payload.get("commandId"), "commandId", maximum=200)
        row, applied = self.store.update_reader_session(
            session_id, action=action, command_id=command_id
        )
        if applied:
            self.gamification_service.reconcile_profile(str(row["language_profile_id"]))
        return self._response(
            {
                "session": self.store.api_row(row),
                "applied": applied,
                "duplicate": not applied,
            }
        )

    def record_reader_exposure_batch(
        self, session_id: str, payload: Any
    ) -> dict[str, Any]:
        session_id = self._id(session_id, "studySessionId")
        payload = self._object(payload)
        unknown = sorted(
            set(payload)
            - {"textDocumentId", "sentenceId", "idempotencyKey", "occurrences"}
        )
        if unknown:
            raise LanguageValidationError(
                "Reader exposure batch contains unsupported fields", details=unknown
            )
        text_id = self._id(payload.get("textDocumentId"), "textDocumentId")
        sentence_id = self._id(payload.get("sentenceId"), "sentenceId")
        idempotency_key = self._text(
            payload.get("idempotencyKey"), "idempotencyKey", maximum=120
        )
        occurrences = payload.get("occurrences")
        if not isinstance(occurrences, list) or len(occurrences) > 500:
            raise LanguageValidationError(
                "occurrences must be a bounded list", details=["occurrences"]
            )
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(occurrences):
            if not isinstance(item, dict) or set(item) != {"lemmaId", "occurrenceCount"}:
                raise LanguageValidationError(
                    "Each occurrence must contain lemmaId and occurrenceCount",
                    details=[f"occurrences[{index}]"],
                )
            lemma_id = self._id(item.get("lemmaId"), f"occurrences[{index}].lemmaId")
            count = item.get("occurrenceCount")
            if (
                lemma_id in seen
                or isinstance(count, bool)
                or not isinstance(count, int)
                or not 1 <= count <= 1000
            ):
                raise LanguageValidationError(
                    "Occurrence claims must be unique bounded positive counts",
                    details=[f"occurrences[{index}]"],
                )
            seen.add(lemma_id)
            normalized.append({"lemma_id": lemma_id, "occurrence_count": count})
        result = self.store.record_reader_exposure_batch(
            session_id=session_id,
            text_id=text_id,
            sentence_id=sentence_id,
            idempotency_key=idempotency_key,
            submitted_occurrences=normalized,
        )
        if result["created"]:
            session = self.store.get_reader_session(session_id)
            self.gamification_service.reconcile_profile(str(session["language_profile_id"]))
        return self._response(
            {
                "created": result["created"],
                "duplicate": result["duplicate"],
                "events": [self.store.api_row(row) for row in result["events"]],
            }
        )

    def listening_materials(self, profile_id: str, *, limit: Any = 100) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        if isinstance(limit, bool):
            raise LanguageValidationError("limit must be an integer", details=["limit"])
        try:
            parsed_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("limit must be an integer", details=["limit"]) from exc
        result = self.store.list_listening_materials(profile_id, limit=parsed_limit)
        return self._response({
            "items": [self.store.api_row(row) for row in result["items"]],
            "total": result["total"],
            "activityPolicyVersion": LISTENING_ACTIVITY_POLICY_VERSION,
            "exposurePolicyVersion": LISTENING_EXPOSURE_POLICY_VERSION,
            "completionPolicyVersion": LISTENING_COMPLETION_POLICY_VERSION,
            "qualificationThreshold": LISTENING_QUALIFICATION_THRESHOLD,
        })

    def content_items(self, profile_id: str, *, limit: Any = 100) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        try:
            parsed_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("limit must be an integer", details=["limit"]) from exc
        return self._response(self.content_inbox.list(profile_id, parsed_limit))

    def content_detail(self, content_id: str) -> dict[str, Any]:
        return self._response(self.content_inbox.detail(self._id(content_id, "contentId")))

    def create_content(self, profile_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.content_inbox.create(
            self._id(profile_id, "profileId"), self._object(payload)
        ))

    def import_content_audio(
        self, profile_id: str, *, data: bytes, title: str, original_name: str, mime_type: str,
    ) -> dict[str, Any]:
        return self._response(self.content_inbox.import_audio(
            self._id(profile_id, "profileId"), data=data, title=title,
            original_name=original_name, mime_type=mime_type,
        ))

    def add_content_transcript(self, content_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.content_inbox.add_transcript(
            self._id(content_id, "contentId"), self._object(payload)
        ))

    def correct_content_alignment(self, alignment_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.content_inbox.correct_alignment(
            self._id(alignment_id, "alignmentId"), self._object(payload)
        ))

    def content_media_file(self, artifact_id: str):
        return self.content_inbox.media_file(self._id(artifact_id, "artifactId"))

    def refresh_content_alignment(self, text_document_id: str) -> None:
        self.content_inbox.refresh_alignment_for_text(text_document_id)

    def listening_progress(self, text_id: str, *, profile_id: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        profile_id = self._id(profile_id, "profileId")
        return self._response({
            "progress": self.store.api_row(self.store.listening_progress(profile_id, text_id)),
            "completionPolicyVersion": LISTENING_COMPLETION_POLICY_VERSION,
        })

    def start_listening_session(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"languageProfileId", "clientSessionId", "mode"})
        if unknown:
            raise LanguageValidationError(
                "Listening session contains unsupported fields", details=unknown
            )
        profile_id = self._id(payload.get("languageProfileId"), "languageProfileId")
        client_id = self._text(payload.get("clientSessionId"), "clientSessionId", maximum=200)
        mode = self._enum(payload.get("mode", "READ_LISTEN"), "mode", set(LISTENING_MODES))
        text = self.store.get_text(text_id)
        document = text["document"]
        if document["language_profile_id"] != profile_id:
            raise LanguageConflictError(
                "Listening text belongs to another profile", code="cross_profile_relationship"
            )
        if document["processing_state"] != "ANALYZED" or not text["analysisRuns"] or not text["sentences"]:
            raise LanguageConflictError(
                "Listening requires an analyzed text with canonical sentences",
                code="language_text_not_analyzed",
            )
        row, created = self.store.create_listening_session({
            "language_profile_id": profile_id,
            "text_document_id": text_id,
            "client_session_id": client_id,
            "mode": mode,
            "activity_policy_version": LISTENING_ACTIVITY_POLICY_VERSION,
            "exposure_policy_version": LISTENING_EXPOSURE_POLICY_VERSION,
            "completion_policy_version": LISTENING_COMPLETION_POLICY_VERSION,
        })
        if (
            row["language_profile_id"] != profile_id
            or row["text_document_id"] != text_id
            or row["session_type"] != "LISTENING"
            or row["mode"] != mode
        ):
            raise LanguageConflictError(
                "Listening session idempotency key belongs to another session",
                code="listening_session_idempotency_conflict",
            )
        return self._response({
            "session": self.store.api_row(row), "created": created, "reused": not created,
        })

    def record_listening_sentence_event(self, session_id: str, payload: Any) -> dict[str, Any]:
        session_id = self._id(session_id, "listeningSessionId")
        payload = self._object(payload)
        allowed = {
            "textDocumentId", "sentenceId", "idempotencyKey", "outcome",
            "playbackSource", "activeMs", "coverageMs", "durationMs", "alignmentId", "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError(
                "Listening sentence event contains unsupported fields", details=unknown
            )
        session = self.store.get_listening_session(session_id)
        text_id = self._id(payload.get("textDocumentId"), "textDocumentId")
        sentence_id = self._id(payload.get("sentenceId"), "sentenceId")
        event_key = self._text(payload.get("idempotencyKey"), "idempotencyKey", maximum=160)
        outcome = self._enum(payload.get("outcome"), "outcome", set(LISTENING_OUTCOMES))
        playback_source = self._enum(
            payload.get("playbackSource"), "playbackSource", set(LISTENING_PLAYBACK_SOURCES)
        )
        document = self.store.get_text(text_id)["document"]
        alignment = None
        alignment_id = None
        if playback_source == "AUTHENTIC_MEDIA":
            alignment_id = self._id(payload.get("alignmentId"), "alignmentId")
            alignment = self.content_inbox.alignment_for_event(text_id, sentence_id, alignment_id)
            expected_source = "AUTHENTIC_MEDIA"
        else:
            expected_source = (
                "CLOUD_TTS"
                if str(document.get("source_type") or "").startswith("GENERATED_")
                else "BROWSER_TTS"
            )
        if playback_source != expected_source:
            raise LanguageConflictError(
                "Listening playback source does not match the text source",
                code="invalid_listening_playback_source",
            )
        authoritative_duration = (
            int(alignment["end_ms"]) - int(alignment["start_ms"])
            if alignment is not None else payload.get("durationMs")
        )
        active_ms, coverage_ms, duration_ms, completion_ratio = validate_playback_timing(
            payload.get("activeMs"), authoritative_duration, payload.get("coverageMs")
        )
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise LanguageValidationError("metadata must be an object", details=["metadata"])
        if len(canonical_json(metadata).encode("utf-8")) > 4096:
            raise LanguageValidationError("metadata is too large", details=["metadata"])
        qualified = qualifies_sentence_event(
            outcome=outcome, completion_ratio=completion_ratio
        )
        result = self.store.record_listening_sentence_event({
            "study_session_id": session_id,
            "language_profile_id": str(session["language_profile_id"]),
            "text_document_id": text_id,
            "sentence_id": sentence_id,
            "idempotency_key": event_key,
            "outcome": outcome,
            "playback_source": playback_source,
            "active_ms": active_ms,
            "coverage_ms": coverage_ms,
            "duration_ms": duration_ms,
            "completion_ratio": completion_ratio,
            "qualified": qualified,
            "completion_policy_version": LISTENING_COMPLETION_POLICY_VERSION,
            "metadata": metadata,
            "alignment_id": alignment_id,
            "exposure_eligible": bool(alignment["exposure_eligible"]) if alignment is not None else True,
        })
        if result["created"]:
            self.gamification_service.reconcile_profile(str(session["language_profile_id"]))
        return self._response({
            "event": self.store.api_row(result["event"]),
            "created": result["created"],
            "duplicate": result["duplicate"],
            "progress": self.store.api_row(result["progress"]),
            "exposures": [self.store.api_row(row) for row in result["exposures"]],
            "qualificationThreshold": LISTENING_QUALIFICATION_THRESHOLD,
        })

    def close_listening_session(self, session_id: str, payload: Any) -> dict[str, Any]:
        session_id = self._id(session_id, "listeningSessionId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"commandId"})
        if unknown:
            raise LanguageValidationError(
                "Listening session close contains unsupported fields", details=unknown
            )
        command_id = self._text(payload.get("commandId"), "commandId", maximum=200)
        row, applied = self.store.close_listening_session(session_id, command_id=command_id)
        return self._response({
            "session": self.store.api_row(row), "applied": applied, "duplicate": not applied,
        })

    def update_reading_progress(self, text_id: str, payload: Any) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        payload = self._object(payload)
        unknown = sorted(
            set(payload)
            - {"languageProfileId", "progressSourceOffset", "progressSentenceId", "status"}
        )
        if unknown:
            raise LanguageValidationError(
                "Reading progress contains unsupported fields", details=unknown
            )
        profile_id = self._id(payload.get("languageProfileId"), "languageProfileId")
        offset = payload.get("progressSourceOffset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise LanguageValidationError(
                "progressSourceOffset must be a non-negative integer",
                details=["progressSourceOffset"],
            )
        sentence_id = (
            self._id(payload["progressSentenceId"], "progressSentenceId")
            if payload.get("progressSentenceId")
            else None
        )
        status = self._enum(payload.get("status", "IN_PROGRESS"), "status", READING_STATUSES)
        snapshot = self.store.analysis_snapshot(text_id)
        if snapshot["document"]["language_profile_id"] != profile_id:
            raise LanguageConflictError(
                "Reading progress belongs to another profile",
                code="cross_profile_relationship",
            )
        if snapshot["analysisRun"] is None:
            raise LanguageConflictError(
                "Reading progress requires an analyzed text",
                code="language_text_not_analyzed",
            )
        coverage = (
            self.coverage_service.calculate(self.store.coverage_rows(text_id))
            if status == "COMPLETED"
            else None
        )
        row = self.store.update_reading_progress(
            text_id=text_id,
            language_profile_id=profile_id,
            progress_source_offset=offset,
            progress_sentence_id=sentence_id,
            status=status,
            coverage_snapshot=coverage,
            analysis_run_id=snapshot["analysisRun"]["id"],
        )
        self.gamification_service.reconcile_profile(profile_id)
        return self._response({"readingProgress": self.store.api_row(row)})

    def record_exposure(self, payload: Any) -> dict[str, Any]:
        payload = self._object(payload)
        idempotency_key = self._text(payload.get("idempotencyKey"), "idempotencyKey", maximum=200)
        source_type = self._text(payload.get("sourceType"), "sourceType", maximum=80).upper()
        if source_type == "LISTENING":
            raise LanguageValidationError(
                "Listening exposures are derived only from authoritative sentence events",
                code="reserved_listening_exposure_source",
            )
        occurrence_count = payload.get("occurrenceCount", 1)
        if isinstance(occurrence_count, bool) or not isinstance(occurrence_count, int) or not 1 <= occurrence_count <= 100000:
            raise LanguageValidationError("occurrenceCount must be an integer from 1 to 100000", details=["occurrenceCount"])
        values = {
            "idempotency_key": idempotency_key,
            "language_profile_id": self._id(payload.get("languageProfileId"), "languageProfileId"),
            "lemma_id": self._id(payload.get("lemmaId"), "lemmaId"),
            "surface_form_id": self._id(payload["surfaceFormId"], "surfaceFormId") if payload.get("surfaceFormId") else None,
            "text_document_id": self._id(payload["textDocumentId"], "textDocumentId") if payload.get("textDocumentId") else None,
            "sentence_id": self._id(payload["sentenceId"], "sentenceId") if payload.get("sentenceId") else None,
            "token_id": self._id(payload["tokenId"], "tokenId") if payload.get("tokenId") else None,
            "study_session_id": self._id(payload.get("studySessionId"), "studySessionId"),
            "source_type": source_type,
            "occurrence_count": occurrence_count,
            "occurred_at": self._optional_text(payload.get("occurredAt"), "occurredAt", maximum=80),
        }
        row, created = self.store.record_exposure(values)
        if created:
            self.gamification_service.reconcile_profile(values["language_profile_id"])
        return self._response({"exposure": self.store.api_row(row), "created": created, "duplicate": not created})

    @staticmethod
    def _topic_slug(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise LanguageValidationError("slug must be a non-empty string", details=["slug"])
        slug = re.sub(r"[^a-z0-9æøå]+", "-", value.strip().casefold()).strip("-")
        if not slug or len(slug) > 80:
            raise LanguageValidationError("slug is invalid", details=["slug"])
        return slug

    @staticmethod
    def _timezone_name(value: Any) -> str:
        name = str(value or DEFAULT_TIMEZONE)
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise LanguageValidationError("timezone is invalid", details=["timezone"]) from exc
        return name

    def list_topics(self, profile_id: str, *, include_archived: Any = False, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        include = str(include_archived).lower() in {"1", "true", "yes"}
        items = self.statistics_service.topic_summaries(
            profile_id, include_archived=include, as_of=as_of
        )
        return self._response({"items": items})

    def get_topic(self, topic_id: str, *, as_of: Any = None) -> dict[str, Any]:
        topic_id = self._id(topic_id, "topicId")
        detail = self.store.get_topic(topic_id)
        mastery = self.statistics_service.topic_summaries(
            str(detail["topic"]["language_profile_id"]), include_archived=True, as_of=as_of
        )
        summary = next(item for item in mastery if item["topic"]["id"] == topic_id)
        return self._response({
            "topic": self.store.api_row(detail["topic"]),
            "lemmas": [self.store.api_row(row) for row in detail["lemmas"]],
            "mastery": summary,
        })

    def create_topic(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"slug", "displayName", "description", "parentTopicId"})
        if unknown:
            raise LanguageValidationError("Topic contains unsupported fields", details=unknown)
        display = self._text(payload.get("displayName"), "displayName", maximum=120)
        parent_id = self._id(payload["parentTopicId"], "parentTopicId") if payload.get("parentTopicId") else None
        row = self.store.create_topic({
            "language_profile_id": profile_id,
            "slug": self._topic_slug(payload.get("slug") or display),
            "display_name": display,
            "description": self._optional_text(payload.get("description"), "description", maximum=2000),
            "parent_topic_id": parent_id,
        })
        return self._response({"topic": self.store.api_row(row)})

    def update_topic(self, topic_id: str, payload: Any) -> dict[str, Any]:
        topic_id = self._id(topic_id, "topicId")
        payload = self._object(payload)
        allowed = {"slug", "displayName", "description", "parentTopicId", "archived"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError("Topic update contains unsupported fields", details=unknown)
        changes: dict[str, Any] = {}
        if "slug" in payload:
            changes["slug"] = self._topic_slug(payload["slug"])
        if "displayName" in payload:
            changes["display_name"] = self._text(payload["displayName"], "displayName", maximum=120)
        if "description" in payload:
            changes["description"] = self._optional_text(payload["description"], "description", maximum=2000)
        if "parentTopicId" in payload:
            changes["parent_topic_id"] = self._id(payload["parentTopicId"], "parentTopicId") if payload["parentTopicId"] else None
        if "archived" in payload:
            if not isinstance(payload["archived"], bool):
                raise LanguageValidationError("archived must be boolean", details=["archived"])
            changes["archived"] = 1 if payload["archived"] else 0
        row = self.store.update_topic(topic_id, changes)
        return self._response({"topic": self.store.api_row(row)})

    def assign_topic_lemma(self, topic_id: str, payload: Any) -> dict[str, Any]:
        topic_id = self._id(topic_id, "topicId")
        payload = self._object(payload)
        unknown = sorted(set(payload) - {"lemmaId", "weight", "provenance", "membershipState", "sourceReference"})
        if unknown:
            raise LanguageValidationError("Topic membership contains unsupported fields", details=unknown)
        detail = self.store.get_topic(topic_id)
        lemma_id = self._id(payload.get("lemmaId"), "lemmaId")
        weight = payload.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 < float(weight) <= 10:
            raise LanguageValidationError("weight must be greater than 0 and at most 10", details=["weight"])
        provenance = self._enum(payload.get("provenance", "MANUAL"), "provenance", TOPIC_PROVENANCE)
        state = self._enum(payload.get("membershipState", "MANUAL"), "membershipState", TOPIC_MEMBERSHIP_STATES)
        if provenance != "MANUAL" or state != "MANUAL":
            raise LanguageValidationError(
                "Phase 5 UI accepts manual topic membership only",
                code="topic_import_not_available",
            )
        row, created = self.store.upsert_topic_lemma({
            "topic_id": topic_id,
            "lemma_id": lemma_id,
            "language_profile_id": detail["topic"]["language_profile_id"],
            "weight": float(weight),
            "provenance": provenance,
            "membership_state": state,
            "source_reference": self._optional_text(payload.get("sourceReference"), "sourceReference", maximum=500),
        })
        return self._response({"membership": self.store.api_row(row), "created": created})

    def remove_topic_lemma(self, topic_id: str, lemma_id: str) -> dict[str, Any]:
        removed = self.store.remove_topic_lemma(
            self._id(topic_id, "topicId"), self._id(lemma_id, "lemmaId")
        )
        return self._response({"removed": removed})

    def _goal_values(self, profile_id: str, payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        metric = self._enum(
            payload.get("metric", current.get("metric") if current else None),
            "metric", set(GOAL_METRIC_UNITS),
        )
        period = self._enum(
            payload.get("period", current.get("period") if current else "WEEK"),
            "period", GOAL_PERIODS,
        )
        unit = self._enum(
            payload.get("unit", current.get("unit") if current else GOAL_METRIC_UNITS[metric]),
            "unit", set(GOAL_METRIC_UNITS.values()),
        )
        if unit != GOAL_METRIC_UNITS[metric]:
            raise LanguageValidationError("unit does not match metric", code="invalid_goal_metric_unit")
        target = payload.get("targetValue", current.get("target_value") if current else None)
        if isinstance(target, bool) or not isinstance(target, (int, float)) or float(target) <= 0:
            raise LanguageValidationError("targetValue must be greater than zero", details=["targetValue"])
        week_start = payload.get("weekStart", current.get("week_start") if current else 1)
        if isinstance(week_start, bool) or not isinstance(week_start, int) or not 1 <= week_start <= 7:
            raise LanguageValidationError("weekStart must be from 1 to 7", details=["weekStart"])
        enabled = payload.get("enabled", bool(current.get("enabled")) if current else True)
        if not isinstance(enabled, bool):
            raise LanguageValidationError("enabled must be boolean", details=["enabled"])
        active_from = self._optional_text(
            payload.get("activeFrom", current.get("active_from") if current else None),
            "activeFrom", maximum=10,
        )
        active_until = self._optional_text(
            payload.get("activeUntil", current.get("active_until") if current else None),
            "activeUntil", maximum=10,
        )
        parsed_dates = {}
        for field, value in (("activeFrom", active_from), ("activeUntil", active_until)):
            if value:
                try:
                    parsed_dates[field] = date.fromisoformat(value)
                except ValueError as exc:
                    raise LanguageValidationError(
                        f"{field} must be an ISO date", details=[field]
                    ) from exc
        if parsed_dates.get("activeFrom") and parsed_dates.get("activeUntil") \
                and parsed_dates["activeFrom"] > parsed_dates["activeUntil"]:
            raise LanguageValidationError(
                "activeFrom must not be after activeUntil",
                details=["activeFrom", "activeUntil"],
            )
        return {
            "language_profile_id": profile_id,
            "metric": metric,
            "period": period,
            "target_value": float(target),
            "unit": unit,
            "active_from": active_from,
            "active_until": active_until,
            "week_start": week_start,
            "timezone": self._timezone_name(payload.get("timezone", current.get("timezone") if current else DEFAULT_TIMEZONE)),
            "enabled": enabled,
            "rule_version": GOAL_RULE_VERSION,
        }

    def list_goals(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response({"items": self.statistics_service.goals(profile_id, as_of=as_of)})

    def create_goal(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        payload = self._object(payload)
        allowed = {"metric", "period", "targetValue", "unit", "activeFrom", "activeUntil", "weekStart", "timezone", "enabled"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError("Goal contains unsupported fields", details=unknown)
        row = self.store.create_goal(self._goal_values(profile_id, payload))
        self.gamification_service.reconcile_profile(profile_id)
        return self._response(self.statistics_service.goal_progress(row))

    def update_goal(self, goal_id: str, payload: Any) -> dict[str, Any]:
        goal_id = self._id(goal_id, "goalId")
        payload = self._object(payload)
        allowed = {"metric", "period", "targetValue", "unit", "activeFrom", "activeUntil", "weekStart", "timezone", "enabled"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise LanguageValidationError("Goal update contains unsupported fields", details=unknown)
        current = self.store.get_goal(goal_id)
        values = self._goal_values(str(current["language_profile_id"]), payload, current)
        values.pop("language_profile_id", None)
        row = self.store.update_goal(goal_id, values)
        self.gamification_service.reconcile_profile(str(current["language_profile_id"]))
        return self._response(self.statistics_service.goal_progress(row))

    def statistics(self, profile_id: str, *, range_name: Any = "30d", as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        result = self.statistics_service.calculate(
            profile_id, range_name=str(range_name), timezone_name=DEFAULT_TIMEZONE, as_of=as_of
        )
        result["cloze"] = self.store.cloze_summary(profile_id)
        result["mistakes"] = self.mistake_intelligence_service.summary(profile_id, as_of=as_of)
        return self._response(result)

    def learning_plan(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        anki = self.anki_sync_service.status(profile_id, probe=True)
        cloze = self.store.cloze_summary(profile_id)
        return self._response(self.learning_plan_service.build(profile_id, as_of=as_of, anki=anki, cloze=cloze))

    def mistakes(self, profile_id: str, *, as_of: Any = None, limit: Any = 10) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        try:
            bounded = max(1, min(int(limit), 25))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("limit must be an integer", details=["limit"]) from exc
        return self._response(self.mistake_intelligence_service.summary(profile_id, as_of=as_of, limit=bounded))

    def mistake_detail(self, profile_id: str, cluster_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        cluster_id = self._text(cluster_id, "clusterId", maximum=80)
        return self._response(self.mistake_intelligence_service.detail(profile_id, cluster_id, as_of=as_of))

    def remediation(self, profile_id: str, *, as_of: Any = None, limit: Any = 5) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        try:
            bounded = max(1, min(int(limit), 10))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("limit must be an integer", details=["limit"]) from exc
        return self._response(self.mistake_intelligence_service.remediation(profile_id, as_of=as_of, limit=bounded))

    def overview(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        statistics = self.statistics_service.calculate(
            profile_id, range_name="7d", timezone_name=DEFAULT_TIMEZONE, as_of=as_of
        )
        goals = self.statistics_service.goals(profile_id, as_of=as_of)
        anki = self.anki_sync_service.status(profile_id, probe=False)
        plan = self.learning_plan_service.build(
            profile_id, as_of=as_of, anki=anki, cloze=self.store.cloze_summary(profile_id)
        )
        mistakes = self.mistake_intelligence_service.summary(profile_id, as_of=as_of, limit=3)
        gamification = self.gamification_service.summary(
            profile_id, as_of=as_of, statistics=statistics
        )
        return self._response({
            "policyVersion": "language.overview/v2",
            "statistics": statistics,
            "goals": goals,
            "todayPlan": plan,
            "topics": statistics["topics"],
            "frequencyCoverage": statistics["frequencyCoverage"],
            "anki": anki,
            "gamification": gamification,
            "mistakes": {
                "activeClusterCount": mistakes["activeClusterCount"],
                "recoveredClusterCount": mistakes["recoveredClusterCount"],
                "topProblems": mistakes["topProblems"][:3],
                "policyVersion": mistakes["policies"]["clustering"],
            },
        })

    def widget_summary(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        return self.today_summary(profile_id, as_of=as_of)

    def today_summary(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        """Small read-only learner snapshot. No analyzer, provider, or live Anki calls."""
        profile_id = self._id(profile_id, "profileId")
        profile = self.store.api_row(self.store.get_profile(profile_id))
        now = datetime.fromisoformat(as_of.replace("Z", "+00:00")) if isinstance(as_of, str) else (as_of or datetime.now(timezone.utc))
        local_day = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
        day_start = datetime.combine(local_day, time.min, ZoneInfo(DEFAULT_TIMEZONE)).astimezone(timezone.utc).isoformat()
        day_end = datetime.combine(local_day, time.max, ZoneInfo(DEFAULT_TIMEZONE)).astimezone(timezone.utc).isoformat()
        with self.store.connection() as connection:
            tracked = int(connection.execute(
                "SELECT COUNT(*) FROM vocabulary_lemmas WHERE language_profile_id=? AND merged_into_id IS NULL",
                (profile_id,),
            ).fetchone()[0])
            known_words = int(connection.execute(
                "SELECT COUNT(*) FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL "
                "AND k.disposition='TRACKED' AND k.knowledge_status IN ('KNOWN','MASTERED')",
                (profile_id,),
            ).fetchone()[0])
            xp = int(connection.execute(
                "SELECT COALESCE(SUM(xp_amount),0) FROM gamification_awards WHERE language_profile_id=?",
                (profile_id,),
            ).fetchone()[0])
            reader_seconds = int(connection.execute(
                "SELECT COALESCE(SUM(active_seconds),0) FROM study_sessions WHERE language_profile_id=? "
                "AND session_type IN ('READER','GENERATED_READER') AND started_at>=? AND started_at<=?",
                (profile_id, day_start, day_end),
            ).fetchone()[0])
            reader_seconds_7d = int(connection.execute(
                "SELECT COALESCE(SUM(active_seconds),0) FROM study_sessions WHERE language_profile_id=? "
                "AND session_type IN ('READER','GENERATED_READER') AND started_at>=? AND started_at<=?",
                (profile_id, (datetime.fromisoformat(day_start) - timedelta(days=6)).isoformat(), day_end),
            ).fetchone()[0])
            recent_reader_dates = [row[0] for row in connection.execute(
                "SELECT started_at FROM study_sessions WHERE language_profile_id=? "
                "AND session_type IN ('READER','GENERATED_READER') AND active_seconds>0 "
                "ORDER BY started_at DESC LIMIT 256", (profile_id,),
            ).fetchall()]
            recent_reader_dates += [row[0] for row in connection.execute(
                "SELECT occurred_at FROM exposure_events WHERE language_profile_id=? AND source_type='READER' "
                "ORDER BY occurred_at DESC LIMIT 256", (profile_id,),
            ).fetchall()]
            recent_reader_dates += [row[0] for row in connection.execute(
                "SELECT completed_at FROM text_reading_progress WHERE language_profile_id=? AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 128", (profile_id,),
            ).fetchall()]
            cloze_done = int(connection.execute(
                "SELECT COUNT(*) FROM cloze_attempts a JOIN cloze_sessions s ON s.id=a.session_id "
                "WHERE s.language_profile_id=? AND a.attempted_at>=? AND a.attempted_at<=?",
                (profile_id, day_start, day_end),
            ).fetchone()[0])
            cloze_review_done, cloze_new_done = connection.execute(
                "SELECT COALESCE(SUM(CASE WHEN s.practice_mode IN ('REVIEW','RECYCLE_MISTAKES','REMEDIATION') THEN 1 ELSE 0 END),0), "
                "COUNT(DISTINCT CASE WHEN s.practice_mode IN ('FAST_TRACK','CURRICULUM') "
                "AND NOT EXISTS (SELECT 1 FROM cloze_attempts earlier "
                "JOIN cloze_sessions earlier_session ON earlier_session.id=earlier.session_id "
                "WHERE earlier_session.language_profile_id=s.language_profile_id "
                "AND earlier.reference_sentence_source=a.reference_sentence_source "
                "AND earlier.reference_sentence_id=a.reference_sentence_id "
                "AND (earlier.attempted_at<a.attempted_at OR (earlier.attempted_at=a.attempted_at AND earlier.id<a.id))) "
                "THEN a.reference_sentence_source || char(31) || a.reference_sentence_id END) "
                "FROM cloze_attempts a JOIN cloze_sessions s ON s.id=a.session_id "
                "WHERE s.language_profile_id=? AND a.attempted_at>=? AND a.attempted_at<=?",
                (profile_id, day_start, day_end),
            ).fetchone()
            reader = connection.execute(
                "SELECT d.id,d.title,p.status,p.progress_source_offset,p.last_read_at,LENGTH(d.raw_text) AS text_length,"
                "(SELECT COUNT(*) FROM text_sentences s WHERE s.text_document_id=d.id) AS sentence_count,"
                "(SELECT COUNT(*) FROM text_sentences s WHERE s.text_document_id=d.id "
                "AND s.source_end<=p.progress_source_offset) AS sentences_read "
                "FROM text_reading_progress p JOIN text_documents d ON d.id=p.text_document_id "
                "WHERE p.language_profile_id=? AND p.status='IN_PROGRESS' "
                "ORDER BY p.last_read_at DESC,p.text_document_id DESC LIMIT 1",
                (profile_id,),
            ).fetchone()
            if reader is None:
                reader = connection.execute(
                    "SELECT d.id,d.title,COALESCE(p.status,'NOT_STARTED') AS status,"
                    "COALESCE(p.progress_source_offset,0) AS progress_source_offset,p.last_read_at,"
                    "LENGTH(d.raw_text) AS text_length,"
                    "(SELECT COUNT(*) FROM text_sentences s WHERE s.text_document_id=d.id) AS sentence_count,"
                    "(SELECT COUNT(*) FROM text_sentences s WHERE s.text_document_id=d.id "
                    "AND s.source_end<=COALESCE(p.progress_source_offset,0)) AS sentences_read "
                    "FROM text_documents d LEFT JOIN text_reading_progress p ON p.text_document_id=d.id "
                    "WHERE d.language_profile_id=? AND d.processing_state='ANALYZED' "
                    "AND COALESCE(p.status,'NOT_STARTED')!='COMPLETED' "
                    "ORDER BY d.created_at DESC,d.id DESC LIMIT 1", (profile_id,),
                ).fetchone()
        anki = self.anki_sync_service.status(profile_id, probe=False)
        last_sync = anki.get("lastSync") or {}
        sync_at = last_sync.get("startedAt") or last_sync.get("started_at")
        sync_day = None
        if sync_at:
            try:
                sync_day = datetime.fromisoformat(sync_at.replace("Z", "+00:00")).astimezone(
                    ZoneInfo(DEFAULT_TIMEZONE)).date()
            except (TypeError, ValueError):
                pass
        active_days = set()
        for value in recent_reader_dates:
            try:
                active_days.add(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    ZoneInfo(DEFAULT_TIMEZONE)).date())
            except (TypeError, ValueError):
                pass
        cursor = local_day if local_day in active_days else local_day - timedelta(days=1)
        streak_days = 0
        while cursor in active_days:
            streak_days += 1
            cursor -= timedelta(days=1)
        return self._response({
            "policyVersion": "language.today-summary/v1", "profileId": profile_id,
            "displayName": profile["displayName"], "localDate": local_day.isoformat(),
            "trackedVocabulary": tracked, "knownWords": known_words,
            "level": level_from_xp(xp), "streakDays": streak_days,
            "reader": {"todaySeconds": reader_seconds, "activeMinutes7d": reader_seconds_7d // 60,
                       "continue": self.store.api_row(dict(reader)) if reader else None},
            "cloze": {"answeredToday": cloze_done, "recommendedQuestionCount": 10 if tracked else None,
                      "reviewedToday": cloze_review_done, "newSentencesToday": cloze_new_done,
                      "dailyReviewGoal": 5, "dailyNewSentenceGoal": 3,
                      "availability": "CHECK_ON_START"},
            "anki": {"configured": anki.get("configured", False), "dueCount": anki.get("dueCount"),
                     "lastSyncAt": sync_at, "stale": sync_day != local_day,
                     "status": anki.get("status")},
            "startHere": tracked == 0 and reader_seconds == 0 and cloze_done == 0,
        })

    def anki_status(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.anki_sync_service.status(self._id(profile_id, "profileId"), probe=True))

    def sync_anki_web(self, profile_id: str, *, force: bool = False) -> dict[str, Any]:
        return self._response(self.anki_sync_service.sync_web(self._id(profile_id, "profileId"), force=force))

    def anki_insights(self, profile_id: str, *, offset: int = 0, limit: int = 50,
                      query: str = "", refresh: bool = False, deck_name: str | None = None) -> dict[str, Any]:
        return self._response(self.anki_sync_service.deck_insights(
            self._id(profile_id, "profileId"), offset=offset, limit=limit,
            query=query, refresh=refresh, deck_name=deck_name,
        ))

    def anki_config(self, profile_id: str) -> dict[str, Any]:
        return self._response({"config": self.anki_sync_service.public_config(self._id(profile_id, "profileId"))})

    def update_anki_config(self, profile_id: str, payload: Any) -> dict[str, Any]:
        return self._response({
            "config": self.anki_sync_service.update_config(self._id(profile_id, "profileId"), payload)
        })

    def test_anki(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.anki_sync_service.test_connection(self._id(profile_id, "profileId")))

    def anki_decks(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.anki_sync_service.decks(self._id(profile_id, "profileId")))

    def vocabulary_anki_status(self, profile_id: str, lemma_ids: list[str]) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        self.store.get_profile(profile_id)
        if not isinstance(lemma_ids, list) or len(lemma_ids) > 100:
            raise LanguageValidationError("Select up to 100 vocabulary items")
        ids = [self._id(value, "lemmaId") for value in lemma_ids]
        return self._response(self.anki_sync_service.vocabulary_card_states(profile_id, ids))

    def anki_models(self, profile_id: str) -> dict[str, Any]:
        return self._response(self.anki_sync_service.models(self._id(profile_id, "profileId")))

    def anki_model_fields(self, profile_id: str, model_name: str) -> dict[str, Any]:
        name = self._text(model_name, "modelName", maximum=200)
        return self._response(self.anki_sync_service.model_fields(self._id(profile_id, "profileId"), name))

    def preview_anki_note(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.anki_sync_service.preview(self._id(lemma_id, "lemmaId"), payload))

    def commit_anki_note(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.anki_sync_service.commit(self._id(lemma_id, "lemmaId"), payload))

    def link_anki_note(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.anki_sync_service.link_existing(self._id(lemma_id, "lemmaId"), payload))

    def resolve_anki_conflict(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self.anki_sync_service.resolve_conflict(self._id(lemma_id, "lemmaId"), payload))

    def get_lemma_anki(self, lemma_id: str) -> dict[str, Any]:
        return self._response(self.anki_sync_service.lemma_state(self._id(lemma_id, "lemmaId")))

    def record_anki_review_evidence(self, lemma_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        lemma_id = self._id(lemma_id, "lemmaId")
        card_id = payload.get("externalCardId")
        reviews = payload.get("reviews")
        lapses = payload.get("lapses")
        interval = payload.get("interval")
        key = f"card:{card_id}:reviews:{reviews}:lapses:{lapses}:interval:{interval}"
        row, created = self.store.record_anki_evidence(
            lemma_id, idempotency_key=key, payload={
                **payload,
                "ruleVersion": "language.anki-evidence/v1",
                "knowledgeMutation": "NONE",
                "historyCapability": "AGGREGATES_ONLY",
            }, created_at=str(payload.get("observedAt") or utc_now()),
        )
        if created:
            profile_id = str(self.store.get_lemma_detail(lemma_id)["lemma"]["language_profile_id"])
            self.gamification_service.reconcile_profile(profile_id)
        return {"event": self.store.api_row(row), "created": created}

    def record_cloze_evidence(self, attempt: dict[str, Any]) -> dict[str, Any]:
        outcome = str(attempt["outcome"])
        event_type = {
            "CORRECT": "CLOZE_CORRECT",
            "INCORRECT": "CLOZE_INCORRECT",
            "REVEALED": "CLOZE_REVEALED",
            "SKIPPED": "CLOZE_SKIPPED",
        }[outcome]
        payload = {
            "sessionId": attempt["session_id"], "itemIndex": int(attempt["item_index"]),
            "outcome": outcome, "responseMs": int(attempt["response_ms"]),
            "referenceTargetStableKey": attempt["reference_target_stable_key"],
            "referenceSentenceSource": attempt["reference_sentence_source"],
            "referenceSentenceId": attempt["reference_sentence_id"],
            "questionType": attempt.get("question_type") or "MULTIPLE_CHOICE",
            "sourceContextType": attempt.get("source_context_type") or "TATOEBA",
            "normalizationVersion": attempt.get("normalization_version"),
            "ruleVersion": "language.cloze-evidence/v1", "knowledgeMutation": "NONE",
        }
        row, created = self.store.record_cloze_evidence(
            str(attempt["target_lemma_id"]), event_type=event_type,
            idempotency_key=str(attempt["idempotency_key"]), payload=payload,
            created_at=str(attempt["attempted_at"]),
        )
        profile_id = str(self.store.get_lemma_detail(str(attempt["target_lemma_id"]))["lemma"]["language_profile_id"])
        self.gamification_service.reconcile_profile(profile_id)
        return {"event": self.store.api_row(row), "created": created}

    def cloze_tracks(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self._require_cloze().tracks(profile_id))

    def start_cloze_session(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self._require_cloze().start_session(profile_id, payload))

    def get_cloze_session(self, session_id: str) -> dict[str, Any]:
        return self._response(self._require_cloze().get_session(self._id(session_id, "sessionId")))

    def submit_cloze_attempt(self, session_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self._require_cloze().submit_attempt(self._id(session_id, "sessionId"), payload))

    def report_cloze_item(self, session_id: str, payload: Any) -> dict[str, Any]:
        return self._response(self._require_cloze().report_item(self._id(session_id, "sessionId"), payload))

    def generate_cloze_audio(self, session_id: str, payload: Any) -> dict[str, Any]:
        session_id = self._id(session_id, "sessionId")
        return self._response(self._require_cloze_audio().generate(session_id, payload))

    def cloze_audio_file(self, cache_key: str):
        return self._require_cloze_audio().audio_file(cache_key)

    def generate_generated_text_audio(
        self, text_id: str, sentence_id: str, payload: Any
    ) -> dict[str, Any]:
        text_id = self._id(text_id, "textId")
        sentence_id = self._id(sentence_id, "sentenceId")
        return self._response(
            self._require_generated_audio().generate(text_id, sentence_id, payload)
        )

    def generated_audio_file(self, cache_key: str):
        return self._require_generated_audio().audio_file(cache_key)

    def word_audio_for_lemma(self, lemma_id: str, *, retry: bool = False) -> dict[str, Any]:
        if self.word_audio_service is None:
            raise LanguageError("Word audio is unavailable", code="word_audio_unavailable", status=503)
        return self._response(self.word_audio_service.status(lemma_id=self._id(lemma_id, "lemmaId"), retry=retry))

    def word_audio_for_token(self, token_id: str, *, retry: bool = False) -> dict[str, Any]:
        if self.word_audio_service is None:
            raise LanguageError("Word audio is unavailable", code="word_audio_unavailable", status=503)
        return self._response(self.word_audio_service.status(token_id=self._id(token_id, "tokenId"), retry=retry))

    def cloze_statistics(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self._require_cloze().statistics(profile_id))

    def pull_anki(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.anki_sync_service.pull(
            profile_id, evidence_recorder=self.record_anki_review_evidence
        ))

    def anki_sync_runs(self, profile_id: str, *, limit: Any = 20) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        try:
            parsed = int(limit)
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("limit must be an integer", details=["limit"]) from exc
        return self._response(self.anki_sync_service.sync_runs(profile_id, parsed))

    def health(self) -> dict[str, Any]:
        info = self.store.schema_info()
        analyzer = self.analyzer_registry.describe(CANONICAL_ANALYZER_ID)
        worker = self.job_manager.status() if self.job_manager is not None else {
            "state": "UNAVAILABLE",
            "workerCount": 0,
            "maxPendingJobs": 0,
            "maxRecoveryAttempts": 0,
            "startupRecovery": {"requeued": 0, "cancelled": 0, "failed": 0},
        }
        return self._response({
            "status": "READY",
            "schemaVersion": info["schemaVersion"],
            "databaseInitialized": info["databaseInitialized"],
            "profileCount": info["profileCount"],
            "canonicalAnalyzer": {
                "id": CANONICAL_ANALYZER_ID,
                "adapterVersion": CANONICAL_ANALYZER_VERSION,
                "modelVersion": CANONICAL_MODEL_VERSION,
                "processors": list(CANONICAL_PROCESSORS),
                "runtimeState": (
                    "PIPELINE_READY"
                    if analyzer["pipelineLoaded"]
                    else "INSTANCE_CREATED_PIPELINE_LAZY"
                    if analyzer["loaded"]
                    else "LAZY_NOT_CREATED"
                ),
            },
            "referenceProviders": {
                "lexicon": (
                    self.reference_lexicon_service.health()
                    if self.reference_lexicon_service is not None
                    else {"configured": False, "available": False}
                ),
                "zipfFrequency": {
                    "id": self.frequency_provider.provider_id,
                    "version": self.frequency_provider.provider_version,
                    "metric": self.frequency_provider.metric,
                },
                "dictionary": self.dictionary_provider.health(),
                "translations": {
                    "englishLearnerGloss": "KELLY_SOURCE_GLOSS_WHEN_MATCHED",
                    "polish": "NOT_CONFIGURED_NO_ACCEPTED_SOURCE",
                    "userTranslations": "AVAILABLE",
                },
                "cefr": "UNSELECTED",
            },
            "analysisWorker": worker,
            "generationProvider": self.generation_provider.health(),
            "generatedReaderAudio": (
                self.generated_audio_service.health()
                if self.generated_audio_service is not None
                else {"state": "UNAVAILABLE"}
            ),
            "listening": {
                "activityPolicyVersion": LISTENING_ACTIVITY_POLICY_VERSION,
                "exposurePolicyVersion": LISTENING_EXPOSURE_POLICY_VERSION,
                "completionPolicyVersion": LISTENING_COMPLETION_POLICY_VERSION,
                "qualificationThreshold": LISTENING_QUALIFICATION_THRESHOLD,
                "browserCapabilityScope": "DEVICE_LOCAL_NOT_SERVER_GLOBAL",
                "browserAudioStored": False,
            },
            "gamification": {
                "xpPolicyVersion": XP_POLICY_VERSION,
                "listeningXpPolicyVersion": LISTENING_XP_POLICY_VERSION,
                "levelPolicyVersion": LEVEL_POLICY_VERSION,
                "achievementPolicyVersion": ACHIEVEMENT_POLICY_VERSION,
                "collectionPolicyVersion": COLLECTION_POLICY_VERSION,
                "questPolicyVersion": QUEST_POLICY_VERSION,
                "campaignPolicyVersion": CAMPAIGN_POLICY_VERSION,
            },
            "curriculum": self.curriculum_service.health(),
            "offsetUnit": OFFSET_UNIT,
        })

    def curriculum(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.curriculum_service.landing(profile_id))

    def curriculum_pack(self, profile_id: str, pack_id: str, version: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.curriculum_service.detail(profile_id, pack_id, version))

    def curriculum_item(
        self, profile_id: str, pack_id: str, version: Any, membership_id: str
    ) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        membership_id = self._id(membership_id, "membershipId")
        return self._response(
            self.curriculum_service.item_detail(profile_id, pack_id, version, membership_id)
        )

    def gamification(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.gamification_service.progress(profile_id, as_of=as_of))

    def achievements(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.gamification_service.achievements(profile_id, as_of=as_of))

    def collections(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.gamification_service.collections(profile_id))

    def quests(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.gamification_service.quests(profile_id, as_of=as_of))

    def campaigns(self, profile_id: str) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response(self.gamification_service.campaigns(profile_id))

    def create_campaign(self, profile_id: str, payload: Any) -> dict[str, Any]:
        profile_id = self._id(profile_id, "profileId")
        return self._response({"campaign": self.gamification_service.create_campaign(profile_id, self._object(payload))})

    def update_campaign(self, campaign_id: str, payload: Any) -> dict[str, Any]:
        campaign_id = self._id(campaign_id, "campaignId")
        return self._response({"campaign": self.gamification_service.update_campaign(campaign_id, self._object(payload))})

    # Thin Phase 7 domain facade; provider communication remains manual.
    def create_generation_request(self, profile_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.create_request(profile_id, payload)

    def get_generation_request(self, request_id: str) -> dict[str, Any]:
        return self.generation_service.get_request(request_id)

    def get_generation_context(self, request_id: str) -> dict[str, Any]:
        return self.generation_service.get_context(request_id)

    def generation_provider_health(self) -> dict[str, Any]:
        return self.generation_service.provider_health()

    def start_automatic_generation(self, request_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.start_automatic(request_id, payload)

    def cancel_automatic_generation(self, request_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.cancel_automatic(request_id, payload)

    def import_generation_candidate(self, request_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.import_candidate(request_id, payload)

    def list_generation_candidates(self, request_id: str) -> dict[str, Any]:
        return self.generation_service.list_candidates(request_id)

    def get_generation_candidate(self, candidate_id: str) -> dict[str, Any]:
        return self.generation_service.get_candidate(candidate_id)

    def analyze_generation_candidate(self, candidate_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.enqueue_analysis(candidate_id, payload)

    def generation_revision_prompt(self, candidate_id: str) -> dict[str, Any]:
        return self.generation_service.revision_prompt(candidate_id)

    def reject_generation_candidate(self, candidate_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.reject(candidate_id, payload)

    def accept_generation_candidate(self, candidate_id: str, payload: Any) -> dict[str, Any]:
        return self.generation_service.accept(candidate_id, payload)

    def export_data(self) -> dict[str, Any]:
        export = self.store.export_data()
        if export["exportVersion"] != EXPORT_VERSION:
            raise LanguageConflictError("Language export version is invalid", code="invalid_language_export")
        return self._response(export)

    def backup_database(self) -> dict[str, Any]:
        return self._response({"backup": self.store.backup_database()})


__all__ = ["LanguageService", "SCHEMA_VERSION"]

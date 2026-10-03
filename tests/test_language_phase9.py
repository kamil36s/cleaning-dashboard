import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from language_learning import LanguageService, LanguageStore
from language_learning.cloze import (
    ANSWER_NORMALIZATION_VERSION,
    ClozeService,
    SHARED_DISTRACTOR_VERSION,
    normalize_typed_answer,
)
from language_learning.errors import LanguageConflictError
from language_learning.schemas import text_fingerprint
from tests.test_language_cloze import build_reference


class FakeCurriculumService:
    def __init__(self, units):
        self.units = units

    def landing(self, _profile_id):
        return {"packs": [{
            "id": "fixture-pack", "version": "7", "name": "Fixture pack",
            "fingerprint": "sha256:fixture-pack-v7",
            "progress": {"eligibleDenominator": len(self.units)},
        }]}

    def detail(self, _profile_id, pack_id, version=None):
        if pack_id != "fixture-pack" or str(version) != "7":
            raise AssertionError("Cloze must request the exact selected curriculum version")
        return {
            "id": pack_id, "version": "7", "name": "Fixture pack",
            "fingerprint": "sha256:fixture-pack-v7",
            "progress": {"items": [{
                "membershipId": f"membership-{index}", "displayTerm": unit.canonical_form,
                "normalizedLookup": unit.normalized_form, "reviewState": "APPROVED", "mappingState": "MAPPED",
                "referenceUnit": {
                    "id": unit.id, "stableKey": unit.stable_key, "canonicalForm": unit.canonical_form,
                    "normalizedForm": unit.normalized_form, "partOfSpeech": unit.part_of_speech,
                },
                "user": {},
            } for index, unit in enumerate(self.units)]},
        }


class Phase9SharedContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.reference, self.reference_targets, _ = build_reference(self.temp.name, 60)
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.cloze = ClozeService(self.service, self.reference.database_path)
        self.service.attach_cloze_service(self.cloze)

    def tearDown(self):
        self.temp.cleanup()

    def add_reader_context(
        self, lemma_display, sentence, start, end, *, source_type="PASTED",
        pos="NOUN", ambiguity="UNAMBIGUOUS", resolution="MODEL_SELECTED",
    ):
        lemma = self.service.upsert_lemma(self.profile["id"], lemma_display, part_of_speech=pos)["lemma"]
        surface = sentence[start:end]
        form = self.service.upsert_surface_form(self.profile["id"], surface)["form"]
        self.service.upsert_form_lemma_mapping(
            self.profile["id"], form["id"], lemma["id"], provider_id="fixture-analyzer",
            provider_version="1", morphology={"rawTag": f"{pos.lower()} exact"},
            ambiguity_state=ambiguity, lexical_status="KNOWN", provenance="ANALYZER",
        )
        document = self.service.create_text_draft({
            "languageProfileId": self.profile["id"], "title": f"Context for {lemma_display}",
            "rawText": sentence, "sourceType": source_type, "sourceReference": "fixture://phase9",
        })["data"]["text"]
        sentence_id = uuid.uuid4().hex
        token_id = uuid.uuid4().hex
        self.store.insert_text_structure(
            document["id"],
            sentences=[{
                "id": sentence_id, "sentence_order": 0, "source_start": 0, "source_end": len(sentence),
                "exact_text": sentence, "fingerprint": text_fingerprint(sentence),
            }],
            tokens=[{
                "id": token_id, "sentence_id": sentence_id, "token_order": 0, "surface": surface,
                "source_start": start, "source_end": end, "token_kind": "WORD",
                "normalized_lookup": surface.casefold(), "surface_form_id": form["id"],
                "selected_lemma_id": lemma["id"], "part_of_speech": pos,
                "morphology": {"rawTag": f"{pos.lower()} exact"}, "provider_id": "fixture-analyzer",
                "provider_version": "1", "ambiguity_state": ambiguity, "lexical_status": "KNOWN",
            }],
            analysis_run={
                "id": uuid.uuid4().hex, "analyzer_id": "fixture-analyzer", "analyzer_version": "1",
                "contract_version": "language.analysis/v1", "state": "COMPLETED",
            },
        )
        with self.store.connection() as connection:
            connection.execute("UPDATE text_documents SET processing_state='ANALYZED' WHERE id=?", (document["id"],))
            connection.execute("UPDATE text_tokens SET resolution_state=? WHERE id=?", (resolution, token_id))
        return lemma, document, sentence_id, token_id

    def add_generation_candidate(self, *, status, document_id=None):
        request_id, candidate_id = uuid.uuid4().hex, uuid.uuid4().hex
        now = "2026-09-17T12:00:00Z"
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO generation_requests(id,language_profile_id,requested_length,requested_token_coverage,"
                "difficulty_preset,selection_rule_version,coverage_policy_version,knowledge_snapshot_fingerprint,"
                "knowledge_snapshot_json,target_snapshot_json,prompt_version,prompt_fingerprint,context_pack_json,"
                "status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (request_id, self.profile["id"], 50, 90, "BALANCED", "targets/v1", "coverage/v1",
                 "sha256:knowledge", "[]", '{"items":[]}', "prompt/v1", "sha256:prompt", "{}",
                 "ACCEPTED" if status == "ACCEPTED" else "HAS_CANDIDATES", now, now),
            )
            connection.execute(
                "INSERT INTO generation_candidates(id,generation_request_id,attempt_number,source,raw_response,"
                "import_format,title,extracted_text,validation_status,status,accepted_text_document_id,created_at,"
                "updated_at,accepted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (candidate_id, request_id, 1, "MANUAL_EXTERNAL_LLM", "fixture", "PLAIN_TEXT", status.title(),
                 "fixture", "VALID" if status == "ACCEPTED" else "INVALID", status,
                 document_id if status == "ACCEPTED" else None, now, now, now if status == "ACCEPTED" else None),
            )

    def start_review(self, question_type="TYPED", seed="phase9-review"):
        return self.service.start_cloze_session(self.profile["id"], {
            "mode": "REVIEW", "itemCount": 10, "questionType": question_type, "seed": seed,
        })["data"]

    def internal_item(self, session_id, index=0):
        items = json.loads(self.store.get_cloze_session(session_id)["session"]["items_json"])
        return items[index]

    def submit(self, session, answer, key):
        item = session["currentItem"]
        return self.service.submit_cloze_attempt(session["id"], {
            "itemIndex": item["index"], "itemFingerprint": item["fingerprint"], "action": "ANSWER",
            "answer": answer, "responseMs": 100, "idempotencyKey": key,
        })["data"]

    def test_exact_typed_normalization_preserves_norwegian_letters_and_rejects_inflections(self):
        self.assertEqual(normalize_typed_answer("  ÆRLIG ØL PÅ  "), "ærlig øl på")
        self.assertNotEqual(normalize_typed_answer("på"), normalize_typed_answer("pa"))
        self.assertEqual(normalize_typed_answer("A\u030A"), normalize_typed_answer("Å"))
        self.assertNotEqual(normalize_typed_answer("øl."), normalize_typed_answer("øl"))
        sentence = "Jeg drikker øl, men dette øl er kaldt."
        start = sentence.rindex("øl")
        lemma, document, sentence_id, _ = self.add_reader_context("øl", sentence, start, start + 2)
        first = self.start_review()["session"]
        frozen = self.internal_item(first["id"])
        self.assertEqual(frozen["sentenceText"][frozen["blankStart"]:frozen["blankEnd"]], "øl")
        self.assertEqual(frozen["acceptedAnswers"], ["øl"])
        self.assertEqual(frozen["ruleVersions"]["answerNormalization"], ANSWER_NORMALIZATION_VERSION)
        with self.store.connection() as connection:
            connection.execute("UPDATE text_sentences SET exact_text='changed after session' WHERE id=?", (sentence_id,))
        self.assertEqual(self.service.get_cloze_session(first["id"])["data"]["session"]["currentItem"]["sentenceText"], sentence)
        correct = self.submit(first, "  ØL  ", "typed-correct")
        duplicate = self.submit(first, "  ØL  ", "typed-correct")
        self.assertEqual(correct["feedback"]["outcome"], "CORRECT")
        self.assertFalse(duplicate["created"])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cloze_attempts WHERE idempotency_key='typed-correct'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_events WHERE source='CLOZE' AND idempotency_key='typed-correct'").fetchone()[0], 1)
            attempt_id = connection.execute("SELECT id FROM cloze_attempts WHERE idempotency_key='typed-correct'").fetchone()[0]
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM gamification_awards WHERE source_type='CLOZE_ATTEMPT' AND source_id=?", (attempt_id,)).fetchone()[0], 1)
            connection.execute("UPDATE text_sentences SET exact_text=? WHERE id=?", (sentence, sentence_id))
        second = self.start_review(seed="wrong-inflection")["session"]
        wrong = self.submit(second, "ølene", "typed-wrong")
        self.assertEqual(wrong["feedback"]["outcome"], "INCORRECT")
        knowledge = self.service.get_lemma(lemma["id"])["data"]["knowledge"]
        self.assertNotEqual(knowledge["knowledgeStatus"], "MASTERED")
        self.assertEqual(document["sourceType"], "PASTED")

    def test_recycle_mode_consumes_shared_mistake_remediation_targets(self):
        sentence = "Jeg kjenner dette ordet."
        start = sentence.index("kjenner")
        lemma, _, _, _ = self.add_reader_context("kjenne", sentence, start, start + len("kjenner"), pos="VERB")
        first = self.start_review(seed="remediation-one")["session"]
        self.submit(first, "vite", "remediation-wrong-one")
        second = self.start_review(seed="remediation-two")["session"]
        self.submit(second, "vite", "remediation-wrong-two")
        remediation = self.service.remediation(self.profile["id"])["data"]
        self.assertEqual(remediation["items"][0]["targetLemmaId"], lemma["id"])
        recycled = self.service.start_cloze_session(self.profile["id"], {
            "mode": "RECYCLE_MISTAKES", "itemCount": 10, "seed": "shared-remediation",
        })["data"]["session"]
        self.assertEqual(recycled["practiceMode"], "REMEDIATION")
        self.assertEqual(recycled["trackKey"], "SHARED_REMEDIATION")
        self.assertEqual(recycled["currentItem"]["targetLemmaId"], lemma["id"])

    def test_reader_ambiguity_unresolved_and_unsafe_markup_fail_closed(self):
        safe = {
            "sentence_text": "Et hus står her.", "surface": "hus", "token_start": 3, "token_end": 6,
            "sentence_start": 0, "ambiguity_state": "UNAMBIGUOUS", "resolution_state": "MODEL_SELECTED",
            "selected_lemma_id": "lemma", "document_source_type": "PASTED", "text_document_id": "doc",
            "sentence_id": "sentence", "token_id": "token", "morphology_json": "{}",
        }
        self.assertEqual(self.cloze._reader_context(safe)["expectedSurfaceForm"], "hus")
        self.assertIsNone(self.cloze._reader_context({**safe, "ambiguity_state": "AMBIGUOUS"}))
        self.assertIsNone(self.cloze._reader_context({**safe, "resolution_state": "UNRESOLVED"}))
        self.assertIsNone(self.cloze._reader_context({**safe, "sentence_text": "<script>hus</script>", "token_start": 8, "token_end": 11}))
        self.assertIsNone(self.cloze._reader_context({**safe, "token_start": 0, "token_end": 3}))

    def test_phrasebook_link_is_eligible_and_cloze_does_not_create_mastery(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "hus", part_of_speech="NOUN")["lemma"]
        self.service.create_phrasebook_entry(self.profile["id"], {
            "expression": "hus", "sourceType": "MANUAL", "sourceEntityId": "fixture-house",
            "sourceContext": "Et hus står her.", "sourceProvenance": {"fixture": True},
            "links": [{"type": "LEMMA", "value": lemma["id"], "metadata": {}}],
        })
        session = self.start_review()["session"]
        item = self.internal_item(session["id"])
        self.assertEqual(item["sourceContextType"], "PHRASEBOOK")
        self.assertEqual(item["sentenceText"][item["blankStart"]:item["blankEnd"]], "hus")
        result = self.submit(session, "HUS", "phrasebook-answer")
        self.assertEqual(result["feedback"]["outcome"], "CORRECT")
        self.assertNotEqual(self.service.get_lemma(lemma["id"])["data"]["knowledge"]["knowledgeStatus"], "MASTERED")
        report = self.service.report_cloze_item(session["id"], {
            "itemIndex": 0, "reason": "WRONG_ANSWER",
        })["data"]
        self.assertEqual(report["suppression"]["sourceContextType"], "PHRASEBOOK")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM phrasebook_entries").fetchone()[0], 1)

    def test_only_accepted_analyzed_generated_documents_are_eligible(self):
        sentence = "Dette er et nytt hus."
        start = sentence.index("hus")
        _, document, _, _ = self.add_reader_context("hus", sentence, start, start + 3, source_type="GENERATED_GEMINI")
        tracks = self.service.cloze_tracks(self.profile["id"])["data"]
        self.assertFalse(tracks["practiceModes"]["review"]["available"])
        self.add_generation_candidate(status="FAILED")
        tracks = self.service.cloze_tracks(self.profile["id"])["data"]
        self.assertFalse(tracks["practiceModes"]["review"]["available"])
        self.add_generation_candidate(status="ACCEPTED", document_id=document["id"])
        tracks = self.service.cloze_tracks(self.profile["id"])["data"]
        self.assertTrue(tracks["practiceModes"]["review"]["available"])
        session = self.start_review()["session"]
        item = self.internal_item(session["id"])
        self.assertEqual(item["sourceContextType"], "GENERATED")
        self.assertIsNotNone(item["source"]["provenance"]["generationCandidateId"])

    def test_same_pos_distractors_are_unique_and_mc_falls_back_to_typed(self):
        filtered = self.cloze._shared_distractors(
            {"id": "target", "part_of_speech": "NOUN", "stable_key": "target-key"},
            {"expectedSurfaceForm": "hus", "partOfSpeech": "NOUN", "morphology": {"rawTag": "noun exact"}},
            [
                {"targetLemmaId": "target", "expectedSurfaceForm": "huset", "partOfSpeech": "NOUN", "morphology": {"rawTag": "noun exact"}},
                {"targetLemmaId": "one", "expectedSurfaceForm": "bord", "partOfSpeech": "NOUN", "morphology": {"rawTag": "noun exact"}},
                {"targetLemmaId": "two", "expectedSurfaceForm": "BORD", "partOfSpeech": "NOUN", "morphology": {"rawTag": "noun exact"}},
                {"targetLemmaId": "three", "expectedSurfaceForm": "stol", "partOfSpeech": "NOUN", "morphology": {"rawTag": "noun other"}},
                {"targetLemmaId": "four", "expectedSurfaceForm": "bok", "partOfSpeech": "NOUN", "morphology": {"rawTag": "noun exact"}},
                {"targetLemmaId": "five", "expectedSurfaceForm": "løper", "partOfSpeech": "VERB", "morphology": {"rawTag": "verb exact"}},
            ],
            "filter-seed",
        )
        self.assertNotIn("huset", filtered)
        self.assertNotIn("løper", filtered)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(len({normalize_typed_answer(value) for value in filtered}), 3)
        for word in ("hus", "bord", "stol", "bok"):
            sentence = f"Dette er et {word}."
            start = sentence.index(word)
            self.add_reader_context(word, sentence, start, start + len(word), pos="NOUN")
        mc = self.start_review("MULTIPLE_CHOICE", seed="enough-distractors")["session"]
        item = self.internal_item(mc["id"])
        self.assertEqual(item["questionType"], "MULTIPLE_CHOICE")
        self.assertEqual(len(item["options"]), 4)
        self.assertEqual(len({normalize_typed_answer(value) for value in item["options"]}), 4)
        self.assertEqual(item["ruleVersions"]["distractors"], SHARED_DISTRACTOR_VERSION)

        isolated = tempfile.TemporaryDirectory()
        try:
            reference, _, _ = build_reference(isolated.name, 10)
            store = LanguageStore(Path(isolated.name) / "language.sqlite")
            service = LanguageService(store); service.initialize(); profile = service.ensure_bokmal_profile()["profile"]
            cloze = ClozeService(service, reference.database_path); service.attach_cloze_service(cloze)
            lemma = service.upsert_lemma(profile["id"], "hus", part_of_speech="NOUN")["lemma"]
            service.create_phrasebook_entry(profile["id"], {
                "expression": "hus", "sourceType": "MANUAL", "sourceContext": "Et hus.",
                "links": [{"type": "LEMMA", "value": lemma["id"], "metadata": {}}],
            })
            result = service.start_cloze_session(profile["id"], {
                "mode": "REVIEW", "itemCount": 10, "questionType": "MULTIPLE_CHOICE", "seed": "fallback",
            })["data"]
            fallback = json.loads(store.get_cloze_session(result["session"]["id"])["session"]["items_json"])[0]
            self.assertEqual(fallback["questionType"], "TYPED")
            self.assertEqual(fallback["options"], [])
        finally:
            isolated.cleanup()

    def test_curriculum_pack_version_is_frozen_and_only_selected_items_create_lemmas(self):
        self.service.curriculum_service = FakeCurriculumService(self.reference_targets[:12])
        with self.store.connection() as connection:
            before = connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas WHERE language_profile_id=?", (self.profile["id"],)).fetchone()[0]
        result = self.service.start_cloze_session(self.profile["id"], {
            "mode": "CURRICULUM", "curriculumPackId": "fixture-pack", "curriculumVersion": "7",
            "itemCount": 10, "questionType": "TYPED", "seed": "curriculum-v7",
        })["data"]
        session = result["session"]
        self.assertEqual(session["mode"], "CURRICULUM")
        self.assertEqual(session["curriculumSnapshot"], {
            "packId": "fixture-pack", "version": "7", "fingerprint": "sha256:fixture-pack-v7", "name": "Fixture pack",
        })
        items = json.loads(self.store.get_cloze_session(session["id"])["session"]["items_json"])
        self.assertTrue(all(item["curriculum"]["version"] == "7" for item in items))
        with self.store.connection() as connection:
            after = connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas WHERE language_profile_id=?", (self.profile["id"],)).fetchone()[0]
        self.assertEqual(after - before, 10)
        self.assertEqual(session["actualItemCount"], 10)

    def test_reference_only_curriculum_target_without_safe_context_fails_honestly(self):
        missing = SimpleNamespace(
            id="missing-reference-unit", stable_key="missing-reference-key", canonical_form="mangler",
            normalized_form="mangler", part_of_speech="VERB",
        )
        self.service.curriculum_service = FakeCurriculumService([missing])
        with self.assertRaisesRegex(LanguageConflictError, "No safe shared-context"):
            self.service.start_cloze_session(self.profile["id"], {
                "mode": "CURRICULUM", "curriculumPackId": "fixture-pack", "curriculumVersion": "7",
                "itemCount": 10, "questionType": "TYPED", "seed": "missing-context",
            })
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

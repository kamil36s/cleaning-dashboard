import json
from pathlib import Path
import tempfile
import unittest
import uuid

from language_learning import LanguageService, LanguageStore
from language_learning.mistakes import (
    CLUSTER_POLICY_VERSION,
    OBSERVATION_POLICY_VERSION,
    REMEDIATION_POLICY_VERSION,
    SEVERITY_POLICY_VERSION,
)


class MistakeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]

    def tearDown(self):
        self.temp.cleanup()

    def lemma(self, display, *, morphology=None, form=None):
        lemma = self.service.upsert_lemma(
            self.profile["id"], display, part_of_speech="VERB"
        )["lemma"]
        surface = self.service.upsert_surface_form(self.profile["id"], form or display)["form"]
        self.service.upsert_form_lemma_mapping(
            self.profile["id"], surface["id"], lemma["id"],
            provider_id="fixture-analyzer", provider_version="1",
            morphology=morphology or {"rawTag": "verb base"},
            ambiguity_state="UNAMBIGUOUS", lexical_status="KNOWN", provenance="ANALYZER",
        )
        return lemma

    def attempt(
        self, lemma, outcome, attempted_at, *, expected=None, answer=None,
        sentence_id=None, morphology=None, question_type="TYPED",
    ):
        expected = expected or lemma["lemmaDisplay"]
        sentence_id = sentence_id or uuid.uuid4().hex
        snapshot = {
            "fingerprint": f"sha256:{uuid.uuid4().hex}",
            "targetLemmaId": lemma["id"], "targetLemmaDisplay": lemma["lemmaDisplay"],
            "expectedSurfaceForm": expected, "morphology": morphology or {"rawTag": "verb expected"},
            "sourceContextType": "READER", "questionType": question_type,
            "source": {
                "sourceId": "READER", "sourceEntityId": "fixture-document",
                "sentenceId": sentence_id, "provenance": {"sentenceFingerprint": f"fp:{sentence_id}"},
            },
        }
        session = self.store.create_cloze_session({
            "language_profile_id": self.profile["id"], "mode": "RECYCLE_MISTAKES",
            "practice_mode": "REVIEW", "track_key": "FIXTURE", "track_version": "fixture/v1",
            "requested_item_count": 10, "seed": uuid.uuid4().hex, "items": [snapshot],
            "question_type": question_type,
        })
        normalized = answer.casefold() if answer else None
        row, _, _ = self.store.record_cloze_attempt({
            "session_id": session["id"], "item_index": 0, "target_lemma_id": lemma["id"],
            "reference_target_stable_key": f"user-lemma:{lemma['id']}",
            "reference_sentence_source": "READER", "reference_sentence_id": sentence_id,
            "item_snapshot": snapshot, "item_fingerprint": snapshot["fingerprint"],
            "expected_surface_form": expected, "options": [expected, answer] if answer else [],
            "chosen_option": answer if question_type == "MULTIPLE_CHOICE" else None,
            "outcome": outcome, "response_ms": 100, "idempotency_key": uuid.uuid4().hex,
            "attempted_at": attempted_at, "rule_versions": {"item": "fixture/v1"},
            "question_type": question_type, "source_context_type": "READER",
            "normalization_version": "language.cloze-answer-normalization/v1",
            "user_answer": answer, "normalized_answer": normalized,
        })
        return row

    def summary(self):
        return self.service.mistakes(
            self.profile["id"], as_of="2026-09-18T12:00:00Z"
        )["data"]

    def invariant_counts(self):
        tables = (
            "vocabulary_lemmas", "lemma_knowledge", "knowledge_events", "cloze_attempts",
            "goal_definitions", "topics", "anki_card_snapshots", "gamification_awards",
        )
        with self.store.connection() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    def test_one_off_is_noise_but_repeated_failures_and_reveals_cluster(self):
        target = self.lemma("kjenne")
        self.attempt(target, "INCORRECT", "2026-09-16T10:00:00Z", answer="nonsense")
        one = self.summary()
        self.assertEqual(one["activeClusterCount"], 0)
        self.assertEqual(one["historicalIncorrectCount"], 1)
        self.attempt(target, "REVEALED", "2026-09-17T10:00:00Z")
        repeated = self.summary()
        target_cluster = next(item for item in repeated["topProblems"] if item["category"] == "TARGET_LEMMA_DIFFICULTY")
        self.assertEqual((target_cluster["incorrectCount"], target_cluster["revealCount"]), (1, 1))
        self.assertEqual(repeated["policies"]["observation"], OBSERVATION_POLICY_VERSION)
        self.assertEqual(repeated["policies"]["clustering"], CLUSTER_POLICY_VERSION)
        self.assertEqual(repeated["policies"]["severity"], SEVERITY_POLICY_VERSION)

    def test_direct_confusion_is_repeated_directional_and_distractor_cooccurrence_is_not_evidence(self):
        expected = self.lemma("kjenne")
        supplied = self.lemma("vite")
        self.attempt(expected, "INCORRECT", "2026-09-15T10:00:00Z", answer="vite", question_type="MULTIPLE_CHOICE")
        first = self.summary()
        self.assertFalse(any(item["category"] == "DIRECTIONAL_CONFUSION" for item in first["topProblems"]))
        self.attempt(expected, "INCORRECT", "2026-09-16T10:00:00Z", answer="vite", question_type="MULTIPLE_CHOICE")
        second = self.summary()
        confusion = next(item for item in second["topProblems"] if item["category"] == "DIRECTIONAL_CONFUSION")
        self.assertEqual(confusion["confusion"]["expectedLemmaId"], expected["id"])
        self.assertEqual(confusion["confusion"]["suppliedLemmaId"], supplied["id"])
        self.assertEqual(confusion["confusion"]["direction"], "EXPECTED_TO_SUPPLIED")
        self.assertEqual(confusion["confusion"]["relationshipClaim"], "LEARNER_RESPONSE_ONLY")
        self.assertFalse(any(
            item["category"] == "DIRECTIONAL_CONFUSION" and item["target"]["lemmaId"] == supplied["id"]
            for item in second["topProblems"]
        ))

    def test_unresolved_typo_and_analyzer_backed_inflection_remain_distinct(self):
        target = self.lemma("jobbe", morphology={"rawTag": "verb infinitive"}, form="jobbe")
        self.lemma("jobbe", morphology={"rawTag": "verb present"}, form="jobber")
        for day in (15, 16):
            self.attempt(
                target, "INCORRECT", f"2026-09-{day}T10:00:00Z",
                expected="jobber", answer="jobbe", morphology={"rawTag": "verb present"},
            )
        result = self.summary()
        self.assertTrue(any(item["category"] == "INFLECTION_CONFUSION" for item in result["topProblems"]))
        typo = self.lemma("skrive")
        for day in (15, 16):
            self.attempt(typo, "INCORRECT", f"2026-09-{day}T11:00:00Z", answer="xqzz")
        result = self.summary()
        unresolved = next(item for item in result["topProblems"] if item["category"] == "UNRESOLVED_FORM_DIFFICULTY")
        self.assertEqual(unresolved["lemmaRelationship"], "NONE")
        self.assertFalse(any(
            item["category"] == "DIRECTIONAL_CONFUSION" and item["target"]["lemmaId"] == typo["id"]
            for item in result["topProblems"]
        ))

    def test_context_difficulty_and_recovery_preserve_history_without_mutation(self):
        target = self.lemma("arbeide")
        hard_context = uuid.uuid4().hex
        for day in (10, 11):
            self.attempt(target, "INCORRECT", f"2026-09-{day}T10:00:00Z", answer="x", sentence_id=hard_context)
        self.attempt(target, "CORRECT", "2026-09-12T10:00:00Z", answer="arbeide", sentence_id=uuid.uuid4().hex)
        self.attempt(target, "CORRECT", "2026-09-13T10:00:00Z", answer="arbeide", sentence_id=uuid.uuid4().hex)
        before = self.invariant_counts()
        result = self.summary()
        after = self.invariant_counts()
        self.assertEqual(before, after)
        context = next(item for item in result["recentRecoveries"] if item["category"] == "CONTEXT_DIFFICULTY")
        self.assertEqual(context["context"]["otherContextSuccesses"], 2)
        self.assertEqual(context["state"], "RECOVERED")
        self.assertEqual(context["historicalFailureCount"], 2)
        knowledge = self.service.get_lemma(target["id"])["data"]["knowledge"]
        self.assertEqual(knowledge["knowledgeStatus"], "NEW")

    def test_shared_remediation_enters_learning_plan_once_and_anki_history_is_unavailable(self):
        target = self.lemma("lese")
        self.attempt(target, "INCORRECT", "2026-09-16T10:00:00Z", answer="x")
        self.attempt(target, "INCORRECT", "2026-09-17T10:00:00Z", answer="x")
        remediation = self.service.remediation(
            self.profile["id"], as_of="2026-09-18T12:00:00Z"
        )["data"]
        self.assertEqual(remediation["policyVersion"], REMEDIATION_POLICY_VERSION)
        self.assertEqual(len(remediation["items"]), 1)
        plan = self.service.learning_plan(
            self.profile["id"], as_of="2026-09-18T12:00:00Z"
        )["data"]
        self.assertEqual(sum(1 for item in plan["items"] if item["kind"] == "CLOZE_MISTAKES"), 1)
        self.assertEqual(plan["cloze"]["remediation"], remediation["items"])
        summary = self.summary()
        self.assertEqual(summary["sourceAvailability"]["ankiReviewHistory"], "NOT_SUPPORTED")
        detail = self.service.mistake_detail(
            self.profile["id"], summary["topProblems"][0]["id"], as_of="2026-09-18T12:00:00Z"
        )["data"]
        self.assertEqual(len(detail["cluster"]["evidence"]), detail["cluster"]["evidenceCount"])


if __name__ == "__main__":
    unittest.main()

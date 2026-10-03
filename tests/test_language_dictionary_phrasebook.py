import sqlite3
import tempfile
import unittest
from pathlib import Path

from language_learning.providers.dictionary import (
    DictionaryProviderError,
    OrdbokeneDictionaryProvider,
)
from language_learning.service import LanguageService
from language_learning.store import LanguageStore


ARTICLE = {
    "article_id": 9296,
    "updated": "2026-09-17 08:00:00",
    "lemmas": [{
        "lemma": "data",
        "paradigm_info": [{
            "tags": ["NOUN", "Neuter"],
            "inflection": [
                {"word_form": "data", "tags": ["Sing", "Ind"]},
                {"word_form": "dataene", "tags": ["Plur", "Def"]},
            ],
        }],
    }],
    "body": {
        "pronunciation": [],
        "definitions": [{
            "type_": "definition", "id": 3, "elements": [{
                "type_": "definition", "id": 4, "elements": [
                    {"type_": "explanation", "content": "opplysninger om verden", "items": []},
                    {"type_": "usage", "text": "faglig"},
                    {"type_": "example", "quote": {"content": "samle inn data", "items": []}},
                    {"type_": "explanation", "content": "kortord for $", "items": [{
                        "type_": "article_ref", "article_id": 9330,
                        "lemmas": [{"lemma": "datateknologi"}],
                    }]},
                ],
            }, {
                "type_": "definition", "id": 5, "elements": [
                    {"type_": "explanation", "content": "digitalt innhold", "items": []},
                ],
            }],
        }],
    },
}


class FakeDictionary:
    def __init__(self, *, fail=False):
        self.fail = fail

    def health(self):
        return {"id": "FIXTURE", "version": "1", "configured": True}

    def lookup_lemma(self, lemma, part_of_speech=None):
        if self.fail:
            raise DictionaryProviderError("fixture offline")
        return {
            "available": True, "lookupStatus": "MATCHED", "articles": [],
            "provider": self.health(), "requestedLemma": lemma,
            "requestedPartOfSpeech": part_of_speech,
        }


class DictionaryProviderTests(unittest.TestCase):
    def test_parses_source_senses_without_inventing_translation_or_pronunciation(self):
        def fetch(url):
            if "/api/articles?" in url:
                return {"articles": {"bm": [9296]}}
            return ARTICLE

        result = OrdbokeneDictionaryProvider(fetch_json=fetch).lookup_lemma("data", "NOUN")
        self.assertEqual(result["lookupStatus"], "MATCHED")
        self.assertEqual(len(result["articles"]), 1)
        article = result["articles"][0]
        self.assertEqual([item["senseId"] for item in article["senses"]], ["9296:4", "9296:5"])
        self.assertEqual(article["senses"][0]["definition"], "opplysninger om verden")
        self.assertEqual(article["senses"][0]["usageLabels"], ["faglig"])
        self.assertEqual(article["senses"][0]["examples"], ["samle inn data"])
        self.assertEqual(article["senses"][0]["relations"][0]["term"], "datateknologi")
        self.assertEqual(article["pronunciations"], [])
        self.assertEqual(article["senses"][0]["translations"], [])
        self.assertEqual(len(result["contentFingerprint"]), 64)

    def test_same_spelling_wrong_pos_is_explicit_mismatch(self):
        def fetch(url):
            return {"articles": {"bm": [9296]}} if "/api/articles?" in url else ARTICLE

        result = OrdbokeneDictionaryProvider(fetch_json=fetch).lookup_lemma("data", "VERB")
        self.assertEqual(result["lookupStatus"], "POS_MISMATCH")
        self.assertEqual(result["articles"], [])


class PhrasebookServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store, dictionary_provider=FakeDictionary())
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.lemma = self.service.upsert_lemma(self.profile["id"], "data", part_of_speech="NOUN")["lemma"]

    def tearDown(self):
        self.temp.cleanup()

    def counts(self):
        with self.store.connection() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "lemma_knowledge", "knowledge_events", "exposure_events",
                    "anki_note_links", "gamification_awards",
                )
            }

    def test_phrasebook_retry_is_idempotent_but_different_context_is_distinct_and_zero_credit(self):
        before = self.counts()
        payload = {
            "expression": "samle inn data",
            "sourceType": "READER",
            "sourceEntityId": "a" * 32,
            "sourceContext": "Vi må samle inn data først.",
            "sourceProvenance": {"sentenceId": "b" * 32},
            "links": [{"type": "LEMMA", "value": self.lemma["id"], "metadata": {}}],
        }
        first = self.service.create_phrasebook_entry(self.profile["id"], payload)["data"]
        retry = self.service.create_phrasebook_entry(self.profile["id"], payload)["data"]
        other = self.service.create_phrasebook_entry(self.profile["id"], {
            **payload, "sourceContext": "De skal samle inn data i morgen.",
        })["data"]
        self.assertTrue(first["created"])
        self.assertTrue(retry["reused"])
        self.assertEqual(first["entry"]["id"], retry["entry"]["id"])
        self.assertNotEqual(first["entry"]["id"], other["entry"]["id"])
        self.assertEqual(before, self.counts())

    def test_user_edits_cannot_overwrite_source_snapshot(self):
        created = self.service.create_phrasebook_entry(self.profile["id"], {
            "expression": "på jobb", "sourceType": "CLOZE", "sourceEntityId": "TATOEBA:1",
            "sourceContext": "Han er på jobb.", "sourceProvenance": {"license": "CC-BY-2.0-FR"},
        })["data"]["entry"]
        updated = self.service.update_phrasebook_entry(created["id"], {
            "note": "Useful", "userTranslation": "w pracy",
        })["data"]["entry"]
        self.assertEqual(updated["expressionText"], "på jobb")
        self.assertEqual(updated["sourceContext"], "Han er på jobb.")
        self.assertEqual(updated["sourceProvenance"], {"license": "CC-BY-2.0-FR"})
        self.assertEqual(updated["userTranslation"], "w pracy")

    def test_user_translation_coexists_with_provider_result_and_survives_refresh(self):
        self.service.upsert_lemma_translation(self.lemma["id"], {
            "targetLocale": "pl-PL", "translation": "dane",
        })
        first = self.service.get_lemma_lexical_detail(self.lemma["id"])["data"]
        second = self.service.get_lemma_lexical_detail(self.lemma["id"])["data"]
        self.assertEqual(first["translations"]["user"][0]["translationText"], "dane")
        self.assertEqual(second["translations"]["user"], first["translations"]["user"])
        self.assertEqual(first["dictionary"]["lookupStatus"], "MATCHED")

    def test_provider_outage_degrades_lexical_section_only(self):
        service = LanguageService(self.store, dictionary_provider=FakeDictionary(fail=True))
        result = service.get_lemma_lexical_detail(self.lemma["id"])["data"]
        self.assertFalse(result["dictionary"]["available"])
        self.assertEqual(result["dictionary"]["lookupStatus"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(service.get_lemma(self.lemma["id"])["data"]["lemma"]["lemmaDisplay"], "data")

    def test_export_contains_user_owned_phase_7_7_tables(self):
        self.service.upsert_lemma_translation(self.lemma["id"], {"targetLocale": "en", "translation": "data"})
        self.service.create_phrasebook_entry(self.profile["id"], {
            "expression": "mine data", "sourceType": "MANUAL",
        })
        exported = self.store.export_data()
        self.assertEqual(exported["exportVersion"], "language-learning-export/v16")
        self.assertEqual(len(exported["data"]["userLemmaTranslations"]), 1)
        self.assertEqual(len(exported["data"]["phrasebookEntries"]), 1)


if __name__ == "__main__":
    unittest.main()

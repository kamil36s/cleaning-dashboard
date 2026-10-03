import http.client
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import server
from language_learning import LanguageJobManager, LanguageService, LanguageStore
from language_learning.analysis.base import AnalyzerUnavailableError
from language_learning.anki_sync import AnkiSyncService
from language_learning.migrations import SCHEMA_VERSION
from language_learning.store import EXPORT_VERSION
from language_learning.reference_core import ReferenceStore
from language_learning.reference_core.fixture_importer import import_fixture
from language_learning.reference_core.service import ReferenceLexiconService
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for
from tests.test_language_anki import FakeAnki


class LanguageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(
            Path(self.temp.name) / "language.sqlite",
            backup_directory=Path(self.temp.name) / "backups",
        )
        self.analyzer = FakeAnalyzer()
        self.fake_anki = FakeAnki()
        anki_sync = AnkiSyncService(self.store, adapter_factory=lambda *args, **kwargs: self.fake_anki)
        self.service = LanguageService(
            self.store,
            analyzer_registry=registry_for(self.analyzer),
            frequency_provider=FakeFrequencyProvider(),
            anki_sync_service=anki_sync,
        )
        self.jobs = LanguageJobManager(self.service, poll_interval=0.01)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.lemma = self.service.upsert_lemma(
            self.profile["id"], "jobb", part_of_speech="NOUN"
        )["lemma"]
        self.form = self.service.upsert_surface_form(self.profile["id"], "jobbene")["form"]
        self.service.upsert_form_lemma_mapping(
            self.profile["id"], self.form["id"], self.lemma["id"]
        )
        self.previous_store = server.LANGUAGE_STORE
        self.previous_service = server.LANGUAGE_SERVICE
        self.previous_jobs = server.LANGUAGE_JOBS
        server.LANGUAGE_STORE = self.store
        server.LANGUAGE_SERVICE = self.service
        server.LANGUAGE_JOBS = self.jobs
        self.httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.jobs.stop()
        server.LANGUAGE_STORE = self.previous_store
        server.LANGUAGE_SERVICE = self.previous_service
        server.LANGUAGE_JOBS = self.previous_jobs
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, raw=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = raw if raw is not None else (json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw_response = response.read().decode("utf-8")
        connection.close()
        return response.status, json.loads(raw_response)

    def wait_for_api_job(self, job_id, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, body = self.request("GET", f"/api/language/jobs/{job_id}")
            self.assertEqual(status, 200)
            if body["data"]["job"]["state"] not in {"QUEUED", "RUNNING"}:
                return body["data"]["job"]
            time.sleep(0.01)
        self.fail(f"job {job_id} did not finish")

    def test_reading_series_routes_feed_continuation_prompt(self):
        profile_id = self.profile["id"]
        root = f"/api/language/profiles/{profile_id}/reading-series"
        status, created = self.request("POST", root, {"title": "Harbor", "premise": "A mystery", "continuityNotes": "Maja knows Erik"})
        self.assertEqual(status, 201)
        series_id = created["data"]["series"]["id"]
        text = self.service.create_text_draft({"languageProfileId": profile_id, "title": "First", "rawText": "Maja så båten."})["data"]["text"]
        status, assignment = self.request("PATCH", f"/api/language/texts/{text['id']}/series", {"seriesId": series_id})
        self.assertEqual(status, 200)
        self.assertEqual(assignment["data"]["assignment"]["episodeNumber"], 1)
        status, listed = self.request("GET", root)
        self.assertEqual(status, 200)
        self.assertEqual(listed["data"]["items"][0]["episodes"][0]["textDocumentId"], text["id"])
        self.assertEqual(self.request("PATCH", f"/api/language/reading-series/{series_id}", {"continuityNotes": "Maja and Erik work together"})[0], 200)
        status, generated = self.request("POST", f"/api/language/profiles/{profile_id}/generation-requests", {
            "length": 200, "difficultyPreset": "BALANCED", "storyMode": "CONTINUE",
            "seriesId": series_id, "previousTextId": text["id"],
        })
        self.assertEqual(status, 201)
        self.assertIn("Maja and Erik work together", generated["data"]["contextPack"]["files"]["prompt.md"])

    def test_grammar_routes_jobs_reviews_ownership_and_authorization(self):
        from tests.test_language_grammar import FixtureParser
        self.service.grammar.parser = FixtureParser()
        text = self.service.create_text_draft({'languageProfileId':self.profile['id'],'title':'Grammar HTTP','rawText':'Jeg jobber i Oslo.'})['data']['text']
        job=self.service.enqueue_analysis(text['id'],{})['data']['job']
        self.wait_for_api_job(job['id'])
        root=f"/api/language/profiles/{self.profile['id']}/grammar"
        self.assertEqual(self.request('GET',root)[0],200)
        url=f"/api/language/texts/{text['id']}/grammar-analysis"
        self.assertEqual(self.request('POST',url,{'languageProfileId':self.profile['id']},headers={'Origin':'https://evil.example'})[0],403)
        status,body=self.request('POST',url,{'languageProfileId':self.profile['id']})
        self.assertIn(status,[200,202]); self.assertEqual(self.wait_for_api_job(body['data']['job']['id'])['state'],'COMPLETED')
        status,body=self.request('GET',root+'/patterns/A1_PRESENT_TENSE')
        self.assertEqual(status,200); occurrence=body['data']['examples'][0]['id']
        self.assertEqual(body['data']['pattern']['state'],'DISCOVERED')
        status,body=self.request('PATCH',f'/api/language/grammar/occurrences/{occurrence}/review',{'languageProfileId':self.profile['id'],'decision':'REJECTED'})
        self.assertEqual(status,200)
        self.assertEqual(self.request('GET',root+'/patterns/A1_PRESENT_TENSE')[1]['data']['examples'][0]['reviewState'],'REJECTED')
        self.assertEqual(self.request('GET',f"/api/language/texts/{text['id']}/grammar?profileId={self.profile['id']}")[1]['data']['status'],'COMPLETED')
        self.assertEqual(self.request('GET',root+'/patterns/UNKNOWN')[0],404)
        self.assertEqual(self.request('POST',url,{'languageProfileId':self.profile['id'],'pattern':'V2'})[0],400)
        self.assertEqual(self.request('GET','/api/language/texts/invalid/grammar?profileId='+self.profile['id'])[0],400)
        other=self.service.create_profile({'languageCode':'nb','locale':'nb','displayName':'Other'})['data']['profile']['id']
        self.assertEqual(self.request('GET',f"/api/language/texts/{text['id']}/grammar?profileId={other}")[0],409)
        self.assertEqual(self.request('PATCH',f'/api/language/grammar/occurrences/{occurrence}/review',{'languageProfileId':other,'decision':'CONFIRMED'})[0],409)

    def test_mistake_intelligence_routes_are_read_only_and_bounded(self):
        status, body = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/mistakes?limit=5&asOf=2026-09-18T12%3A00%3A00Z"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["activeClusterCount"], 0)
        self.assertEqual(body["data"]["sourceAvailability"]["ankiReviewHistory"], "NOT_SUPPORTED")
        status, remediation = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/remediation?limit=5&asOf=2026-09-18T12%3A00%3A00Z"
        )
        self.assertEqual(status, 200)
        self.assertEqual(remediation["data"]["items"], [])
        status, detail = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/mistakes/mi_missing"
        )
        self.assertEqual(status, 404)
        self.assertEqual(detail["code"], "mistake_cluster_not_found")
        status, _ = self.request(
            "POST", f"/api/language/profiles/{self.profile['id']}/mistakes", {}
        )
        self.assertEqual(status, 404)

    def test_health_profiles_and_startup_paths_never_instantiate_stanza(self):
        with mock.patch(
            "language_learning.analysis.norwegian_bokmal.NorwegianBokmalStanzaAnalyzer.__init__",
            side_effect=AssertionError("Stanza must not load"),
        ) as analyzer:
            status, health = self.request("GET", "/api/language/health")
            profiles_status, profiles = self.request("GET", "/api/language/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(profiles_status, 200)
        self.assertEqual(health["data"]["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(
            health["data"]["listening"]["browserCapabilityScope"],
            "DEVICE_LOCAL_NOT_SERVER_GLOBAL",
        )
        self.assertEqual(health["data"]["offsetUnit"], "UNICODE_CODE_POINT")
        self.assertEqual(health["data"]["canonicalAnalyzer"]["runtimeState"], "LAZY_NOT_CREATED")
        self.assertEqual(profiles["data"]["items"][0]["languageCode"], "nb")
        serialized = json.dumps(health).lower()
        self.assertNotIn(".sqlite", serialized)
        self.assertNotIn(self.temp.name.lower(), serialized)
        analyzer.assert_not_called()

    def test_phase76_gamification_reads_and_campaign_writes_are_thin(self):
        profile_id = self.profile["id"]
        status, progress = self.request(
            "GET", f"/api/language/profiles/{profile_id}/gamification?asOf=2026-09-17T10:00:00Z"
        )
        self.assertEqual(status, 200)
        self.assertEqual(progress["data"]["level"]["label"], "Norwegian Level 1")
        self.assertEqual(len(progress["data"]["today"]["items"]), 3)
        status, created = self.request(
            "POST", f"/api/language/profiles/{profile_id}/campaigns", {
                "name": "Norway Spring 2027", "targetDate": "2027-05-01",
                "milestones": [{"type": "CLOZE_ATTEMPTS", "target": 100}],
            },
        )
        self.assertEqual(status, 201)
        campaign_id = created["data"]["campaign"]["id"]
        self.assertIsNone(created["data"]["campaign"]["universalReadinessPercent"])
        status, campaigns = self.request("GET", f"/api/language/profiles/{profile_id}/campaigns")
        self.assertEqual(status, 200)
        self.assertEqual(campaigns["data"]["items"][0]["name"], "Norway Spring 2027")
        status, updated = self.request(
            "PATCH", f"/api/language/campaigns/{campaign_id}", {"enabled": False}
        )
        self.assertEqual(status, 200)
        self.assertFalse(updated["data"]["campaign"]["enabled"])

    def test_phase78_curriculum_reads_and_version_pinned_campaign_are_thin(self):
        profile_id = self.profile["id"]
        with self.store.connection() as connection:
            before = connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0]
        status, landing = self.request("GET", f"/api/language/profiles/{profile_id}/curriculum")
        self.assertEqual(status, 200)
        self.assertEqual(len(landing["data"]["packs"]), 5)
        pack = next(item for item in landing["data"]["packs"] if item["id"] == "nb.public-services.tax")
        self.assertEqual(pack["progress"]["eligibleDenominator"], 5)
        status, detail = self.request(
            "GET", f"/api/language/profiles/{profile_id}/curriculum/nb.public-services.tax/versions/1"
        )
        self.assertEqual(status, 200)
        mapped = next(item for item in detail["data"]["progress"]["items"] if item["mappingState"] == "MAPPED")
        status, item = self.request(
            "GET",
            f"/api/language/profiles/{profile_id}/curriculum/nb.public-services.tax/versions/1/items/{mapped['membershipId']}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(item["data"]["item"]["membershipId"], mapped["membershipId"])
        with self.store.connection() as connection:
            after = connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0]
        self.assertEqual(after, before)
        status, campaign = self.request(
            "POST", f"/api/language/profiles/{profile_id}/campaigns", {
                "name": "Tax pack", "targetDate": "2027-05-01",
                "milestones": [{
                    "type": "CURRICULUM_PACK_PROGRESS", "packId": "nb.public-services.tax",
                    "packVersion": 1, "target": 75,
                }],
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(campaign["data"]["campaign"]["milestones"][0]["packVersion"], 1)
        status, missing = self.request("POST", "/api/language/award-xp", {"xp": 500})
        self.assertEqual(status, 404)

    def test_search_detail_controlled_edit_and_exact_text_draft(self):
        status, listing = self.request(
            "GET",
            f"/api/language/profiles/{self.profile['id']}/vocabulary?q=jobbene&limit=10",
        )
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in listing["data"]["items"]], [self.lemma["id"]])
        status, updated = self.request(
            "PATCH",
            f"/api/language/lemmas/{self.lemma['id']}",
            {"knowledgeStatus": "KNOWN", "recognition": 4, "userNotes": "manuell"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["data"]["knowledge"]["knowledgeStatus"], "KNOWN")
        raw = "Ærlig 😊 jobb\n  blåbær"
        status, created = self.request(
            "POST",
            "/api/language/texts",
            {"languageProfileId": self.profile["id"], "title": "Unicode", "rawText": raw},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["data"]["text"]["offsetUnit"], "UNICODE_CODE_POINT")
        status, loaded = self.request("GET", f"/api/language/texts/{created['data']['text']['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(loaded["data"]["document"]["rawText"].encode(), raw.encode())
        self.assertEqual(loaded["data"]["sentences"], [])
        self.assertEqual(loaded["data"]["tokens"], [])

    def test_reader_study_pack_import_matches_exact_sentences_and_preserves_saved_notes(self):
        status, created = self.request("POST", "/api/language/texts", {
            "languageProfileId": self.profile["id"], "title": "Study pack", "rawText": "Jeg jobber.",
        })
        self.assertEqual(status, 201)
        text_id = created["data"]["text"]["id"]
        status, queued = self.request("POST", f"/api/language/texts/{text_id}/analyze", {})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_for_api_job(queued["data"]["job"]["id"])["state"], "COMPLETED")
        status, notes = self.request("GET", f"/api/language/texts/{text_id}/study-notes")
        self.assertEqual(status, 200)
        sentence = notes["data"]["items"][0]
        self.assertIsNone(sentence["english"])
        status, text = self.request("GET", f"/api/language/texts/{text_id}")
        self.assertEqual(status, 200)
        words = [token for token in text["data"]["tokens"] if token["tokenKind"] == "WORD"]
        self.assertEqual(len(words), 2)
        row = {"sentenceId": sentence["sentenceId"], "source": sentence["source"],
               "english": "I work.",
               "glosses": [{"source": "Jeg jobber", "english": "I work", "tokenIds": [word["id"] for word in words]}],
               "grammarHint": "The present tense of jobbe is jobber."}
        status, imported = self.request("POST", f"/api/language/texts/{text_id}/study-notes/import", {"sentences": [row]})
        self.assertEqual(status, 200)
        self.assertEqual(imported["data"]["items"][0]["english"], "I work.")
        self.assertEqual(imported["data"]["items"][0]["grammarHint"], row["grammarHint"])
        self.assertEqual(imported["data"]["items"][0]["glosses"], row["glosses"])
        status, rejected = self.request("POST", f"/api/language/texts/{text_id}/study-notes/import", {
            "sentences": [{**row, "glosses": [{"source": "jobber", "english": "work", "tokenIds": [words[1]["id"]]}]}],
        })
        self.assertEqual(status, 400)
        status, rejected = self.request("POST", f"/api/language/texts/{text_id}/study-notes/import", {
            "sentences": [{**row, "glosses": [{**row["glosses"][0], "source": "jeg jobber"}]}],
        })
        self.assertEqual(status, 400)
        status, rejected = self.request("POST", f"/api/language/texts/{text_id}/study-notes/import", {
            "sentences": [{**row, "source": "A different sentence."}],
        })
        self.assertEqual(status, 400)
        status, saved = self.request("GET", f"/api/language/texts/{text_id}/study-notes")
        self.assertEqual(saved["data"]["items"][0]["english"], "I work.")
        self.assertEqual(saved["data"]["items"][0]["glosses"], row["glosses"])

    def test_phase10_listening_routes_are_thin_and_persist_canonical_evidence(self):
        created_status, created = self.request("POST", "/api/language/texts", {
            "languageProfileId": self.profile["id"], "title": "Listening API",
            "rawText": "Jeg jobber.", "sourceType": "PASTED",
        })
        self.assertEqual(created_status, 201)
        text_id = created["data"]["text"]["id"]
        queued_status, queued = self.request("POST", f"/api/language/texts/{text_id}/analyze", {})
        self.assertEqual(queued_status, 202)
        self.assertEqual(self.wait_for_api_job(queued["data"]["job"]["id"])["state"], "COMPLETED")
        text_status, text = self.request("GET", f"/api/language/texts/{text_id}")
        self.assertEqual(text_status, 200)
        sentence_id = text["data"]["sentences"][0]["id"]

        list_status, listing = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/listening"
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(listing["data"]["items"][0]["listeningStatus"], "NOT_STARTED")
        session_status, started = self.request(
            "POST", f"/api/language/texts/{text_id}/listening-sessions", {
                "languageProfileId": self.profile["id"], "clientSessionId": "http-listen-1",
                "mode": "READ_LISTEN",
            },
        )
        self.assertEqual(session_status, 201)
        session_id = started["data"]["session"]["id"]
        event_status, event = self.request(
            "POST", f"/api/language/listening-sessions/{session_id}/sentence-events", {
                "textDocumentId": text_id, "sentenceId": sentence_id,
                "idempotencyKey": "http-event-1", "outcome": "ENDED",
                "playbackSource": "BROWSER_TTS", "activeMs": 1000, "durationMs": 1000,
            },
        )
        self.assertEqual(event_status, 201)
        self.assertTrue(event["data"]["event"]["qualified"])
        progress_status, progress = self.request(
            "GET", f"/api/language/texts/{text_id}/listening-progress?profileId={self.profile['id']}"
        )
        self.assertEqual(progress_status, 200)
        self.assertEqual(progress["data"]["progress"]["status"], "COMPLETED")
        close_status, closed = self.request(
            "PATCH", f"/api/language/listening-sessions/{session_id}", {"commandId": "http-close-1"}
        )
        self.assertEqual(close_status, 200)
        self.assertEqual(closed["data"]["session"]["status"], "COMPLETED")

    def test_phase77_lexical_translation_and_phrasebook_routes_are_thin(self):
        provider = mock.Mock()
        provider.health.return_value = {"id": "FIXTURE", "version": "1", "configured": True}
        provider.lookup_lemma.return_value = {
            "available": True, "lookupStatus": "MATCHED", "articles": [],
            "provider": provider.health.return_value,
        }
        self.service.dictionary_provider = provider
        status, lexical = self.request("GET", f"/api/language/lemmas/{self.lemma['id']}/lexical-detail")
        self.assertEqual(status, 200)
        self.assertEqual(lexical["data"]["dictionary"]["lookupStatus"], "MATCHED")
        provider.lookup_lemma.assert_called_once_with("jobb", "NOUN")

        status, translated = self.request(
            "POST", f"/api/language/lemmas/{self.lemma['id']}/translations",
            {"targetLocale": "pl-PL", "translation": "praca"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(translated["data"]["translation"]["translationText"], "praca")

        payload = {
            "expression": "på jobb", "sourceType": "READER",
            "sourceEntityId": "a" * 32, "sourceContext": "Han er på jobb.",
            "sourceProvenance": {"sentenceId": "b" * 32},
        }
        status, created = self.request(
            "POST", f"/api/language/profiles/{self.profile['id']}/phrasebook", payload,
        )
        self.assertEqual(status, 201)
        entry_id = created["data"]["entry"]["id"]
        retry_status, retry = self.request(
            "POST", f"/api/language/profiles/{self.profile['id']}/phrasebook", payload,
        )
        self.assertEqual(retry_status, 200)
        self.assertTrue(retry["data"]["reused"])
        list_status, listing = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/phrasebook?q=p%C3%A5&sourceType=READER",
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(listing["data"]["pagination"]["total"], 1)
        patch_status, updated = self.request(
            "PATCH", f"/api/language/phrasebook/{entry_id}",
            {"note": "useful", "userTranslation": "w pracy"},
        )
        self.assertEqual(patch_status, 200)
        self.assertEqual(updated["data"]["entry"]["userTranslation"], "w pracy")
        delete_status, deleted = self.request("DELETE", f"/api/language/phrasebook/{entry_id}")
        self.assertEqual(delete_status, 200)
        self.assertTrue(deleted["data"]["deleted"])
        translation_delete_status, _ = self.request(
            "DELETE", f"/api/language/lemmas/{self.lemma['id']}/translations?targetLocale=pl-PL",
        )
        self.assertEqual(translation_delete_status, 200)

    def test_profile_create_get_patch_and_duplicate_are_bounded(self):
        payload = {"languageCode": "sv", "locale": "sv-SE", "displayName": "Swedish"}
        status, created = self.request("POST", "/api/language/profiles", payload)
        self.assertEqual(status, 201)
        profile_id = created["data"]["profile"]["id"]
        duplicate_status, duplicate = self.request("POST", "/api/language/profiles", payload)
        self.assertEqual(duplicate_status, 200)
        self.assertFalse(duplicate["data"]["created"])
        status, updated = self.request(
            "PATCH", f"/api/language/profiles/{profile_id}", {"displayName": "Svenska", "status": "INACTIVE"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["data"]["profile"]["displayName"], "Svenska")
        get_status, detail = self.request("GET", f"/api/language/profiles/{profile_id}")
        self.assertEqual(get_status, 200)
        self.assertEqual(detail["data"]["profile"]["status"], "INACTIVE")

    def test_merge_endpoint_redirects_and_audits(self):
        duplicate = self.service.upsert_lemma(
            self.profile["id"], "job", part_of_speech="NOUN"
        )["lemma"]
        status, merged = self.request("POST", "/api/language/lemmas/merge", {
            "sourceLemmaId": duplicate["id"],
            "targetLemmaId": self.lemma["id"],
            "note": "manual duplicate",
        })
        self.assertEqual(status, 200)
        self.assertEqual(merged["data"]["targetLemmaId"], self.lemma["id"])
        source_status, source = self.request("GET", f"/api/language/lemmas/{duplicate['id']}")
        self.assertEqual(source_status, 200)
        self.assertEqual(source["data"]["lemma"]["mergedIntoId"], self.lemma["id"])
        target_status, target = self.request("GET", f"/api/language/lemmas/{self.lemma['id']}")
        self.assertEqual(target_status, 200)
        self.assertEqual(target["data"]["events"][-1]["eventType"], "LEMMA_MERGED")

    def test_form_mapping_evidence_and_manual_lock_endpoint(self):
        alternative = self.service.upsert_lemma(
            self.profile["id"], "jobbe", part_of_speech="VERB"
        )["lemma"]
        self.service.upsert_form_lemma_mapping(
            self.profile["id"],
            self.form["id"],
            alternative["id"],
            provider_id="stanza-nb-bokmaal",
            provider_version="1.0.0",
            ambiguity_state="AMBIGUOUS",
        )

        status, evidence = self.request(
            "GET", f"/api/language/forms/{self.form['id']}/mapping"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(evidence["data"]["mappings"]), 2)

        status, locked = self.request(
            "PATCH",
            f"/api/language/forms/{self.form['id']}/mapping",
            {"lemmaId": alternative["id"]},
        )
        self.assertEqual(status, 200)
        selected = next(
            row for row in locked["data"]["mappings"]
            if row["lemmaId"] == alternative["id"]
        )
        self.assertTrue(selected["manualLocked"])
        self.assertEqual(selected["mappingProvenance"], "MANUAL")
        self.assertEqual(selected["manualProvenance"], "LANGUAGE_PHASE3_UI")

        detail_status, detail = self.request(
            "GET", f"/api/language/lemmas/{alternative['id']}"
        )
        self.assertEqual(detail_status, 200)
        form = next(row for row in detail["data"]["forms"] if row["id"] == self.form["id"])
        self.assertEqual(len(form["candidateMappings"]), 2)

    def test_form_mapping_endpoint_validates_ids_and_payload(self):
        status, body = self.request(
            "PATCH",
            f"/api/language/forms/{self.form['id']}/mapping",
            {"lemmaId": "not-an-id"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_language_id")

        status, body = self.request(
            "GET", "/api/language/forms/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/mapping"
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "language_form_not_found")

    def test_malformed_json_invalid_id_payload_limit_and_error_envelopes(self):
        malformed_status, malformed = self.request("POST", "/api/language/texts", raw=b"{")
        self.assertEqual(malformed_status, 400)
        self.assertEqual(set(malformed), {"ok", "error", "code", "details"})
        self.assertEqual(malformed["code"], "invalid_json")
        invalid_status, invalid = self.request("GET", "/api/language/lemmas/not-an-id")
        self.assertEqual(invalid_status, 400)
        self.assertEqual(invalid["code"], "invalid_language_id")
        large_status, large = self.request(
            "POST", "/api/language/texts", raw=b"{}", headers={"Content-Length": str(3 * 1024 * 1024)}
        )
        self.assertEqual(large_status, 413)
        self.assertEqual(large["code"], "payload_too_large")

    def test_write_authorization_reuses_origin_policy(self):
        status, body = self.request(
            "PATCH",
            f"/api/language/lemmas/{self.lemma['id']}",
            {"knowledgeStatus": "KNOWN"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body, {
            "ok": False,
            "error": "Origin not allowed",
            "code": "origin_not_allowed",
            "details": [],
        })
        detail = self.service.get_lemma(self.lemma["id"])["data"]
        self.assertEqual(detail["knowledge"]["knowledgeStatus"], "NEW")

    def test_content_inbox_routes_use_post_get_patch_and_managed_media(self):
        profile_id = self.profile["id"]
        created_status, created = self.request(
            "POST", f"/api/language/profiles/{profile_id}/content", {
                "sourceType": "PASTED_TEXT", "title": "API text", "text": "Jeg har en jobb.",
            },
        )
        self.assertEqual(created_status, 201)
        content_id = created["data"]["item"]["id"]
        list_status, listing = self.request("GET", f"/api/language/profiles/{profile_id}/content")
        self.assertEqual(list_status, 200)
        self.assertIn(content_id, {item["id"] for item in listing["data"]["items"]})
        detail_status, detail = self.request("GET", f"/api/language/content/{content_id}")
        self.assertEqual(detail_status, 200)
        self.assertEqual(detail["data"]["item"]["sourceType"], "PASTED_TEXT")

        audio = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40
        upload_status, upload = self.request(
            "POST",
            f"/api/language/profiles/{profile_id}/content/audio?title=Owned&fileName=owned.wav",
            raw=audio,
            headers={"Content-Type": "audio/wav"},
        )
        self.assertEqual(upload_status, 201)
        artifact_id = upload["data"]["media"]["id"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", f"/api/language/content/media/{artifact_id}", headers={"Range": "bytes=0-7"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        self.assertEqual(response.status, 206)
        self.assertEqual(response.getheader("Content-Type"), "audio/wav")
        self.assertEqual(body, audio[:8])

        forbidden_status, forbidden = self.request(
            "POST", f"/api/language/profiles/{profile_id}/content", {
                "sourceType": "PASTED_TEXT", "title": "Blocked", "text": "Blocked.",
            }, headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(forbidden_status, 403)
        self.assertEqual(forbidden["code"], "origin_not_allowed")

    def test_export_and_backup_are_versioned_safe_and_consistent(self):
        status, exported = self.request("GET", "/api/language/export")
        self.assertEqual(status, 200)
        self.assertEqual(exported["data"]["exportVersion"], EXPORT_VERSION)
        self.assertEqual(exported["data"]["data"]["vocabularyLemmas"][0]["id"], self.lemma["id"])
        status, backup = self.request("POST", "/api/language/backup", {})
        self.assertEqual(status, 201)
        backup_json = json.dumps(backup)
        self.assertNotIn(self.temp.name, backup_json)
        self.assertNotIn("path", backup_json.lower())
        backup_path = self.store.backup_directory / backup["data"]["backup"]["fileName"]
        with sqlite3.connect(backup_path) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT id FROM vocabulary_lemmas").fetchone()[0], self.lemma["id"])
        rejected_status, rejected = self.request(
            "POST", "/api/language/backup", {"destination": str(Path(self.temp.name) / "elsewhere.sqlite")}
        )
        self.assertEqual(rejected_status, 400)
        self.assertEqual(rejected["code"], "invalid_backup_request")

    def test_unexpected_failures_do_not_leak_paths_sql_or_secrets(self):
        leaked = RuntimeError(f"SELECT * FROM secrets at {self.temp.name} token=abc")
        with mock.patch.object(self.service, "health", side_effect=leaked):
            status, body = self.request("GET", "/api/language/health")
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "language_internal_error")
        serialized = json.dumps(body)
        self.assertNotIn(self.temp.name, serialized)
        self.assertNotIn("SELECT", serialized)
        self.assertNotIn("token", serialized)

    def test_future_phase_routes_do_not_exist(self):
        for path in (
            "/api/language/generate",
            "/api/language/anki/sync",
            "/api/language/cloze",
        ):
            with self.subTest(path=path):
                status, body = self.request("POST", path, {})
                self.assertEqual(status, 404)
                self.assertNotIn("data", body)

    def test_analysis_job_polling_text_history_preview_commit_and_cancel_routes(self):
        entered = threading.Event()
        release = threading.Event()
        self.analyzer.entered = entered
        self.analyzer.release = release
        create_status, created = self.request("POST", "/api/language/texts", {
            "languageProfileId": self.profile["id"],
            "title": "Async",
            "rawText": "jobbene",
        })
        self.assertEqual(create_status, 201)
        text_id = created["data"]["text"]["id"]

        analyze_status, queued = self.request(
            "POST", f"/api/language/texts/{text_id}/analyze", {}
        )
        self.assertEqual(analyze_status, 202)
        job_id = queued["data"]["job"]["id"]
        self.assertTrue(entered.wait(timeout=2))
        poll_status, running = self.request("GET", f"/api/language/jobs/{job_id}")
        self.assertEqual(poll_status, 200)
        self.assertEqual(running["data"]["job"]["state"], "RUNNING")
        release.set()
        completed = self.wait_for_api_job(job_id)
        self.assertEqual(completed["state"], "COMPLETED")
        duplicate_status, duplicate = self.request(
            "POST", f"/api/language/texts/{text_id}/analyze", {}
        )
        self.assertEqual(duplicate_status, 200)
        self.assertTrue(duplicate["data"]["reused"])
        self.assertEqual(duplicate["data"]["job"]["id"], job_id)

        list_status, listing = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/texts?limit=1"
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(listing["data"]["items"][0]["id"], text_id)
        self.assertEqual(listing["data"]["items"][0]["latestJobState"], "COMPLETED")

        self.analyzer.release = None
        self.analyzer.entered = None
        self.analyzer.variant = "changed"
        preview_status, preview_body = self.request(
            "POST", f"/api/language/texts/{text_id}/reanalyze/preview", {}
        )
        self.assertEqual(preview_status, 202)
        preview = self.wait_for_api_job(preview_body["data"]["job"]["id"])
        self.assertEqual(preview["state"], "COMPLETED")
        self.assertGreaterEqual(preview["result"]["summary"]["lemmaChanges"], 1)
        commit_status, commit_body = self.request(
            "POST",
            f"/api/language/texts/{text_id}/reanalyze/commit",
            {"previewJobId": preview["id"]},
        )
        self.assertEqual(commit_status, 202)
        commit = self.wait_for_api_job(commit_body["data"]["job"]["id"])
        self.assertEqual(commit["state"], "COMPLETED")

        cancel_text = self.service.create_text_draft({
            "languageProfileId": self.profile["id"], "title": "Cancel", "rawText": "jobb"
        })["data"]["text"]
        gate_entered = threading.Event()
        gate_release = threading.Event()
        self.analyzer.entered = gate_entered
        self.analyzer.release = gate_release
        _, cancel_queued = self.request(
            "POST", f"/api/language/texts/{cancel_text['id']}/analyze", {}
        )
        self.assertTrue(gate_entered.wait(timeout=2))
        cancel_status, cancel_body = self.request(
            "POST", f"/api/language/jobs/{cancel_queued['data']['job']['id']}/cancel", {}
        )
        self.assertEqual(cancel_status, 200)
        self.assertTrue(cancel_body["data"]["job"]["cancelRequested"])
        gate_release.set()
        cancelled = self.wait_for_api_job(cancel_queued["data"]["job"]["id"])
        self.assertEqual(cancelled["state"], "CANCELLED")

    def test_analysis_failure_is_polled_safely_and_options_are_rejected(self):
        text = self.service.create_text_draft({
            "languageProfileId": self.profile["id"],
            "title": "Unavailable",
            "rawText": "jobbene",
        })["data"]["text"]
        invalid_status, invalid = self.request(
            "POST", f"/api/language/texts/{text['id']}/analyze", {"modelPath": self.temp.name}
        )
        self.assertEqual(invalid_status, 400)
        self.assertEqual(invalid["code"], "invalid_language_request")

        self.analyzer.failure = AnalyzerUnavailableError(f"missing at {self.temp.name}")
        status, queued = self.request(
            "POST", f"/api/language/texts/{text['id']}/analyze", {}
        )
        self.assertEqual(status, 202)
        failed = self.wait_for_api_job(queued["data"]["job"]["id"])
        self.assertEqual(failed["state"], "FAILED")
        self.assertEqual(failed["errorCode"], "canonical_analyzer_unavailable")
        serialized = json.dumps(failed)
        self.assertNotIn(self.temp.name, serialized)
        self.assertNotIn("modelPath", serialized)

    def test_reader_session_exposure_progress_history_and_reanalysis_routes(self):
        create_status, created = self.request("POST", "/api/language/texts", {
            "languageProfileId": self.profile["id"],
            "title": "Reader flow",
            "rawText": "jobb jobben jobber jobbene",
        })
        self.assertEqual(create_status, 201)
        text_id = created["data"]["text"]["id"]
        analyze_status, queued = self.request(
            "POST", f"/api/language/texts/{text_id}/analyze", {}
        )
        self.assertEqual(analyze_status, 202)
        self.assertEqual(self.wait_for_api_job(queued["data"]["job"]["id"])["state"], "COMPLETED")
        _, reader = self.request("GET", f"/api/language/texts/{text_id}")
        sentence_id = reader["data"]["sentences"][0]["id"]
        counts = {}
        for token in reader["data"]["tokens"]:
            if token["tokenKind"] == "WORD" and token.get("selectedLemmaId"):
                counts[token["selectedLemmaId"]] = counts.get(token["selectedLemmaId"], 0) + 1
        occurrences = [
            {"lemmaId": lemma_id, "occurrenceCount": count}
            for lemma_id, count in sorted(counts.items())
        ]

        session_status, session_body = self.request(
            "POST", "/api/language/study-sessions", {
                "languageProfileId": self.profile["id"],
                "textDocumentId": text_id,
                "clientSessionId": "api-reader-session",
            },
        )
        self.assertEqual(session_status, 201)
        session = session_body["data"]["session"]
        batch = {
            "textDocumentId": text_id,
            "sentenceId": sentence_id,
            "idempotencyKey": "api-reader-session:sentence-0",
            "occurrences": occurrences,
        }
        exposure_status, exposure = self.request(
            "POST", f"/api/language/study-sessions/{session['id']}/exposures", batch
        )
        retry_status, retry = self.request(
            "POST", f"/api/language/study-sessions/{session['id']}/exposures", batch
        )
        self.assertEqual(exposure_status, 201)
        self.assertEqual(retry_status, 200)
        self.assertTrue(exposure["data"]["created"])
        self.assertTrue(retry["data"]["duplicate"])

        progress_status, progress = self.request(
            "PATCH", f"/api/language/texts/{text_id}/reading-progress", {
                "languageProfileId": self.profile["id"],
                "progressSourceOffset": len("jobb jobben jobber jobbene"),
                "progressSentenceId": sentence_id,
                "status": "COMPLETED",
            },
        )
        self.assertEqual(progress_status, 200)
        self.assertEqual(progress["data"]["readingProgress"]["status"], "COMPLETED")
        command_status, command = self.request(
            "PATCH", f"/api/language/study-sessions/{session['id']}", {
                "action": "COMPLETE", "commandId": "complete-1"
            },
        )
        self.assertEqual(command_status, 200)
        self.assertEqual(command["data"]["session"]["status"], "COMPLETED")
        _, history = self.request(
            "GET", f"/api/language/profiles/{self.profile['id']}/texts?limit=10"
        )
        item = next(row for row in history["data"]["items"] if row["id"] == text_id)
        self.assertEqual(item["readingStatus"], "COMPLETED")
        self.assertIn("coverage", item)

        preview_status, preview_body = self.request(
            "POST", f"/api/language/texts/{text_id}/reanalyze/preview", {}
        )
        self.assertEqual(preview_status, 202)
        preview = self.wait_for_api_job(preview_body["data"]["job"]["id"])
        blocked_status, blocked = self.request(
            "POST", f"/api/language/texts/{text_id}/reanalyze/commit",
            {"previewJobId": preview["id"]},
        )
        self.assertEqual(blocked_status, 409)
        self.assertEqual(blocked["code"], "studied_text_reanalysis_blocked")

    def test_phase5_overview_statistics_topic_goal_and_widget_routes(self):
        profile_id = self.profile["id"]
        topic_status, topic_body = self.request(
            "POST",
            f"/api/language/profiles/{profile_id}/topics",
            {"displayName": "Work", "description": "Manual scope"},
        )
        self.assertEqual(topic_status, 201)
        topic_id = topic_body["data"]["topic"]["id"]
        assign_status, _ = self.request(
            "POST",
            f"/api/language/topics/{topic_id}/lemmas",
            {"lemmaId": self.lemma["id"], "weight": 2, "provenance": "MANUAL"},
        )
        self.assertEqual(assign_status, 201)

        topic_list_status, topic_list = self.request(
            "GET", f"/api/language/profiles/{profile_id}/topics?includeArchived=true"
        )
        topic_detail_status, topic_detail = self.request(
            "GET", f"/api/language/topics/{topic_id}"
        )
        self.assertEqual(topic_list_status, 200)
        self.assertEqual(topic_detail_status, 200)
        self.assertEqual(topic_list["data"]["items"][0]["mappedLemmaCount"], 1)
        self.assertEqual(
            topic_detail["data"]["mastery"]["denominatorQuality"]["scope"],
            "USER_MAPPED_LEMMAS_ONLY",
        )

        goal_status, goal_body = self.request(
            "POST",
            f"/api/language/profiles/{profile_id}/goals",
            {"metric": "NEW_WORDS", "targetValue": 5, "unit": "WORDS"},
        )
        self.assertEqual(goal_status, 201)
        goal_id = goal_body["data"]["goal"]["id"]
        goals_status, goals = self.request(
            "GET", f"/api/language/profiles/{profile_id}/goals"
        )
        self.assertEqual(goals_status, 200)
        self.assertEqual(goals["data"]["items"][0]["target"], 5)
        disable_status, disabled = self.request(
            "PATCH", f"/api/language/goals/{goal_id}", {"enabled": False}
        )
        self.assertEqual(disable_status, 200)
        self.assertFalse(disabled["data"]["goal"]["enabled"])

        for route, expected_key in (
            ("overview", "statistics"),
            ("statistics?range=7d", "vocabulary"),
            ("learning-plan", "items"),
            ("widget-summary", "streakDays"),
        ):
            status, body = self.request(
                "GET", f"/api/language/profiles/{profile_id}/{route}"
            )
            self.assertEqual(status, 200)
            self.assertIn(expected_key, body["data"])

        remove_status, _ = self.request(
            "DELETE", f"/api/language/topics/{topic_id}/lemmas/{self.lemma['id']}"
        )
        self.assertEqual(remove_status, 200)

    def test_productization_read_routes_do_not_create_learning_evidence(self):
        profile_id = self.profile["id"]
        with self.store.connection() as db:
            before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("knowledge_events", "exposure_events", "cloze_attempts", "gamification_awards")}
        routes = (
            (f"/api/language/profiles/{profile_id}/today-summary", "policyVersion"),
            (f"/api/language/profiles/{profile_id}/widget-summary", "policyVersion"),
            (f"/api/language/lemmas/{self.lemma['id']}/preview", "lemmaDisplay"),
            (f"/api/language/profiles/{profile_id}/lexical-preview?surface=jobbene", "lemmaDisplay"),
            (f"/api/language/profiles/{profile_id}/lexical-preview?surface=ukjent", "lemmaDisplay"),
        )
        with mock.patch.object(self.service.dictionary_provider, "lookup_lemma", side_effect=AssertionError("dictionary call")):
            with mock.patch.object(self.service.anki_sync_service, "status", wraps=self.service.anki_sync_service.status) as anki_status:
                for path, key in routes:
                    status, body = self.request("GET", path)
                    self.assertEqual(status, 200, path)
                    self.assertIn(key, body["data"])
                self.assertTrue(all(call.kwargs.get("probe") is False for call in anki_status.call_args_list))
        with self.store.connection() as db:
            after = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in before}
        self.assertEqual(after, before)

    def test_phase6_anki_routes_are_thin_preview_first_and_secret_free(self):
        profile_id = self.profile["id"]
        config_status, config = self.request(
            "PATCH", f"/api/language/profiles/{profile_id}/anki/config", {
                "enabled": True, "endpoint": "http://127.0.0.1:8765",
                "deckName": "Language Test", "modelName": "Dashboard",
                "fieldMap": {"target": "Front", "lemma": "Lemma", "dashboardKey": "DashboardKey"},
            },
        )
        self.assertEqual(config_status, 200)
        self.assertNotIn("apiKey", config["data"]["config"])
        for suffix in ("status", "config", "decks", "models", "models/Dashboard/fields", "sync-runs"):
            status, body = self.request("GET", f"/api/language/profiles/{profile_id}/anki/{suffix}")
            self.assertEqual(status, 200, suffix)
            self.assertTrue(body["ok"])
        preview_status, preview_body = self.request(
            "POST", f"/api/language/lemmas/{self.lemma['id']}/anki/preview", {}
        )
        self.assertEqual(preview_status, 200)
        self.assertEqual(preview_body["data"]["action"], "CREATE")
        self.assertEqual(self.fake_anki.write_calls, [])
        commit_status, commit = self.request(
            "POST", f"/api/language/lemmas/{self.lemma['id']}/anki/commit", {
                "confirm": True,
                "previewFingerprint": preview_body["data"]["previewFingerprint"],
            },
        )
        self.assertEqual(commit_status, 200)
        self.assertEqual(commit["data"]["action"], "CREATE")
        state_status, state = self.request("GET", f"/api/language/lemmas/{self.lemma['id']}/anki")
        self.assertEqual(state_status, 200)
        self.assertTrue(state["data"]["linked"])
        pull_status, pull = self.request("POST", f"/api/language/profiles/{profile_id}/anki/pull", {})
        self.assertEqual(pull_status, 200)
        self.assertEqual(pull["data"]["dueCount"], 1)
        web_status, web = self.request("POST", f"/api/language/profiles/{profile_id}/anki/sync-web", {"force": True})
        self.assertEqual(web_status, 200)
        self.assertTrue(web["data"]["syncedAt"])
        self.assertIn("sync", self.fake_anki.write_calls)
        invalid_status, _ = self.request("POST", f"/api/language/profiles/{profile_id}/anki/sync-web", {"force": "yes"})
        self.assertEqual(invalid_status, 400)

    def test_phase7_generation_routes_are_manual_local_and_reader_gated(self):
        created_status, created = self.request(
            "POST", f"/api/language/profiles/{self.profile['id']}/generation-requests",
            {"length": 200, "difficultyPreset": "BALANCED", "explicitTargetLemmaIds": [self.lemma["id"]]},
        )
        self.assertEqual(created_status, 201)
        request_id = created["data"]["request"]["id"]
        for suffix in ("", "/context-pack", "/candidates"):
            status, body = self.request("GET", f"/api/language/generation-requests/{request_id}{suffix}")
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
        imported_status, imported = self.request(
            "POST", f"/api/language/generation-requests/{request_id}/candidates",
            {"response": json.dumps({"title": "Arbeid", "text": "jobb jobben"})},
        )
        self.assertEqual(imported_status, 201)
        candidate_id = imported["data"]["candidate"]["id"]
        queued_status, _ = self.request("POST", f"/api/language/generation-candidates/{candidate_id}/analyze", {})
        self.assertEqual(queued_status, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, candidate = self.request("GET", f"/api/language/generation-candidates/{candidate_id}")
            self.assertEqual(status, 200)
            if candidate["data"]["candidate"]["status"] not in {"QUEUED", "ANALYZING"}:
                break
            time.sleep(0.01)
        revision_status, revision = self.request("GET", f"/api/language/generation-candidates/{candidate_id}/revision-prompt")
        self.assertEqual(revision_status, 200)
        self.assertIn("manual revision request", revision["data"]["prompt"])
        accepted_status, accepted = self.request("POST", f"/api/language/generation-candidates/{candidate_id}/accept", {})
        self.assertEqual(accepted_status, 201)
        self.assertEqual(accepted["data"]["document"]["sourceType"], "GENERATED_MANUAL_LLM")

    def test_phase7_5c_read_only_reference_routes_and_user_evidence_invariant(self):
        reference_path = Path(self.temp.name) / "reference.sqlite"
        import_fixture(
            ReferenceStore(reference_path),
            Path(__file__).parent / "fixtures" / "language" / "reference" / "reference_v1.json",
        )
        self.service.attach_reference_lexicon_service(ReferenceLexiconService(reference_path))
        health_status, health = self.request("GET", "/api/language/reference/health")
        self.assertEqual(health_status, 200)
        self.assertTrue(health["data"]["available"])
        self.assertNotIn(str(reference_path), json.dumps(health))

        lemma_status, lemma = self.request(
            "GET", f"/api/language/lemmas/{self.lemma['id']}/reference"
        )
        self.assertEqual(lemma_status, 200)
        self.assertEqual(set(lemma["data"]), {"user", "reference", "resolution"})
        self.assertEqual(lemma["data"]["resolution"]["status"], "UNMATCHED")

        create_status, created = self.request("POST", "/api/language/texts", {
            "languageProfileId": self.profile["id"], "title": "Reference expression",
            "rawText": "ugler i mosen", "sourceType": "PASTED",
        })
        self.assertEqual(create_status, 201)
        text_id = created["data"]["text"]["id"]
        queued_status, queued = self.request("POST", f"/api/language/texts/{text_id}/analyze", {})
        self.assertEqual(queued_status, 202)
        self.assertEqual(self.wait_for_api_job(queued["data"]["job"]["id"])["state"], "COMPLETED")
        with self.store.connection() as connection:
            before = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("knowledge_events", "exposure_events", "anki_note_links", "cloze_attempts", "topic_lemmas")
            }
        profile_status, profile = self.request(
            "GET", f"/api/language/texts/{text_id}/reference-profile"
        )
        self.assertEqual(profile_status, 200)
        reference_profile = profile["data"]["referenceProfile"]
        self.assertTrue(reference_profile["available"])
        self.assertEqual(reference_profile["mweOccurrences"], 1)
        self.assertEqual(reference_profile["expressions"][0]["surfaceText"], "ugler i mosen")
        text_status, text = self.request("GET", f"/api/language/texts/{text_id}")
        self.assertEqual(text_status, 200)
        self.assertEqual(text["data"]["coverage"]["policyVersion"], "language.coverage-policy/v1")
        self.assertEqual(text["data"]["referenceProfile"]["profileVersion"], "language.reference-text-profile/v1")
        with self.store.connection() as connection:
            after = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

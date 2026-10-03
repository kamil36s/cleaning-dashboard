import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from language_learning import LanguageService, LanguageStore
from language_learning.jobs import LanguageJobManager
from language_learning.cloze_audio import ClozeAudioService, DEFAULT_TTS_VOICE
from language_learning.generated_audio import GeneratedTextAudioService
from language_learning.schemas import text_fingerprint
from language_learning.word_audio import WordAudioService
import server


class FakeProvider:
    def __init__(self):
        self.calls = []

    def synthesize(self, **payload):
        self.calls.append(payload)
        return b"ID3" + b"\x00" * 64


class WordAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = LanguageStore(root / "language.sqlite")
        self.language = LanguageService(self.store)
        self.language.initialize()
        self.profile = self.language.ensure_bokmal_profile()["profile"]
        self.provider = FakeProvider()
        cache = ClozeAudioService(self.store, root / "audio", provider=self.provider,
                                  environment={"NORWEGIAN_TTS_VOICE": DEFAULT_TTS_VOICE})
        self.audio = WordAudioService(self.store, cache)
        self.language.attach_word_audio_service(self.audio)
        self.language.attach_generated_audio_service(GeneratedTextAudioService(self.store, cache))
        self.lemma = self.store.upsert_lemma({
            "language_profile_id": self.profile["id"], "lemma_display": "plan",
            "lemma_normalized": "plan", "canonical_key": "plan|NOUN",
            "part_of_speech": "NOUN",
        })[0]
        self.other = self.store.upsert_lemma({
            "language_profile_id": self.profile["id"], "lemma_display": "hus",
            "lemma_normalized": "hus", "canonical_key": "hus|NOUN",
            "part_of_speech": "NOUN",
        })[0]
        self.text_id = "a" * 32
        self.token_id = "b" * 32
        raw = "plan hus ny"
        with self.store.connection() as connection:
            connection.execute("UPDATE lemma_knowledge SET knowledge_status='KNOWN' WHERE lemma_id=?", (self.other["id"],))
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,"
                "content_fingerprint,processing_state,offset_unit,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self.text_id, self.profile["id"], "Text", raw, "PASTED", text_fingerprint(raw),
                 "ANALYZED", "UNICODE_CODE_POINT", "now", "now"),
            )
            for index, (surface, lemma_id) in enumerate((("plan", self.lemma["id"]), ("hus", self.other["id"]), ("ny", None))):
                connection.execute(
                    "INSERT INTO text_tokens(id,language_profile_id,text_document_id,token_order,surface,"
                    "source_start,source_end,offset_unit,token_kind,selected_lemma_id,ambiguity_state,lexical_status) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (self.token_id if index == 2 else f"{index + 1:032x}", self.profile["id"], self.text_id,
                     index, surface, index * 4, index * 4 + len(surface), "UNICODE_CODE_POINT", "WORD",
                     lemma_id, "NOT_REPORTED", "NOT_ASSESSED"),
                )

    def tearDown(self):
        self.temp.cleanup()

    def test_backfill_deduplicates_vocabulary_and_new_text_words_and_prioritizes_clicked_word(self):
        self.assertEqual(self.audio.enqueue_all(), 3)
        self.assertEqual(self.audio.enqueue_all(), 0)
        clicked = self.audio.status(lemma_id=self.lemma["id"], retry=True)
        self.assertEqual(clicked["state"], "QUEUED")
        self.assertEqual(self.store.claim_next_word_audio_job()["word_text"], "plan")
        token = self.audio.status(token_id=self.token_id)
        self.assertEqual(token["word"], "ny")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM word_audio_jobs").fetchone()[0], 3)

    def test_worker_generates_single_word_once_and_serves_cached_audio(self):
        self.audio.enqueue_all()
        self.audio.status(lemma_id=self.lemma["id"], retry=True)
        job = self.store.claim_next_word_audio_job()
        self.audio.process(job)
        self.assertEqual(self.provider.calls[0]["text"], job["word_text"])
        self.assertEqual(self.provider.calls[0]["language_code"], "nb-NO")
        status = self.audio.status(lemma_id=self.lemma["id"])
        self.assertEqual(status["state"], "READY")
        self.assertTrue(status["audioUrl"].endswith(".mp3"))
        cache_key = status["audioUrl"].rsplit("/", 1)[1].removesuffix(".mp3")
        self.assertTrue(self.audio.sentence_audio.audio_file(cache_key)[0].is_file())
        self.assertEqual(self.audio.enqueue_all(), 0)

    def test_interrupted_job_recovers_and_failed_job_can_be_retried(self):
        self.audio.enqueue_all()
        self.audio.status(lemma_id=self.lemma["id"], retry=True)
        job = self.store.claim_next_word_audio_job()
        self.assertEqual(self.store.recover_word_audio_jobs(), 1)
        job = self.store.claim_next_word_audio_job()
        self.store.finish_word_audio_job(job["cache_key"], error_code="test_provider_error")
        source = self.lemma["id"]
        self.assertEqual(self.audio.status(lemma_id=source)["state"], "FAILED")
        self.assertEqual(self.audio.status(lemma_id=source, retry=True)["state"], "QUEUED")

    def test_http_word_audio_status_retry_and_cached_stream(self):
        previous = server.LANGUAGE_SERVICE
        server.LANGUAGE_SERVICE = self.language
        httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def request(method, path, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            headers = {} if body is None else {"Content-Type": "application/json"}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result

        try:
            path = f"/api/language/lemmas/{self.lemma['id']}/audio"
            status, body = request("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["data"]["state"], "QUEUED")
            status, body = request("POST", path, {})
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(body)["data"]["word"], "plan")
            self.audio.process(self.store.claim_next_word_audio_job())
            status, body = request("GET", path)
            self.assertEqual(status, 200)
            audio_url = json.loads(body)["data"]["audioUrl"]
            status, body = request("GET", audio_url)
            self.assertEqual(status, 200)
            self.assertTrue(body.startswith(b"ID3"))
            status, body = request("GET", f"/api/language/tokens/{self.token_id}/audio")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["data"]["word"], "ny")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            server.LANGUAGE_SERVICE = previous

    def test_worker_backfills_existing_words_on_start(self):
        manager = LanguageJobManager(self.language, poll_interval=0.02)
        try:
            manager.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with self.store.connection() as connection:
                    ready = connection.execute("SELECT COUNT(*) FROM word_audio_jobs WHERE state='READY'").fetchone()[0]
                if ready == 3:
                    break
                time.sleep(0.02)
            self.assertEqual(ready, 3)
            self.assertEqual(len(self.provider.calls), 3)
        finally:
            manager.stop()

    def test_new_vocabulary_word_enters_queue_without_restart(self):
        created = self.language.upsert_lemma(self.profile["id"], "bok", part_of_speech="NOUN")
        status = self.audio.status(lemma_id=created["lemma"]["id"])
        self.assertEqual(status["state"], "QUEUED")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM word_audio_jobs").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

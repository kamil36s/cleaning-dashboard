import http.client
import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import server
from language_learning import LanguageService, LanguageStore
from language_learning.cloze import ClozeService
from language_learning.cloze_audio import (
    GOOGLE_TTS_ENDPOINT,
    ClozeAudioError,
    ClozeAudioService,
    DEFAULT_TTS_VOICE,
    GoogleCloudChirpProvider,
)
from language_learning.generated_audio import GeneratedTextAudioService
from language_learning.errors import LanguageConflictError, LanguageValidationError
from language_learning.schemas import text_fingerprint
from tests.test_language_cloze import build_reference


class FakeProvider:
    def __init__(self, *, failure=None, delay=0):
        self.failure = failure
        self.delay = delay
        self.calls = []
        self._guard = threading.Lock()

    def synthesize(self, **payload):
        with self._guard:
            self.calls.append(payload)
        if self.delay:
            time.sleep(self.delay)
        if self.failure:
            raise self.failure
        return b"ID3" + (b"\x00" * 128)


class FakeGoogleResponse:
    ok = True
    status_code = 200

    def json(self):
        return {"audioContent": base64.b64encode(b"ID3" + (b"\x00" * 32)).decode("ascii")}


class FakeAuthorizedSession:
    def __init__(self, credentials):
        self.credentials = credentials
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeGoogleResponse()

    def close(self):
        self.closed = True


class ClozeSentenceAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.reference, _, _ = build_reference(root, 60)
        self.store = LanguageStore(root / "language.sqlite")
        self.language = LanguageService(self.store)
        self.language.initialize()
        self.profile = self.language.ensure_bokmal_profile()["profile"]
        self.cloze = ClozeService(self.language, self.reference.database_path)
        self.language.attach_cloze_service(self.cloze)
        self.started = self.language.start_cloze_session(self.profile["id"], {
            "trackKey": "FAST_TRACK_1", "itemCount": 10, "seed": "audio-fixture",
        })["data"]["session"]
        self.item = self.started["currentItem"]
        self.audio_root = root / "audio"

    def tearDown(self):
        self.temp.cleanup()

    def payload(self):
        return {"itemIndex": self.item["index"], "itemFingerprint": self.item["fingerprint"]}

    def service(self, provider):
        return ClozeAudioService(
            self.store, self.audio_root, provider=provider,
            environment={"NORWEGIAN_TTS_VOICE": DEFAULT_TTS_VOICE},
        )

    def generated_sentence(self, sentence_text, *, source_type="GENERATED_GEMINI", suffix="1"):
        text_id = ("a" * 31) + suffix
        sentence_id = ("b" * 31) + suffix
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,"
                "content_fingerprint,processing_state,offset_unit,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "Generated", sentence_text, source_type,
                 text_fingerprint(sentence_text), "ANALYZED", "UNICODE_CODE_POINT", "now", "now"),
            )
            connection.execute(
                "INSERT INTO text_sentences(id,text_document_id,sentence_order,source_start,source_end,"
                "offset_unit,exact_text,fingerprint) VALUES(?,?,?,?,?,?,?,?)",
                (sentence_id, text_id, 0, 0, len(sentence_text), "UNICODE_CODE_POINT",
                 sentence_text, text_fingerprint(sentence_text)),
            )
        return text_id, sentence_id

    def test_google_adapter_posts_expected_chirp_request_without_exposing_credentials(self):
        sessions = []

        def load_credentials(**kwargs):
            self.assertEqual(kwargs["quota_project_id"], "fixture-project")
            return object(), "fixture-project"

        def make_session(credentials):
            session = FakeAuthorizedSession(credentials)
            sessions.append(session)
            return session

        provider = GoogleCloudChirpProvider(
            environment={"GOOGLE_CLOUD_PROJECT": "fixture-project"},
            credentials_loader=load_credentials,
            session_factory=make_session,
        )
        audio = provider.synthesize(
            text="Han kan svømme på ryggen.",
            language_code="nb-NO",
            voice_id=DEFAULT_TTS_VOICE,
            audio_encoding="MP3",
        )

        self.assertTrue(audio.startswith(b"ID3"))
        self.assertTrue(sessions[0].closed)
        url, request = sessions[0].calls[0]
        self.assertEqual(url, GOOGLE_TTS_ENDPOINT)
        self.assertEqual(request["timeout"], 45)
        self.assertEqual(request["json"], {
            "input": {"text": "Han kan svømme på ryggen."},
            "voice": {"languageCode": "nb-NO", "name": DEFAULT_TTS_VOICE},
            "audioConfig": {"audioEncoding": "MP3"},
        })

    def test_cache_miss_sends_full_sentence_saves_file_and_second_request_is_a_hit(self):
        provider = FakeProvider()
        audio = self.service(provider)
        first = audio.generate(self.started["id"], self.payload())
        second = audio.generate(self.started["id"], self.payload())

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["audioUrl"], second["audioUrl"])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["text"], self.item["sentenceText"])
        self.assertEqual(provider.calls[0]["language_code"], "nb-NO")
        self.assertEqual(provider.calls[0]["voice_id"], DEFAULT_TTS_VOICE)
        missing_surface = self.item["sentenceText"][self.item["blankStart"]:self.item["blankEnd"]]
        self.assertTrue(missing_surface)
        self.assertIn(missing_surface, provider.calls[0]["text"])
        self.assertNotIn("___", provider.calls[0]["text"])

        cache_key = first["audioUrl"].rsplit("/", 1)[1].removesuffix(".mp3")
        metadata = self.store.get_cloze_sentence_audio(cache_key)
        self.assertEqual(metadata["sentence_text"], self.item["sentenceText"])
        self.assertEqual(metadata["reference_sentence_id"], self.item["source"]["sentenceId"])
        self.assertEqual(metadata["text_hash"], audio._text_hash(self.item["sentenceText"]))
        self.assertTrue((self.audio_root / metadata["audio_path"]).is_file())

        never_call = FakeProvider(failure=AssertionError("provider should not be called"))
        cache_reader = self.service(never_call)
        third = cache_reader.generate(self.started["id"], self.payload())
        self.assertTrue(third["cached"])
        self.assertEqual(never_call.calls, [])

    def test_missing_cached_file_is_regenerated(self):
        first_provider = FakeProvider()
        audio = self.service(first_provider)
        result = audio.generate(self.started["id"], self.payload())
        cache_key = result["audioUrl"].rsplit("/", 1)[1].removesuffix(".mp3")
        metadata = self.store.get_cloze_sentence_audio(cache_key)
        (self.audio_root / metadata["audio_path"]).unlink()

        second_provider = FakeProvider()
        regenerated = self.service(second_provider).generate(self.started["id"], self.payload())
        self.assertFalse(regenerated["cached"])
        self.assertEqual(len(second_provider.calls), 1)
        self.assertTrue((self.audio_root / metadata["audio_path"]).is_file())

    def test_provider_failure_does_not_damage_the_cloze_session(self):
        failure = ClozeAudioError("fixture failure", code="fixture_tts_failure", status=502)
        audio = self.service(FakeProvider(failure=failure))
        with self.assertRaises(ClozeAudioError) as caught:
            audio.generate(self.started["id"], self.payload())
        self.assertEqual(caught.exception.code, "fixture_tts_failure")
        self.assertEqual(self.cloze.get_session(self.started["id"])["session"]["id"], self.started["id"])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cloze_sentence_audio").fetchone()[0], 0)

    def test_simultaneous_requests_generate_only_once(self):
        provider = FakeProvider(delay=0.1)
        audio = self.service(provider)
        results = []
        errors = []

        def run():
            try:
                results.append(audio.generate(self.started["id"], self.payload()))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(sorted(item["cached"] for item in results), [False, True])

    def test_generated_reader_audio_uses_authoritative_sentence_and_cache(self):
        provider = FakeProvider()
        shared = self.service(provider)
        generated = GeneratedTextAudioService(self.store, shared)
        text_id, sentence_id = self.generated_sentence("Jeg har en jobb.")
        first = generated.generate(text_id, sentence_id, {})
        second = generated.generate(text_id, sentence_id, {})
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["text"], "Jeg har en jobb.")
        self.assertTrue(first["audioUrl"].startswith("/api/language/audio/"))
        with self.store.connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM generated_text_sentence_audio WHERE text_document_id=?",
                (text_id,),
            ).fetchone()[0], 1)

    def test_generated_audio_rejects_arbitrary_text_and_non_generated_documents(self):
        generated = GeneratedTextAudioService(self.store, self.service(FakeProvider()))
        text_id, sentence_id = self.generated_sentence("Ikke tillatt.", source_type="PASTED", suffix="2")
        with self.assertRaises(LanguageValidationError):
            generated.generate(text_id, sentence_id, {"text": "synthesize this instead"})
        with self.assertRaises(LanguageConflictError):
            generated.generate(text_id, sentence_id, {})

    def test_generated_audio_reuses_identical_existing_cloze_cache(self):
        provider = FakeProvider()
        shared = self.service(provider)
        cloze_result = shared.generate(self.started["id"], self.payload())
        text_id, sentence_id = self.generated_sentence(self.item["sentenceText"], suffix="3")
        generated_result = GeneratedTextAudioService(self.store, shared).generate(text_id, sentence_id, {})
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(generated_result["cached"])
        self.assertEqual(cloze_result["cacheKey"], generated_result["cacheKey"])

    def test_generated_audio_failure_preserves_reader_text_and_creates_no_link(self):
        failure = ClozeAudioError("fixture failure", code="fixture_tts_failure", status=502)
        generated = GeneratedTextAudioService(self.store, self.service(FakeProvider(failure=failure)))
        text_id, sentence_id = self.generated_sentence("Teksten består.", suffix="4")
        with self.assertRaises(ClozeAudioError):
            generated.generate(text_id, sentence_id, {})
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT raw_text FROM text_documents WHERE id=?", (text_id,)).fetchone()[0], "Teksten består.")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_text_sentence_audio").fetchone()[0], 0)

    def test_http_generation_route_and_local_audio_stream(self):
        provider = FakeProvider()
        audio = self.service(provider)
        self.language.attach_cloze_audio_service(audio)
        self.language.attach_generated_audio_service(GeneratedTextAudioService(self.store, audio))
        generated_text_id, generated_sentence_id = self.generated_sentence("Jeg arbeider hjemme.", suffix="5")
        previous_service = server.LANGUAGE_SERVICE
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
            result = response.status, dict(response.headers), response.read()
            connection.close()
            return result

        try:
            status, _, raw = request(
                "POST",
                f"/api/language/cloze/sessions/{self.started['id']}/items/{self.item['index']}/audio",
                {"itemFingerprint": self.item["fingerprint"]},
            )
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertFalse(payload["data"]["cached"])
            status, headers, raw = request("GET", payload["data"]["audioUrl"])
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "audio/mpeg")
            self.assertEqual(raw, b"ID3" + (b"\x00" * 128))
            status, _, raw = request(
                "POST",
                f"/api/language/texts/{generated_text_id}/sentences/{generated_sentence_id}/audio",
                {},
            )
            generated_payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertTrue(generated_payload["data"]["audioUrl"].startswith("/api/language/audio/"))
            status, headers, raw = request("GET", generated_payload["data"]["audioUrl"])
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "audio/mpeg")
            self.assertEqual(raw, b"ID3" + (b"\x00" * 128))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server.LANGUAGE_SERVICE = previous_service


if __name__ == "__main__":
    unittest.main()

"""Representative Phase 12 HTTP boundaries over the existing test server."""

import http.client
import os
import unittest
from unittest import mock

from tests import test_language_api
from server import is_protected_static_path


class LanguagePhase12SecurityTests(unittest.TestCase):
    setUp = test_language_api.LanguageApiTests.setUp
    tearDown = test_language_api.LanguageApiTests.tearDown
    request = test_language_api.LanguageApiTests.request

    def test_mature_write_routes_reject_foreign_origin_before_payload(self):
        profile = self.profile["id"]
        id_ = "0" * 32
        routes = [
            ("POST", "/api/language/lemmas/merge"),
            ("POST", f"/api/language/texts/{id_}/analyze"),
            ("POST", f"/api/language/profiles/{profile}/cloze/sessions"),
            ("POST", f"/api/language/texts/{id_}/listening-sessions"),
            ("POST", f"/api/language/profiles/{profile}/content/audio"),
            ("POST", f"/api/language/profiles/{profile}/benchmarks"),
            ("POST", f"/api/language/profiles/{profile}/anki/pull"),
            ("POST", "/api/language/backup"),
            ("PATCH", f"/api/language/grammar/occurrences/{id_}/review"),
        ]
        for method, route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.request(method, route, {},
                    headers={"Origin": "https://foreign.example"})[0], 403)

    def test_private_files_are_denied_by_python_static_handler(self):
        routes = [
            "/data/language-learning.sqlite",
            "/data/language-learning.sqlite-wal",
            "/data/language-learning/media/owned.wav",
            "/data/audio/language-learning/nb/cloze/cached.mp3",
            "/data/reference/language-reference-nb.sqlite",
            "/data/reference/sources/private.tsv",
            "/data/backups/language-package/manifest.json",
            "/language_learning/benchmark_content/v1.json",
            "/language_learning/service.py",
            "/.env.production",
        ]
        for route in routes:
            with self.subTest(route=route):
                self.assertTrue(is_protected_static_path(route))
                connection = http.client.HTTPConnection("127.0.0.1", self.port)
                connection.request("GET", route)
                response = connection.getresponse()
                response.read()
                connection.close()
                self.assertEqual(response.status, 404)

    def test_provider_secrets_are_absent_from_health_and_export(self):
        sentinel = "PHASE12_PRIVATE_SENTINEL"
        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": sentinel,
            "LANGUAGE_ANKI_CONNECT_API_KEY": sentinel,
            "GOOGLE_APPLICATION_CREDENTIALS": sentinel,
        }):
            for route in ("/api/language/health", "/api/language/export"):
                with self.subTest(route=route):
                    status, body = self.request("GET", route)
                    self.assertEqual(status, 200)
                    self.assertNotIn(sentinel, str(body))


if __name__ == "__main__":
    unittest.main()

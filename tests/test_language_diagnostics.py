from __future__ import annotations

import json
import unittest
from unittest import mock

from scripts.diagnose_language_env import anki_status


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._payload


class LanguageDiagnosticTests(unittest.TestCase):
    def test_anki_probe_uses_only_read_only_version_action(self) -> None:
        with mock.patch(
            "scripts.diagnose_language_env.request.urlopen",
            return_value=_FakeResponse({"result": 6, "error": None}),
        ) as opener:
            status = anki_status("http://127.0.0.1:8765", "secret-test-key")

        sent_request = opener.call_args.args[0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual({"action", "version", "key"}, set(payload))
        self.assertEqual("version", payload["action"])
        self.assertNotIn("secret-test-key", json.dumps(status))
        self.assertTrue(status["reachable"])
        self.assertEqual(6, status["apiVersion"])

    def test_anki_probe_rejects_non_loopback_url_without_request(self) -> None:
        with mock.patch("scripts.diagnose_language_env.request.urlopen") as opener:
            status = anki_status("https://example.com/anki", None)
        opener.assert_not_called()
        self.assertFalse(status["reachable"])
        self.assertIn("loopback", status["error"])


if __name__ == "__main__":
    unittest.main()

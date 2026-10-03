import io
import json
import socket
import unittest
import urllib.error

from language_learning.providers.anki import (
    AnkiAdapter,
    AnkiAdapterError,
    AnkiTimeoutError,
    AnkiUnavailableError,
    validate_local_endpoint,
)


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return Response(outcome)


def envelope(result=None, error=None):
    return json.dumps({"result": result, "error": error}).encode()


class AnkiProviderTests(unittest.TestCase):
    def test_endpoint_allowlist_accepts_loopback_only(self):
        self.assertEqual(validate_local_endpoint("http://127.0.0.1:8765/"), "http://127.0.0.1:8765")
        self.assertEqual(validate_local_endpoint("http://[::1]:8765"), "http://[::1]:8765")
        for value in ("https://127.0.0.1:8765", "http://localhost:8765", "http://example.com:8765", "file:///tmp/a"):
            with self.assertRaises(ValueError, msg=value):
                validate_local_endpoint(value)

    def test_capability_and_discovery_validate_results_and_send_key_server_side(self):
        opener = Opener([envelope(6), envelope(["Deck"]), envelope(["Model"]), envelope(["Front", "Back"])])
        adapter = AnkiAdapter(api_key="secret", opener=opener)
        self.assertTrue(adapter.capabilities().api()["supported"])
        self.assertEqual(adapter.deck_names(), ["Deck"])
        self.assertEqual(adapter.model_names(), ["Model"])
        self.assertEqual(adapter.model_field_names("Model"), ["Front", "Back"])
        sent = json.loads(opener.requests[0][0].data)
        self.assertEqual(sent["key"], "secret")

    def test_empty_deck_has_zero_counts(self):
        adapter = AnkiAdapter(opener=Opener([envelope({})]))
        self.assertEqual(adapter.deck_stats("Default"), {"new": 0, "learn": 0, "due": 0})

    def test_connection_refused_timeout_and_http_404_are_normalized(self):
        refused = AnkiAdapter(opener=Opener([urllib.error.URLError("refused")]))
        with self.assertRaises(AnkiUnavailableError):
            refused.capabilities()
        timed = AnkiAdapter(opener=Opener([socket.timeout()]))
        with self.assertRaises(AnkiTimeoutError):
            timed.capabilities()
        http = AnkiAdapter(opener=Opener([
            urllib.error.HTTPError("http://127.0.0.1:8765", 404, "not found", {}, io.BytesIO())
        ]))
        with self.assertRaises(AnkiAdapterError) as caught:
            http.capabilities()
        self.assertEqual(caught.exception.state, "HTTP_ERROR")

    def test_invalid_json_shape_and_api_key_rejection_are_safe(self):
        for body in (b"not json", json.dumps({"value": 6}).encode()):
            with self.assertRaises(AnkiAdapterError) as caught:
                AnkiAdapter(opener=Opener([body])).capabilities()
            self.assertEqual(caught.exception.code, "anki_invalid_response")
        with self.assertRaises(AnkiAdapterError) as caught:
            AnkiAdapter(opener=Opener([envelope(None, "API key invalid")])).capabilities()
        self.assertEqual(caught.exception.code, "anki_api_key_rejected")

    def test_adapter_exposes_no_destructive_or_scheduling_action(self):
        adapter = AnkiAdapter(opener=Opener([]))
        for action in ("deleteNotes", "changeDeck", "setDueDate"):
            with self.assertRaises(AnkiAdapterError) as caught:
                adapter.invoke(action)
            self.assertEqual(caught.exception.code, "anki_action_unsupported")


if __name__ == "__main__":
    unittest.main()

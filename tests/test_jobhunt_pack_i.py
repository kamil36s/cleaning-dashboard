from email import policy
from email.parser import BytesParser
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntError, JobhuntService, JobhuntWorker
from jobhunt_backend.migrations import SCHEMA_VERSION
from jobhunt_backend.sources.email_transport import ImapMailboxTransport, MailTransportError
from jobhunt_backend.sources.pracuj import (
    MAX_MESSAGE_BYTES,
    MAX_PARTS,
    PRACUJ_PARSER_VERSION,
    PracujJobAlertAdapter,
    normalize_pracuj_url,
)
from tests.test_jobhunt_pack_g import FakeNavAdapter, feed_item


FIXTURES = Path(__file__).parent / "fixtures" / "jobhunt"


class FakeMailboxSession:
    def __init__(self, messages, *, uidvalidity="77"):
        self.messages = messages
        self.uidvalidity = uidvalidity
        self.searches = []
        self.header_fetches = []
        self.message_fetches = []

    def search_uids(self, *, after_uid, since, maximum):
        self.searches.append({"after_uid": after_uid, "since": since, "maximum": maximum})
        return [uid for uid in sorted(self.messages) if uid > after_uid][:maximum]

    def fetch_headers(self, uid):
        self.header_fetches.append(uid)
        message = BytesParser(policy=policy.default).parsebytes(self.messages[uid], headersonly=True)
        return {key: str(message.get(key) or "") for key in (
            "From", "Return-Path", "Message-ID", "Subject", "Date", "Authentication-Results"
        )}

    def fetch_message(self, uid, *, maximum_bytes):
        self.message_fetches.append(uid)
        raw = self.messages[uid]
        if len(raw) > maximum_bytes:
            raise MailTransportError("message too large", classification="malformed_message")
        return raw


class FakeMailboxTransport:
    configured = True
    mailbox = "Job Hunt/Pracuj"

    def __init__(self, messages, *, uidvalidity="77"):
        self.session = FakeMailboxSession(messages, uidvalidity=uidvalidity)

    def safe_config(self):
        return {
            "configured": True,
            "host": "imap.example.test",
            "port": 993,
            "usernameConfigured": True,
            "mailbox": self.mailbox,
            "tls": True,
        }

    class _Context:
        def __init__(self, session):
            self.session = session

        def __enter__(self):
            return self.session

        def __exit__(self, *args):
            return False

    def open(self):
        return self._Context(self.session)


class JobhuntPackIParserTests(unittest.TestCase):
    def fixture(self, name):
        return (FIXTURES / name).read_bytes()

    def test_plain_html_multipart_and_missing_message_id(self):
        expected = {
            "pack-i-plain.eml": ("QA Engineer", "ACME Polska", "Krakow, Poland"),
            "pack-i-html.eml": ("Python Developer", "Example Labs", "Warszawa"),
            "pack-i-multipart.eml": ("DevOps Engineer", "Infra Example", "Gdansk"),
            "pack-i-missing-message-id.eml": ("Test Engineer", "Missing ID Example", "Lodz"),
        }
        for name, fields in expected.items():
            with self.subTest(name=name):
                parsed = PracujJobAlertAdapter.parse(self.fixture(name))
                self.assertTrue(parsed.recognized)
                self.assertEqual((parsed.items[0].title, parsed.items[0].company, parsed.items[0].location), fields)
                self.assertNotIn("utm_", parsed.items[0].url)
                self.assertNotIn("fbclid", parsed.items[0].url)

    def test_sender_recognition_is_conservative(self):
        for name in ("pack-i-unrelated.eml", "pack-i-spoofed.eml"):
            with self.subTest(name=name):
                self.assertFalse(PracujJobAlertAdapter.parse(self.fixture(name)).recognized)

    def test_transfer_encodings_and_multiple_jobs(self):
        quoted = PracujJobAlertAdapter.parse(self.fixture("pack-i-quoted-printable.eml"))
        encoded = PracujJobAlertAdapter.parse(self.fixture("pack-i-base64.eml"))
        multiple = PracujJobAlertAdapter.parse(self.fixture("pack-i-multiple.eml"))
        self.assertTrue(quoted.recognized)
        self.assertEqual(quoted.items[0].title, "Inżynier Testów")
        self.assertTrue(encoded.recognized)
        self.assertEqual(encoded.items[0].title, "Base64 Engineer")
        self.assertEqual([item.title for item in multiple.items], ["First Engineer", "Second Engineer"])

    def test_bounds_and_url_normalization(self):
        with self.assertRaises(MailTransportError) as caught:
            PracujJobAlertAdapter.parse(b"x" * (MAX_MESSAGE_BYTES + 1))
        self.assertEqual(caught.exception.classification, "malformed_message")
        many_parts = [
            "From: alert@pracuj.pl", "Return-Path: <bounce@pracuj.pl>",
            "Message-ID: <many@pracuj.pl>", "Subject: JobAlert - many parts",
            "MIME-Version: 1.0", 'Content-Type: multipart/mixed; boundary="many"', "",
        ]
        for _ in range(MAX_PARTS + 1):
            many_parts.extend(["--many", "Content-Type: text/plain", "", "JobAlert"])
        many_parts.append("--many--")
        with self.assertRaises(MailTransportError) as multipart_error:
            PracujJobAlertAdapter.parse("\r\n".join(many_parts).encode())
        self.assertEqual(multipart_error.exception.classification, "malformed_message")
        self.assertEqual(
            normalize_pracuj_url(
                "http://www.pracuj.pl/praca/test,offer-123?utm_source=x&ref=kept#fragment"
            ),
            "https://www.pracuj.pl/praca/test,offer-123?ref=kept",
        )
        self.assertIsNone(normalize_pracuj_url("https://example.test/praca/test,offer-123"))

    def test_imap_transport_uses_verified_tls_readonly_select_and_peek_only(self):
        raw = self.fixture("pack-i-plain.eml")

        class Client:
            def __init__(self, *args, **kwargs):
                self.init = (args, kwargs)
                self.calls = []

            def login(self, username, password):
                self.calls.append(("LOGIN", username, password))
                return "OK", []

            def select(self, mailbox, readonly=False):
                self.calls.append(("SELECT", mailbox, readonly))
                return "OK", [b"1"]

            def response(self, name):
                self.calls.append(("RESPONSE", name))
                return "UIDVALIDITY", [b"123"]

            def uid(self, command, *args):
                self.calls.append(("UID", command, *args))
                if command == "SEARCH":
                    return "OK", [b"9"]
                return "OK", [(b"9 FETCH", raw)]

            def logout(self):
                self.calls.append(("LOGOUT",))

        created = []

        def factory(*args, **kwargs):
            client = Client(*args, **kwargs)
            created.append(client)
            return client

        transport = ImapMailboxTransport(environment={
            "JOBHUNT_PRACUJ_IMAP_HOST": "imap.example.test",
            "JOBHUNT_PRACUJ_IMAP_USER": "reader",
            "JOBHUNT_PRACUJ_IMAP_PASSWORD": "secret",
            "JOBHUNT_PRACUJ_MAILBOX": "Alerts",
        }, client_factory=factory)
        with transport.open() as session:
            self.assertEqual(session.search_uids(after_uid=8), [9])
            session.fetch_headers(9)
            self.assertEqual(session.fetch_message(9, maximum_bytes=MAX_MESSAGE_BYTES), raw)
        calls = created[0].calls
        self.assertIn(("SELECT", "Alerts", True), calls)
        wire = repr(calls)
        self.assertIn("BODY.PEEK", wire)
        self.assertNotIn("STORE", wire)
        self.assertNotIn("EXPUNGE", wire)
        self.assertNotIn("secret", str(transport.safe_config()))


class JobhuntPackIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        messages = {
            10: (FIXTURES / "pack-i-unrelated.eml").read_bytes(),
            11: (FIXTURES / "pack-i-spoofed.eml").read_bytes(),
            12: (FIXTURES / "pack-i-plain.eml").read_bytes(),
        }
        self.transport = FakeMailboxTransport(messages)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite",
            private_root=self.root / "private",
            environment={},
            mail_transport=self.transport,
        )
        self.service.initialize()
        self.worker = JobhuntWorker(self.service)

    def tearDown(self):
        self.worker.stop(timeout=1)
        self.temp.cleanup()

    def _run_ready(self, maximum=20):
        completed = []
        for _ in range(maximum):
            item = self.worker.run_once()
            if item is None:
                break
            completed.append(item)
        return completed

    def test_schema_source_and_full_mail_to_job_pipeline(self):
        self.assertEqual(SCHEMA_VERSION, 13)
        self.assertEqual(self.service.store.schema_status()["version"], 13)
        status = self.service.pracuj_status()["data"]
        self.assertEqual(status["source"]["policy"]["accessMethod"], "official_email_alert")
        self.assertFalse(status["source"]["policy"]["enabled"])
        self.assertNotIn("password", str(status).casefold())

        track = self.service.get_track("track_seed_norway_qa")["data"]["track"]
        profile = self.service.create_search_profile(track["id"], {
            "name": "QA Pracuj alert",
            "includeKeywords": ["QA", "testing"],
            "countries": ["Poland"],
            "regionsCities": ["Krakow"],
            "plannedSourceKeys": ["pracuj"],
        })["data"]["searchProfile"]
        binding = self.service.create_pracuj_binding({
            "subjectMatcher": "QA Krakow",
            "searchProfileId": profile["id"],
            "enabled": True,
        })["data"]["binding"]
        self.assertEqual(binding["searchProfileId"], profile["id"])

        enabled = self.service.pracuj_enable()["data"]
        self.assertTrue(enabled["source"]["policy"]["enabled"])
        processed = self._run_ready()
        self.assertTrue(any(item["job_type"] == "pracuj_mail_poll" for item in processed))
        self.assertTrue(any(item["job_type"] == "pracuj_process_message" for item in processed))
        self.assertTrue(any(item["job_type"] == "extract_capture" for item in processed))

        self.assertEqual(self.transport.session.header_fetches, [10, 11, 12])
        # A plausible From/Subject pair advances to the bounded full-message
        # trust check; the spoof is rejected there and never archived.
        self.assertEqual(self.transport.session.message_fetches, [11, 12])
        self.assertIsNotNone(self.transport.session.searches[0]["since"])
        self.assertEqual(self.transport.session.searches[0]["maximum"], 500)
        listings = self.service.list_source_listings(source_id="source_pracuj")["data"]["listings"]
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing["hints"]["title"], "QA Engineer")
        self.assertEqual(listing["searchProfiles"][0]["id"], profile["id"])
        captures = self.service.get_source_listing(listing["id"])["data"]["captures"]
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0]["contentType"], "message/rfc822")
        self.assertEqual(captures[0]["inputMethod"], "pracuj_jobalert")
        preview = self.service.get_raw_capture(captures[0]["id"])["data"]
        self.assertEqual(preview["rendering"], "inert_text_only")
        self.assertNotIn("Return-Path", preview["content"])
        with self.assertRaises(JobhuntError) as ai_error:
            self.service.ai_extract_capture(captures[0]["id"], {})
        self.assertEqual(ai_error.exception.code, "ai_email_source_not_supported")

        jobs = self.service.list_jobs()["data"]["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"]["name"], "Pracuj.pl")
        runs = self.service.list_capture_extraction_runs(captures[0]["id"])["data"]["runs"]
        self.assertEqual(runs[0]["extractorVersion"], PRACUJ_PARSER_VERSION)

        state = self.service.pracuj_mail_state()["data"]["mailState"]
        self.assertEqual(state["messagesInspected"], 3)
        self.assertEqual(state["alertsRecognized"], 1)
        self.assertEqual(state["capturesCreated"], 1)

    def test_same_alert_repoll_is_idempotent_and_uidvalidity_reset_stops(self):
        self.service.pracuj_enable()
        self._run_ready()
        before = self.service.list_source_listings(source_id="source_pracuj")["data"]["listings"]
        self.service.pracuj_sync()
        self._run_ready()
        after = self.service.list_source_listings(source_id="source_pracuj")["data"]["listings"]
        self.assertEqual(len(before), len(after))
        self.assertEqual(before[0]["captureCount"], after[0]["captureCount"])

        self.transport.session.uidvalidity = "88"
        self.service.pracuj_sync()
        failure = self.worker.run_once()
        self.assertEqual(failure["state"], "failed")
        self.assertEqual(failure["error_class"], "uid_reset")
        state = self.service.pracuj_mail_state()["data"]["mailState"]
        self.assertEqual(state["lastErrorClass"], "uid_reset")

    def test_later_alert_for_same_offer_adds_capture_not_listing(self):
        self.service.pracuj_enable()
        self._run_ready()
        later = (FIXTURES / "pack-i-plain.eml").read_bytes().replace(
            b"<pack-i-plain@alerts.pracuj.pl>", b"<pack-i-later@alerts.pracuj.pl>"
        ).replace(b"08:00:00 +0200", b"09:00:00 +0200")
        self.transport.session.messages[13] = later
        self.service.pracuj_sync()
        self._run_ready()
        listings = self.service.list_source_listings(source_id="source_pracuj")["data"]["listings"]
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["captureCount"], 2)

    def test_changed_official_template_fails_visibly_without_archiving(self):
        service = JobhuntService(
            self.root / "malformed.sqlite", private_root=self.root / "malformed-private",
            environment={}, mail_transport=FakeMailboxTransport({
                5: (FIXTURES / "pack-i-malformed.eml").read_bytes(),
            }),
        )
        service.initialize()
        worker = JobhuntWorker(service)
        service.pracuj_enable()
        failed = worker.run_once()
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error_class"], "parser_failure")
        state = service.pracuj_mail_state()["data"]["mailState"]
        self.assertEqual(state["lastErrorClass"], "parser_failure")
        with service.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_email_messages").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_blobs").fetchone()[0], 0)
        worker.stop(timeout=1)

    def test_nav_and_pracuj_duplicate_is_reviewable_mergeable_and_reversible(self):
        nav = FakeNavAdapter()
        item = feed_item()
        item["_feed_entry"].update({"businessName": "ACME Polska", "municipal": "Krakow"})
        nav.queue_feed([item])
        nav.detail["json"]["employer"]["name"] = "ACME Polska"
        nav.detail["json"]["workLocations"] = [{"city": "Krakow", "country": "Poland"}]
        service = JobhuntService(
            self.root / "cross-source.sqlite",
            private_root=self.root / "cross-source-private",
            environment={}, nav_adapter=nav,
            mail_transport=FakeMailboxTransport({
                12: (FIXTURES / "pack-i-plain.eml").read_bytes(),
            }),
        )
        service.initialize()
        worker = JobhuntWorker(service)
        track = service.get_track("track_seed_qa_poland")["data"]["track"]
        profile = service.create_search_profile(track["id"], {
            "name": "Cross-source QA", "includeKeywords": ["QA"],
            "countries": ["Poland"], "regionsCities": ["Krakow"],
            "plannedSourceKeys": ["nav", "pracuj"],
        })["data"]["searchProfile"]
        service.create_pracuj_binding({
            "subjectMatcher": "QA Krakow", "searchProfileId": profile["id"], "enabled": True,
        })
        service.nav_enable()
        service.pracuj_enable()
        for _ in range(30):
            if worker.run_once() is None:
                break
        jobs = service.list_jobs()["data"]["jobs"]
        self.assertEqual(len(jobs), 2)
        # Refresh in the candidate's canonical orientation before the decision.
        first = service.list_duplicates()["data"]["items"][0]
        service.scan_job_for_duplicates(first["leftJob"]["id"])
        candidate = service.list_duplicates()["data"]["items"][0]
        detail = service.get_duplicate(candidate["id"])["data"]
        self.assertTrue(detail["evidenceCurrent"])
        self.assertTrue(detail["safety"]["safe"])
        with service.store.read_connection() as connection:
            before_captures = connection.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0]
            before_blobs = connection.execute("SELECT COUNT(*) FROM raw_blobs").fetchone()[0]
        merged = service.merge_duplicate(candidate["id"], {"confirm": True})["data"]["merge"]
        self.assertEqual(merged["state"], "active")
        self.assertEqual(service.list_jobs()["data"]["total"], 1)
        reverted = service.unmerge(merged["id"], {"note": "Pack I reversibility proof"})["data"]["merge"]
        self.assertEqual(reverted["state"], "reverted")
        self.assertEqual(service.list_jobs()["data"]["total"], 2)
        with service.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_captures").fetchone()[0], before_captures)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_blobs").fetchone()[0], before_blobs)
        worker.stop(timeout=1)


if __name__ == "__main__":
    unittest.main()

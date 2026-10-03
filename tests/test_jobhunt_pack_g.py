import io
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path

from jobhunt_backend import JobhuntService, JobhuntWorker
from jobhunt_backend.extraction.ai.prompt import prepare_source_text
from jobhunt_backend.extraction.ai import FakeAIExtractionProvider
from jobhunt_backend.migrations import SCHEMA_VERSION
from jobhunt_backend.sources.nav import (
    NAV_ADAPTER_VERSION,
    NavResponse,
    NavSourceAdapter,
    NavSourceError,
)


def nav_detail(*, description="Test APIs", status="ACTIVE"):
    return {
        "uuid": "vacancy-1",
        "status": status,
        "json": {
            "title": "QA Engineer",
            "description": description,
            "employer": {"name": "Example AS"},
            "workLocations": [{"city": "Oslo", "country": "Norway"}],
            "engagementtype": "Fast",
            "extent": "Heltid",
            "published": "2026-09-20T10:00:00Z",
            "expires": "2026-10-20T10:00:00Z",
            "applicationDue": "2026-10-19",
            "sourceurl": "https://arbeidsplassen.nav.no/stillinger/stilling/vacancy-1",
            "applicationUrl": "https://example.test/apply",
            "contactList": [{"name": "Private Person", "email": "private@example.test"}],
        },
    }


def feed_item(*, status="ACTIVE", modified="2026-09-20T10:00:00Z"):
    return {
        "id": f"entry-{modified}-{status}",
        "url": "/api/v1/feedentry/entry-1",
        "date_modified": modified,
        "_feed_entry": {
            "uuid": "vacancy-1", "status": status, "title": "QA Engineer",
            "businessName": "Example AS", "municipal": "Oslo", "sistEndret": modified,
        },
    }


class FakeNavAdapter:
    key = "fake-nav"
    version = NAV_ADAPTER_VERSION

    def __init__(self):
        self.token_configured = True
        self.feed_results = []
        self.detail = nav_detail()
        self.failure = None
        self.polled_states = []

    validate_path = staticmethod(NavSourceAdapter.validate_path)
    feed_header = staticmethod(NavSourceAdapter.feed_header)

    def queue_feed(self, items, *, next_path=None, not_modified=False):
        raw = json.dumps({"items": items}).encode()
        response = NavResponse(
            "feed", "/api/v1/feed", 304 if not_modified else 200,
            None if not_modified else {"items": items}, raw if not_modified is False else b"",
            '"feed-etag"', "Sun, 20 Sep 2026 10:00:00 GMT", 1.5,
        )
        self.feed_results.append({
            "not_modified": not_modified, "response": response, "items": items,
            "next_path": next_path, "page_id": "page-1", "next_id": None,
            "feed_version": "v1",
        })

    def poll_feed(self, state, policy):
        self.polled_states.append(dict(state))
        del policy
        if self.failure:
            raise self.failure
        if self.feed_results:
            return self.feed_results.pop(0)
        self.queue_feed([], not_modified=True)
        return self.feed_results.pop(0)

    def fetch_listing(self, identity, policy):
        del policy
        raw = json.dumps(self.detail, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return NavResponse(
            "detail", str(identity["detail_path"]), 200, self.detail, raw,
            '"detail-etag"', "Sun, 20 Sep 2026 10:00:00 GMT", 2.5,
        )


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self, limit):
        return self._raw[:limit]

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RecordingOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class JobhuntPackGTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.adapter = FakeNavAdapter()
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private",
            environment={}, nav_adapter=self.adapter,
        )
        self.service.initialize()
        self.worker = JobhuntWorker(self.service)

    def tearDown(self):
        self.worker.stop(timeout=1)
        self.temp.cleanup()

    def add_nav_profile(self):
        track = self.service.get_track("track_seed_norway_qa")["data"]["track"]
        profile = self.service.create_search_profile(track["id"], {
            "name": "QA in Oslo", "includeKeywords": ["QA", "testing"],
            "countries": ["Norway"], "regionsCities": ["Oslo"],
            "plannedSourceKeys": ["nav"],
        })["data"]["searchProfile"]
        return track, profile

    def test_schema_source_upgrade_and_explicit_enablement(self):
        self.assertEqual(self.service.store.schema_status()["version"], SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, 13)
        status = self.service.nav_status()["data"]
        self.assertTrue(status["source"]["adapter"]["implemented"])
        self.assertFalse(status["source"]["policy"]["enabled"])
        self.assertEqual(status["source"]["policy"]["operationalState"], "disabled")
        self.assertTrue(status["tokenConfigured"])
        with self.service.store.read_connection() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertTrue({"worker_jobs", "source_sync_state", "source_request_observations"}.issubset(tables))

    def test_worker_idempotency_transactional_claim_cancel_and_recovery(self):
        first, reused = self.worker.enqueue(
            job_type="extract_capture", payload={"captureId": "missing"},
            idempotency_key="same-key",
        )
        second, second_reused = self.worker.enqueue(
            job_type="extract_capture", payload={"captureId": "other"},
            idempotency_key="same-key",
        )
        self.assertFalse(reused)
        self.assertTrue(second_reused)
        self.assertEqual(first["id"], second["id"])

        claimed = []
        barrier = threading.Barrier(3)

        def claim(owner):
            barrier.wait()
            claimed.append(self.service.store.claim_worker_job(
                lease_owner=owner, lease_expires_at="2099-01-01T00:00:00+00:00",
                now="2098-09-23T10:00:00+00:00",
            ))

        threads = [threading.Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(item is not None for item in claimed), 1)

        with self.service.store.transaction() as connection:
            connection.execute(
                "UPDATE worker_jobs SET lease_expires_at=? WHERE id=?",
                ("2020-01-01T00:00:00+00:00", first["id"]),
            )
        recovery = self.service.store.recover_worker_jobs(now="2026-09-23T10:01:00+00:00")
        self.assertEqual(recovery["requeued"], 1)
        cancelled = self.worker.cancel(first["id"])
        self.assertEqual(cancelled["state"], "cancelled")

        running, _ = self.worker.enqueue(
            job_type="extract_capture", payload={"captureId": "another"},
            idempotency_key="running-cancel",
        )
        self.service.store.claim_worker_job(
            lease_owner=self.worker.owner, lease_expires_at="2099-01-01T00:00:00+00:00",
            now="2098-09-23T10:00:00+00:00",
        )
        requested = self.worker.cancel(running["id"])
        self.assertEqual(requested["state"], "running")
        self.assertTrue(requested["cancellation_requested"])

    def test_retry_persists_backoff_and_degraded_source_health(self):
        self.adapter.failure = NavSourceError(
            "rate limited", classification="rate_limit", retryable=True,
            retry_after_seconds=30, request_path="/api/v1/feed", status_code=429,
        )
        self.service.nav_enable()
        failed = self.worker.run_once()
        self.assertEqual(failed["state"], "retry_wait")
        self.assertEqual(failed["error_class"], "rate_limit")
        self.assertGreater(failed["next_attempt_at"], failed["updated_at"])
        status = self.service.nav_status()["data"]
        self.assertEqual(status["source"]["policy"]["operationalState"], "degraded")
        self.assertIsNotNone(status["source"]["policy"]["backoffUntil"])
        self.assertEqual(status["feedState"]["last_error_class"], "rate_limit")
        self.assertEqual(status["recentRequests"][0]["status_code"], 429)

    def test_conditional_headers_are_scoped_to_the_feed_page(self):
        self.adapter.queue_feed([], next_path="/api/v1/feed/page-2")
        self.adapter.queue_feed([])
        self.service.nav_enable()
        self.worker.run_once()
        self.worker.run_once()
        first, second = self.adapter.polled_states
        self.assertEqual(first["feed_path"], "/api/v1/feed")
        self.assertIsNotNone(first.get("bootstrap_if_modified_since"))
        self.assertEqual(second["feed_path"], "/api/v1/feed/page-2")
        self.assertIsNone(second.get("etag"))
        self.assertIsNone(second.get("last_modified"))
        self.assertIsNone(second.get("bootstrap_if_modified_since"))

    def test_recovered_stale_page_job_resumes_the_persisted_cursor(self):
        self.adapter.queue_feed([], next_path="/api/v1/feed/page-2")
        self.service.store.set_source_enabled("source_nav", enabled=True, now="2026-09-23T10:00:00+00:00")
        first = self.service.nav_coordinator.poll_feed(
            {"feedPath": "/api/v1/feed"}, cancelled=lambda: False, progress=lambda *_: None,
        )
        self.assertFalse(first["tail"])
        recovered = self.service.nav_coordinator.poll_feed(
            {"feedPath": "/api/v1/feed"}, cancelled=lambda: False, progress=lambda *_: None,
        )
        self.assertTrue(recovered["staleCheckpoint"])
        self.assertEqual(recovered["followups"][0]["payload"]["feedPath"], "/api/v1/feed/page-2")
        self.assertEqual(len(self.adapter.polled_states), 1)

    def test_end_to_end_feed_filter_capture_extract_project_refresh_and_inactive(self):
        track, profile = self.add_nav_profile()
        self.adapter.queue_feed([feed_item()])
        enabled = self.service.nav_enable()
        self.assertEqual(enabled["data"]["scheduledJob"]["type"], "nav_feed_poll")

        self.assertEqual(self.worker.run_once()["state"], "completed")
        self.assertEqual(self.worker.run_once()["state"], "completed")
        self.assertEqual(self.worker.run_once()["state"], "completed")

        listings = self.service.list_source_listings(source_id="nav")["data"]["listings"]
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing["externalId"], "vacancy-1")
        self.assertIn(profile["id"], [item["id"] for item in listing["searchProfiles"]])
        self.assertIn(track["id"], [item["id"] for item in listing["tracks"]])
        self.assertEqual(listing["captureCount"], 1)
        self.assertIsNotNone(listing["canonicalJobId"])
        job_id = listing["canonicalJobId"]
        job = self.service.get_job(job_id)["data"]["job"]
        self.assertEqual(job["role"], "QA Engineer")
        self.assertEqual(job["company"], "Example AS")
        self.assertFalse(job["sourceExpired"])

        capture_id = listing["latestCaptureId"]
        runs = self.service.list_capture_extraction_runs(capture_id)["data"]["runs"]
        self.assertIn("nav_structured@1", [run["extractorVersion"] for run in runs])
        facts = []
        for run in runs:
            facts.extend(self.service.get_extraction_facts(run["id"])["data"]["facts"])
        self.assertIn("applicationDue", [fact["sourceField"] for fact in facts])
        self.assertIn("vacancy-1", [str(fact["value"]) for fact in facts])

        override = self.service.create_override(job_id, {
            "field": "company", "value": "Human company", "reason": "verified",
        })["data"]["override"]
        self.service.update_profile({"headline": "Persistent profile"})
        before_app = self.service.get_application(job_id)["data"]["application"]["id"]

        payload = {
            "source": "nav", "sourceUuid": "vacancy-1", "feedEntryId": "entry-new",
            "detailPath": "/api/v1/feedentry/entry-1", "candidateProfileIds": [profile["id"]],
            "header": {"title": "QA Engineer", "company": "Example AS", "municipality": "Oslo"},
        }
        unchanged = self.service.nav_coordinator.fetch_listing(
            payload, cancelled=lambda: False, progress=lambda *_: None,
        )
        self.assertTrue(unchanged["unchanged"])
        self.assertEqual(unchanged["followups"], [])

        self.adapter.detail = nav_detail(description="Test APIs and accessibility")
        changed = self.service.nav_coordinator.fetch_listing(
            payload, cancelled=lambda: False, progress=lambda *_: None,
        )
        self.assertTrue(changed["captureCreated"])
        self.assertEqual(len(changed["followups"]), 1)
        self.service.extract_capture(changed["captureId"])
        refreshed = self.service.get_job(job_id)["data"]["job"]
        self.assertEqual(refreshed["company"], "Human company")
        self.assertEqual(self.service.get_application(job_id)["data"]["application"]["id"], before_app)
        self.assertEqual(self.service.get_profile()["data"]["profile"]["headline"], "Persistent profile")
        self.assertEqual(override["field"], "company")

        self.adapter.queue_feed([feed_item(status="INACTIVE", modified="2026-09-22T10:00:00Z")])
        self.service.nav_coordinator.poll_feed(
            {"feedPath": "/api/v1/feed"}, cancelled=lambda: False, progress=lambda *_: None,
        )
        ended = self.service.get_source_listing(listing["id"])["data"]["listing"]
        self.assertEqual(ended["lifecycleState"], "removed")
        self.assertEqual(ended["captureCount"], 2)
        self.assertTrue(self.service.get_job(job_id)["data"]["job"]["sourceExpired"])

    def test_prefilter_favors_recall_and_multiple_profile_matches(self):
        track, first = self.add_nav_profile()
        second = self.service.create_search_profile(track["id"], {
            "name": "Testing", "includeKeywords": ["test"], "plannedSourceKeys": ["nav"],
        })["data"]["searchProfile"]
        profiles = [
            item for item in self.service.store.enabled_source_profiles("source_nav")
            if item["id"] in {first["id"], second["id"]}
        ]
        missing_title = {"title": None, "company": "Example AS", "municipality": "Oslo"}
        self.assertEqual(
            set(self.service.nav_coordinator.matcher.prefilter(missing_title, profiles)),
            {first["id"], second["id"]},
        )
        self.assertEqual(
            set(self.service.nav_coordinator.matcher.full_match(nav_detail(), profiles)),
            {first["id"], second["id"]},
        )

    def test_nav_ai_preparation_removes_contacts(self):
        prepared, version = prepare_source_text(
            json.dumps(nav_detail()), "application/json", redact_contact_fields=True,
        )
        self.assertEqual(version, "json_contact_minimized@1")
        self.assertNotIn("Private Person", prepared)
        self.assertNotIn("private@example.test", prepared)
        self.assertNotIn("contactList", prepared)
        self.assertIn("QA Engineer", prepared)

        self.add_nav_profile()
        self.adapter.queue_feed([feed_item()])
        self.service.nav_enable()
        self.worker.run_once()
        self.worker.run_once()
        self.worker.run_once()
        capture_id = self.service.list_source_listings(source_id="nav")["data"]["listings"][0]["latestCaptureId"]
        provider = FakeAIExtractionProvider([{"facts": [], "openFacts": [], "warnings": []}])
        self.service.ai_provider = provider
        self.service.ai_provider_injected = True
        self.service.ai_extract_capture(capture_id)
        prompt = provider.calls[0].user_prompt
        self.assertNotIn("Private Person", prompt)
        self.assertNotIn("private@example.test", prompt)
        self.assertIn("QA Engineer", prompt)


class NavAdapterContractTests(unittest.TestCase):
    def test_headers_conditionals_schema_and_allowlist(self):
        payload = {"id": "page", "items": [], "next_url": None}
        opener = RecordingOpener(FakeResponse(payload, headers={
            "ETag": '"next"', "Last-Modified": "Sun, 20 Sep 2026 10:00:00 GMT",
        }))
        adapter = NavSourceAdapter(environment={"JOBHUNT_NAV_TOKEN": "secret"}, opener=opener)
        result = adapter.poll_feed({
            "feed_path": "/api/v1/feed", "etag": '"old"',
            "last_modified": "Sat, 19 Sep 2026 10:00:00 GMT",
        }, {})
        self.assertFalse(result["not_modified"])
        request = opener.requests[0][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.get_header("If-none-match"), '"old"')
        self.assertEqual(request.get_header("If-modified-since"), "Sat, 19 Sep 2026 10:00:00 GMT")
        for unsafe in (
            "http://pam-stilling-feed.nav.no/api/v1/feed",
            "https://evil.test/api/v1/feed",
            "https://pam-stilling-feed.nav.no/other",
            "https://pam-stilling-feed.nav.no@evil.test/api/v1/feed",
        ):
            with self.assertRaises(NavSourceError):
                adapter.validate_path(unsafe, operation="feed")

    def test_http_error_classification_timeout_and_limits(self):
        cases = ((401, "authentication", False), (403, "forbidden", False),
                 (429, "rate_limit", True), (500, "transient_server", True))
        for status, classification, retryable in cases:
            with self.subTest(status=status):
                error = urllib.error.HTTPError(
                    "https://pam-stilling-feed.nav.no/api/v1/feed", status, "error",
                    {"Retry-After": "7"}, io.BytesIO(b"{}"),
                )
                adapter = NavSourceAdapter(
                    environment={"JOBHUNT_NAV_TOKEN": "secret"},
                    opener=RecordingOpener(error=error),
                )
                with self.assertRaises(NavSourceError) as caught:
                    adapter.poll_feed({"feed_path": "/api/v1/feed"}, {})
                self.assertEqual(caught.exception.classification, classification)
                self.assertEqual(caught.exception.retryable, retryable)
                if status == 429:
                    self.assertEqual(caught.exception.retry_after_seconds, 7)

        timeout_adapter = NavSourceAdapter(
            environment={"JOBHUNT_NAV_TOKEN": "secret"},
            opener=RecordingOpener(error=socket.timeout()),
        )
        with self.assertRaises(NavSourceError) as caught:
            timeout_adapter.poll_feed({"feed_path": "/api/v1/feed"}, {})
        self.assertEqual(caught.exception.classification, "timeout")
        self.assertTrue(caught.exception.retryable)

        malformed = NavSourceAdapter(
            environment={"JOBHUNT_NAV_TOKEN": "secret"},
            opener=RecordingOpener(FakeResponse({"wrong": []})),
        )
        with self.assertRaises(NavSourceError):
            malformed.poll_feed({"feed_path": "/api/v1/feed"}, {})

        invalid_json = NavSourceAdapter(
            environment={"JOBHUNT_NAV_TOKEN": "secret"},
            opener=RecordingOpener(FakeResponse(b"{not-json")),
        )
        with self.assertRaises(NavSourceError) as caught:
            invalid_json.poll_feed({"feed_path": "/api/v1/feed"}, {})
        self.assertEqual(caught.exception.classification, "malformed_response")

        oversized = NavSourceAdapter(
            environment={"JOBHUNT_NAV_TOKEN": "secret"},
            opener=RecordingOpener(FakeResponse({"items": [], "padding": "x" * 5000})),
            max_feed_bytes=1024,
        )
        with self.assertRaises(NavSourceError) as caught:
            oversized.poll_feed({"feed_path": "/api/v1/feed"}, {})
        self.assertEqual(caught.exception.classification, "validation")

    def test_not_modified_is_a_normal_conditional_result(self):
        error = urllib.error.HTTPError(
            "https://pam-stilling-feed.nav.no/api/v1/feed", 304, "not modified",
            {"ETag": '"same"'}, io.BytesIO(b""),
        )
        adapter = NavSourceAdapter(
            environment={"JOBHUNT_NAV_TOKEN": "secret"},
            opener=RecordingOpener(error=error),
        )
        result = adapter.poll_feed({"feed_path": "/api/v1/feed", "etag": '"same"'}, {})
        self.assertTrue(result["not_modified"])
        self.assertEqual(result["response"].status_code, 304)


if __name__ == "__main__":
    unittest.main()

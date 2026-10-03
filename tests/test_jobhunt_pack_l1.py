import io
import hashlib
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path

from jobhunt_backend import JobhuntService, JobhuntWorker
from jobhunt_backend.dedupe import compare_jobs
from jobhunt_backend.migrations import SCHEMA_VERSION
from jobhunt_backend.sources.jobbnorge import (
    JOBBNORGE_ADAPTER_VERSION,
    JobbnorgeResponse,
    JobbnorgeSourceAdapter,
    JobbnorgeSourceError,
)
from jobhunt_backend.ingestion.jobbnorge import JobbnorgeDiscoveryMatcher
from tests.test_jobhunt_pack_g import FakeNavAdapter, feed_item, nav_detail


FIXTURES = Path(__file__).parent / "fixtures" / "jobhunt"


class FakeJobbnorgeAdapter:
    key = "fake-jobbnorge"
    version = JOBBNORGE_ADAPTER_VERSION

    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.calls = []
        self.failure = None

    jobs_path = staticmethod(JobbnorgeSourceAdapter.jobs_path)

    def fetch_jobs(self, query, *, page, results):
        self.calls.append({"query": dict(query), "page": page, "results": results})
        if self.failure:
            raise self.failure
        items = self.pages.pop(0) if self.pages else []
        raw = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        path = self.jobs_path(query, page=page, results=results)
        return JobbnorgeResponse(
            "jobs", path, 200, items, raw, None, None, 2.5,
        )


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self, limit):
        return self.raw[:limit]

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


class JobhuntPackL1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        page_one = json.loads((FIXTURES / "pack-l1-jobs.json").read_text(encoding="utf-8"))
        expired = json.loads((FIXTURES / "pack-l1-expired.json").read_text(encoding="utf-8"))
        self.adapter = FakeJobbnorgeAdapter([page_one, expired, [page_one[0]]])
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite",
            private_root=self.root / "private",
            environment={
                "JOBHUNT_JOBBNORGE_PAGE_SIZE": "2",
                "JOBHUNT_JOBBNORGE_MAX_PAGES": "2",
                "JOBHUNT_JOBBNORGE_POLL_SECONDS": "300",
            },
            jobbnorge_adapter=self.adapter,
        )
        self.service.initialize()
        self.worker = JobhuntWorker(self.service)
        with self.service.store.transaction() as connection:
            connection.execute("UPDATE track_search_profiles SET status='paused'")
        track = self.service.get_track("track_seed_norway_qa")["data"]["track"]
        self.first_profile = self.service.create_search_profile(track["id"], {
            "name": "Jobbnorge QA",
            "roleIntent": "quality engineering",
            "includeKeywords": ["QA Engineer"],
            "plannedSourceKeys": ["jobbnorge"],
        })["data"]["searchProfile"]
        second_track = self.service.get_track("track_seed_norway_physical")["data"]["track"]
        self.second_profile = self.service.create_search_profile(second_track["id"], {
            "name": "Jobbnorge quality",
            "includeKeywords": ["quality"],
            "plannedSourceKeys": ["jobbnorge"],
        })["data"]["searchProfile"]

    def tearDown(self):
        self.worker.stop(timeout=1)
        self.temp.cleanup()

    def drain_ready(self, limit=30):
        completed = []
        for _ in range(limit):
            result = self.worker.run_once()
            if result is None:
                break
            completed.append(result)
        return completed

    def test_schema_source_and_end_to_end_collection_evidence(self):
        self.assertEqual(SCHEMA_VERSION, 13)
        status = self.service.jobbnorge_status()["data"]
        self.assertFalse(status["source"]["policy"]["enabled"])
        self.assertEqual(status["source"]["policy"]["accessMethod"], "official_api")
        self.assertFalse(status["auth"]["required"])
        self.assertFalse(status["api"]["singleJobEndpoint"])

        enabled = self.service.jobbnorge_enable()["data"]
        self.assertEqual(enabled["scheduledJob"]["type"], "jobbnorge_poll")
        completed = self.drain_ready()
        self.assertTrue(completed)
        self.assertTrue(all(item["state"] == "completed" for item in completed))
        self.assertEqual(len(self.adapter.calls), 3)
        self.assertEqual([item["page"] for item in self.adapter.calls], [1, 2, 1])
        terms = [item["query"]["term"] for item in self.adapter.calls]
        self.assertEqual(terms[0], terms[1])
        self.assertEqual({terms[0], terms[2]}, {"QA Engineer", "quality"})

        listings = self.service.list_source_listings(source_id="jobbnorge")["data"]["listings"]
        self.assertEqual({item["externalId"] for item in listings}, {"41001", "41002", "41003"})
        matched = next(item for item in listings if item["externalId"] == "41001")
        unmatched = next(item for item in listings if item["externalId"] == "41002")
        expired = next(item for item in listings if item["externalId"] == "41003")
        self.assertEqual(matched["captureCount"], 1)
        self.assertEqual(unmatched["captureCount"], 0)
        self.assertEqual(expired["lifecycleState"], "expired")
        self.assertEqual(
            {item["id"] for item in matched["searchProfiles"]},
            {self.first_profile["id"], self.second_profile["id"]},
        )
        self.assertEqual(
            {item["id"] for item in matched["tracks"]},
            {"track_seed_norway_qa", "track_seed_norway_physical"},
        )

        detail = self.service.get_source_listing(matched["id"])["data"]["listing"]
        self.assertEqual(len(detail["collectionEvidence"]), 2)
        self.assertEqual({item["jsonPointer"] for item in detail["collectionEvidence"]}, {"/0"})
        self.assertTrue(all(item["derivedCaptureId"] == matched["latestCaptureId"] for item in detail["collectionEvidence"]))

        capture = self.service.get_raw_capture(matched["latestCaptureId"])["data"]["capture"]
        self.assertTrue(capture["metadata"]["derivedRepresentation"])
        self.assertFalse(capture["metadata"]["exactHttpBody"])
        runs = self.service.list_capture_extraction_runs(capture["id"])["data"]["runs"]
        self.assertIn("jobbnorge_structured@1", {item["extractorVersion"] for item in runs})
        job = self.service.get_job(matched["canonicalJobId"])["data"]["job"]
        self.assertEqual(job["role"], "QA Engineer")
        self.assertEqual(job["company"], "Example University")
        evaluations = self.service.list_job_evaluations(matched["canonicalJobId"])["data"]
        self.assertTrue(evaluations["targets"])
        self.assertTrue(all(item["evaluation"] is not None for item in evaluations["targets"]))

        skill_fact = {
            "namespace": "job", "fact_type": "skill", "source_field": "pack_l1_fixture",
            "source_wording": "SQL", "value_type": "text", "value_text": "SQL",
            "value_number": None, "value_boolean": None, "value_json": None,
            "requirement_preference": "required", "state": "explicit_positive",
            "confidence": 1.0,
            "evidence_locator": {
                "kind": "collection_json_pointer",
                "collectionCaptureId": detail["collectionEvidence"][0]["collectionCaptureId"],
                "jsonPointer": "/0/summary",
            },
            "validation_state": "valid", "normalization_state": "unmapped",
            "normalization": {
                "concept_id": "concept_skill_sql", "rule_version": "normalization@1",
                "confidence": 1.0,
            },
        }
        self.service.store.save_extraction_batch(
            capture_id=capture["id"], extractor_kind="manual_hints",
            extractor_version="pack-l1-skill-regression@1",
            input_hash=hashlib.sha256(b"pack-l1-sql").hexdigest(),
            output_schema_version="jobhunt-facts@1", facts=[skill_fact], warnings=[],
            now="2026-09-24T12:00:00+00:00",
        )
        intelligence = self.service.get_track_skill_intelligence(
            "track_seed_norway_qa", population="current", window="90d"
        )["data"]
        sql = next(item for item in intelligence["skills"] if item["reference"] == "skill:SQL")
        self.assertEqual(sql["demand"]["jobsMentioning"], 1)

        expected = json.dumps(
            json.loads((FIXTURES / "pack-l1-jobs.json").read_text(encoding="utf-8")),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_hash = hashlib.sha256(expected).hexdigest()
        with self.service.store.read_connection() as connection:
            collection = connection.execute(
                "SELECT * FROM source_collection_captures WHERE blob_sha256=?",
                (expected_hash,),
            ).fetchone()
        archived = self.service.raw_archive.read_verified(
            relative_path=self.service.store.get_raw_blob(collection["blob_sha256"])["relative_path"],
            expected_hash=collection["blob_sha256"],
            expected_size=collection["response_bytes"],
        )
        self.assertEqual(archived, expected)

        sync = self.service.jobbnorge_sync_state()["data"]["queryState"]
        self.assertEqual(sync["pagesFetched"], 3)
        self.assertEqual(sync["requestsMade"], 3)
        self.assertIsNotNone(sync["cycleCompletedAt"])
        metrics = self.service.store.ingestion_metrics()
        self.assertGreaterEqual(metrics["collectionCaptures"], 3)
        with self.service.store.read_connection() as connection:
            ai_jobs = connection.execute(
                "SELECT COUNT(*) FROM worker_jobs WHERE job_type='ai_extract_capture'"
            ).fetchone()[0]
        self.assertEqual(ai_jobs, 0)

    def test_repoll_is_stable_and_changed_item_creates_new_derived_capture(self):
        self.service.jobbnorge_enable()
        self.drain_ready()
        listing = self.service.store.source_listing_by_external_id("source_jobbnorge", "41001")
        original_job_id = listing["canonical_job_id"]
        changed = json.loads((FIXTURES / "pack-l1-jobs.json").read_text(encoding="utf-8"))[0]
        changed["summary"] = "Quality engineering with changed source evidence."
        self.adapter.pages = [[changed], []]
        self.service.jobbnorge_sync()
        self.drain_ready()
        refreshed = self.service.store.source_listing_by_external_id("source_jobbnorge", "41001")
        self.assertEqual(refreshed["canonical_job_id"], original_job_id)
        self.assertEqual(refreshed["capture_count"], 2)
        self.assertGreaterEqual(len(refreshed["collection_evidence"]), 3)

    def test_bounded_malformed_body_is_archived_before_visible_failure(self):
        raw = b"{not-json"
        self.adapter.failure = JobbnorgeSourceError(
            "malformed", classification="malformed_response", status_code=200,
            request_path="/v1/Jobs?results=2&page=1", response_bytes=len(raw), raw=raw,
        )
        self.service.jobbnorge_enable()
        result = self.worker.run_once()
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_class"], "malformed_response")
        status = self.service.jobbnorge_status()["data"]
        self.assertEqual(status["queryState"]["lastErrorClass"], "malformed_response")
        with self.service.store.read_connection() as connection:
            row = connection.execute(
                "SELECT safe_metadata_json FROM source_collection_captures"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertFalse(json.loads(row[0])["responseValidated"])

    def test_rate_limit_persists_backoff_and_source_controls_are_independent(self):
        self.adapter.failure = JobbnorgeSourceError(
            "rate limited", classification="rate_limit", retryable=True,
            status_code=429, retry_after_seconds=30,
            request_path="/v1/Jobs?results=2&page=1",
        )
        self.service.jobbnorge_enable()
        result = self.worker.run_once()
        self.assertEqual(result["state"], "retry_wait")
        self.assertEqual(result["error_class"], "rate_limit")
        status = self.service.jobbnorge_status()["data"]
        self.assertEqual(status["source"]["policy"]["operationalState"], "degraded")
        self.assertIsNotNone(status["source"]["policy"]["backoffUntil"])
        self.assertEqual(status["recentRequests"][0]["status_code"], 429)
        sources = {item["key"]: item for item in self.service.list_sources()["data"]["sources"]}
        self.assertFalse(sources["nav"]["policy"]["enabled"])
        self.assertFalse(sources["pracuj"]["policy"]["enabled"])
        self.service.jobbnorge_pause()
        sources = {item["key"]: item for item in self.service.list_sources()["data"]["sources"]}
        self.assertFalse(sources["jobbnorge"]["policy"]["enabled"])
        self.service.store.set_source_enabled("source_nav", enabled=True, now="2026-09-24T12:00:00+00:00")
        self.service.store.set_source_enabled("source_pracuj", enabled=True, now="2026-09-24T12:00:00+00:00")
        sources = {item["key"]: item for item in self.service.list_sources()["data"]["sources"]}
        self.assertTrue(sources["nav"]["policy"]["enabled"])
        self.assertTrue(sources["pracuj"]["policy"]["enabled"])
        self.assertFalse(sources["jobbnorge"]["policy"]["enabled"])
        self.service.store.set_source_enabled("source_nav", enabled=False, now="2026-09-24T12:01:00+00:00")
        self.service.store.set_source_enabled("source_pracuj", enabled=False, now="2026-09-24T12:01:00+00:00")
        manual = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "offline-manual",
            "inputMode": "text", "contentType": "text/plain", "content": "Manual remains available",
        })["data"]
        self.assertEqual(manual["listing"]["source"]["key"], "manual")

    def test_pagination_checkpoint_resumes_after_restart_and_rejects_invalid_state(self):
        items = json.loads((FIXTURES / "pack-l1-jobs.json").read_text(encoding="utf-8"))
        self.adapter.pages = [items]
        self.service.store.set_source_enabled(
            "source_jobbnorge", enabled=True, now="2026-09-24T10:00:00+00:00"
        )
        first = self.service.jobbnorge_coordinator.poll(
            {"cycleId": "restart-cycle", "queryIndex": 0, "page": 1},
            cancelled=lambda: False, progress=lambda *_: None,
        )
        page_two = next(
            item for item in first["followups"]
            if item["job_type"] == "jobbnorge_poll"
        )["payload"]
        self.assertEqual(page_two["page"], 2)

        resumed_adapter = FakeJobbnorgeAdapter([
            json.loads((FIXTURES / "pack-l1-expired.json").read_text(encoding="utf-8"))
        ])
        resumed = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private",
            environment={"JOBHUNT_JOBBNORGE_PAGE_SIZE": "2", "JOBHUNT_JOBBNORGE_MAX_PAGES": "2"},
            jobbnorge_adapter=resumed_adapter,
        )
        resumed.initialize()
        second = resumed.jobbnorge_coordinator.poll(
            page_two, cancelled=lambda: False, progress=lambda *_: None,
        )
        self.assertEqual(second["page"], 2)
        self.assertEqual(len(resumed_adapter.calls), 1)
        duplicate = resumed.jobbnorge_coordinator.poll(
            {"cycleId": "restart-cycle", "queryIndex": 0, "page": 1},
            cancelled=lambda: False, progress=lambda *_: None,
        )
        self.assertTrue(duplicate["staleCheckpoint"])
        self.assertEqual(len(resumed_adapter.calls), 1)
        with self.assertRaises(JobbnorgeSourceError):
            resumed.jobbnorge_coordinator.poll(
                {"cycleId": "invalid", "queryIndex": -1, "page": 0},
                cancelled=lambda: False, progress=lambda *_: None,
            )

    def test_recall_safe_matching_for_missing_fields(self):
        profile = {
            "id": "profile-edge", "include_keywords": ["QA"],
            "exclude_keywords": [], "role_intent": "Quality",
            "regions_cities": ["Oslo"], "work_models": ["remote"],
            "contract_hints": [], "schedule_hints": [], "language_hints": [],
            "seniority_hints": [],
        }
        edge = json.loads((FIXTURES / "pack-l1-edge.json").read_text(encoding="utf-8"))
        self.assertEqual(JobbnorgeDiscoveryMatcher().match(edge, [profile]), ["profile-edge"])

    def test_forbidden_is_a_non_retrying_visible_policy_failure(self):
        self.adapter.failure = JobbnorgeSourceError(
            "forbidden", classification="forbidden", retryable=False,
            status_code=403, request_path="/v1/Jobs?results=2&page=1",
        )
        self.service.jobbnorge_enable()
        result = self.worker.run_once()
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_class"], "forbidden")
        status = self.service.jobbnorge_status()["data"]
        self.assertEqual(status["source"]["policy"]["operationalState"], "degraded")
        self.assertEqual(status["source"]["policy"]["lastErrorClass"], "forbidden")

    def test_nav_cross_source_candidate_merge_and_unmerge_preserve_histories(self):
        nav = FakeNavAdapter()
        nav.detail = nav_detail()
        nav.detail["json"].update({
            "title": "QA Engineer", "employer": {"name": "University X"},
            # Both source discovery records still retain Oslo. The public
            # Jobbnorge result has only free-text location, so keep structured
            # canonical geography unknown on both sides for this dedupe case.
            "workLocations": [],
            "description": "Quality engineering, accessibility testing, and test automation.",
        })
        item = json.loads((FIXTURES / "pack-l1-jobs.json").read_text(encoding="utf-8"))[0]
        item["employer"] = "University X"
        combined = JobhuntService(
            self.root / "cross-source.sqlite", private_root=self.root / "cross-private",
            environment={}, nav_adapter=nav, jobbnorge_adapter=FakeJobbnorgeAdapter([[item]]),
        )
        combined.initialize()
        worker = JobhuntWorker(combined)
        try:
            with combined.store.transaction() as connection:
                connection.execute("UPDATE track_search_profiles SET status='paused'")
            profile = combined.create_search_profile("track_seed_norway_qa", {
                "name": "Cross source QA", "includeKeywords": ["QA Engineer"],
                "plannedSourceKeys": ["nav", "jobbnorge"],
            })["data"]["searchProfile"]
            nav.queue_feed([feed_item()])
            combined.nav_enable()
            combined.jobbnorge_enable()
            for _ in range(30):
                if worker.run_once() is None:
                    break
            listings = combined.list_source_listings()["data"]["listings"]
            relevant = [item for item in listings if item["searchProfiles"] and item["searchProfiles"][0]["id"] == profile["id"]]
            self.assertEqual({item["source"]["key"] for item in relevant}, {"nav", "jobbnorge"})
            scan = combined.scan_job_for_duplicates(relevant[0]["canonicalJobId"], force_reopen=True)
            candidate = combined.get_duplicate(scan["candidateIds"][0])["data"]["candidate"]
            left = combined._prepare_dedupe_context(candidate["leftJob"]["id"])
            right = combined._prepare_dedupe_context(candidate["rightJob"]["id"])
            combined.store.save_duplicate_candidate(
                left_job_id=candidate["leftJob"]["id"],
                right_job_id=candidate["rightJob"]["id"],
                comparison=compare_jobs(left, right),
                now="2026-09-24T12:30:00+00:00",
                force_reopen=True,
            )
            candidate = combined.get_duplicate(candidate["id"])["data"]["candidate"]
            detail = combined.get_duplicate(candidate["id"])["data"]
            merged = combined.merge_duplicate(candidate["id"], {
                "confirm": True, "survivorJobId": detail["safety"]["survivorJobId"],
            })["data"]["merge"]
            self.assertEqual(combined.dedupe_summary()["data"]["summary"]["canonicalJobs"], 1)
            self.assertEqual(len(combined.list_source_listings()["data"]["listings"]), 2)
            combined.unmerge(merged["id"], {})
            self.assertEqual(combined.dedupe_summary()["data"]["summary"]["canonicalJobs"], 2)
            self.assertEqual(len(combined.list_source_listings()["data"]["listings"]), 2)
        finally:
            worker.stop(timeout=1)


class JobbnorgeAdapterContractTests(unittest.TestCase):
    def test_allowlist_query_headers_and_no_authentication(self):
        opener = RecordingOpener(FakeResponse([]))
        adapter = JobbnorgeSourceAdapter(opener=opener)
        response = adapter.fetch_jobs(
            {"term": "QA engineer", "orderby": "Published", "period": "All", "abroad": False},
            page=2, results=25,
        )
        self.assertEqual(response.items, [])
        request = opener.requests[0][0]
        self.assertEqual(request.full_url.split("?", 1)[0], "https://publicapi.jobbnorge.no/v1/Jobs")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(request.get_header("Accept"), "application/json")
        for unsafe in (
            "http://publicapi.jobbnorge.no/v1/Jobs",
            "https://evil.test/v1/Jobs",
            "https://publicapi.jobbnorge.no/v1/Jobs/count",
            "https://publicapi.jobbnorge.no@evil.test/v1/Jobs",
            "/v1/Jobs?unsafe=true",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(JobbnorgeSourceError):
                adapter.validate_path(unsafe)

    def test_error_classification_retry_after_timeout_and_bounds(self):
        for status, classification, retryable in (
            (403, "forbidden", False), (429, "rate_limit", True),
            (500, "transient_server", True), (302, "unexpected_redirect", False),
        ):
            with self.subTest(status=status):
                if status == 302:
                    opener = RecordingOpener(FakeResponse([], status=302, headers={"Location": "https://evil.test"}))
                else:
                    error = urllib.error.HTTPError(
                        "https://publicapi.jobbnorge.no/v1/Jobs", status, "error",
                        {"Retry-After": "9"}, io.BytesIO(b"{}"),
                    )
                    opener = RecordingOpener(error=error)
                with self.assertRaises(JobbnorgeSourceError) as caught:
                    JobbnorgeSourceAdapter(opener=opener).fetch_jobs({}, page=1, results=10)
                self.assertEqual(caught.exception.classification, classification)
                self.assertEqual(caught.exception.retryable, retryable)
                if status == 429:
                    self.assertEqual(caught.exception.retry_after_seconds, 9)

        with self.assertRaises(JobbnorgeSourceError) as caught:
            JobbnorgeSourceAdapter(
                opener=RecordingOpener(error=socket.timeout())
            ).fetch_jobs({}, page=1, results=10)
        self.assertEqual(caught.exception.classification, "timeout")
        self.assertTrue(caught.exception.retryable)

        with self.assertRaises(JobbnorgeSourceError) as caught:
            JobbnorgeSourceAdapter(
                opener=RecordingOpener(error=urllib.error.URLError("offline"))
            ).fetch_jobs({}, page=1, results=10)
        self.assertEqual(caught.exception.classification, "network")
        self.assertTrue(caught.exception.retryable)

        with self.assertRaises(JobbnorgeSourceError) as caught:
            JobbnorgeSourceAdapter(
                opener=RecordingOpener(FakeResponse(b"{bad"))
            ).fetch_jobs({}, page=1, results=10)
        self.assertEqual(caught.exception.classification, "malformed_response")
        self.assertEqual(caught.exception.raw, b"{bad")

        with self.assertRaises(JobbnorgeSourceError) as caught:
            JobbnorgeSourceAdapter(
                opener=RecordingOpener(FakeResponse(b"[" + b" " * 2048 + b"]")),
                max_response_bytes=1024,
            ).fetch_jobs({}, page=1, results=10)
        self.assertEqual(caught.exception.classification, "oversized_response")


if __name__ == "__main__":
    unittest.main()

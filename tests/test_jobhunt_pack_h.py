import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntError, JobhuntService, JobhuntWorker
from jobhunt_backend.migrations import MIGRATIONS, SCHEMA_VERSION


class JobhuntPackHTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private",
            environment={},
        )
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def import_job(
        self, external_id, *, company="Example AS", title="QA Engineer", city="Oslo",
        country="Norway", date_posted="2026-09-20", description="Test APIs and web applications",
        source_url=None, salary_min=None, salary_max=None,
    ):
        payload = {
            "title": title, "company": company, "city": city, "country": country,
            "datePosted": date_posted, "description": description,
        }
        if salary_min is not None or salary_max is not None:
            payload["salary"] = {
                "min": salary_min, "max": salary_max,
                "currency": "NOK", "period": "month",
            }
        imported = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": external_id,
            "originalUrl": source_url, "inputMode": "json", "contentType": "application/json",
            "content": json.dumps(payload),
        })["data"]
        extracted = self.service.extract_capture(imported["capture"]["id"])["data"]
        return {
            "job_id": extracted["projection"]["canonicalJobId"],
            "listing_id": imported["listing"]["id"],
            "capture_id": imported["capture"]["id"],
            "dedupe": extracted["dedupeScan"],
        }

    def open_candidate(self):
        first = self.import_job("manual-a")
        second = self.import_job("manual-b", company="Example", description="Test APIs and web applications")
        candidate = self.service.list_duplicates()["data"]["items"][0]
        return first, second, candidate

    def counts(self):
        with self.service.store.read_connection() as connection:
            names = (
                "source_listings", "raw_captures", "extraction_runs", "extracted_facts",
                "application_events",
            )
            return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}

    def test_schema_candidate_rules_ordering_idempotency_and_unknowns(self):
        self.assertEqual(SCHEMA_VERSION, 13)
        with self.service.store.read_connection() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertTrue({
            "dedupe_job_keys", "dedupe_job_urls", "duplicate_candidates",
            "duplicate_candidate_events", "canonical_job_merges",
            "canonical_job_merge_events",
        }.issubset(tables))

        first, second, candidate = self.open_candidate()
        self.assertLess(candidate["leftJob"]["id"], candidate["rightJob"]["id"])
        self.assertEqual(candidate["ruleVersion"], "dedupe@1")
        self.assertIn("company_title_location_time", candidate["reasonCodes"])
        self.assertGreater(candidate["evidence"]["descriptionSimilarity"], 0.9)
        self.assertIsNone(candidate["evidence"]["salaryCompatible"])
        self.assertEqual(candidate["hardContradictions"], [])
        fingerprint = candidate["evidenceFingerprint"]
        self.service.scan_job_for_duplicates(first["job_id"])
        repeated = self.service.list_duplicates()["data"]["items"]
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0]["evidenceFingerprint"], fingerprint)

        different_company = self.import_job("manual-c", company="Other Logistics")
        different_role = self.import_job("manual-d", title="Warehouse Operative")
        all_pairs = self.service.list_duplicates(state="all")["data"]["items"]
        self.assertFalse(any(
            different_company["job_id"] in {item["leftJob"]["id"], item["rightJob"]["id"]}
            for item in all_pairs
        ))
        self.assertFalse(any(
            different_role["job_id"] in {item["leftJob"]["id"], item["rightJob"]["id"]}
            for item in all_pairs
        ))

    def test_pack_g_to_h_migration_preserves_worker_queue(self):
        database = self.root / "pack-g.sqlite"
        now = "2026-09-23T10:00:00+00:00"
        with sqlite3.connect(database) as connection:
            for migration in MIGRATIONS[:8]:
                connection.executescript(migration.sql)
            connection.execute(
                "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
            )
            connection.executemany(
                "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(?,?,?,NULL)",
                [(item.version, now, item.checksum) for item in MIGRATIONS[:8]],
            )
            connection.execute(
                """INSERT INTO worker_jobs(
                       id,job_type,payload_json,idempotency_key,state,stage,next_attempt_at,
                       created_at,updated_at
                   ) VALUES('worker-old','nav_feed_poll','{}','old-key','queued','queued',?,?,?)""",
                (now, now, now),
            )
        migrated = JobhuntService(database, private_root=self.root / "migrated-private", environment={})
        migrated.initialize()
        self.assertEqual(migrated.store.schema_status()["version"], 13)
        self.assertEqual(migrated.store.get_worker_job("worker-old")["job_type"], "nav_feed_poll")
        worker = JobhuntWorker(migrated)
        added, reused = worker.enqueue(
            job_type="dedupe_scan_job", payload={"jobId": "missing"},
            idempotency_key="pack-h-dedupe-job",
        )
        self.assertFalse(reused)
        self.assertEqual(added["job_type"], "dedupe_scan_job")

    def test_salary_and_dates_are_supporting_evidence_only(self):
        first = self.import_job(
            "salary-a", company="Salary AS", date_posted="2026-09-20",
            salary_min=50_000, salary_max=70_000,
        )
        second = self.import_job(
            "salary-b", company="Salary", date_posted="2026-09-21",
            salary_min=60_000, salary_max=80_000,
        )
        candidate = next(
            item for item in self.service.list_duplicates()["data"]["items"]
            if {item["leftJob"]["id"], item["rightJob"]["id"]} == {first["job_id"], second["job_id"]}
        )
        self.assertTrue(candidate["evidence"]["salaryCompatible"])
        self.assertEqual(candidate["evidence"]["publicationDeltaDays"], 1)
        self.assertIn("salary_compatible", candidate["reasonCodes"])
        self.assertEqual(candidate["state"], "open")
        self.assertEqual(self.service.dedupe_summary()["data"]["summary"]["activeMerges"], 0)

    def test_not_duplicate_dismissal_and_material_evidence_change(self):
        first, second, candidate = self.open_candidate()
        decided = self.service.decide_duplicate(
            candidate["id"], {"note": "Separate hiring rounds"}, dismissed=False,
        )["data"]["candidate"]
        self.assertEqual(decided["state"], "not_duplicate")
        self.service.scan_job_for_duplicates(first["job_id"])
        self.assertEqual(
            self.service.get_duplicate(candidate["id"])["data"]["candidate"]["state"],
            "not_duplicate",
        )
        self.service.update_job(second["job_id"], {"role": "Senior QA Engineer"})
        reopened = self.service.get_duplicate(candidate["id"])["data"]["candidate"]
        self.assertEqual(reopened["state"], "open")
        self.assertNotEqual(reopened["evidenceFingerprint"], candidate["evidenceFingerprint"])
        dismissed = self.service.decide_duplicate(candidate["id"], {}, dismissed=True)["data"]["candidate"]
        self.assertEqual(dismissed["state"], "dismissed")

    def test_exact_url_auto_merge_is_conservative_and_audited(self):
        url_a = "https://example.test/apply?id=42&utm_source=nav#details"
        url_b = "https://EXAMPLE.test:443/apply?id=42&utm_medium=email"
        first = self.import_job("exact-a", source_url=url_a)
        before = self.counts()
        second = self.import_job("exact-b", company="Example", source_url=url_b)
        summary = self.service.dedupe_summary()["data"]["summary"]
        self.assertEqual(summary["activeMerges"], 1)
        self.assertEqual(summary["canonicalJobs"], 1)
        self.assertEqual(summary["sourceListings"], 2)
        self.assertEqual(summary["rawCaptures"], 2)
        merges = self.service.list_dedupe_merges()["data"]["items"]
        self.assertEqual(merges[0]["origin"], "deterministic_auto")
        self.assertIn("shared_normalized_url", merges[0]["reason"])
        self.assertEqual(self.service.list_jobs()["data"]["total"], 1)
        alias_ids = {first["job_id"], second["job_id"]} - {merges[0]["survivorJobId"]}
        alias = self.service.get_job(alias_ids.pop())["data"]["mergeAlias"]
        self.assertEqual(alias["survivorJobId"], merges[0]["survivorJobId"])
        after = self.counts()
        for name in ("source_listings", "raw_captures", "extraction_runs", "extracted_facts"):
            self.assertGreaterEqual(after[name], before[name])

    def test_hard_authoritative_identity_contradiction_prevents_auto_merge(self):
        first = self.import_job("nav-copy-a", source_url="https://example.test/shared")
        second = self.import_job("nav-copy-b", company="Example", source_url="https://example.test/shared")
        active_merge = self.service.list_dedupe_merges(state="active")["data"]["items"][0]
        self.service.unmerge(active_merge["id"], {})
        with self.service.store.transaction() as connection:
            connection.execute(
                "UPDATE source_listings SET source_id='source_nav' WHERE id IN (?,?)",
                (first["listing_id"], second["listing_id"]),
            )
        result = self.service.explicit_dedupe_scan(first["job_id"], {})["data"]
        self.assertFalse(result["autoMergeIds"])
        candidate = self.service.list_duplicates()["data"]["items"][0]
        self.assertIn("different_authoritative_source_ids", candidate["hardContradictions"])
        detail = self.service.get_duplicate(candidate["id"])["data"]
        self.assertFalse(detail["safety"]["safe"])

    def test_manual_merge_preserves_evidence_tracks_and_unmerge_reprojects(self):
        first, second, candidate = self.open_candidate()
        self.service.set_job_tracks(first["job_id"], {
            "trackIds": ["track_seed_qa_poland"], "origin": "manual",
        })
        self.service.set_job_tracks(second["job_id"], {
            "trackIds": ["track_seed_norway_qa"], "origin": "manual",
        })
        before = self.counts()
        detail = self.service.get_duplicate(candidate["id"])["data"]
        merged = self.service.merge_duplicate(candidate["id"], {
            "confirm": True, "survivorJobId": detail["safety"]["survivorJobId"],
        })["data"]["merge"]
        survivor_tracks = self.service.get_job_tracks(merged["survivorJobId"])["data"]["tracks"]
        self.assertEqual(
            {item["trackId"] for item in survivor_tracks if item["assigned"]},
            {"track_seed_qa_poland", "track_seed_norway_qa"},
        )
        with self.service.store.read_connection() as connection:
            owners = {row[0] for row in connection.execute(
                "SELECT canonical_job_id FROM source_listings WHERE id IN (?,?)",
                (first["listing_id"], second["listing_id"]),
            )}
        self.assertEqual(owners, {merged["survivorJobId"]})
        self.assertEqual(before, self.counts())

        changed = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "manual-b",
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps({
                "title": "QA Engineer", "company": "Example", "city": "Oslo",
                "country": "Norway", "datePosted": "2026-09-21",
                "description": "Test APIs, web applications, and mobile releases",
            }),
        })["data"]
        self.service.extract_capture(changed["capture"]["id"])
        post_capture_count = self.counts()["raw_captures"]
        reverted = self.service.unmerge(merged["id"], {"note": "Wrong hiring round"})["data"]["merge"]
        self.assertEqual(reverted["state"], "reverted")
        self.assertEqual(self.service.list_jobs()["data"]["total"], 2)
        self.assertEqual(self.counts()["raw_captures"], post_capture_count)
        with self.service.store.read_connection() as connection:
            owner = connection.execute(
                "SELECT canonical_job_id FROM source_listings WHERE id=?", (second["listing_id"],)
            ).fetchone()[0]
        self.assertEqual(owner, second["job_id"])
        self.assertEqual(
            self.service.get_duplicate(candidate["id"])["data"]["candidate"]["state"],
            "not_duplicate",
        )
        self.service.scan_job_for_duplicates(first["job_id"])
        self.assertEqual(self.service.dedupe_summary()["data"]["summary"]["activeMerges"], 0)

    def test_application_and_override_safety_blocks_unsafe_merge(self):
        first, second, candidate = self.open_candidate()
        self.service.application_command(first["job_id"], {"type": "applied"})
        self.service.application_command(second["job_id"], {"type": "applied"})
        detail = self.service.get_duplicate(candidate["id"])["data"]
        self.assertIn("both_applications_have_meaningful_history", detail["safety"]["blockers"])
        with self.assertRaises(JobhuntError) as blocked:
            self.service.merge_duplicate(candidate["id"], {"confirm": True})
        self.assertEqual(blocked.exception.code, "duplicate_merge_unsafe")

        third = self.import_job("override-a", company="Override AS")
        fourth = self.import_job("override-b", company="Override", description="Test APIs and web applications")
        override_candidate = next(
            item for item in self.service.list_duplicates()["data"]["items"]
            if {item["leftJob"]["id"], item["rightJob"]["id"]} == {third["job_id"], fourth["job_id"]}
        )
        self.service.create_override(third["job_id"], {
            "field": "company", "value": "Override One", "reason": "Verified locally",
        })
        self.service.create_override(fourth["job_id"], {
            "field": "company", "value": "Override Two", "reason": "Verified locally",
        })
        override_detail = self.service.get_duplicate(override_candidate["id"])["data"]
        self.assertIn("conflicting_active_human_overrides", override_detail["safety"]["blockers"])

    def test_meaningful_application_and_single_override_choose_survivor_without_rewriting_history(self):
        first = self.import_job("meaningful-a", company="History AS")
        second = self.import_job("meaningful-b", company="History", description="Test APIs and web applications")
        candidate = next(
            item for item in self.service.list_duplicates()["data"]["items"]
            if {item["leftJob"]["id"], item["rightJob"]["id"]} == {first["job_id"], second["job_id"]}
        )
        self.service.application_command(second["job_id"], {"type": "applied"})
        events_before = self.service.get_application(second["job_id"])["data"]["events"]
        detail = self.service.get_duplicate(candidate["id"])["data"]
        self.assertEqual(detail["safety"]["survivorJobId"], second["job_id"])
        merged = self.service.merge_duplicate(candidate["id"], {"confirm": True})["data"]["merge"]
        self.assertEqual(merged["survivorJobId"], second["job_id"])
        self.assertEqual(
            self.service.get_application(second["job_id"])["data"]["events"], events_before,
        )

        self.service.unmerge(merged["id"], {})
        third = self.import_job("override-only-a", company="Override Safe AS")
        fourth = self.import_job("override-only-b", company="Override Safe", description="Test APIs and web applications")
        override_candidate = next(
            item for item in self.service.list_duplicates()["data"]["items"]
            if {item["leftJob"]["id"], item["rightJob"]["id"]} == {third["job_id"], fourth["job_id"]}
        )
        override = self.service.create_override(fourth["job_id"], {
            "field": "company", "value": "Override Safe", "reason": "Verified locally",
        })["data"]["override"]
        override_detail = self.service.get_duplicate(override_candidate["id"])["data"]
        self.assertEqual(override_detail["safety"]["survivorJobId"], fourth["job_id"])
        safe_merge = self.service.merge_duplicate(override_candidate["id"], {"confirm": True})["data"]["merge"]
        self.assertEqual(safe_merge["survivorJobId"], fourth["job_id"])
        active = self.service.store.list_overrides(fourth["job_id"])
        self.assertIn(override["id"], {item["id"] for item in active if item["state"] == "active"})

    def test_worker_post_projection_scan_is_durable_and_idempotent(self):
        worker = JobhuntWorker(self.service)
        imported = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "worker-a",
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps({"title": "QA Engineer", "company": "Worker AS"}),
        })["data"]
        extracted = self.service.extract_capture(imported["capture"]["id"])["data"]
        self.assertTrue(extracted["dedupeScan"]["queued"])
        jobs = self.service.store.list_worker_jobs(states=["queued"], limit=20)
        scan = next(item for item in jobs if item["job_type"] == "dedupe_scan_job")
        processed = worker.run_once()
        self.assertEqual(processed["id"], scan["id"])
        self.assertEqual(processed["state"], "completed")
        duplicate, reused = worker.enqueue(
            job_type="dedupe_scan_job",
            payload={"jobId": extracted["projection"]["canonicalJobId"]},
            idempotency_key="dedupe-test-stable",
        )
        same, same_reused = worker.enqueue(
            job_type="dedupe_scan_job", payload={"jobId": "other"},
            idempotency_key="dedupe-test-stable",
        )
        self.assertFalse(reused)
        self.assertTrue(same_reused)
        self.assertEqual(duplicate["id"], same["id"])


if __name__ == "__main__":
    unittest.main()

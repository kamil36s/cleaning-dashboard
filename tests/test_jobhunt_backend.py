import base64
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from jobhunt_backend import JobhuntError, JobhuntService
from jobhunt_backend.migrations import SCHEMA_VERSION


def offer(legacy_id="legacy-hsbc", **overrides):
    value = {
        "id": legacy_id,
        "company": "HSBC",
        "role": "QA Analyst",
        "seniority": "mid",
        "location": {"city": "Krakow", "country": "Poland", "workMode": "hybrid"},
        "contract": {"type": "UoP"},
        "salary": {"min": 12000, "max": 16000, "currency": "PLN", "period": "month", "isKnown": True},
        "source": {"name": "manual", "url": "https://example.test/jobs/1", "capturedAt": "2026-09-18T10:00:00+02:00"},
        "status": "applied",
        "priority": "P1",
        "nextAction": "follow_up",
        "match": {"score": 82, "summary": "Historical imported fit", "isExperimental": True},
        "requirements": {"mustHave": ["Manual QA"], "niceToHave": ["API"], "tools": ["Jira"]},
        "analysis": {
            "greenFlags": ["UAT"], "redFlags": ["API gap"],
            "skillGaps": ["Postman"], "fitReasons": ["Relevant QA work"],
        },
        "cv": {"recommendedVersion": "QA/UAT", "bulletsToEmphasize": ["Led UAT"]},
        "application": {
            "dateApplied": "2026-09-18", "followUpDate": "2026-09-25",
            "recruiterName": "Ada", "recruiterContact": "ada@example.test",
        },
        "notes": "Private note",
        "originalText": "Original advertisement",
        "customUnsupportedField": {"kept": True},
    }
    value.update(overrides)
    return value


def migration_payload(offers=None, *, key="jobhunt-test-migration-0001", settings=None):
    return {
        "schemaVersion": 1,
        "idempotencyKey": key,
        "offers": list(offers or []),
        "matchSettings": list(settings or [{"id": "manual_qa", "label": "Manual QA", "weight": 27}]),
    }


class JobhuntBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "jobhunt.sqlite"
        self.private = self.root / "private"
        self.service = JobhuntService(self.database, private_root=self.private)
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_clean_database_has_ordered_schema_foreign_keys_and_wal(self):
        status = self.service.store.schema_status()
        self.assertEqual(status["version"], SCHEMA_VERSION)
        self.assertTrue(status["foreignKeys"])
        self.assertEqual(status["journalMode"], "wal")
        with self.service.store.read_connection() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertIn("canonical_jobs", tables)
            self.assertIn("application_events", tables)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO application_events(id,application_id,event_type,occurred_at,payload_json,origin)
                       VALUES('evt_bad','missing','created','2026-09-18T00:00:00Z','{}','user')"""
                )

    def test_empty_and_repeated_migration_are_verified_and_idempotent(self):
        payload = migration_payload([])
        first = self.service.migrate_local_storage(payload)["data"]
        second = self.service.migrate_local_storage(payload)["data"]
        self.assertTrue(first["verified"])
        self.assertEqual(first["migrationId"], second["migrationId"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(self.service.store.counts(), {
            "jobs": 0, "applications": 0, "events": 0, "evaluations": 0, "migrations": 1,
        })
        recovery = self.database.parent / first["recoverySnapshot"]["path"]
        self.assertTrue(recovery.is_file())

    def test_migration_preserves_evaluation_settings_and_lossless_payload(self):
        result = self.service.migrate_local_storage(migration_payload([offer()]))["data"]
        self.assertEqual(result["imported"], 1)
        jobs = self.service.list_jobs()["data"]["jobs"]
        self.assertEqual(len(jobs), 1)
        migrated = jobs[0]
        self.assertEqual(migrated["legacyId"], "legacy-hsbc")
        self.assertEqual(migrated["match"]["score"], 82)
        self.assertEqual(migrated["evaluationSource"], "legacy_imported")
        self.assertEqual(migrated["analysis"]["skillGaps"], ["Postman"])
        self.assertEqual(migrated["cv"]["recommendedVersion"], "QA/UAT")
        self.assertEqual(self.service.get_match_settings()["data"]["settings"][0]["weight"], 27)
        row = self.service.store.get_offer_row(migrated["id"])
        raw = json.loads(row["legacy_payload_json"])
        self.assertEqual(raw["customUnsupportedField"], {"kept": True})
        events = self.service.get_application(migrated["id"])["data"]["events"]
        self.assertTrue({
            "imported", "status_changed", "applied", "follow_up_scheduled",
            "recruiter_updated", "note_changed",
        }.issubset({event["type"] for event in events}))

    def test_multiple_and_changed_migration_reuses_legacy_identity(self):
        first = migration_payload([offer(), offer("legacy-two", company="Sii")])
        self.service.migrate_local_storage(first)
        changed = migration_payload(
            [offer(company="Changed only in recovery evidence")],
            key="jobhunt-test-migration-0002",
        )
        result = self.service.migrate_local_storage(changed)["data"]
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["alreadyExisting"], 1)
        self.assertEqual(self.service.store.counts()["jobs"], 2)
        self.assertEqual(self.service.store.counts()["applications"], 2)

    def test_duplicate_legacy_id_fails_without_partial_canonical_import(self):
        payload = migration_payload([offer(), offer()], key="jobhunt-test-duplicate-0001")
        with self.assertRaisesRegex(JobhuntError, "Duplicate legacy ID"):
            self.service.migrate_local_storage(payload)
        counts = self.service.store.counts()
        self.assertEqual(counts["jobs"], 0)
        self.assertEqual(counts["applications"], 0)
        self.assertEqual(counts["events"], 0)
        self.assertEqual(counts["migrations"], 1)
        self.assertEqual(len(list((self.private / "backups").glob("local-storage-*.json"))), 1)

    def test_failed_import_transaction_rolls_back_every_domain_row(self):
        payload = migration_payload(
            [offer(), offer("legacy-two", company="Sii")],
            key="jobhunt-test-rollback-0001",
        )
        original = self.service.store._insert_offer
        calls = 0

        def fail_second(connection, item):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected failure")
            return original(connection, item)

        with mock.patch.object(self.service.store, "_insert_offer", side_effect=fail_second):
            with self.assertRaisesRegex(JobhuntError, "no canonical records"):
                self.service.migrate_local_storage(payload)
        counts = self.service.store.counts()
        self.assertEqual(counts["jobs"], 0)
        self.assertEqual(counts["applications"], 0)
        self.assertEqual(counts["events"], 0)
        self.assertEqual(counts["evaluations"], 0)
        self.assertEqual(counts["migrations"], 1)

    def test_expired_legacy_job_is_separate_from_application_status(self):
        expired = offer(status="expired", expiresAt="2026-09-01")
        self.service.migrate_local_storage(migration_payload([expired]))
        job = self.service.list_jobs()["data"]["jobs"][0]
        self.assertEqual(job["status"], "expired")
        self.assertEqual(job["applicationStatus"], "to_review")
        self.assertTrue(job["sourceExpired"])

    def test_missing_legacy_fields_migrate_as_unknown_without_losing_raw_shape(self):
        sparse = {
            "id": "legacy-sparse",
            "company": "Sparse Co",
            "source": {"url": "javascript:alert(1)"},
            "unexpected": [1, 2, 3],
        }
        result = self.service.migrate_local_storage(
            migration_payload([sparse], key="jobhunt-test-sparse-0001")
        )["data"]
        self.assertTrue(result["verified"])
        job = self.service.list_jobs()["data"]["jobs"][0]
        self.assertEqual(job["role"], "unknown")
        self.assertEqual(job["priority"], "unknown")
        self.assertEqual(job["source"]["url"], "")
        self.assertTrue(any("source URL" in warning for warning in result["warnings"]))
        row = self.service.store.get_offer_row(job["id"])
        self.assertEqual(json.loads(row["legacy_payload_json"])["unexpected"], [1, 2, 3])

    def test_create_update_transition_and_soft_delete_keep_history(self):
        created = self.service.create_job({
            "company": "Acme", "role": "Tester", "source": {"url": "https://example.test/acme"},
            "status": "to_review", "priority": "P2", "match": {"score": 60},
        })["data"]["job"]
        job_id = created["id"]
        updated = self.service.update_job(job_id, {
            "notes": "Remember this", "priority": "P1", "status": "worth_applying",
        })["data"]["job"]
        self.assertEqual(updated["notes"], "Remember this")
        self.assertEqual(updated["priority"], "P1")
        self.assertEqual(updated["applicationStatus"], "worth_applying")
        self.service.application_command(job_id, {"type": "applied"})
        application = self.service.get_application(job_id)["data"]
        self.assertEqual(application["application"]["status"], "applied")
        self.assertEqual(application["application"]["nextAction"], "follow_up")
        self.assertEqual(application["application"]["followUpDate"],
                         (date.today() + timedelta(days=7)).isoformat())
        self.assertIn("applied", {event["type"] for event in application["events"]})
        self.service.delete_job(job_id)
        self.assertEqual(self.service.list_jobs()["data"]["jobs"], [])
        hidden = self.service.store.get_offer_row(job_id, include_deleted=True)
        self.assertIsNotNone(hidden["deleted_at"])
        self.assertIn("deleted", {event["type"] for event in self.service.store.application_events(hidden["application_id"])})

    def test_application_projection_and_event_are_atomic(self):
        self.service.migrate_local_storage(migration_payload([offer(status="to_review", application={})]))
        job = self.service.list_jobs()["data"]["jobs"][0]
        before = self.service.get_application(job["id"])["data"]
        original = self.service.store._append_event

        def fail_schedule(connection, application_id, event):
            if event["type"] == "follow_up_scheduled":
                raise RuntimeError("injected event failure")
            return original(connection, application_id, event)

        with mock.patch.object(self.service.store, "_append_event", side_effect=fail_schedule):
            with self.assertRaises(RuntimeError):
                self.service.application_command(job["id"], {"type": "applied"})
        after = self.service.get_application(job["id"])["data"]
        self.assertEqual(after["application"]["status"], before["application"]["status"])
        self.assertEqual(after["events"], before["events"])

    def test_valid_malformed_and_oversized_logos(self):
        png = b"\x89PNG\r\n\x1a\nsmall"
        valid = offer(branding={"logoDataUrl": "data:image/png;base64," + base64.b64encode(png).decode("ascii")})
        result = self.service.migrate_local_storage(migration_payload([valid]))["data"]
        self.assertEqual(result["warnings"], [])
        job = self.service.list_jobs()["data"]["jobs"][0]
        self.assertTrue(job["branding"]["logoDataUrl"].startswith("data:image/png;base64,"))
        self.assertEqual(len(list((self.private / "assets" / "branding").glob("*.png"))), 1)
        stored_raw = json.loads(self.service.store.get_offer_row(job["id"])["legacy_payload_json"])
        self.assertNotIn("logoDataUrl", stored_raw["branding"])
        self.assertEqual(stored_raw["_jobhuntBrandingEvidence"]["status"], "stored")
        recovery = self.database.parent / result["recoverySnapshot"]["path"]
        recovered_offer = json.loads(recovery.read_text(encoding="utf-8"))["offers"][0]
        self.assertIn("logoDataUrl", recovered_offer["branding"])

        malformed_service = JobhuntService(self.root / "bad.sqlite", private_root=self.root / "bad-private")
        malformed_service.initialize()
        malformed = offer("bad", branding={"logoDataUrl": "data:image/png;base64,not-base64!"})
        malformed_result = malformed_service.migrate_local_storage(
            migration_payload([malformed], key="jobhunt-test-logo-bad")
        )["data"]
        self.assertTrue(any("logo" in warning.lower() for warning in malformed_result["warnings"]))

        large_service = JobhuntService(self.root / "large.sqlite", private_root=self.root / "large-private")
        large_service.initialize()
        oversized_raw = b"\x89PNG\r\n\x1a\n" + b"x" * (512 * 1024)
        oversized = offer("large", branding={"logoDataUrl": "data:image/png;base64," + base64.b64encode(oversized_raw).decode("ascii")})
        large_result = large_service.migrate_local_storage(
            migration_payload([oversized], key="jobhunt-test-logo-large")
        )["data"]
        self.assertTrue(any("512 KB" in warning for warning in large_result["warnings"]))


if __name__ == "__main__":
    unittest.main()

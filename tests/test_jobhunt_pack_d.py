import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobhunt_backend import JobhuntError, JobhuntService
from jobhunt_backend.ingestion.archive import StoredBlob
from jobhunt_backend.migrations import MIGRATIONS, SCHEMA_VERSION


FIXTURES = Path(__file__).parent / "fixtures" / "jobhunt"


def seed_pack_c_database(path: Path) -> None:
    now = "2026-09-18T10:00:00+00:00"
    with sqlite3.connect(path) as connection:
        for migration in MIGRATIONS[:4]:
            connection.executescript(migration.sql)
        connection.execute(
            "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(?,?,?,NULL)",
            [(item.version, now, item.checksum) for item in MIGRATIONS[:4]],
        )
        connection.execute(
            """INSERT INTO career_tracks(id,slug,name,purpose,status,countries_json,regions_cities_json,
                   remote_allowed,relocation_relevant,primary_currency,evaluation_policy_version,rationale,
                   notes,seed_key,created_at,updated_at)
               VALUES('track_old','old','Old Track','','exploring','[]','[]',NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO track_search_profiles(id,track_id,name,status,include_keywords_json,
                   exclude_keywords_json,countries_json,regions_cities_json,work_models_json,schedule_hints_json,
                   contract_hints_json,language_hints_json,seniority_hints_json,planned_source_keys_json,
                   created_at,updated_at)
               VALUES('profile_old','track_old','Old Search','enabled','[]','[]','[]','[]','[]','[]','[]','[]','[]',?, ?,?)""",
            (json.dumps(["nav", "unknown_legacy"]), now, now),
        )


class JobhuntPackDTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private"
        )
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def import_text(self, content="Exact QA advertisement\n", **extra):
        payload = {
            "sourceKey": "manual", "inputMode": "text", "contentType": "text/plain",
            "content": content, "externalListingId": "manual-1", "titleHint": "QA Tester",
            **extra,
        }
        return self.service.manual_import(payload)["data"]

    def test_pack_c_to_pack_d_migration_resolves_known_hints_and_preserves_unknown(self):
        database = self.root / "pack-c.sqlite"
        seed_pack_c_database(database)
        migrated = JobhuntService(database, private_root=self.root / "pack-c-private")
        migrated.initialize()
        self.assertEqual(migrated.store.schema_status()["version"], SCHEMA_VERSION)
        with migrated.store.read_connection() as connection:
            ledger = connection.execute(
                "SELECT version,checksum FROM jobhunt_schema_migrations ORDER BY version"
            ).fetchall()
            bindings = connection.execute(
                """SELECT d.source_key FROM search_profile_sources b
                   JOIN source_definitions d ON d.id=b.source_id
                   WHERE b.search_profile_id='profile_old'"""
            ).fetchall()
        self.assertEqual([row[0] for row in ledger], [item.version for item in MIGRATIONS])
        self.assertEqual([row[1] for row in ledger], [item.checksum for item in MIGRATIONS])
        self.assertEqual([row[0] for row in bindings], ["nav"])
        resolution = migrated.store.search_profile_source_resolution("profile_old")
        self.assertEqual(resolution, {"resolved": ["nav"], "unresolved": ["unknown_legacy"]})

    def test_source_and_policy_seeds_are_idempotent_and_live_sources_require_enablement(self):
        first = self.service.list_sources()["data"]["sources"]
        self.service.initialize()
        second = self.service.list_sources()["data"]["sources"]
        self.assertEqual(len(first), 10)
        self.assertEqual(len(second), 10)
        manual = next(item for item in second if item["key"] == "manual")
        self.assertTrue(manual["adapter"]["implemented"])
        self.assertEqual(manual["policy"]["operationalState"], "manual_only")
        nav = next(item for item in second if item["key"] == "nav")
        self.assertTrue(nav["adapter"]["implemented"])
        self.assertFalse(nav["policy"]["enabled"])
        self.assertEqual(nav["policy"]["operationalState"], "disabled")
        pracuj = next(item for item in second if item["key"] == "pracuj")
        self.assertTrue(pracuj["adapter"]["implemented"])
        self.assertFalse(pracuj["policy"]["enabled"])
        self.assertEqual(pracuj["policy"]["operationalState"], "disabled")
        jobbnorge = next(item for item in second if item["key"] == "jobbnorge")
        self.assertTrue(jobbnorge["adapter"]["implemented"])
        self.assertFalse(jobbnorge["policy"]["enabled"])
        self.assertEqual(jobbnorge["policy"]["operationalState"], "disabled")
        external = [item for item in second if item["key"] not in {"manual", "nav", "pracuj", "jobbnorge"}]
        self.assertTrue(all(not item["policy"]["enabled"] for item in external))
        self.assertTrue(all(item["policy"]["operationalState"] == "planned" for item in external))
        self.assertTrue(all(not item["adapter"]["implemented"] for item in external))

    def test_exact_text_bytes_hash_path_idempotency_and_changed_history(self):
        content = "  Exact text with CRLF\r\nsecond line\n"
        first = self.import_text(content, originalUrl="https://Example.test/jobs/1#fragment")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.assertEqual(first["capture"]["sha256"], digest)
        self.assertEqual(first["capture"]["changeState"], "first")
        self.assertTrue(first["blobCreated"])
        capture = self.service.get_raw_capture(first["capture"]["id"])["data"]
        self.assertEqual(capture["content"], content)
        expected = self.root / "private" / "raw" / "sha256" / digest[:2] / digest[2:4] / f"{digest}.txt"
        self.assertEqual(expected.read_bytes(), content.encode("utf-8"))

        repeated = self.import_text(content, originalUrl="https://Example.test/jobs/1#fragment")
        self.assertEqual(repeated["listing"]["id"], first["listing"]["id"])
        self.assertEqual(repeated["capture"]["id"], first["capture"]["id"])
        self.assertTrue(repeated["captureReused"])
        self.assertTrue(repeated["blobReused"])

        changed = self.import_text(content + "changed", originalUrl="https://Example.test/jobs/1#fragment")
        self.assertNotEqual(changed["capture"]["id"], first["capture"]["id"])
        history = self.service.list_listing_captures(first["listing"]["id"])["data"]["captures"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["changeState"], "changed")
        self.assertEqual(history[1]["changeState"], "first")

    def test_html_json_and_file_modes_preserve_safe_types(self):
        html = (FIXTURES / "manual-qa.html").read_text(encoding="utf-8")
        html_result = self.service.manual_import({
            "sourceKey": "pracuj", "inputMode": "html", "contentType": "text/html",
            "content": html, "originalUrl": "https://example.test/jobs/html",
        })["data"]
        self.assertEqual(html_result["capture"]["contentType"], "text/html")
        self.assertEqual(self.service.get_raw_capture(html_result["capture"]["id"])["data"]["content"], html)

        json_bytes = (FIXTURES / "manual-qa.json").read_bytes()
        file_result = self.service.manual_import({
            "sourceKey": "manual", "inputMode": "file", "filename": "synthetic.json",
            "declaredContentType": "application/octet-stream",
            "contentBase64": base64.b64encode(json_bytes).decode("ascii"),
        })["data"]
        self.assertEqual(file_result["capture"]["contentType"], "application/json")
        self.assertEqual(self.service.get_raw_capture(file_result["capture"]["id"])["data"]["content"].encode(), json_bytes)

    def test_identical_bytes_reuse_one_blob_while_capture_mime_stays_observation_specific(self):
        text = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "same-text",
            "inputMode": "text", "contentType": "text/plain", "content": "same bytes",
        })["data"]
        html = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "same-html",
            "inputMode": "html", "contentType": "text/html", "content": "same bytes",
        })["data"]
        self.assertEqual(text["capture"]["sha256"], html["capture"]["sha256"])
        self.assertTrue(html["blobReused"])
        self.assertEqual(text["capture"]["contentType"], "text/plain")
        self.assertEqual(html["capture"]["contentType"], "text/html")
        self.assertEqual(self.service.store.ingestion_metrics()["uniqueBlobs"], 1)

    def test_listing_context_hints_lifecycle_and_canonical_job_seam(self):
        track = self.service.list_tracks()["data"]["tracks"][0]
        profile = self.service.get_track(track["id"])["data"]["searchProfiles"][0]
        job = self.service.create_job({"company": "Synthetic", "role": "QA"})["data"]["job"]
        result = self.import_text(
            "Context capture", externalListingId="context-1", titleHint="Source title",
            companyHint="Source company", locationHint="Remote", trackId=track["id"],
            searchProfileId=profile["id"], canonicalJobId=job["id"], lifecycleState="expired",
        )
        detail = self.service.get_source_listing(result["listing"]["id"])["data"]["listing"]
        self.assertEqual(detail["hints"]["title"], "Source title")
        self.assertEqual(detail["lifecycleState"], "expired")
        self.assertEqual(detail["canonicalJobId"], job["id"])
        self.assertEqual(detail["tracks"][0]["id"], track["id"])
        self.assertEqual(detail["searchProfiles"][0]["id"], profile["id"])

    def test_validation_bounds_mime_extension_url_and_json(self):
        cases = [
            ({"inputMode": "text", "contentType": "text/html", "content": "x"}, "invalid_manual_mime"),
            ({"inputMode": "json", "contentType": "application/json", "content": "{"}, "invalid_manual_json"),
            ({"inputMode": "text", "contentType": "text/plain", "content": "x", "originalUrl": "file:///tmp/job"}, "invalid_source_url"),
            ({"inputMode": "file", "filename": "bad.exe", "contentBase64": "eA=="}, "invalid_manual_file"),
            ({"inputMode": "text", "contentType": "text/plain", "content": "x" * (1024 * 1024 + 1)}, "raw_capture_too_large"),
        ]
        for payload, code in cases:
            with self.subTest(code=code), self.assertRaises(JobhuntError) as caught:
                self.service.manual_import({"sourceKey": "manual", **payload})
            self.assertEqual(caught.exception.code, code)

    def test_archive_health_detects_missing_corrupt_and_orphan_without_repair(self):
        first = self.import_text("missing")
        capture = self.service.store.get_capture(first["capture"]["id"])
        path = self.root / "private" / capture["relative_path"]
        path.unlink()
        missing = self.service.storage_health()["data"]
        self.assertEqual(missing["missingCount"], 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"corrupt")
        corrupt = self.service.storage_health()["data"]
        self.assertEqual(corrupt["corruptCount"], 1)
        orphan = self.root / "private" / "raw" / "sha256" / "aa" / "bb" / ("a" * 64 + ".txt")
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("orphan", encoding="utf-8")
        health = self.service.storage_health()["data"]
        self.assertEqual(health["orphanCount"], 1)
        self.assertTrue(path.exists())
        self.assertTrue(orphan.exists())

    def test_archive_write_failure_and_existing_hash_mismatch_create_no_db_rows(self):
        with patch.object(self.service.raw_archive, "store", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.import_text("write failure")
        self.assertEqual(self.service.store.ingestion_metrics()["captures"], 0)

        content = b"verified bytes"
        digest = hashlib.sha256(content).hexdigest()
        target = self.root / "private" / "raw" / "sha256" / digest[:2] / digest[2:4] / f"{digest}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"wrong")
        with self.assertRaises(JobhuntError) as caught:
            self.import_text(content.decode())
        self.assertEqual(caught.exception.code, "raw_blob_integrity_failed")
        self.assertEqual(self.service.store.ingestion_metrics()["captures"], 0)

    def test_raw_capture_database_rows_are_immutable(self):
        result = self.import_text("immutable")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.service.store.transaction() as connection:
                connection.execute("UPDATE raw_captures SET source_url='https://changed.test' WHERE id=?", (result["capture"]["id"],))


if __name__ == "__main__":
    unittest.main()

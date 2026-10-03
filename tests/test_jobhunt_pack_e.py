import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntService
from jobhunt_backend.migrations import MIGRATIONS, SCHEMA_VERSION


FIXTURES = Path(__file__).parent / "fixtures" / "jobhunt"


def seed_pack_d_database(path: Path) -> None:
    now = "2026-09-18T10:00:00+00:00"
    with sqlite3.connect(path) as connection:
        for migration in MIGRATIONS[:5]:
            connection.executescript(migration.sql)
        connection.execute(
            "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(?,?,?,NULL)",
            [(item.version, now, item.checksum) for item in MIGRATIONS[:5]],
        )


class JobhuntPackETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private"
        )
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def import_fixture(self, name: str, *, external_id: str, title_hint=None):
        path = FIXTURES / name
        mime = "text/html" if path.suffix == ".html" else "application/json"
        mode = "html" if path.suffix == ".html" else "json"
        return self.service.manual_import({
            "sourceKey": "manual", "externalListingId": external_id,
            "inputMode": mode, "contentType": mime,
            "content": path.read_text(encoding="utf-8"), "titleHint": title_hint,
        })["data"]

    def test_pack_d_to_e_migration_and_fresh_schema(self):
        database = self.root / "pack-d.sqlite"
        seed_pack_d_database(database)
        migrated = JobhuntService(database, private_root=self.root / "migrated-private")
        migrated.initialize()
        self.assertEqual(migrated.store.schema_status()["version"], SCHEMA_VERSION)
        with migrated.store.read_connection() as connection:
            versions = [row[0] for row in connection.execute(
                "SELECT version FROM jobhunt_schema_migrations ORDER BY version"
            )]
            fact_columns = {row[1] for row in connection.execute("PRAGMA table_info(extracted_facts)")}
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertEqual(versions, [item.version for item in MIGRATIONS])
        self.assertTrue({"value_text", "value_number", "value_boolean", "value_json"}.issubset(fact_columns))
        self.assertTrue({"review_items", "human_overrides", "canonical_job_projections"}.issubset(tables))

    def test_json_ld_facts_evidence_unknown_negative_normalization_and_idempotency(self):
        imported = self.import_fixture("pack-e-jobposting.json", external_id="jsonld-1")
        first = self.service.extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual([run["extractorKind"] for run in first["runs"]], ["manual_hints", "json_ld_jobposting"])
        run = next(item for item in first["runs"] if item["extractorKind"] == "json_ld_jobposting")
        detail = self.service.get_extraction_facts(run["id"])["data"]
        facts = detail["facts"]
        by_type = {}
        for fact in facts:
            by_type.setdefault(fact["type"], []).append(fact)
        self.assertEqual(by_type["title"][0]["value"], "QA Engineer")
        self.assertEqual(by_type["salary_min"][0]["value"], 50000.0)
        self.assertEqual(by_type["salary_min"][0]["currency"], "NOK")
        self.assertEqual(by_type["salary_min"][0]["period"], "month")
        self.assertIn("pointer", by_type["salary_min"][0]["evidence"])
        norwegian = next(fact for fact in by_type["language"] if fact["value"] == "Norwegian")
        self.assertEqual(norwegian["state"], "explicit_negative")
        self.assertEqual(norwegian["requirementPreference"], "required")
        self.assertFalse(any(fact["type"] == "shift_work" for fact in facts))
        sql = next(fact for fact in by_type["skill"] if fact["value"] == "SQL")
        self.assertEqual(sql["sourceWording"], "SQL")
        self.assertEqual(sql["normalization"]["conceptKey"], "SQL")
        self.assertEqual(sql["normalization"]["ruleVersion"], "normalization@1")
        open_fact = next(fact for fact in by_type["other"] if fact["sourceField"] == "companyTransport")
        self.assertEqual(open_fact["value"], "Bus from Bergen every Monday")
        self.assertEqual(first["projection"]["outcome"], "created")
        projected_job = self.service.get_job(first["projection"]["canonicalJobId"])["data"]["job"]
        self.assertEqual(projected_job["evaluationSource"], "none")
        self.assertIsNone(projected_job["match"]["score"])

        second = self.service.extract_capture(imported["capture"]["id"])["data"]
        self.assertTrue(all(run["reused"] for run in second["runs"]))
        self.assertEqual(first["projection"]["projectionId"], second["projection"]["projectionId"])
        with self.service.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0], 2)
            fact_count = connection.execute("SELECT COUNT(*) FROM extracted_facts").fetchone()[0]
            self.assertEqual(fact_count, len(facts))
            fact_id = connection.execute("SELECT id FROM extracted_facts LIMIT 1").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            with self.service.store.transaction() as connection:
                connection.execute("UPDATE extracted_facts SET confidence=0.1 WHERE id=?", (fact_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.service.store.transaction() as connection:
                connection.execute("UPDATE extraction_runs SET status='failed' WHERE id=?", (run["id"],))

    def test_html_is_inert_extracts_jobposting_and_reviews_malformed_json_ld(self):
        imported = self.import_fixture("pack-e-jobposting.html", external_id="html-1")
        result = self.service.extract_capture(imported["capture"]["id"])["data"]
        kinds = {run["extractorKind"]: run for run in result["runs"]}
        self.assertIn("json_ld_jobposting", kinds)
        self.assertIn("html_metadata", kinds)
        self.assertGreater(kinds["json_ld_jobposting"]["factCount"], 0)
        self.assertGreater(kinds["json_ld_jobposting"]["warningCount"], 0)
        job = self.service.get_job(result["projection"]["canonicalJobId"])["data"]
        self.assertEqual(job["job"]["role"], "HTML QA Engineer")
        self.assertEqual(job["provenance"]["ruleVersion"], "projection@1")
        reviews = self.service.list_reviews()["data"]["items"]
        self.assertIn("malformed_structured_metadata", {item["reason"] for item in reviews})
        preview = self.service.get_raw_capture(imported["capture"]["id"])["data"]
        self.assertIn("globalThis.shouldNeverRun", preview["content"])
        self.assertEqual(preview["rendering"], "inert_text_only")

    def test_structured_json_preserves_open_fact_and_explicit_false(self):
        imported = self.import_fixture("pack-e-structured.json", external_id="structured-1")
        result = self.service.extract_capture(imported["capture"]["id"])["data"]
        run = next(item for item in result["runs"] if item["extractorKind"] == "json_structured")
        facts = self.service.get_extraction_facts(run["id"])["data"]["facts"]
        shift = next(fact for fact in facts if fact["type"] == "shift_work")
        self.assertIs(shift["value"], False)
        self.assertEqual(shift["state"], "explicit_negative")
        self.assertTrue(any(fact["type"] == "other" and fact["sourceField"] == "companyTransport" for fact in facts))
        self.assertTrue(any(fact["normalization"] and fact["normalization"]["conceptKey"] == "POSTMAN" for fact in facts))
        self.assertTrue(any(fact["value"] == "Playwright" and fact["requirementPreference"] == "preferred" for fact in facts))
        reviews = self.service.list_reviews()["data"]["items"]
        self.assertIn("unsupported_unexpected_fact", {item["reason"] for item in reviews})

    def test_insufficient_identity_creates_review_not_fake_job(self):
        imported = self.service.manual_import({
            "sourceKey": "manual", "inputMode": "text", "contentType": "text/plain",
            "content": "Unstructured prose is deliberately not parsed.", "externalListingId": "text-no-hint",
        })["data"]
        result = self.service.extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(result["projection"]["outcome"], "review_required")
        self.assertIsNone(result["projection"]["canonicalJobId"])
        reviews = self.service.list_reviews()["data"]["items"]
        self.assertEqual(reviews[0]["reason"], "insufficient_identity")
        self.assertEqual(self.service.store.visible_job_count(), 0)

    def test_invalid_salary_range_is_retained_for_review_but_not_projected(self):
        imported = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "invalid-salary",
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps({
                "title": "Synthetic role",
                "salary": {"min": 70000, "max": 60000, "currency": "NOK", "period": "month"},
            }),
        })["data"]
        result = self.service.extract_capture(imported["capture"]["id"])["data"]
        structured = next(run for run in result["runs"] if run["extractorKind"] == "json_structured")
        self.assertEqual(structured["status"], "completed_with_warnings")
        facts = self.service.get_extraction_facts(structured["id"])["data"]["facts"]
        salary = [fact for fact in facts if fact["type"] in {"salary_min", "salary_max"}]
        self.assertTrue(all(fact["validationState"] == "invalid" for fact in salary))
        job = self.service.get_job(result["projection"]["canonicalJobId"])["data"]["job"]
        self.assertFalse(job["salary"]["isKnown"])
        self.assertIn("conflicting_salary", {
            item["reason"] for item in self.service.list_reviews()["data"]["items"]
        })

    def test_reprocessing_conflicts_preserve_history_and_human_override_wins(self):
        first = self.import_fixture("pack-e-conflict-v1.json", external_id="conflict-1")
        first_result = self.service.extract_capture(first["capture"]["id"])["data"]
        job_id = first_result["projection"]["canonicalJobId"]
        self.service.application_command(job_id, {"type": "applied"})
        self.service.update_profile({"headline": "Stable profile"})
        assessment = self.service.start_assessment({
            "instrumentId": "career-work-preferences", "instrumentVersion": "1.0.0",
        })["data"]["run"]
        track_id = self.service.list_tracks()["data"]["tracks"][0]["id"]
        self.service.set_job_tracks(job_id, {"trackIds": [track_id], "origin": "manual"})
        app_before = self.service.get_application(job_id)["data"]
        profile_before = self.service.get_profile()["data"]["profile"]

        second = self.import_fixture("pack-e-conflict-v2.json", external_id="conflict-1")
        second_result = self.service.extract_capture(second["capture"]["id"])["data"]
        self.assertEqual(second_result["projection"]["canonicalJobId"], job_id)
        reviews = self.service.list_reviews()["data"]["items"]
        reasons = {item["reason"] for item in reviews}
        self.assertIn("conflicting_salary", reasons)
        self.assertIn("conflicting_location", reasons)
        self.assertEqual(self.service.get_application(job_id)["data"], app_before)
        self.assertEqual(self.service.get_profile()["data"]["profile"], profile_before)
        self.assertEqual(self.service.get_assessment_run(assessment["id"])["data"]["run"], assessment)
        self.assertTrue(next(item for item in self.service.get_job_tracks(job_id)["data"]["tracks"] if item["trackId"] == track_id)["assigned"])

        override = self.service.create_override(job_id, {
            "field": "salary_min", "value": 55000, "reason": "Confirmed with recruiter",
        })["data"]
        self.assertEqual(override["override"]["author"], "local_user")
        self.assertEqual(self.service.get_job(job_id)["data"]["job"]["salary"]["min"], 55000)
        rerun = self.service.extract_capture(second["capture"]["id"])["data"]
        self.assertTrue(all(run["reused"] for run in rerun["runs"]))
        job_facts = self.service.get_job_facts(job_id)["data"]
        self.assertEqual(job_facts["projection"]["snapshot"]["salary_min"], 55000)
        self.assertIn(override["override"]["id"], job_facts["projection"]["appliedOverrideIds"])
        salary_values = {fact["value"] for fact in job_facts["facts"] if fact["type"] == "salary_min"}
        self.assertEqual(salary_values, {50000.0, 60000.0})


if __name__ == "__main__":
    unittest.main()

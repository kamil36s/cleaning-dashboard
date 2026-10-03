import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntError, JobhuntService
from jobhunt_backend.assessments import AssessmentManifestLoader, ManifestValidationError, score_assessment
from jobhunt_backend.assessments.loader import definition_hash
from jobhunt_backend.migrations import MIGRATION_1_SQL, MIGRATION_2_SQL, MIGRATIONS, SCHEMA_VERSION


def seed_pack_a_database(path: Path) -> None:
    migration = MIGRATIONS[0]
    now = "2026-09-18T10:00:00+00:00"
    connection = sqlite3.connect(path)
    connection.executescript(MIGRATION_1_SQL)
    connection.execute(
        "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
    )
    connection.execute(
        "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(1,?,?,NULL)",
        (now, migration.checksum),
    )
    connection.execute(
        """INSERT INTO canonical_jobs(
               id,legacy_id,legacy_fingerprint,company,role_title,seniority,location_city,
               location_country,work_mode,hybrid_details,contract_type,contract_details,
               salary_min,salary_max,salary_currency,salary_period,salary_tax_type,salary_is_known,
               source_name,source_url,source_captured_at,expires_at,original_text,requirements_json,
               branding_path,branding_mime,branding_sha256,legacy_payload_json,created_at,updated_at,
               archived_at,deleted_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "job_pack_a", "legacy_pack_a", "fingerprint-pack-a", "Pack A Co", "Tester",
            "unknown", "Krakow", "Poland", "hybrid", "unknown", "UoP", "unknown",
            None, None, "unknown", "unknown", "unknown", 0, "manual", None, None, None,
            "original", "{}", None, None, None, "{}", now, now, None, None,
        ),
    )
    connection.execute(
        """INSERT INTO applications(
               id,job_id,current_status,source_expired,priority,next_action,date_applied,
               follow_up_date,recruiter_name,recruiter_contact,notes,created_at,updated_at
           ) VALUES('app_pack_a','job_pack_a','to_review',0,'P2','analyze',NULL,NULL,NULL,NULL,'',?,?)""",
        (now, now),
    )
    connection.execute(
        """INSERT INTO legacy_evaluation_snapshots(
               id,job_id,snapshot_kind,match_score,match_category,match_summary,is_experimental,
               green_flags_json,red_flags_json,skill_gaps_json,fit_reasons_json,
               recommended_cv_version,cv_bullets_json,created_at,updated_at
           ) VALUES('eval_pack_a','job_pack_a','legacy_imported',72,'good_fit','legacy',1,'[]','[]','[]','[]','unknown','[]',?,?)""",
        (now, now),
    )
    connection.commit()
    connection.close()


class JobhuntPackBTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private"
        )
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_schema_and_pack_a_to_pack_b_migration_preserve_pack_a_rows(self):
        self.assertEqual(self.service.store.schema_status()["version"], SCHEMA_VERSION)
        old_database = self.root / "pack-a.sqlite"
        seed_pack_a_database(old_database)
        migrated = JobhuntService(old_database, private_root=self.root / "pack-a-private")
        migrated.initialize()
        self.assertEqual(migrated.store.schema_status()["version"], SCHEMA_VERSION)
        self.assertEqual(migrated.store.counts()["jobs"], 1)
        self.assertEqual(migrated.list_jobs()["data"]["jobs"][0]["company"], "Pack A Co")
        self.assertEqual(migrated.get_profile()["data"]["profile"]["revision"], 0)
        migrated.initialize()
        with migrated.store.read_connection() as connection:
            ledger = connection.execute(
                "SELECT version,checksum FROM jobhunt_schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual([row[0] for row in ledger], [item.version for item in MIGRATIONS])
        self.assertEqual(ledger[1][1], MIGRATIONS[1].checksum)
        self.assertEqual(ledger[2][1], MIGRATIONS[2].checksum)

    def test_existing_pack_b_schema_migrates_without_rewriting_migration_two(self):
        old_database = self.root / "pack-b-v2.sqlite"
        with sqlite3.connect(old_database) as connection:
            connection.executescript(MIGRATION_1_SQL)
            connection.executescript(MIGRATION_2_SQL)
            connection.execute(
                "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
            )
            connection.executemany(
                "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(?,?,?,NULL)",
                [
                    (1, "2026-09-18T10:00:00+00:00", MIGRATIONS[0].checksum),
                    (2, "2026-09-18T10:00:00+00:00", MIGRATIONS[1].checksum),
                ],
            )

        migrated = JobhuntService(old_database, private_root=self.root / "pack-b-v2-private")
        migrated.initialize()

        with migrated.store.read_connection() as connection:
            ledger = connection.execute(
                "SELECT version,checksum,backup_path FROM jobhunt_schema_migrations ORDER BY version"
            ).fetchall()
            initial = connection.execute(
                "SELECT fingerprint,snapshot_json,changed_at FROM career_profile_revisions WHERE revision=0"
            ).fetchone()
            connection.execute(
                "INSERT INTO career_profile_revisions(revision,fingerprint,snapshot_json,changed_at) VALUES(1,?,?,?)",
                (initial[0], initial[1], initial[2]),
            )
            connection.commit()

        self.assertEqual([row[0] for row in ledger], [item.version for item in MIGRATIONS])
        self.assertEqual(ledger[1][1], "sha256:f32167233d2b211b3246c895495aed46812526a5909692f10b7aa171867422df")
        self.assertTrue(ledger[2][2])
        self.assertTrue((old_database.parent / ledger[2][2]).is_file())

    def test_profile_crud_unknown_semantics_and_reproducible_revisions(self):
        initial = self.service.get_profile()["data"]["profile"]
        self.assertIsNone(initial["currentRoleTitle"])
        self.assertEqual(initial["skills"], [])
        updated = self.service.update_profile({
            "currentRoleTitle": "QA Analyst", "headline": None,
            "professionalSummary": "Structured testing experience",
        })["data"]["profile"]
        self.assertEqual(updated["revision"], 1)
        self.assertNotEqual(updated["fingerprint"], initial["fingerprint"])

        experience = self.service.save_profile_record("experience", {
            "jobTitle": "QA Analyst", "employer": "ACME", "isCurrent": None,
            "domains": ["finance"], "description": "Manual evidence",
        })["data"]
        self.assertIsNone(experience["record"]["isCurrent"])
        experience_id = experience["record"]["id"]
        skill = self.service.save_profile_record("skills", {
            "displayName": "API testing", "level": None, "confidence": 4,
            "developmentInterest": 5, "evidenceNotes": "Postman projects",
        })["data"]["record"]
        self.assertIsNone(skill["level"])
        self.assertEqual(skill["confidence"], 4)
        self.assertEqual(skill["developmentInterest"], 5)
        self.service.save_profile_record("preferences", {
            "dimensionKey": "remote_work", "value": True, "importance": 4,
            "confidence": 3,
        })
        self.service.save_profile_record("constraints", {
            "constraintKey": "minimum_salary", "value": {"amount": 12000, "currency": "PLN", "period": "month"},
            "isHard": True,
        })
        profile = self.service.get_profile()["data"]["profile"]
        self.assertGreaterEqual(profile["revision"], 5)
        revision = self.service.store.profile_revision(profile["revision"])
        self.assertEqual(revision["fingerprint"], profile["fingerprint"])
        self.assertEqual(revision["snapshot"]["skills"][0]["display_name"], "API testing")

        changed = self.service.save_profile_record(
            "experience", {"employer": "ACME Group"}, record_id=experience_id
        )["data"]["record"]
        self.assertEqual(changed["employer"], "ACME Group")
        self.service.delete_profile_record("experience", experience_id)
        self.assertEqual(self.service.get_profile()["data"]["profile"]["experience"], [])

    def test_all_profile_entity_families_persist(self):
        records = {
            "education": {"institution": "University", "fieldProgram": "Testing"},
            "certifications": {"name": "ISTQB", "issuer": "ISTQB"},
            "languages": {"languageName": "English", "proficiency": "C1", "proficiencyScheme": "CEFR", "confidence": 4},
            "evidence": {"targetType": "profile", "fieldName": "headline", "notes": "Reviewed manually"},
        }
        for kind, payload in records.items():
            self.service.save_profile_record(kind, payload)
        profile = self.service.get_profile()["data"]["profile"]
        self.assertEqual(profile["education"][0]["institution"], "University")
        self.assertEqual(profile["certifications"][0]["name"], "ISTQB")
        self.assertEqual(profile["languages"][0]["proficiency"], "C1")
        self.assertEqual(profile["evidence"][0]["origin"], "manual_user")

    def test_manifest_validation_hash_stability_and_catalog(self):
        loader = AssessmentManifestLoader()
        manifests = loader.load(refresh=True)
        self.assertEqual(loader.errors, [])
        self.assertEqual({item["instrumentId"] for item in manifests}, {
            "onet-interest-profiler-short-form",
            "ipip-50-big-five-markers",
            "career-work-preferences",
        })
        for manifest in manifests:
            self.assertEqual(manifest["definitionHash"], definition_hash(manifest))
        catalog = self.service.list_assessments()["data"]["instruments"]
        self.assertTrue(all(item["available"] for item in catalog))
        self.assertEqual({item["status"] for item in catalog}, {"not_started"})

    def test_malformed_manifest_is_rejected_and_not_loaded(self):
        directory = self.root / "manifests"
        directory.mkdir()
        (directory / "broken.json").write_text(json.dumps({"instrumentId": "broken"}), encoding="utf-8")
        loader = AssessmentManifestLoader(directory)
        self.assertEqual(loader.load(), [])
        self.assertEqual(len(loader.errors), 1)

    def test_draft_resume_answer_update_completion_immutability_and_retake(self):
        started = self.service.start_assessment({"instrumentId": "career-work-preferences"})["data"]
        run_id = started["run"]["id"]
        first_item = started["instrument"]["items"][0]["id"]
        self.service.save_assessment_responses(run_id, {"responses": {first_item: 2}})
        resumed = self.service.get_assessment_run(run_id)["data"]["run"]
        self.assertEqual(resumed["responses"][first_item], 2)
        self.service.save_assessment_responses(run_id, {"responses": {first_item: 5}})
        self.assertEqual(self.service.get_assessment_run(run_id)["data"]["run"]["responses"][first_item], 5)
        with self.assertRaisesRegex(JobhuntError, "missing required responses"):
            self.service.complete_assessment(run_id)

        answers = {item["id"]: 4 for item in started["instrument"]["items"]}
        self.service.save_assessment_responses(run_id, {"responses": answers})
        completed = self.service.complete_assessment(run_id)["data"]["run"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["instrumentVersion"], "1.0.0")
        self.assertEqual(completed["scores"][0]["normalizedScore"], 75.0)
        with self.assertRaisesRegex(JobhuntError, "immutable"):
            self.service.save_assessment_responses(run_id, {"responses": {first_item: 1}})

        retake = self.service.start_assessment({"instrumentId": "career-work-preferences"})["data"]["run"]
        self.assertNotEqual(retake["id"], run_id)
        history = next(
            item for item in self.service.list_assessments()["data"]["instruments"]
            if item["instrumentId"] == "career-work-preferences"
        )["history"]
        self.assertEqual({item["id"] for item in history}, {run_id, retake["id"]})

    def test_ipip_reverse_keying_is_deterministic(self):
        manifest = self.service.assessment_loader.get("ipip-50-big-five-markers")
        all_fives = {item["id"]: 5 for item in manifest["items"]}
        first = score_assessment(manifest, all_fives)
        second = score_assessment(manifest, all_fives)
        self.assertEqual(first, second)
        scores = {item["dimension"]: item["rawScore"] for item in first}
        self.assertEqual(scores["extraversion"], 30)
        self.assertEqual(scores["emotional_stability"], 18)
        self.assertEqual(scores["intellect_imagination"], 38)
        with self.assertRaises(ManifestValidationError):
            score_assessment(manifest, {"ipip-01": 5})

    def test_database_triggers_protect_completed_responses_scores_and_run(self):
        started = self.service.start_assessment({"instrumentId": "career-work-preferences"})["data"]
        run_id = started["run"]["id"]
        answers = {item["id"]: 3 for item in started["instrument"]["items"]}
        self.service.save_assessment_responses(run_id, {"responses": answers})
        self.service.complete_assessment(run_id)
        with self.service.store.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE assessment_responses SET raw_answer_json='1' WHERE run_id=?",
                    (run_id,),
                )
        with self.service.store.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE assessment_scores SET raw_score=0 WHERE run_id=?",
                    (run_id,),
                )
        with self.service.store.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM assessment_runs WHERE id=?", (run_id,))


if __name__ == "__main__":
    unittest.main()

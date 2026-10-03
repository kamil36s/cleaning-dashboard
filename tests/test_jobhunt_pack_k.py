import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from jobhunt_backend import JobhuntService
from jobhunt_backend.skill_intelligence import SKILL_INTELLIGENCE_VERSION


class JobhuntPackKTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private", environment={}
        )
        self.service.initialize()
        self.track_id = "track_seed_qa_poland"
        self.jobs = {}
        self.fact_ids = {}

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def text_fact(fact_type, wording, requirement="unknown", concept_id=None):
        value = {
            "namespace": "job", "fact_type": fact_type, "source_field": "pack_k_fixture",
            "source_wording": wording, "value_type": "text", "value_text": wording,
            "value_number": None, "value_boolean": None, "value_json": None,
            "requirement_preference": requirement, "state": "explicit_positive",
            "confidence": 1.0, "evidence_locator": {"kind": "fixture"},
            "validation_state": "valid", "normalization_state": "unmapped",
        }
        if concept_id:
            value["normalization"] = {
                "concept_id": concept_id, "rule_version": "normalization@1", "confidence": 1.0,
            }
        return value

    @staticmethod
    def number_fact(fact_type, value):
        return {
            "namespace": "job", "fact_type": fact_type, "source_field": "pack_k_fixture",
            "source_wording": str(value), "value_type": "number", "value_text": None,
            "value_number": value, "value_boolean": None, "value_json": None,
            "requirement_preference": "unknown", "state": "explicit_positive",
            "confidence": 1.0, "evidence_locator": {"kind": "fixture"},
            "validation_state": "valid", "normalization_state": "not_applicable",
        }

    def create_job(self, key, facts=None):
        content = json.dumps({
            "title": f"QA Engineer {key}", "company": f"Pack K {key}",
            "city": "Krakow", "country": "Poland", "datePosted": "2026-09-23",
        })
        imported = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": f"pack-k-{key}",
            "inputMode": "json", "contentType": "application/json", "content": content,
        })["data"]
        extracted = self.service.extract_capture(imported["capture"]["id"])["data"]
        job_id = extracted["projection"]["canonicalJobId"]
        if facts:
            digest = hashlib.sha256(f"{key}-{uuid.uuid4()}".encode()).hexdigest()
            run, _ = self.service.store.save_extraction_batch(
                capture_id=imported["capture"]["id"], extractor_kind="manual_hints",
                extractor_version=f"pack-k-fixture@{key}", input_hash=digest,
                output_schema_version="jobhunt-facts@1", facts=facts, warnings=[],
                now="2026-09-23T12:00:00+00:00",
            )
            self.fact_ids[key] = [
                item["id"] for item in self.service.store.facts_for_run(run["id"])
            ]
            self.service.store.project_listing(
                imported["listing"]["id"], capture_id=imported["capture"]["id"],
                now="2026-09-23T12:01:00+00:00",
            )
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        self.jobs[key] = job_id
        return job_id

    def seed_population(self):
        sql = "concept_skill_sql"
        playwright = "concept_tool_playwright"
        norwegian = "concept_spoken_norwegian"
        required_sql = self.text_fact("skill", "SQL", "required", sql)
        self.create_job("a", [required_sql, required_sql.copy(), required_sql.copy()])
        self.create_job("b", [
            required_sql.copy(), self.text_fact("tool", "Playwright", "required", playwright),
        ])
        self.create_job("c", [
            required_sql.copy(), self.text_fact("language", "Norwegian C1", "required", norwegian),
        ])
        self.create_job("d", [
            required_sql.copy(), self.number_fact("salary_min", 40),
            self.number_fact("salary_max", 50),
            self.text_fact("salary_currency", "PLN"),
            self.text_fact("salary_period", "month"),
            self.text_fact("salary_tax_type", "gross"),
        ])
        self.create_job("e", [self.text_fact("skill", "SQL", "preferred", sql)])
        self.create_job("f", [self.text_fact("skill", "SQL", "optional", sql)])
        self.create_job("g", [self.text_fact("skill", "SQL", "unknown", sql)])
        self.create_job("h", [
            self.text_fact("skill", "SQL", "required", sql),
            self.text_fact("skill", "SQL", "preferred", sql),
        ])
        self.create_job("i", [self.text_fact("skill", "Structured Query Language", "required")])
        self.create_job("j")
        self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "SQL", "level": 0,
            "confidence": 5, "developmentInterest": 4,
        })
        self.service.save_profile_record("skills", {
            "displayName": "Playwright", "normalizedKey": "PLAYWRIGHT", "level": 0,
            "confidence": 5, "developmentInterest": 5,
        })
        self.service.save_profile_record("constraints", {
            "constraintKey": "minimum_salary",
            "value": {"amount": 100, "currency": "PLN", "period": "month", "taxType": "gross"},
            "isHard": True,
        })
        for key in ("a", "b", "c", "d"):
            self.service.explicit_evaluate_job_track(self.jobs[key], self.track_id)

    def intelligence(self):
        return self.service.get_track_skill_intelligence(self.track_id)["data"]

    def test_distinct_job_demand_requirement_classes_unknowns_and_unlocks(self):
        self.seed_population()
        data = self.intelligence()
        sql = next(item for item in data["skills"] if item["reference"] == "skill:SQL")

        self.assertEqual(data["population"]["canonicalJobDenominator"], 10)
        self.assertEqual(data["coverage"]["jobsWithSkillEvidence"], 9)
        self.assertEqual(data["coverage"]["jobsWithoutSkillEvidence"], 1)
        self.assertEqual(data["coverage"]["jobsWithCurrentEvaluations"], 4)
        self.assertEqual(sql["demand"]["jobsMentioning"], 8)
        self.assertEqual(sql["demand"]["requiredJobs"], 4)
        self.assertEqual(sql["demand"]["preferredJobs"], 1)
        self.assertEqual(sql["demand"]["optionalJobs"], 1)
        self.assertEqual(sql["demand"]["unknownRequirementJobs"], 1)
        self.assertEqual(sql["demand"]["ambiguousRequirementJobs"], 1)
        self.assertEqual(sql["demand"]["percentAllTrackJobs"], 80.0)
        self.assertEqual(sql["user"]["requiredGaps"], 4)
        self.assertEqual(sql["opportunity"]["strictJobsUnlocked"], 1)
        self.assertEqual(sql["opportunity"]["potentialJobsUnlocked"], 1)
        self.assertEqual(sql["opportunity"]["multiGapOpportunities"], 1)
        self.assertEqual(sql["priority"]["classification"], "medium")
        self.assertTrue(sql["priority"]["reasons"])
        self.assertNotIn("score", sql["priority"])
        self.assertTrue(sql["profileEvidence"]["exists"])
        self.assertEqual(sql["profileEvidence"]["level"], 0)
        self.assertEqual(data["versions"]["skillIntelligence"], SKILL_INTELLIGENCE_VERSION)

        detail = self.service.get_track_skill_detail(
            self.track_id, "skill:SQL"
        )["data"]["skill"]
        self.assertEqual(len(detail["findingJobs"]), 4)
        self.assertTrue(any(
            finding["status"] == "gap"
            for job in detail["findingJobs"] for finding in job["findings"]
        ))
        self.assertEqual([item["id"] for item in detail["strictUnlockJobs"]], [self.jobs["a"]])
        self.assertEqual([item["id"] for item in detail["potentialUnlockJobs"]], [self.jobs["c"]])
        self.assertEqual([item["id"] for item in detail["multiGapJobs"]], [self.jobs["b"]])
        self.assertEqual(detail["sourceTerms"][0]["jobCount"], 8)

    def test_missing_profile_is_unknown_not_gap_and_minimum_sample_is_explicit(self):
        for key in ("one", "two"):
            self.create_job(key, [
                self.text_fact("tool", "Jira", "required", "concept_tool_jira")
            ])
            self.service.explicit_evaluate_job_track(self.jobs[key], self.track_id)
        data = self.intelligence()
        jira = next(item for item in data["skills"] if item["reference"] == "tool:JIRA")
        self.assertEqual(jira["user"]["unknown"], 2)
        self.assertEqual(jira["user"]["requiredGaps"], 0)
        self.assertFalse(jira["profileEvidence"]["exists"])
        self.assertEqual(jira["priority"]["classification"], "insufficient_evidence")
        self.assertEqual(data["priorityPolicy"]["minimumPopulation"], 5)

    def test_mapping_and_profile_changes_reaggregate_without_source_reparse(self):
        self.seed_population()
        before = self.intelligence()
        before_sql = next(item for item in before["skills"] if item["reference"] == "skill:SQL")
        self.assertEqual(before_sql["demand"]["jobsMentioning"], 8)
        self.assertTrue(any(item["term"] == "Structured Query Language" for item in before["unmapped"]["terms"]))
        with self.service.store.transaction() as connection:
            connection.execute(
                """INSERT INTO fact_normalizations(
                       id,fact_id,concept_id,rule_version,confidence,mapping_origin,
                       is_manual,state,created_at
                   ) VALUES(?,?,?,?,?,'manual',1,'active',?)""",
                (
                    "mapping_pack_k_manual", self.fact_ids["i"][0], "concept_skill_sql",
                    "normalization@1-manual", 1.0, "2026-09-23T13:00:00+00:00",
                ),
            )
        mapped = self.intelligence()
        mapped_sql = next(item for item in mapped["skills"] if item["reference"] == "skill:SQL")
        self.assertEqual(mapped_sql["demand"]["jobsMentioning"], 9)
        self.assertNotEqual(
            before["versions"]["mappingFingerprint"], mapped["versions"]["mappingFingerprint"]
        )

        run_count = None
        with self.service.store.read_connection() as connection:
            run_count = connection.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0]
        skills = self.service.get_profile()["data"]["profile"]["skills"]
        skill_id = next(item["id"] for item in skills if item["normalizedKey"] == "SQL")
        self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "SQL", "level": 4,
            "confidence": 5, "developmentInterest": 4,
        }, record_id=skill_id)
        for key in ("a", "b", "c", "d"):
            self.service.explicit_evaluate_job_track(self.jobs[key], self.track_id)
        # Profile edits do not alter market demand or parse source material.
        after_profile = self.intelligence()
        after_sql = next(item for item in after_profile["skills"] if item["reference"] == "skill:SQL")
        self.assertEqual(after_sql["demand"]["jobsMentioning"], 9)
        self.assertEqual(after_sql["user"]["requiredGaps"], 0)
        self.assertGreater(after_sql["user"]["supported"], 0)
        with self.service.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0], run_count)

    def test_merge_and_unmerge_change_distinct_job_denominator_without_losing_terms(self):
        self.create_job("merge-one", [
            self.text_fact("skill", "SQL", "required", "concept_skill_sql")
        ])
        self.create_job("merge-two", [
            self.text_fact("skill", "SQL", "required", "concept_skill_sql")
        ])
        before = self.intelligence()
        self.assertEqual(before["population"]["canonicalJobDenominator"], 2)
        self.assertEqual(before["skills"][0]["demand"]["jobsMentioning"], 2)

        survivor = self.jobs["merge-one"]
        absorbed = self.jobs["merge-two"]
        with self.service.store.read_connection() as connection:
            absorbed_listing = connection.execute(
                "SELECT id FROM source_listings WHERE canonical_job_id=?", (absorbed,)
            ).fetchone()[0]
        with self.service.store.transaction() as connection:
            connection.execute(
                "UPDATE source_listings SET canonical_job_id=? WHERE canonical_job_id=?",
                (survivor, absorbed),
            )
            connection.execute(
                "UPDATE canonical_jobs SET merged_into_job_id=?,merged_at=? WHERE id=?",
                (survivor, "2026-09-23T14:00:00+00:00", absorbed),
            )
        merged = self.intelligence()
        sql = next(item for item in merged["skills"] if item["reference"] == "skill:SQL")
        self.assertEqual(merged["population"]["canonicalJobDenominator"], 1)
        self.assertEqual(sql["demand"]["jobsMentioning"], 1)
        self.assertEqual(sql["sourceTerms"][0]["observationCount"], 2)

        with self.service.store.transaction() as connection:
            connection.execute(
                "UPDATE source_listings SET canonical_job_id=? WHERE id=?", (absorbed, absorbed_listing)
            )
            connection.execute(
                "UPDATE canonical_jobs SET merged_into_job_id=NULL,merged_at=NULL WHERE id=?",
                (absorbed,),
            )
        restored = self.intelligence()
        restored_sql = next(item for item in restored["skills"] if item["reference"] == "skill:SQL")
        self.assertEqual(restored["population"]["canonicalJobDenominator"], 2)
        self.assertEqual(restored_sql["demand"]["jobsMentioning"], 2)

    def test_current_excludes_inactive_but_historical_window_retains_it(self):
        self.create_job("inactive", [
            self.text_fact("skill", "SQL", "required", "concept_skill_sql")
        ])
        with self.service.store.transaction() as connection:
            connection.execute(
                "UPDATE applications SET source_expired=1 WHERE job_id=?", (self.jobs["inactive"],)
            )
        current = self.intelligence()
        historical = self.service.get_track_skill_intelligence(
            self.track_id, population="historical", window="30d"
        )["data"]
        self.assertEqual(current["population"]["canonicalJobDenominator"], 0)
        self.assertEqual(historical["population"]["canonicalJobDenominator"], 1)
        self.assertEqual(historical["population"]["timeAnchorHierarchy"][0], "source publication/date-posted fact")

    def test_priority_policy_high_is_componentized_without_a_score(self):
        for index in range(5):
            self.create_job(f"priority-{index}", [
                self.text_fact("skill", "SQL", "required", "concept_skill_sql")
            ])
        self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "SQL", "level": 0,
            "confidence": 5, "developmentInterest": 1,
        })
        for index in range(5):
            self.service.explicit_evaluate_job_track(
                self.jobs[f"priority-{index}"], self.track_id
            )
        sql = next(
            item for item in self.intelligence()["skills"]
            if item["reference"] == "skill:SQL"
        )
        self.assertEqual(sql["priority"]["classification"], "high")
        self.assertEqual(sql["priority"]["components"]["requiredDemand"], 5)
        self.assertEqual(sql["priority"]["components"]["requiredGaps"], 5)
        self.assertEqual(sql["priority"]["components"]["strictJobsUnlocked"], 5)
        self.assertNotIn("score", sql["priority"])
        self.assertTrue(any("explicitly require" in reason for reason in sql["priority"]["reasons"]))

    def test_track_populations_are_independent_and_paused_history_is_readable(self):
        second_track = self.service.create_track({
            "name": "Pack K second Track", "status": "exploring",
            "geography": {"countries": ["NO"], "remoteAllowed": None,
                          "relocationRelevant": True},
        })["data"]["track"]["id"]
        self.create_job("shared", [
            self.text_fact("skill", "SQL", "required", "concept_skill_sql")
        ])
        self.service.set_job_tracks(
            self.jobs["shared"], {"trackIds": [self.track_id, second_track]}
        )
        self.create_job("first-only", [
            self.text_fact("tool", "Jira", "preferred", "concept_tool_jira")
        ])
        first = self.intelligence()
        second = self.service.get_track_skill_intelligence(second_track)["data"]
        self.assertEqual(first["population"]["canonicalJobDenominator"], 2)
        self.assertEqual(second["population"]["canonicalJobDenominator"], 1)
        self.assertEqual(first["sourceMix"]["manual"], 2)
        self.assertEqual(second["sourceMix"]["manual"], 1)

        self.service.update_track(second_track, {"status": "paused"})
        historical = self.service.get_track_skill_intelligence(
            second_track, population="historical", window="30d"
        )["data"]
        self.assertEqual(historical["track"]["status"], "paused")
        self.assertEqual(historical["population"]["canonicalJobDenominator"], 1)
        self.assertEqual(historical["materialization"]["strategy"], "bounded_live_query")


if __name__ == "__main__":
    unittest.main()

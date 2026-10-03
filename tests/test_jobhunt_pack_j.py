import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntError, JobhuntService, JobhuntWorker
from jobhunt_backend.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATOR_VERSION,
    default_policy,
    evaluate,
    fingerprint,
    validate_policy,
)
from jobhunt_backend.migrations import SCHEMA_VERSION


def fact(
    identifier,
    fact_type,
    wording,
    *,
    requirement="required",
    state="explicit_positive",
):
    return {
        "id": identifier,
        "fact_type": fact_type,
        "value_type": "text",
        "value_text": wording,
        "source_wording": wording,
        "requirement_preference": requirement,
        "state": state,
        "validation_state": "valid",
        "concept_key": None,
        "display_label": None,
        "extractor_kind": "deterministic",
        "evidence_locator": {"kind": "test"},
    }


def evaluator_context(*, profile=None, facts=None, job=None, track=None, policy=None):
    profile_value = {
        "skills": [],
        "languages": [],
        "experience": [],
        "preferences": [],
        "constraints": [],
        "evidence": [],
    }
    profile_value.update(profile or {})
    return {
        "profile": profile_value,
        "facts": list(facts or []),
        "job": {
            "id": "job-test",
            "role_title": "QA Engineer",
            "location_country": "NO",
            "work_mode": "hybrid",
            "contract_type": "employment",
            "salary_min": 50_000,
            "salary_max": 70_000,
            "salary_currency": "NOK",
            "salary_period": "month",
            "salary_tax_type": "gross",
            "requirements_json": "{}",
            **(job or {}),
        },
        "track": {
            "id": "track-test",
            "countries": ["NO"],
            "remote_allowed": True,
            "relocation_relevant": False,
            **(track or {}),
        },
        "policy": policy or default_policy(),
        "policy_record": {
            "id": "policy-test",
            "policy_version": 1,
            "fingerprint": "sha256:" + "a" * 64,
        },
        "projection": None,
        "projection_fingerprint": "sha256:" + "b" * 64,
        "profile_changed_at": "2026-09-23T10:00:00+00:00",
        "profile_revision": 1,
        "profile_fingerprint": "sha256:" + "c" * 64,
        "track_context_fingerprint": "sha256:" + "d" * 64,
        "input_fingerprint": "sha256:" + "e" * 64,
    }


def findings(result, *, dimension=None, label=None):
    values = result["findings"]
    if dimension:
        values = [item for item in values if item["dimension"] == dimension]
    if label:
        values = [item for item in values if item["display_params"]["label"] == label]
    return values


class JobhuntPackJEvaluatorTests(unittest.TestCase):
    def test_policy_is_bounded_and_fingerprint_is_stable(self):
        policy = default_policy()
        self.assertEqual(validate_policy(policy), policy)
        self.assertEqual(fingerprint(policy), fingerprint(copy.deepcopy(policy)))
        self.assertEqual(policy["aggregate"], "none")

        invalid_dimension = copy.deepcopy(policy)
        invalid_dimension["dimensions"]["personality"] = {
            "enabled": True,
            "importance": "primary",
        }
        with self.assertRaisesRegex(ValueError, "known Pack J dimensions"):
            validate_policy(invalid_dimension)

        invalid_threshold = copy.deepcopy(policy)
        invalid_threshold["skillThresholds"] = {"partialMin": 4, "supportedMin": 3}
        with self.assertRaisesRegex(ValueError, "partialMin"):
            validate_policy(invalid_threshold)

        executable = copy.deepcopy(policy)
        executable["expression"] = "profile.sql > 2"
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_policy(executable)

    def test_skill_unknown_partial_gap_supported_and_requirement_class(self):
        required = fact("fact-sql", "skill", "SQL", requirement="required")
        preferred = fact("fact-api", "skill", "API testing", requirement="preferred")

        missing = evaluate(evaluator_context(facts=[required]))
        sql = findings(missing, dimension="skills")[0]
        self.assertEqual(sql["status"], "unknown")
        self.assertEqual(sql["requirement_class"], "required")

        def skill_result(level):
            return evaluate(evaluator_context(
                facts=[required, preferred],
                profile={"skills": [
                    {
                        "id": "skill-sql", "display_name": "SQL",
                        "normalized_key": "sql", "level": level,
                        "origin": "manual_user",
                    },
                    {
                        "id": "skill-api", "display_name": "API testing",
                        "normalized_key": "api testing", "level": 0,
                        "origin": "manual_user",
                    },
                ]},
            ))

        self.assertEqual(findings(skill_result(0), label="SQL")[0]["status"], "gap")
        partial = findings(skill_result(2), label="SQL")[0]
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["display_params"]["supportedMin"], 3)
        supported = findings(skill_result(4), label="SQL")[0]
        self.assertEqual(supported["status"], "supported")
        self.assertEqual(supported["profile_evidence"][0]["id"], "skill-sql")
        preferred_gap = findings(skill_result(4), label="API testing")[0]
        self.assertEqual(preferred_gap["status"], "gap")
        self.assertEqual(preferred_gap["requirement_class"], "preferred")
        self.assertNotEqual(preferred_gap["status"], "blocker")

    def test_language_semantics_include_cefr_unknown_and_explicit_negative(self):
        english = fact("language-en", "language", "English B2")
        supported = evaluate(evaluator_context(
            facts=[english],
            profile={"languages": [{
                "id": "profile-en", "language_name": "English",
                "proficiency": "C1", "origin": "manual_user",
            }]},
        ))
        self.assertEqual(findings(supported, label="English")[0]["status"], "supported")

        norwegian = fact("language-no", "language", "Norwegian C1")
        gap = evaluate(evaluator_context(
            facts=[norwegian],
            profile={"languages": [{
                "id": "profile-no", "language_name": "Norwegian",
                "proficiency": "A2", "origin": "manual_user",
            }]},
        ))
        self.assertEqual(findings(gap, label="Norwegian")[0]["status"], "gap")
        self.assertEqual(
            findings(evaluate(evaluator_context(facts=[norwegian])), label="Norwegian")[0]["status"],
            "unknown",
        )

        unlevelled = fact("language-plain", "language", "English required")
        plain = evaluate(evaluator_context(
            facts=[unlevelled],
            profile={"languages": [{
                "id": "profile-en", "language_name": "English",
                "proficiency": None, "origin": "manual_user",
            }]},
        ))
        self.assertEqual(findings(plain, label="English")[0]["status"], "supported")

        negative = fact(
            "language-negative", "language", "Norwegian is not required",
            state="explicit_negative",
        )
        negative_result = evaluate(evaluator_context(facts=[negative]))
        negative_finding = findings(negative_result, dimension="preferences")[0]
        self.assertEqual(negative_finding["status"], "supported")
        self.assertEqual(negative_finding["explanation_code"], "language_explicitly_not_required")

    def test_experience_uses_only_comparable_structured_dates(self):
        requirement = fact("experience-qa", "experience", "3 years QA experience")
        record = {
            "id": "experience-1", "job_title": "QA Analyst", "employer": "ACME",
            "start_date": "2020-01-01", "end_date": "2024-01-01",
            "is_current": 0, "domains_json": ["testing"], "origin": "manual_user",
        }
        supported = evaluate(evaluator_context(
            facts=[requirement], profile={"experience": [record]},
        ))
        supported_finding = findings(supported, dimension="experience")[0]
        self.assertEqual(supported_finding["status"], "supported")
        self.assertEqual(supported_finding["display_params"]["profileRecordIds"], ["experience-1"])
        self.assertEqual(
            [item["id"] for item in supported_finding["profile_evidence"]],
            ["experience-1"],
        )

        short = evaluate(evaluator_context(
            facts=[requirement],
            profile={"experience": [{**record, "end_date": "2021-01-01"}]},
        ))
        self.assertEqual(findings(short, dimension="experience")[0]["status"], "gap")

        undated = evaluate(evaluator_context(
            facts=[requirement],
            profile={"experience": [{**record, "start_date": None, "end_date": None}]},
        ))
        self.assertEqual(findings(undated, dimension="experience")[0]["status"], "unknown")

        unrelated = evaluate(evaluator_context(
            facts=[fact("experience-python", "experience", "3 years Python development")],
            profile={"experience": [record]},
        ))
        self.assertEqual(findings(unrelated, dimension="experience")[0]["status"], "unknown")

    def test_salary_geography_and_work_conditions_preserve_unknowns_and_blockers(self):
        hard_floor = {
            "id": "constraint-salary",
            "constraint_key": "minimum_salary",
            "value_json": {
                "amount": 80_000, "currency": "NOK",
                "period": "month", "taxType": "gross",
            },
            "is_hard": 1,
            "origin": "manual_user",
        }
        base = {"constraints": [hard_floor]}
        below = evaluate(evaluator_context(profile=base))
        self.assertEqual(findings(below, dimension="compensation")[0]["status"], "blocker")

        overlap = evaluate(evaluator_context(
            profile=base,
            job={"salary_min": 70_000, "salary_max": 90_000},
        ))
        self.assertEqual(findings(overlap, dimension="compensation")[0]["status"], "supported")
        above = evaluate(evaluator_context(
            profile=base,
            job={"salary_min": 90_000, "salary_max": 110_000},
        ))
        self.assertEqual(findings(above, dimension="compensation")[0]["status"], "supported")
        missing = evaluate(evaluator_context(
            profile=base, job={"salary_min": None, "salary_max": None},
        ))
        self.assertEqual(findings(missing, dimension="compensation")[0]["status"], "unknown")
        currency = evaluate(evaluator_context(profile=base, job={"salary_currency": "PLN"}))
        self.assertEqual(findings(currency, dimension="compensation")[0]["status"], "unknown")
        tax = evaluate(evaluator_context(profile=base, job={"salary_tax_type": "net"}))
        self.assertEqual(findings(tax, dimension="compensation")[0]["status"], "unknown")
        no_upper_bound = evaluate(evaluator_context(
            profile=base, job={"salary_min": 70_000, "salary_max": None},
        ))
        self.assertEqual(
            findings(no_upper_bound, dimension="compensation")[0]["status"], "unknown"
        )

        oslo_job = {"location_country": "NO"}
        norway = evaluate(evaluator_context(job=oslo_job, track={"countries": ["NO"]}))
        poland = evaluate(evaluator_context(job=oslo_job, track={"countries": ["PL"]}))
        self.assertEqual(findings(norway, dimension="geography")[0]["status"], "supported")
        self.assertEqual(findings(poland, dimension="geography")[0]["status"], "blocker")

        profile_country = {
            "id": "constraint-country", "constraint_key": "allowed_countries",
            "value_json": {"countries": ["PL"]}, "is_hard": 1,
            "origin": "manual_user",
        }
        profile_geo = evaluate(evaluator_context(
            profile={"constraints": [profile_country]},
            job=oslo_job,
            track={"countries": ["NO"]},
        ))
        self.assertEqual(
            findings(profile_geo, label="Career Profile geography")[0]["status"],
            "blocker",
        )

        hard_work_model = {
            "id": "constraint-work", "constraint_key": "allowed_work_models",
            "value_json": ["remote"], "is_hard": 1, "origin": "manual_user",
        }
        blocked = evaluate(evaluator_context(
            profile={"constraints": [hard_work_model]},
            job={"work_mode": "onsite", "contract_type": None},
        ))
        self.assertEqual(findings(blocked, label="Work model")[0]["status"], "blocker")

        preferred_remote = {
            "id": "preference-remote", "dimension_key": "remote_work",
            "value_json": True, "importance": 4, "origin": "manual_user",
        }
        preference_gap = evaluate(evaluator_context(
            profile={"preferences": [preferred_remote]},
            job={"work_mode": "onsite", "contract_type": None},
        ))
        self.assertEqual(findings(preference_gap, label="Work model")[0]["status"], "gap")
        unknown = evaluate(evaluator_context(
            profile={"constraints": [hard_work_model]},
            job={"work_mode": None, "contract_type": None},
        ))
        self.assertEqual(findings(unknown, label="Work model")[0]["status"], "unknown")

        hard_contract = {
            "id": "constraint-contract", "constraint_key": "prohibited_contract_types",
            "value_json": ["b2b"], "is_hard": 1, "origin": "manual_user",
        }
        contract = evaluate(evaluator_context(
            profile={"constraints": [hard_contract]},
            job={"work_mode": None, "contract_type": "b2b"},
        ))
        self.assertEqual(findings(contract, label="Contract")[0]["status"], "blocker")

        hard_schedule = {
            "id": "constraint-schedule", "constraint_key": "allowed_schedules",
            "value_json": ["day"], "is_hard": 1, "origin": "manual_user",
        }
        night = fact("schedule-night", "schedule", "night")
        schedule = evaluate(evaluator_context(
            facts=[night], profile={"constraints": [hard_schedule]},
            job={"work_mode": None, "contract_type": None},
        ))
        self.assertEqual(findings(schedule, label="Schedule")[0]["status"], "blocker")
        day = fact("schedule-day", "schedule", "day")
        compatible_schedule = evaluate(evaluator_context(
            facts=[day], profile={"constraints": [hard_schedule]},
            job={"work_mode": None, "contract_type": None},
        ))
        self.assertEqual(
            findings(compatible_schedule, label="Schedule")[0]["status"], "supported"
        )


class JobhuntPackJIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite",
            private_root=self.root / "private",
            environment={},
        )
        self.service.initialize()
        self.track_id = "track_seed_qa_poland"

    def tearDown(self):
        self.temp.cleanup()

    def create_job(self, *, suffix="one", country="Poland", requirements=None):
        created = self.service.create_job({
            "company": "Pack J Example",
            "role": "QA Engineer",
            "location": {"city": "Krakow", "country": country, "workMode": "hybrid"},
            "contract": {"type": "employment"},
            "salary": {
                "min": 12_000, "max": 16_000, "currency": "PLN",
                "period": "month", "taxType": "gross", "isKnown": True,
            },
            "source": {"name": "manual", "url": f"https://example.test/jobs/{suffix}"},
            "requirements": requirements or {
                "mustHave": ["SQL"], "niceToHave": ["API testing"], "tools": [],
            },
            "match": {"score": 91, "summary": "Legacy only", "isExperimental": True},
            "analysis": {"skillGaps": ["legacy gap"]},
            "originalText": "Pack J deterministic test advertisement",
        })["data"]["job"]
        return created["id"]

    def drain_worker(self, maximum=100):
        worker = JobhuntWorker(self.service)
        completed = []
        for _ in range(maximum):
            item = worker.run_once()
            if item is None:
                break
            completed.append(item)
        worker.stop(timeout=1)
        return completed

    def test_schema_initial_policy_seed_idempotency_versions_and_immutability(self):
        self.assertEqual(SCHEMA_VERSION, 13)
        self.assertEqual(self.service.store.schema_status()["version"], 13)
        tracks = self.service.list_tracks()["data"]["tracks"]
        with self.service.store.read_connection() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            policy_count = connection.execute(
                "SELECT COUNT(*) FROM track_evaluation_policies"
            ).fetchone()[0]
        self.assertTrue({
            "track_evaluation_policies", "evaluations", "evaluation_dimensions",
            "evaluation_findings", "evaluation_current",
        }.issubset(tables))
        self.assertEqual(policy_count, len(tracks))

        first = self.service.get_track_evaluation_policy(self.track_id)["data"]["policy"]
        self.assertEqual(first["version"], 1)
        edited = copy.deepcopy(first["policy"])
        edited["skillThresholds"] = {"partialMin": 2, "supportedMin": 4}
        saved = self.service.create_track_evaluation_policy(
            self.track_id, {"policy": edited},
        )["data"]
        self.assertFalse(saved["reused"])
        self.assertEqual(saved["policy"]["version"], 2)
        self.assertNotEqual(saved["policy"]["fingerprint"], first["fingerprint"])

        reused = self.service.create_track_evaluation_policy(
            self.track_id, {"policy": copy.deepcopy(edited)},
        )["data"]
        self.assertTrue(reused["reused"])
        self.service.initialize()
        current = self.service.get_track_evaluation_policy(self.track_id)["data"]["policy"]
        history = self.service.get_track_evaluation_policy_history(self.track_id)["data"]["items"]
        self.assertEqual(current["version"], 2)
        self.assertEqual([item["version"] for item in history], [2, 1])
        self.assertEqual(
            self.service.get_track(self.track_id)["data"]["track"]["evaluationPolicyVersion"],
            "2",
        )
        with self.service.store.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE track_evaluation_policies SET origin='seed' WHERE id=?",
                    (saved["policy"]["id"],),
                )

        invalid = copy.deepcopy(edited)
        invalid["skillThresholds"] = {"partialMin": 5, "supportedMin": 1}
        with self.assertRaises(JobhuntError) as error:
            self.service.create_track_evaluation_policy(self.track_id, {"policy": invalid})
        self.assertEqual(error.exception.code, "invalid_evaluation_policy")

    def test_evaluation_versions_currentness_evidence_and_application_separation(self):
        job_id = self.create_job()
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        first = self.service.explicit_evaluate_job_track(job_id, self.track_id)["data"]["evaluation"]
        self.assertEqual(first["state"], "current")
        self.assertEqual(first["evaluatorVersion"], EVALUATOR_VERSION)
        self.assertEqual(first["evaluationSchemaVersion"], EVALUATION_SCHEMA_VERSION)
        self.assertNotIn("score", first)
        self.assertEqual(len(first["dimensions"]), 5)
        sql = next(item for item in first["findings"] if item["display"]["label"] == "SQL")
        self.assertEqual(sql["status"], "unknown")
        self.assertTrue(sql["jobEvidence"])
        self.assertEqual(sql["policyEvidence"]["policyVersion"], 1)

        self.service.application_command(job_id, {"type": "applied"})
        still_current = self.service.get_evaluation(first["id"])["data"]["evaluation"]
        self.assertEqual(still_current["state"], "current")

        profile_change = self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "sql", "level": 4,
            "confidence": 5, "developmentInterest": 2,
        })["data"]
        self.assertTrue(profile_change["evaluationRecompute"]["queued"])
        stale = self.service.get_evaluation(first["id"])["data"]["evaluation"]
        self.assertEqual(stale["state"], "stale")

        second = self.service.explicit_evaluate_job_track(job_id, self.track_id)["data"]["evaluation"]
        self.assertNotEqual(second["id"], first["id"])
        self.assertGreater(second["profileRevision"], first["profileRevision"])
        self.assertEqual(
            next(item for item in second["findings"] if item["display"]["label"] == "SQL")["status"],
            "supported",
        )
        historical = self.service.get_evaluation(first["id"])["data"]["evaluation"]
        self.assertEqual(historical["state"], "historical")
        with self.service.store.transaction() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE evaluations SET blocker_count=99 WHERE id=?", (first["id"],)
                )

        legacy = self.service.get_job(job_id)["data"]["job"]
        self.assertEqual(legacy["match"]["score"], 91)
        self.assertNotEqual(legacy["evaluationSource"], "deterministic")

    def test_policy_change_and_factual_job_change_enqueue_and_recompute(self):
        job_id = self.create_job()
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        self.drain_worker()
        initial = self.service.explicit_evaluate_job_track(job_id, self.track_id)["data"]["evaluation"]

        policy = copy.deepcopy(
            self.service.get_track_evaluation_policy(self.track_id)["data"]["policy"]["policy"]
        )
        policy["skillThresholds"] = {"partialMin": 2, "supportedMin": 4}
        response = self.service.create_track_evaluation_policy(
            self.track_id, {"policy": policy},
        )["data"]
        self.assertTrue(response["evaluationRecompute"]["queued"])
        jobs = self.drain_worker()
        self.assertTrue(any(item["job_type"] == "evaluation_recompute" for item in jobs))
        after_policy = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(after_policy["id"], initial["id"])
        self.assertEqual(after_policy["policyVersion"], 2)
        self.assertEqual(
            self.service.get_evaluation(initial["id"])["data"]["evaluation"]["policyVersion"],
            1,
        )

        self.service.update_job(job_id, {
            "requirements": {
                "mustHave": ["SQL", "Python"],
                "niceToHave": ["API testing"],
                "tools": [],
            }
        })
        stale = self.service.get_evaluation(after_policy["id"])["data"]["evaluation"]
        self.assertEqual(stale["state"], "stale")
        self.drain_worker()
        after_job = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(after_job["id"], after_policy["id"])
        self.assertEqual(
            next(item for item in after_job["findings"] if item["display"]["label"] == "Python")["status"],
            "unknown",
        )

    def test_paused_and_archived_tracks_preserve_history_and_skip_automatic_work(self):
        job_id = self.create_job()
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        current = self.service.explicit_evaluate_job_track(job_id, self.track_id)["data"]["evaluation"]
        self.drain_worker()
        self.service.update_track(self.track_id, {"status": "exploring"})
        self.service.save_profile_record("skills", {
            "displayName": "API testing", "normalizedKey": "api testing", "level": 3,
        })
        self.drain_worker()
        exploring = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(exploring["id"], current["id"])
        self.assertEqual(exploring["state"], "current")
        current = exploring

        self.service.update_track(self.track_id, {"status": "paused"})
        self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "sql", "level": 5,
        })
        self.drain_worker()
        paused = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertEqual(paused["id"], current["id"])
        self.assertEqual(paused["state"], "stale")

        self.service.update_track(self.track_id, {"status": "active"})
        self.drain_worker()
        activated = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(activated["id"], current["id"])
        self.assertEqual(activated["state"], "current")

        self.service.update_track(self.track_id, {"status": "paused"})
        manual = self.service.explicit_evaluate_job_track(job_id, self.track_id)["data"]["evaluation"]
        self.assertNotEqual(manual["id"], current["id"])
        self.service.update_track(self.track_id, {"status": "archived"})
        history = self.service.list_job_evaluations(job_id)["data"]["history"]
        self.assertGreaterEqual(len(history), 2)

    def import_job(self, external_id, *, company="Merge Example AS", return_details=False):
        imported = self.service.manual_import({
            "sourceKey": "manual",
            "externalListingId": external_id,
            "inputMode": "json",
            "contentType": "application/json",
            "content": json.dumps({
                "title": "QA Engineer", "company": company,
                "city": "Oslo", "country": "Norway",
                "datePosted": "2026-09-20",
                "description": "Test APIs and web applications",
            }),
        })["data"]
        extracted = self.service.extract_capture(imported["capture"]["id"])["data"]
        details = {
            "jobId": extracted["projection"]["canonicalJobId"],
            "captureId": imported["capture"]["id"],
        }
        return details if return_details else details["jobId"]

    def test_override_and_reextraction_recompute_without_touching_application_history(self):
        imported = self.import_job("pack-j-override", return_details=True)
        job_id = imported["jobId"]
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        initial = self.service.explicit_evaluate_job_track(
            job_id, self.track_id,
        )["data"]["evaluation"]
        self.assertEqual(
            next(item for item in initial["findings"] if item["dimension"] == "geography")["status"],
            "blocker",
        )
        application_before = copy.deepcopy(self.service.get_application(job_id)["data"])
        extraction_runs_before = copy.deepcopy(
            self.service.list_capture_extraction_runs(imported["captureId"])["data"]["runs"]
        )

        profile_change = self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "sql", "level": 4,
        })["data"]
        self.assertTrue(profile_change["evaluationRecompute"]["queued"])
        self.drain_worker()
        after_profile = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(after_profile["id"], initial["id"])
        self.assertEqual(
            self.service.list_capture_extraction_runs(imported["captureId"])["data"]["runs"],
            extraction_runs_before,
        )
        self.assertEqual(self.service.get_application(job_id)["data"], application_before)

        changed = self.service.create_override(job_id, {
            "field": "location_country", "value": "Poland", "reason": "verified by user",
        })["data"]
        self.assertTrue(changed["evaluationRecompute"]["queued"])
        self.drain_worker()
        after_override = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(after_override["id"], after_profile["id"])
        self.assertEqual(
            next(item for item in after_override["findings"] if item["dimension"] == "geography")["status"],
            "supported",
        )
        self.assertEqual(self.service.get_application(job_id)["data"], application_before)

        reextracted = self.service.extract_capture(imported["captureId"])["data"]
        self.assertIn(
            changed["override"]["id"], reextracted["projection"]["appliedOverrideIds"],
        )
        self.drain_worker()
        after_reextraction = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertEqual(after_reextraction["state"], "current")
        self.assertEqual(self.service.get_application(job_id)["data"], application_before)

    def test_track_geography_change_invalidates_and_recomputes_current_evaluation(self):
        job_id = self.create_job(country="Poland")
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        initial = self.service.explicit_evaluate_job_track(
            job_id, self.track_id,
        )["data"]["evaluation"]
        current_track = self.service.get_track(self.track_id)["data"]["track"]
        changed = self.service.update_track(self.track_id, {
            "geography": {
                **current_track["geography"],
                "countries": ["Norway"],
                "remoteAllowed": False,
            },
        })
        self.assertEqual(changed["data"]["track"]["geography"]["countries"], ["Norway"])
        self.assertEqual(
            self.service.get_evaluation(initial["id"])["data"]["evaluation"]["state"],
            "stale",
        )
        self.drain_worker()
        recomputed = self.service.list_job_evaluations(job_id)["data"]["targets"][0]["evaluation"]
        self.assertNotEqual(recomputed["id"], initial["id"])
        self.assertEqual(
            next(item for item in recomputed["findings"] if item["dimension"] == "geography")["status"],
            "blocker",
        )

    def test_merge_and_unmerge_evaluate_only_active_canonical_jobs(self):
        first = self.import_job("pack-j-merge-a")
        second = self.import_job("pack-j-merge-b", company="Merge Example")
        candidate = self.service.list_duplicates()["data"]["items"][0]
        survivor = candidate["leftJob"]["id"]
        absorbed = candidate["rightJob"]["id"]
        self.service.set_job_tracks(absorbed, {"trackIds": [self.track_id]})
        before = self.service.explicit_evaluate_job_track(absorbed, self.track_id)["data"]["evaluation"]

        merge = self.service.merge_duplicate(candidate["id"], {
            "survivorJobId": survivor, "confirm": True,
        })["data"]["merge"]
        self.drain_worker()
        current = self.service.list_track_evaluations(self.track_id)["data"]["items"]
        self.assertEqual([item["jobId"] for item in current], [survivor])
        self.assertIsNotNone(self.service.get_evaluation(before["id"])["data"]["evaluation"])

        self.service.unmerge(merge["id"], {})
        self.drain_worker()
        restored = self.service.list_track_evaluations(self.track_id)["data"]["items"]
        self.assertEqual([item["jobId"] for item in restored], [absorbed])
        all_rows = self.service.store.list_evaluation_rows(track_id=self.track_id)
        self.assertGreaterEqual(len(all_rows), 2)


if __name__ == "__main__":
    unittest.main()

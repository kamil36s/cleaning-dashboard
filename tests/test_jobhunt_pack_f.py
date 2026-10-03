import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntService
from jobhunt_backend.extraction.ai import (
    AIProviderError,
    FakeAIExtractionProvider,
    PROMPT_ID,
    PROMPT_VERSION,
    RESPONSE_SCHEMA_VERSION,
)
from jobhunt_backend.migrations import MIGRATIONS, SCHEMA_VERSION


FIXTURES = Path(__file__).parent / "fixtures" / "jobhunt"


def seed_pack_e_database(path: Path) -> None:
    now = "2026-09-23T08:00:00+00:00"
    with sqlite3.connect(path) as connection:
        for migration in MIGRATIONS[:6]:
            connection.executescript(migration.sql)
        connection.execute(
            "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(?,?,?,NULL)",
            [(item.version, now, item.checksum) for item in MIGRATIONS[:6]],
        )


def fact(
    fact_type,
    value,
    evidence,
    *,
    state="explicit_positive",
    preference="unknown",
    confidence=0.9,
    namespace="job",
):
    value_type = "boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "text"
    key = {"boolean": "valueBoolean", "number": "valueNumber", "text": "valueText"}[value_type]
    return {
        "namespace": namespace,
        "type": fact_type,
        "state": state,
        "requirementPreference": preference,
        "valueType": value_type,
        key: value,
        "sourceWording": evidence,
        "evidenceQuote": evidence,
        "confidence": confidence,
    }


def response(*facts, open_facts=None, warnings=None):
    return {"facts": list(facts), "openFacts": list(open_facts or []), "warnings": list(warnings or [])}


class JobhuntPackFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def service(self, outcomes, environment=None):
        provider = FakeAIExtractionProvider(outcomes)
        service = JobhuntService(
            self.root / f"jobhunt-{id(provider)}.sqlite",
            private_root=self.root / f"private-{id(provider)}",
            ai_provider=provider,
            environment=environment or {"JOBHUNT_AI_MAX_RETRIES": "1", "JOBHUNT_AI_RETRY_DELAY_SECONDS": "0"},
        )
        service.initialize()
        return service, provider

    @staticmethod
    def import_text(service, content, external_id="pack-f", title_hint=None):
        return service.manual_import({
            "sourceKey": "manual", "externalListingId": external_id,
            "inputMode": "text", "contentType": "text/plain", "content": content,
            "titleHint": title_hint,
        })["data"]

    @staticmethod
    def import_json(service, payload, external_id="pack-f-json"):
        return service.manual_import({
            "sourceKey": "manual", "externalListingId": external_id,
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps(payload),
        })["data"]

    def test_pack_e_to_f_migration_preserves_runs_facts_and_adds_ai_extension(self):
        database = self.root / "pack-e.sqlite"
        seed_pack_e_database(database)
        migrated = JobhuntService(database, private_root=self.root / "migrated-private")
        migrated.initialize()
        self.assertEqual(migrated.store.schema_status()["version"], SCHEMA_VERSION)
        with migrated.store.read_connection() as connection:
            versions = [row[0] for row in connection.execute("SELECT version FROM jobhunt_schema_migrations ORDER BY version")]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(extraction_runs)")}
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(versions, [item.version for item in MIGRATIONS])
        self.assertTrue({"ai_provider", "ai_model", "ai_prompt_fingerprint", "ai_raw_response_json"}.issubset(columns))
        self.assertIn("ai_extraction_attempts", tables)
        self.assertEqual(violations, [])

    def test_valid_ai_facts_reuse_common_model_preserve_negative_preference_open_fact_and_prompt_boundary(self):
        advert = (FIXTURES / "pack-f-qa-unstructured.txt").read_text(encoding="utf-8") + "\n" + (
            FIXTURES / "pack-f-prompt-injection.txt"
        ).read_text(encoding="utf-8")
        open_fact = fact("company_transport", "Company transport from Bergen", "Company transport from Bergen", namespace="source")
        open_fact["label"] = "Company transport"
        service, provider = self.service([response(
            fact("title", "QA Engineer", "QA Engineer"),
            fact("skill", "SQL", "SQL is required", preference="required"),
            fact("tool", "Playwright", "Playwright is preferred", preference="preferred"),
            fact("language", "Norwegian", "Norwegian is not required", state="explicit_negative", preference="required"),
            open_facts=[open_fact],
        )])
        imported = self.import_text(service, advert)
        result = service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(result["run"]["extractorKind"], "ai")
        self.assertEqual(result["run"]["ai"]["provider"], "fake")
        self.assertEqual(result["run"]["ai"]["promptId"], PROMPT_ID)
        self.assertEqual(result["run"]["ai"]["promptVersion"], PROMPT_VERSION)
        self.assertEqual(result["run"]["ai"]["responseSchemaVersion"], RESPONSE_SCHEMA_VERSION)
        self.assertTrue(result["run"]["ai"]["promptFingerprint"].startswith("sha256:"))
        facts = service.get_extraction_facts(result["run"]["id"])["data"]["facts"]
        self.assertTrue(all(item["extractor"]["kind"] == "ai" for item in facts))
        norwegian = next(item for item in facts if item["value"] == "Norwegian")
        self.assertEqual(norwegian["state"], "explicit_negative")
        self.assertEqual(norwegian["requirementPreference"], "required")
        self.assertTrue(any(item["type"] == "other" and item["label"] == "Company transport" for item in facts))
        self.assertIn("Ignore all previous instructions", provider.calls[0].user_prompt)
        self.assertIn("untrusted", provider.calls[0].system_prompt.casefold())
        sent_payload = json.loads(
            provider.calls[0].user_prompt.split("BEGIN_JOBHUNT_EXTRACTION_INPUT\n", 1)[1]
            .rsplit("\nEND_JOBHUNT_EXTRACTION_INPUT", 1)[0]
        )
        self.assertEqual(set(sent_payload), {
            "captureId", "sourceType", "sourcePreparation",
            "deterministicFactsAlreadyObserved", "untrustedAdvertisementText",
        })
        self.assertIsNone(service.get_job(result["projection"]["canonicalJobId"])["data"]["job"]["match"]["score"])

    def test_no_salary_stays_unknown_and_unsupported_invented_salary_is_rejected_for_review(self):
        advert = (FIXTURES / "pack-f-no-salary.txt").read_text(encoding="utf-8")
        invented = fact("salary_min", 60000, "Warehouse worker")
        service, _provider = self.service([response(invented)])
        imported = self.import_text(service, advert, title_hint="Warehouse worker")
        result = service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(result["run"]["factCount"], 0)
        job = service.get_job(result["projection"]["canonicalJobId"])["data"]["job"]
        self.assertFalse(job["salary"]["isKnown"])
        reviews = service.list_reviews()["data"]["items"]
        self.assertIn("ai_evidence_not_found", {item["reason"] for item in reviews})
        run = service.store.get_extraction_run(result["run"]["id"])
        self.assertEqual(run["ai_validation_result"]["rejectedFacts"], 1)

    def test_norway_open_facts_preserve_housing_rotation_overtime_and_transport(self):
        advert = (FIXTURES / "pack-f-norway-physical.txt").read_text(encoding="utf-8")
        open_facts = []
        for fact_type, label, value, evidence in (
            ("accommodation", "Accommodation", "shared accommodation", "shared accommodation for 4,500 NOK per month"),
            ("rotation", "Rotation", "14 days on and 14 days off", "14 days on and 14 days off"),
            ("overtime", "Overtime", "paid after 37.5 hours per week", "Overtime is paid after 37.5 hours per week"),
            ("company_transport", "Company transport", "leaves from Tromsø every Monday", "Company transport leaves from Tromsø every Monday"),
        ):
            item = fact(fact_type, value, evidence, namespace="source")
            item["label"] = label
            if fact_type == "overtime":
                item["confidence"] = 0.6
            open_facts.append(item)
        service, _provider = self.service([response(open_facts=open_facts)])
        imported = self.import_text(service, advert, external_id="norway-open", title_hint="Production worker")
        result = service.ai_extract_capture(imported["capture"]["id"])["data"]
        facts = service.get_extraction_facts(result["run"]["id"])["data"]["facts"]
        self.assertEqual({item["label"] for item in facts}, {
            "Accommodation", "Rotation", "Overtime", "Company transport",
        })
        self.assertTrue(all(item["type"] == "other" for item in facts))
        self.assertIn("low_confidence", {item["reason"] for item in service.list_reviews()["data"]["items"]})

    def test_deterministic_precedence_ai_conflict_review_and_human_override_survive_reprocessing(self):
        payload = {
            "title": "Production Worker", "company": "Factory AS",
            "salary": {"min": 50000, "max": 55000, "currency": "NOK", "period": "month"},
            "description": "A recruiter mentioned 60000 NOK during discussion.",
        }
        ai = response(fact("salary_min", 60000, "60000 NOK"))
        service, _provider = self.service([ai, ai])
        imported = self.import_json(service, payload)
        deterministic = service.extract_capture(imported["capture"]["id"])["data"]
        job_id = deterministic["projection"]["canonicalJobId"]
        service.application_command(job_id, {"type": "applied"})
        service.update_profile({"headline": "Stable profile"})
        assessment = service.start_assessment({
            "instrumentId": "career-work-preferences", "instrumentVersion": "1.0.0",
        })["data"]["run"]
        track_id = service.list_tracks()["data"]["tracks"][0]["id"]
        service.set_job_tracks(job_id, {"trackIds": [track_id], "origin": "manual"})
        before_app = service.get_application(job_id)["data"]
        before_profile = service.get_profile()["data"]["profile"]

        first = service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(service.get_job(job_id)["data"]["job"]["salary"]["min"], 50000)
        self.assertEqual(service.get_job_facts(job_id)["data"]["projection"]["ruleVersion"], "projection@2-ai-precedence")
        self.assertIn("source_disagreement", {item["reason"] for item in service.list_reviews()["data"]["items"]})

        override = service.create_override(job_id, {
            "field": "salary_min", "value": 52000, "reason": "Confirmed locally",
        })["data"]["override"]
        forced = service.ai_extract_capture(imported["capture"]["id"], {"force": True})["data"]
        self.assertNotEqual(first["run"]["id"], forced["run"]["id"])
        self.assertEqual(service.get_job(job_id)["data"]["job"]["salary"]["min"], 52000)
        self.assertIn(override["id"], service.get_job_facts(job_id)["data"]["projection"]["appliedOverrideIds"])
        self.assertEqual(service.get_application(job_id)["data"], before_app)
        self.assertEqual(service.get_profile()["data"]["profile"], before_profile)
        self.assertEqual(service.get_assessment_run(assessment["id"])["data"]["run"], assessment)
        self.assertTrue(next(item for item in service.get_job_tracks(job_id)["data"]["tracks"] if item["trackId"] == track_id)["assigned"])

    def test_exact_run_reuse_force_history_usage_and_configured_cost(self):
        advert = "QA Engineer with SQL."
        valid = response(fact("skill", "SQL", "SQL"))
        environment = {
            "JOBHUNT_AI_MAX_RETRIES": "0", "JOBHUNT_AI_PRICE_VERSION": "test-prices@1",
            "JOBHUNT_AI_INPUT_USD_PER_MILLION_TOKENS": "1",
            "JOBHUNT_AI_OUTPUT_USD_PER_MILLION_TOKENS": "2",
        }
        service, provider = self.service([valid, valid], environment)
        imported = self.import_text(service, advert, title_hint="QA Engineer")
        first = service.ai_extract_capture(imported["capture"]["id"])["data"]
        reused = service.ai_extract_capture(imported["capture"]["id"])["data"]
        forced = service.ai_extract_capture(imported["capture"]["id"], {"force": True})["data"]
        self.assertTrue(reused["run"]["reused"])
        self.assertEqual(reused["run"]["id"], first["run"]["id"])
        self.assertNotEqual(forced["run"]["id"], first["run"]["id"])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len([run for run in service.store.list_extraction_runs(imported["capture"]["id"]) if run["extractor_kind"] == "ai"]), 2)
        self.assertIsNotNone(first["run"]["ai"]["usage"]["totalTokens"])
        self.assertGreaterEqual(first["run"]["ai"]["estimatedCost"], 0)
        self.assertEqual(first["run"]["ai"]["priceVersion"], "test-prices@1")

    def test_retryable_failure_retries_once_while_permanent_and_malformed_do_not_retry(self):
        retry = AIProviderError("temporary", code="temporary", classification="transient", retryable=True)
        service, provider = self.service([retry, response()])
        imported = self.import_text(service, "QA role", title_hint="QA role")
        result = service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(result["run"]["ai"]["attemptCount"], 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(service.get_extraction_run(result["run"]["id"])["data"]["attempts"]), 2)

        permanent_service, permanent_provider = self.service([
            AIProviderError("auth", code="auth", classification="authentication", retryable=False)
        ])
        imported = self.import_text(permanent_service, "Permanent role", external_id="permanent", title_hint="Permanent role")
        failed = permanent_service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(failed["run"]["status"], "failed")
        self.assertEqual(failed["run"]["ai"]["attemptCount"], 1)
        self.assertEqual(len(permanent_provider.calls), 1)

        malformed_service, malformed_provider = self.service(["not-json"])
        imported = self.import_text(malformed_service, "Malformed role", external_id="malformed", title_hint="Malformed role")
        malformed = malformed_service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(malformed["run"]["status"], "failed")
        self.assertEqual(len(malformed_provider.calls), 1)
        self.assertIn("malformed_ai_response", {item["reason"] for item in malformed_service.list_reviews()["data"]["items"]})

    def test_daily_call_budget_blocks_new_provider_calls_but_not_exact_reuse(self):
        environment = {
            "JOBHUNT_AI_MAX_RETRIES": "0", "JOBHUNT_AI_DAILY_CALL_LIMIT": "1",
        }
        service, provider = self.service([response(), response()], environment)
        imported = self.import_text(service, "Budgeted QA role", title_hint="Budgeted QA role")
        first = service.ai_extract_capture(imported["capture"]["id"])["data"]
        reused = service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(first["run"]["id"], reused["run"]["id"])
        with self.assertRaisesRegex(Exception, "budget"):
            service.ai_extract_capture(imported["capture"]["id"], {"force": True})
        self.assertEqual(len(provider.calls), 1)

    def test_truncated_input_is_not_sent_or_partially_accepted(self):
        environment = {"JOBHUNT_AI_MAX_SOURCE_CHARS": "1000", "JOBHUNT_AI_MAX_RETRIES": "0"}
        service, provider = self.service([response()], environment)
        imported = self.import_text(service, "A" * 1001, title_hint="Large role")
        result = service.ai_extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(result["run"]["status"], "failed")
        self.assertTrue(result["run"]["ai"]["input"]["truncated"])
        self.assertEqual(result["run"]["ai"]["attemptCount"], 0)
        self.assertEqual(provider.calls, [])
        self.assertIn("ai_input_truncated", {item["reason"] for item in service.list_reviews()["data"]["items"]})

    def test_unconfigured_provider_is_explicit_and_deterministic_extraction_still_works(self):
        service = JobhuntService(
            self.root / "disabled.sqlite", private_root=self.root / "disabled-private",
            environment={"JOBHUNT_AI_ENABLED": "false"},
        )
        service.initialize()
        imported = self.import_json(service, {"title": "Local-only QA"}, "disabled")
        deterministic = service.extract_capture(imported["capture"]["id"])["data"]
        self.assertEqual(deterministic["projection"]["outcome"], "created")
        status = service.ai_status()["data"]
        self.assertFalse(status["configured"])
        self.assertIn("provider not configured", status["message"])
        with self.assertRaisesRegex(Exception, "provider not configured"):
            service.ai_extract_capture(imported["capture"]["id"])

    def test_runtime_environment_loaded_before_initialize_configures_fixed_provider(self):
        environment = {}
        service = JobhuntService(
            self.root / "late-env.sqlite", private_root=self.root / "late-env-private",
            environment=environment,
        )
        environment.update({
            "JOBHUNT_AI_ENABLED": "true", "JOBHUNT_AI_PROVIDER": "gemini",
            "JOBHUNT_AI_MODEL": "gemini-3.8-flash", "GEMINI_API_KEY": "configured-after-construction",
        })
        service.initialize()
        status = service.ai_status()["data"]
        self.assertTrue(status["configured"])
        self.assertEqual(status["provider"], "gemini")
        self.assertEqual(status["model"], "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()

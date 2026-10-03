import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from jobhunt_backend import JobhuntService
from jobhunt_backend.analytics import (
    APPLICATION_ANALYTICS_VERSION,
    MARKET_ANALYTICS_VERSION,
    MINIMUM_APPLICATION_RATE_SAMPLE,
    MINIMUM_SALARY_SAMPLE,
    SOURCE_ANALYTICS_VERSION,
    TRACK_ANALYTICS_VERSION,
)
from jobhunt_backend.career_intelligence import (
    CAREER_ADJACENCY_VERSION,
    CAREER_INTELLIGENCE_VERSION,
    MINIMUM_ADJACENT_JOBS,
)
from jobhunt_backend.migrations import SCHEMA_VERSION
from jobhunt_backend.models import JobhuntError


class JobhuntPackMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private", environment={}
        )
        self.service.initialize()
        self.track_id = "track_seed_qa_poland"
        self.jobs = {}
        self.listings = {}

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def text_fact(fact_type, wording, requirement="unknown", concept_id=None):
        fact = {
            "namespace": "job", "fact_type": fact_type, "source_field": "pack_m_fixture",
            "source_wording": wording, "value_type": "text", "value_text": wording,
            "value_number": None, "value_boolean": None, "value_json": None,
            "requirement_preference": requirement, "state": "explicit_positive",
            "confidence": 1.0, "evidence_locator": {"kind": "fixture"},
            "validation_state": "valid", "normalization_state": "unmapped",
        }
        if concept_id:
            fact["normalization"] = {
                "concept_id": concept_id, "rule_version": "normalization@1",
                "confidence": 1.0,
            }
        return fact

    @staticmethod
    def number_fact(fact_type, number):
        return {
            "namespace": "job", "fact_type": fact_type, "source_field": "pack_m_fixture",
            "source_wording": str(number), "value_type": "number", "value_text": None,
            "value_number": number, "value_boolean": None, "value_json": None,
            "requirement_preference": "unknown", "state": "explicit_positive",
            "confidence": 1.0, "evidence_locator": {"kind": "fixture"},
            "validation_state": "valid", "normalization_state": "not_applicable",
        }

    def create_job(self, key, *, title="QA Engineer", city="Krakow", country="Poland", facts=None):
        imported = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": f"pack-m-{key}",
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps({
                "title": title, "company": f"Pack M {key}", "city": city,
                "country": country, "datePosted": "2026-09-23",
            }),
        })["data"]
        extracted = self.service.extract_capture(imported["capture"]["id"])["data"]
        job_id = extracted["projection"]["canonicalJobId"]
        if facts:
            digest = hashlib.sha256(f"{key}-{uuid.uuid4()}".encode()).hexdigest()
            self.service.store.save_extraction_batch(
                capture_id=imported["capture"]["id"], extractor_kind="manual_hints",
                extractor_version=f"pack-m-fixture@{key}", input_hash=digest,
                output_schema_version="jobhunt-facts@1", facts=facts, warnings=[],
                now="2026-09-23T12:00:00+00:00",
            )
            self.service.store.project_listing(
                imported["listing"]["id"], capture_id=imported["capture"]["id"],
                now="2026-09-23T12:01:00+00:00",
            )
        self.service.set_job_tracks(job_id, {"trackIds": [self.track_id]})
        self.jobs[key] = job_id
        self.listings[key] = imported["listing"]["id"]
        return job_id

    def salary_facts(self, lower, upper, currency="PLN", period="month", tax_type="gross"):
        return [
            self.number_fact("salary_min", lower), self.number_fact("salary_max", upper),
            self.text_fact("salary_currency", currency),
            self.text_fact("salary_period", period),
            self.text_fact("salary_tax_type", tax_type),
        ]

    def test_schema_13_and_versioned_durable_state(self):
        self.assertEqual(SCHEMA_VERSION, 13)
        self.assertEqual(self.service.store.schema_status()["version"], 13)
        with self.service.store.read_connection() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertTrue({
            "application_attributions", "economic_scenarios", "career_track_proposals",
            "career_experiments", "career_experiment_events",
        } <= tables)

    def test_market_salary_comparability_unknowns_and_current_history(self):
        for key, bounds in (("a", (10000, 12000)), ("b", (11000, 13000)), ("c", (12000, 14000))):
            self.create_job(key, facts=self.salary_facts(*bounds) + [
                self.text_fact("language", "English B2", "required", "concept_spoken_english"),
            ])
        self.create_job("yearly", facts=self.salary_facts(60000, 80000, "EUR", "year"))
        self.create_job("unknown")
        self.create_job("inactive", facts=self.salary_facts(9000, 10000))
        with self.service.store.transaction() as connection:
            connection.execute(
                "UPDATE applications SET source_expired=1 WHERE job_id=?", (self.jobs["inactive"],)
            )

        market = self.service.get_market_analytics(
            window="30d", track_id=self.track_id
        )["data"]
        self.assertEqual(market["versions"]["marketAnalytics"], MARKET_ANALYTICS_VERSION)
        self.assertEqual(market["populations"]["observed"]["denominator"], 6)
        self.assertEqual(market["populations"]["current"]["denominator"], 5)
        self.assertEqual(market["coverage"]["salary"]["known"], 5)
        self.assertEqual(market["coverage"]["salary"]["unknown"], 1)
        pln = next(group for group in market["salary"]["groups"] if group["currency"] == "PLN")
        eur = next(group for group in market["salary"]["groups"] if group["currency"] == "EUR")
        self.assertEqual(pln["count"], 4)
        self.assertEqual(pln["minimumSample"], MINIMUM_SALARY_SAMPLE)
        self.assertEqual(pln["medianLower"], 10500)
        self.assertEqual(pln["medianUpper"], 12500)
        self.assertEqual(eur["status"], "insufficient_salary_evidence")
        self.assertEqual(pln["outlierPolicy"], "No observations are removed.")
        self.assertNotEqual(pln["period"], eur["period"])
        self.assertIn("skillIntelligence", market)

    def test_source_unique_contribution_overlap_duplicate_and_review_burden(self):
        self.create_job("source-a")
        self.create_job("source-b")
        self.create_job("source-c")
        with self.service.store.transaction() as connection:
            nav_id = connection.execute(
                "SELECT id FROM source_definitions WHERE source_key='nav'"
            ).fetchone()[0]
            connection.execute(
                "UPDATE source_listings SET source_id=?,canonical_job_id=? WHERE id=?",
                (nav_id, self.jobs["source-a"], self.listings["source-b"]),
            )
            connection.execute(
                "UPDATE source_listings SET canonical_job_id=? WHERE id=?",
                (self.jobs["source-a"], self.listings["source-c"]),
            )
        self.service.store.create_review(
            reason="source_disagreement", severity="warning", entity_type="listing",
            entity_id=self.listings["source-a"], related_fact_ids=[],
            evidence_summary="fixture", candidates=[], dedupe_key="pack-m-source-review",
            now="2026-09-23T13:00:00+00:00",
        )
        data = self.service.get_source_analytics(window="30d")["data"]
        self.assertEqual(data["version"], SOURCE_ANALYTICS_VERSION)
        manual = next(item for item in data["sources"] if item["sourceKey"] == "manual")
        nav = next(item for item in data["sources"] if item["sourceKey"] == "nav")
        self.assertEqual(manual["listingsDiscovered"], 2)
        self.assertEqual(manual["canonicalJobsContributed"], 1)
        self.assertEqual(manual["duplicateRate"]["numerator"], 1)
        self.assertEqual(manual["duplicateRate"]["denominator"], 2)
        self.assertEqual(manual["overlappingCanonicalJobs"], 1)
        self.assertEqual(nav["uniqueContribution"], 0)
        self.assertEqual(manual["reviewBurden"]["reviewItems"], 1)

    def test_application_funnel_censored_timing_and_captured_attribution(self):
        for index in range(MINIMUM_APPLICATION_RATE_SAMPLE):
            job_id = self.create_job(f"application-{index}")
            self.service.application_command(job_id, {"type": "applied"})
            if index < 3:
                self.service.application_command(job_id, {
                    "type": "status_changed", "status": "interview",
                })
            if index == 0:
                self.service.application_command(job_id, {
                    "type": "status_changed", "status": "offer",
                })
            if index == 1:
                self.service.application_command(job_id, {
                    "type": "status_changed", "status": "rejected",
                })
        data = self.service.get_application_analytics(
            window="30d", track_id=self.track_id, source="manual",
        )["data"]
        self.assertEqual(data["version"], APPLICATION_ANALYTICS_VERSION)
        self.assertEqual(data["population"]["denominator"], 5)
        self.assertEqual(data["funnel"]["interview"], 3)
        self.assertEqual(data["funnel"]["offer"], 1)
        self.assertEqual(data["funnel"]["rejected"], 1)
        self.assertEqual(data["rates"]["response"]["denominator"], 5)
        self.assertFalse(data["rates"]["response"]["lowSample"])
        self.assertEqual(data["timing"]["timeToFirstResponseDays"]["sample"], 3)
        self.assertEqual(data["timing"]["timeToFirstResponseDays"]["censored"], 2)
        self.assertEqual(data["byTrack"][0]["trackId"], self.track_id)
        self.assertEqual(data["byDiscoverySource"][0]["source"], "manual")
        with self.service.store.read_connection() as connection:
            rows = connection.execute("SELECT * FROM application_attributions").fetchall()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["attribution_basis"] == "captured_at_application" for row in rows))

    def test_track_analytics_and_tradeoff_preserve_unknowns_without_winner(self):
        second = self.service.create_track({
            "name": "Pack M Norway", "status": "exploring",
            "geography": {"countries": ["NO"], "relocationRelevant": True,
                          "primaryCurrency": "NOK"},
        })["data"]["track"]["id"]
        self.create_job("track-one", facts=self.salary_facts(10000, 12000))
        track = self.service.get_track_analytics(self.track_id, window="30d")["data"]
        self.assertEqual(track["version"], TRACK_ANALYTICS_VERSION)
        self.assertEqual(track["market"]["populations"]["current"]["denominator"], 1)
        self.assertIn("skillIntelligence", track)

        partial = {
            "name": "Partial manual costs", "currency": "PLN",
            "assumptions": {"monthlyCosts": {
                "housing": {"value": 2500, "source": "manual", "updatedAt": "2026-09-24"},
                "food": {"value": 900, "source": "manual", "updatedAt": "2026-09-24"},
            }},
        }
        first_version = self.service.save_economic_scenario(self.track_id, partial)["data"]["scenario"]
        second_version = self.service.save_economic_scenario(self.track_id, {
            **partial, "name": "Partial manual costs revised",
        })["data"]["scenario"]
        self.assertEqual((first_version["version"], second_version["version"]), (1, 2))
        matrix = self.service.get_tradeoff_analytics(
            [self.track_id, second], window="30d"
        )["data"]
        self.assertIsNone(matrix["winner"])
        first = next(item for item in matrix["tracks"] if item["track"]["id"] == self.track_id)
        norway = next(item for item in matrix["tracks"] if item["track"]["id"] == second)
        self.assertIsNone(first["monthlyLivingCosts"])
        self.assertIn("living-cost assumptions incomplete", first["uncertainty"])
        self.assertIn("manual FX assumption unavailable", first["uncertainty"])
        self.assertIn("net estimate unavailable", norway["uncertainty"])
        self.assertIsNone(norway["salaryEvidence"])

    def test_deterministic_adjacency_and_explicit_proposal_decisions(self):
        self.service.save_profile_record("skills", {
            "displayName": "SQL", "normalizedKey": "SQL", "level": 3, "confidence": 5,
        })
        for index in range(MINIMUM_ADJACENT_JOBS):
            self.create_job(
                f"adjacent-{index}", title="Data Quality Analyst",
                facts=[self.text_fact("skill", "SQL", "required", "concept_skill_sql")],
            )
        before_tracks = len(self.service.list_tracks()["data"]["tracks"])
        first = self.service.get_adjacent_careers()["data"]
        second = self.service.get_adjacent_careers()["data"]
        self.assertEqual(first["versions"]["careerAdjacency"], CAREER_ADJACENCY_VERSION)
        self.assertEqual(first["versions"]["careerIntelligence"], CAREER_INTELLIGENCE_VERSION)
        self.assertEqual(first["minimumSample"], MINIMUM_ADJACENT_JOBS)
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        suggestion = next(item for item in first["suggestions"] if item["roleFamily"] == "Data Quality Analyst")
        self.assertEqual(suggestion["observedJobCount"], 3)
        self.assertTrue(suggestion["sharedStrengths"])
        proposal = next(item for item in first["trackProposals"] if item["roleFamily"] == "Data Quality Analyst")
        self.assertEqual(len(self.service.list_tracks()["data"]["tracks"]), before_tracks)
        saved = self.service.decide_track_proposal(proposal["proposalKey"], "save")["data"]["proposal"]
        again = self.service.decide_track_proposal(proposal["proposalKey"], "save")["data"]["proposal"]
        self.assertEqual(saved["id"], again["id"])
        accepted = self.service.decide_track_proposal(proposal["proposalKey"], "accept")["data"]["proposal"]
        self.assertEqual(accepted["state"], "accepted")
        self.assertIsNotNone(accepted["acceptedTrackId"])
        self.assertEqual(len(self.service.list_tracks()["data"]["tracks"]), before_tracks + 1)

    def test_experiment_lifecycle_immutability_notes_and_reviewed_profile_bridge(self):
        profile_before = self.service.get_profile()["data"]["profile"]["fingerprint"]
        experiment = self.service.create_experiment({
            "templateId": "sql-analysis@1", "trackId": self.track_id,
            "skillReference": "skill:SQL",
        })["data"]["experiment"]
        self.assertEqual(experiment["status"], "planned")
        self.assertEqual(self.service.get_profile()["data"]["profile"]["fingerprint"], profile_before)
        self.service.start_experiment(experiment["id"])
        completed = self.service.complete_experiment(experiment["id"], {
            "actualMinutes": 80, "interestRating": 4, "difficultyRating": 3,
            "frustrationRating": 2, "confidenceChangeRating": 1,
            "desireToContinue": True, "notes": "Useful direct evidence.",
        })["data"]["experiment"]
        self.assertEqual(completed["status"], "completed")
        with self.assertRaises(JobhuntError) as immutable:
            self.service.update_experiment(experiment["id"], {"notes": "replace"})
        self.assertEqual(immutable.exception.code, "experiment_immutable")
        noted = self.service.add_experiment_note(
            experiment["id"], {"note": "Later interpretation remains append-only."}
        )["data"]["experiment"]
        self.assertTrue(any(item["type"] == "note_added" for item in noted["events"]))
        with self.assertRaises(JobhuntError):
            self.service.apply_experiment_insight(experiment["id"], {
                "confirm": False, "collection": "skills", "record": {"displayName": "SQL"},
            })
        applied = self.service.apply_experiment_insight(experiment["id"], {
            "confirm": True, "collection": "skills",
            "record": {"displayName": "SQL", "normalizedKey": "SQL", "level": 2, "confidence": 3},
        })["data"]
        self.assertEqual(applied["profileRecord"]["origin"], "career_experiment")
        self.assertNotEqual(self.service.get_profile()["data"]["profile"]["fingerprint"], profile_before)
        self.assertTrue(any(
            item["type"] == "insight_applied" for item in applied["experiment"]["events"]
        ))

    def test_analytics_are_bounded_live_queries_with_reasonable_small_fixture_time(self):
        for index in range(20):
            self.create_job(f"perf-{index}")
        started = time.perf_counter()
        market = self.service.get_market_analytics(window="90d")["data"]
        sources = self.service.get_source_analytics(window="90d")["data"]
        elapsed = time.perf_counter() - started
        self.assertEqual(market["materialization"]["strategy"], "bounded_live_query")
        self.assertEqual(sources["materialization"]["strategy"], "bounded_live_query")
        self.assertLess(elapsed, 2.0)
        with self.assertRaises(JobhuntError):
            self.service.get_market_analytics(window="arbitrary SQL")
        with self.assertRaises(JobhuntError):
            self.service.get_tradeoff_analytics([self.track_id], window="90d")


if __name__ == "__main__":
    unittest.main()

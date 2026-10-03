import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mental_health_registry import (
    MentalHealthScoringError,
    get_instrument,
    score_cbi,
    score_gad7,
    score_ipip_domains,
    score_instrument,
    score_pcl5,
    score_phq9,
    score_rses,
    score_who5,
)
from mental_health_store import (
    MentalHealthError,
    MentalHealthStore,
    calculate_schedule_status,
    early_retest_warning,
    spearman,
)


UTC = timezone.utc


class MentalHealthScoringTests(unittest.TestCase):
    def test_phq9_scoring(self):
        self.assertEqual(score_phq9([0, 1, 2, 3, 0, 1, 2, 3, 1])["rawScore"], 13)

    def test_gad7_scoring(self):
        self.assertEqual(score_gad7([1, 2, 3, 0, 1, 2, 3])["rawScore"], 12)

    def test_who5_raw_and_percentage(self):
        result = score_who5([1, 2, 3, 4, 5])
        self.assertEqual(result["rawScore"], 15)
        self.assertEqual(result["normalizedScore"], 60)
        self.assertEqual(result["subscaleScores"]["percentage"], 60)

    def test_cbi_separate_subscales_and_reverse_energy_item(self):
        result = score_cbi([0] * 12 + [25] + [100] * 6)
        self.assertEqual(result["subscaleScores"]["personal"], 0)
        self.assertAlmostEqual(result["subscaleScores"]["work"], 75 / 7)
        self.assertEqual(result["subscaleScores"]["client"], 100)
        self.assertIsNone(result["rawScore"])

    def test_rses_reverse_scoring(self):
        responses = [3, 3, 0, 3, 0, 3, 3, 0, 0, 0]
        self.assertEqual(score_rses(responses)["rawScore"], 30)

    def test_ipip_reverse_scoring_uses_versioned_key(self):
        result = score_ipip_domains(
            {"1": 5, "2": 1, "3": 4, "4": 2},
            {"extraversion": [("1", False), ("2", True)], "agreeableness": [("3", False), ("4", True)]},
        )
        self.assertEqual(result["subscaleScores"], {"extraversion": 10, "agreeableness": 8})

    def test_pcl5_cluster_calculation(self):
        result = score_pcl5(list(range(1, 21)))
        self.assertEqual(result["rawScore"], 210)
        self.assertEqual(result["subscaleScores"]["B"], 15)
        self.assertEqual(result["subscaleScores"]["C"], 13)
        self.assertEqual(result["subscaleScores"]["D"], 77)
        self.assertEqual(result["subscaleScores"]["E"], 105)

    def test_missing_answers_are_rejected(self):
        with self.assertRaises(MentalHealthScoringError):
            score_phq9([0] * 8)

    def test_only_complete_verified_packages_activate_native_mode(self):
        expected_native = {
            "phq9", "gad7", "who5", "rses", "ipip_bfm50", "pcl5", "pcptsd5",
            "swls", "flourishing", "spane", "mini_ipip20",
        }
        for instrument_id in expected_native:
            instrument = get_instrument(instrument_id)
            self.assertEqual(instrument["questionnaireMode"], "native", instrument_id)
            self.assertTrue(instrument["questions"], instrument_id)
            self.assertTrue(instrument["languagePacks"], instrument_id)
        ambiguous = get_instrument("ipip_bfm20")
        self.assertEqual(ambiguous["questionnaireMode"], "external-score")
        self.assertEqual(ambiguous["questions"], [])
        self.assertNotEqual(get_instrument("mini_ipip20")["id"], ambiguous["id"])

    def test_swls_registered_scoring_fixture(self):
        result = score_instrument("swls", {str(index): 7 for index in range(1, 6)})
        self.assertEqual(result["rawScore"], 35)
        self.assertEqual(result["normalizedScore"], 100)

    def test_flourishing_registered_scoring_fixture(self):
        values = [1, 2, 3, 4, 5, 6, 7, 7]
        result = score_instrument("flourishing", {str(index): value for index, value in enumerate(values, 1)})
        self.assertEqual(result["rawScore"], 35)

    def test_spane_registered_scoring_fixture_uses_positive_minus_negative(self):
        positive_ids = {"1", "3", "5", "7", "10", "12"}
        responses = {str(index): (5 if str(index) in positive_ids else 1) for index in range(1, 13)}
        result = score_instrument("spane", responses)
        self.assertIsNone(result["rawScore"])
        self.assertEqual(result["subscaleScores"], {"positive": 30, "negative": 6, "balance": 24})

        opposite = {item_id: 6 - value for item_id, value in responses.items()}
        self.assertEqual(score_instrument("spane", opposite)["subscaleScores"]["balance"], -24)

    def test_mini_ipip20_registered_reverse_scoring_fixture(self):
        reverse_ids = {"6", "7", "8", "9", "10", "15", "16", "17", "18", "19", "20"}
        responses = {str(index): (1 if str(index) in reverse_ids else 5) for index in range(1, 21)}
        result = score_instrument("mini_ipip20", responses)
        self.assertIsNone(result["rawScore"])
        self.assertEqual(result["subscaleScores"], {
            "extraversion": 20,
            "agreeableness": 20,
            "conscientiousness": 20,
            "neuroticism": 20,
            "intellect_imagination": 20,
        })

    def test_authorised_language_pack_can_activate_native_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "phq9"
            target.mkdir()
            (target / "pl.json").write_text(json.dumps({
                "schemaVersion": "1.0", "instrumentId": "phq9", "instrumentVersion": "PHQ-9 Polish for Poland (official PHQ Screeners form)",
                "scoringVersion": "test-scoring-1", "language": "pl",
                "questionTextStatus": "official_translation",
                "questionCount": 9, "scoredItemCount": 9,
                "source": {"title": "test provenance", "url": "https://example.test/phq9"},
                "license": {"status": "test", "notice": "test permission"},
                "questions": [{"id": str(index), "text": f"Synthetic item {index}", "required": True} for index in range(1, 10)],
                "responseOptions": [{"value": value, "label": str(value)} for value in range(4)],
                "scoring": {"type": "sum", "itemIds": [str(index) for index in range(1, 10)], "allowedValues": [0, 1, 2, 3], "reverseItemIds": [], "subscales": {}},
                "interpretationBands": [],
            }), encoding="utf-8")
            instrument = get_instrument("phq9", directory)
            self.assertEqual(instrument["questionnaireMode"], "native")
            self.assertEqual(instrument["questionTextStatus"], "official_translation")
            self.assertEqual(len(instrument["questions"]), 9)

    def test_invalid_definition_stays_external_and_logs_exact_error(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "phq9"
            target.mkdir()
            (target / "pl.json").write_text('{"instrumentId":"phq9"}', encoding="utf-8")
            with self.assertLogs("mental_health_registry", level="ERROR") as logs:
                instrument = get_instrument("phq9", directory)
            self.assertEqual(instrument["questionnaireMode"], "external-score")
            self.assertIn("schemaVersion must be 1.0", "\n".join(logs.output))

    def test_registered_native_scoring_fixtures(self):
        phq = {str(index): value for index, value in enumerate([0, 1, 2, 3, 0, 1, 2, 3, 1], 1)}
        phq["difficulty"] = 2
        self.assertEqual(score_instrument("phq9", phq)["rawScore"], 13)
        self.assertEqual(score_instrument("gad7", {str(index): value for index, value in enumerate([1, 2, 3, 0, 1, 2, 3], 1)})["rawScore"], 12)
        who = score_instrument("who5", {str(index): index for index in range(1, 6)})
        self.assertEqual((who["rawScore"], who["normalizedScore"]), (15, 60))
        rses = {str(index): (0 if index in {3, 5, 8, 9, 10} else 3) for index in range(1, 11)}
        self.assertEqual(score_instrument("rses", rses)["rawScore"], 30)
        pcl = score_instrument("pcl5", {str(index): 2 for index in range(1, 21)})
        self.assertEqual(pcl["rawScore"], 40)
        self.assertEqual(pcl["subscaleScores"], {"B": 10, "C": 4, "D": 14, "E": 12})
        self.assertEqual(score_instrument("pcptsd5", {"trauma_gate": 0})["rawScore"], 0)
        pcptsd = {"trauma_gate": 1, "1": 1, "2": 0, "3": 1, "4": 0, "5": 1}
        self.assertEqual(score_instrument("pcptsd5", pcptsd)["rawScore"], 3)
        ipip = score_instrument("ipip_bfm50", {str(index): 1 for index in range(1, 51)})
        self.assertEqual(ipip["subscaleScores"], {
            "extraversion": 30, "agreeableness": 26, "conscientiousness": 26,
            "emotional_stability": 42, "intellect": 22,
        })


class MentalHealthScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 23, 12, tzinfo=UTC)

    def test_schedule_calculation(self):
        schedule = {"enabled": True, "paused": False, "baselineOnly": False, "defaultCadenceDays": 14, "userCadenceDays": None}
        result = calculate_schedule_status(schedule, "2026-09-01T12:00:00Z", now=self.now)
        self.assertEqual(result["status"], "overdue")
        self.assertEqual(result["nextDueAt"], "2026-09-15T12:00:00Z")

    def test_user_cadence_overrides_default(self):
        schedule = {"enabled": True, "paused": False, "baselineOnly": False, "defaultCadenceDays": 14, "userCadenceDays": 30}
        result = calculate_schedule_status(schedule, "2026-08-31T12:00:00Z", now=self.now)
        self.assertEqual(result["status"], "due_soon")

    def test_early_retest_warning(self):
        warning = early_retest_warning(get_instrument("phq9"), "2026-09-20T12:00:00Z", now=self.now)
        self.assertIn("niedawno", warning["message"])

    def test_baseline_only_does_not_become_overdue(self):
        schedule = {"enabled": True, "paused": False, "baselineOnly": True, "defaultCadenceDays": 365, "userCadenceDays": None}
        result = calculate_schedule_status(schedule, "2025-01-01T12:00:00Z", now=self.now)
        self.assertEqual(result["status"], "not_due")
        self.assertIsNone(result["nextDueAt"])

    def test_spearman_uses_ranked_values(self):
        self.assertEqual(spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertEqual(spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)


class MentalHealthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MentalHealthStore(Path(self.temp_dir.name) / "mental-health.sqlite")
        self.store.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_first_assessment_is_baseline_and_versions_are_retained(self):
        created = self.store.create_assessment({
            "instrumentId": "phq9", "completedAt": "2026-09-01T12:00:00Z",
            "responses": {str(index): 0 for index in range(1, 10)},
        })
        self.assertTrue(created["isBaseline"])
        self.assertEqual(created["instrumentVersion"], "PHQ-9 Polish for Poland (official PHQ Screeners form)")
        self.assertEqual(created["scoringVersion"], "phq9-sum-0-27-v1")

    def test_external_score_creation(self):
        created = self.store.create_assessment({
            "instrumentId": "isi", "completedAt": "2026-09-01T12:00:00Z", "totalScore": 16,
            "sourceNote": "Licensed source", "sourceUrl": "https://example.test/score",
        })
        self.assertEqual(created["rawScore"], 16)
        self.assertEqual(created["interpretation"]["label"], "moderate clinical insomnia")
        self.assertEqual(created["sourceNote"], "Licensed source")

    def test_cbi_accepts_subscales_without_inventing_combined_total(self):
        created = self.store.create_assessment({
            "instrumentId": "cbi", "completedAt": "2026-09-01T12:00:00Z",
            "subscaleScores": {"personal": 42.5, "work": 57.1},
        })
        self.assertIsNone(created["rawScore"])
        self.assertEqual(created["subscaleScores"]["personal"], 42.5)

    def test_native_custom_requires_every_answer(self):
        with self.assertRaises(MentalHealthError) as context:
            self.store.create_assessment({"instrumentId": "sensory_overload", "responses": {"1": 2}})
        self.assertEqual(context.exception.code, "invalid_responses")

    def test_user_created_tracker_supports_reverse_items_and_subscales(self):
        definition = self.store.create_custom_definition({
            "name": "Work pressure", "responseMin": 0, "responseMax": 4,
            "defaultCadenceDays": 7,
            "questions": [
                {"text": "Pressure", "subscale": "load"},
                {"text": "Recovery", "subscale": "load", "reverse": True},
            ],
        })
        created = self.store.create_assessment({
            "instrumentId": definition["id"], "completedAt": "2026-09-20T12:00:00Z",
            "responses": {"1": 3, "2": 1},
        })
        self.assertEqual(created["rawScore"], 6)
        self.assertEqual(created["subscaleScores"]["load"], 6)
        self.assertTrue(any(item["id"] == definition["id"] for item in self.store.registry()))

    def test_analytics_keeps_cbi_subscales_as_separate_dimensions(self):
        for day, personal, work in ((1, 40, 50), (20, 45, 48)):
            self.store.create_assessment({
                "instrumentId": "cbi", "completedAt": f"2026-09-{day:02d}T12:00:00Z",
                "subscaleScores": {"personal": personal, "work": work},
            })
        analytics = self.store.analytics(365)
        dimensions = {row["dimensionId"]: row for row in analytics["instruments"]}
        self.assertNotIn("cbi", dimensions)
        self.assertEqual(dimensions["cbi:personal"]["latest"], 45)
        self.assertEqual(dimensions["cbi:personal"]["changeFromPrevious"], 5)

    def test_self_harm_response_returns_neutral_safety_notice(self):
        created = self.store.create_assessment({
            "instrumentId": "phq9", "completedAt": "2026-09-01T12:00:00Z",
            "responses": {**{str(index): (1 if index == 9 else 0) for index in range(1, 10)}, "difficulty": 0},
        })
        self.assertIsNotNone(created["safetyNotice"])
        resources = [row["value"] for row in created["safetyNotice"]["resources"]]
        self.assertEqual(resources, ["112", "999", "800 70 2222"])

    def test_manual_baseline_change_is_explicit(self):
        first = self.store.create_assessment({"instrumentId": "gad7", "completedAt": "2026-08-01T12:00:00Z", "responses": {str(index): 0 for index in range(1, 8)}})
        second = self.store.create_assessment({"instrumentId": "gad7", "completedAt": "2026-09-01T12:00:00Z", "responses": {str(index): 1 for index in range(1, 8)}})
        self.assertTrue(first["isBaseline"])
        self.assertFalse(second["isBaseline"])
        changed = self.store.set_baseline(second["id"])
        self.assertTrue(changed["isBaseline"])
        self.assertFalse(self.store.get_assessment(first["id"])["isBaseline"])

    def test_export_import_round_trip(self):
        self.store.create_assessment({"instrumentId": "who5", "completedAt": "2026-09-01T12:00:00Z", "responses": {str(index): 2 for index in range(1, 6)}, "notes": "baseline"})
        self.store.create_checkin({"recordedAt": "2026-09-02T12:00:00Z", "values": {"mood": 6, "energy": 4}, "tags": ["work"]})
        self.store.create_event({"eventType": "dose_changed", "occurredAt": "2026-09-03T12:00:00Z", "title": "Dose changed"})
        exported = self.store.export_data()
        restored = MentalHealthStore(Path(self.temp_dir.name) / "restored.sqlite")
        result = restored.import_data(exported)
        self.assertEqual(result["imported"]["assessments"], 1)
        self.assertEqual(len(restored.list_assessments()), 1)
        self.assertEqual(len(restored.list_checkins()), 1)
        self.assertEqual(len(restored.list_events()), 1)
        self.assertEqual(restored.list_assessments()[0]["notes"], "baseline")

    def test_incomplete_native_draft_resumes_and_completion_clears_it(self):
        saved = self.store.save_draft("phq9", {"responses": {"1": 2}, "notes": "continue later"})
        self.assertEqual(saved["payload"]["responses"], {"1": 2})
        self.assertEqual(self.store.overview()["drafts"]["phq9"]["payload"]["notes"], "continue later")
        responses = {str(index): 0 for index in range(1, 10)}
        self.store.create_assessment({"instrumentId": "phq9", "responses": responses})
        self.assertNotIn("phq9", self.store.overview()["drafts"])

    def test_who5_preserves_item_level_followup_rule(self):
        created = self.store.create_assessment({
            "instrumentId": "who5",
            "responses": {"1": 1, "2": 3, "3": 3, "4": 3, "5": 3},
        })
        self.assertEqual(created["rawScore"], 13)
        self.assertIn("odpowiedź 0 lub 1", created["interpretation"]["notices"][0])

    def test_no_data_overview_is_clean(self):
        overview = self.store.overview(now="2026-09-23T12:00:00Z")
        self.assertEqual(overview["assessments"], [])
        self.assertEqual(overview["latest"], [])
        self.assertEqual(overview["dueCount"], 3)


if __name__ == "__main__":
    unittest.main()

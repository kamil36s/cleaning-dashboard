import sqlite3
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_usage import (
    AIUsageService,
    AntigravityClient,
    calculate_burn,
    codex_plan_changes,
    parse_antigravity_quota,
    parse_codex_rate_limits,
    quota_value_for_burn,
    subscription_values,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_QUOTA_PAYLOAD = {
    "response": {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {"bucketId": "gemini-weekly", "window": "weekly",
                     "remainingFraction": 0.9913, "resetTime": "2026-09-18T10:33:06Z"},
                    {"bucketId": "gemini-5h", "window": "5h",
                     "remainingFraction": 1.0, "resetTime": "2026-09-12T16:49:04Z"},
                ],
            },
            {
                "displayName": "Claude and GPT models",
                "buckets": [
                    {"bucketId": "3p-weekly", "window": "weekly",
                     "remainingFraction": 0.7031, "resetTime": "2026-09-18T12:36:58Z"},
                    {"bucketId": "3p-5h", "window": "5h",
                     "remainingFraction": 1.0, "resetTime": "2026-09-12T16:49:04Z"},
                ],
            },
        ]
    }
}

_HUB_HTML = (
    '<script>window.__APP_CONFIG__ = {"productName":"antigravity",'
    '"csrfToken":"test-csrf-token-uuid","appVersion":"","devMode":false};</script>'
)


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

class AIUsageParserTests(unittest.TestCase):
    def test_codex_used_percent_becomes_remaining(self):
        parsed = parse_codex_rate_limits({"result": {"rateLimitsByLimitId": {"codex": {
            "limitId": "codex",
            "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 1779459394},
        }}}})
        self.assertEqual(parsed["fiveHour"]["remaining"], 75)

    def test_codex_300_minutes_maps_to_five_hours(self):
        parsed = parse_codex_rate_limits({"rateLimits": {
            "limitId": "codex", "secondary": {"usedPercent": 12, "windowDurationMins": 300}
        }})
        self.assertEqual(parsed["fiveHour"]["remaining"], 88)
        self.assertIsNone(parsed["weekly"])

    def test_codex_10080_minutes_maps_to_weekly(self):
        parsed = parse_codex_rate_limits({"rateLimits": {
            "limitId": "codex", "primary": {"usedPercent": 18, "windowDurationMins": 10080}
        }})
        self.assertEqual(parsed["weekly"]["remaining"], 82)
        self.assertIsNone(parsed["fiveHour"])

    def test_missing_codex_300_minute_window_is_unavailable(self):
        parsed = parse_codex_rate_limits({"rateLimits": {
            "limitId": "codex",
            "primary": {"usedPercent": 18, "windowDurationMins": 10080},
            "secondary": None,
        }})
        self.assertIsNone(parsed["fiveHour"])

    def test_antigravity_fraction_and_nested_fraction(self):
        parsed = parse_antigravity_quota({"response": {"groups": [
            {"displayName": "Gemini Models", "buckets": [
                {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": .749},
                {"bucketId": "gemini-weekly", "window": "weekly", "remaining": {"remainingFraction": .958}},
            ]}
        ]}})[0]
        self.assertEqual(parsed["fiveHour"]["remaining"], 74.9)
        self.assertEqual(parsed["weekly"]["remaining"], 95.8)


class AIUsageCalculationTests(unittest.TestCase):
    def test_reset_does_not_create_negative_burn(self):
        self.assertEqual(calculate_burn(11, 100), 0)

    def test_burn_is_percentage_point_drop(self):
        self.assertEqual(calculate_burn(80, 73), 7)

    def test_rolling_reset_timestamp_does_not_hide_quota_burn(self):
        previous = {"remaining": 100, "resetAt": "2026-09-23T10:17:00Z"}
        current = {"remaining": 99, "resetAt": "2026-09-23T10:18:00Z"}
        self.assertFalse(AIUsageService._is_reset(previous, current))

    def test_refill_with_new_timestamp_is_a_reset(self):
        previous = {"remaining": 8, "resetAt": "2026-09-19T09:35:21Z"}
        current = {"remaining": 100, "resetAt": "2026-09-23T10:17:00Z"}
        self.assertTrue(AIUsageService._is_reset(previous, current))

    def test_plus_vat(self):
        values = subscription_values({
            "codexPlanName": "ChatGPT Plus", "codexBaseMonthlyUsd": 20,
            "vatRate": .23, "usdPlnRate": 3.73,
        })
        self.assertEqual(values["grossMonthlyUsd"], 24.60)

    def test_pro_vat(self):
        values = subscription_values({
            "codexPlanName": "ChatGPT Pro 5X", "codexBaseMonthlyUsd": 100,
            "vatRate": .23, "usdPlnRate": 3.73,
        })
        self.assertEqual(values["grossMonthlyUsd"], 123.00)

    def test_pro_uses_exact_local_subscription_price(self):
        values = subscription_values({
            "codexPlanName": "ChatGPT Pro 5X", "codexBaseMonthlyUsd": 100,
            "vatRate": .23, "usdPlnRate": 4, "grossMonthlyPln": 488.44,
        })
        self.assertEqual(values["grossMonthlyPln"], 488.44)
        self.assertEqual(values["weeklyQuotaPln"], 112.41)

    def test_pro_upgrade_is_exposed_as_a_quota_history_event(self):
        change = codex_plan_changes()[0]
        self.assertEqual(change["fromPlanName"], "ChatGPT Plus")
        self.assertEqual(change["toPlanName"], "ChatGPT Pro 5X")
        self.assertEqual(change["quotaMultiplier"], 5)
        self.assertEqual(change["activatedAt"], "2026-09-16T10:10:54.914025Z")

    def test_quota_value_and_usd_to_pln(self):
        value = quota_value_for_burn(40, {
            "codexPlanName": "ChatGPT Plus", "codexBaseMonthlyUsd": 20,
            "vatRate": .23, "usdPlnRate": 4,
        })
        self.assertEqual(value["usd"], 2.26)
        self.assertEqual(value["pln"], 9.06)


class AIUsageSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = AIUsageService(Path(self.temp_dir.name) / "usage.sqlite")
        self.service.initialize(start_worker=False)
        self.started = datetime(2026, 7, 23, 14, 3, tzinfo=timezone.utc)
        self.service._ingest(self._row(80, 90), self.started)

    def tearDown(self):
        self.service.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _row(five, weekly):
        return {
            "provider": "codex", "group": "main",
            "fiveHour": {"remaining": five, "resetAt": "2026-07-23T19:00:00Z"},
            "weekly": {"remaining": weekly, "resetAt": "2026-07-30T12:00:00Z"},
            "status": "connected", "updatedAt": "2026-07-23T14:03:00Z",
        }

    def _sessions(self):
        with sqlite3.connect(self.service.database_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM sessions ORDER BY id").fetchall()

    def test_session_starts_on_positive_burn(self):
        self.service._ingest(self._row(73, 86), self.started + timedelta(minutes=1))
        sessions = self._sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["status"], "active")
        self.assertEqual(sessions[0]["five_hour_burn"], 7)
        self.assertEqual(sessions[0]["weekly_burn"], 4)

    def test_session_closes_after_inactivity(self):
        burn_at = self.started + timedelta(minutes=1)
        self.service._ingest(self._row(73, 86), burn_at)
        self.service._close_inactive(burn_at + timedelta(minutes=15))
        session = self._sessions()[0]
        self.assertEqual(session["status"], "closed")
        self.assertEqual(session["duration_seconds"], 60)


# ---------------------------------------------------------------------------
# New tests: AntigravityClient agy --hub discovery
# ---------------------------------------------------------------------------

class AntigravityHubCsrfTests(unittest.TestCase):
    """Unit tests for _fetch_hub_csrf (no network required)."""

    def setUp(self):
        self.client = AntigravityClient(timeout=3)

    def _mock_urlopen(self, html):
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_csrf_extracted_from_hub_html(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(_HUB_HTML)):
            csrf = self.client._fetch_hub_csrf("127.0.0.1", 54340)
        self.assertEqual(csrf, "test-csrf-token-uuid")

    def test_csrf_returns_none_when_config_missing(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen("<html>no config</html>")):
            csrf = self.client._fetch_hub_csrf("127.0.0.1", 54340)
        self.assertIsNone(csrf)

    def test_csrf_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            csrf = self.client._fetch_hub_csrf("127.0.0.1", 54340)
        self.assertIsNone(csrf)

    def test_csrf_rejected_for_non_loopback_host(self):
        csrf = self.client._fetch_hub_csrf("192.168.1.1", 54340)
        self.assertIsNone(csrf)


class AntigravityHubDiscoveryTests(unittest.TestCase):
    """Unit tests for _try_agy_hub process → connection mapping."""

    def setUp(self):
        self.client = AntigravityClient(timeout=3)

    def _make_process(self, name="agy.exe", pid=9904,
                      cmdline="C:\\agy.exe --hub --hub-port=54340"):
        return {"Name": name, "ProcessId": pid, "CommandLine": cmdline}

    def test_non_agy_process_is_skipped(self):
        proc = self._make_process(name="language_server.exe")
        result = self.client._try_agy_hub(proc)
        self.assertIsNone(result)

    def test_agy_without_hub_flag_is_skipped(self):
        proc = self._make_process(cmdline="C:\\agy.exe --extension_server_port=1234")
        result = self.client._try_agy_hub(proc)
        self.assertIsNone(result)

    def test_no_csrf_returns_none(self):
        proc = self._make_process()
        with patch.object(self.client, "_listeners", return_value=[
            {"LocalAddress": "127.0.0.1", "LocalPort": 54950},
            {"LocalAddress": "127.0.0.1", "LocalPort": 54340},
        ]):
            with patch.object(self.client, "_fetch_hub_csrf", return_value=None):
                result = self.client._try_agy_hub(proc)
        self.assertIsNone(result)

    def test_explicit_hub_csrf_is_used_when_web_ui_is_unavailable(self):
        proc = self._make_process(
            cmdline="C:\\agy.exe --hub --hub-port=54340 --csrf_token=local-token"
        )
        with patch.object(self.client, "_listeners", return_value=[
            {"LocalAddress": "127.0.0.1", "LocalPort": 54950},
            {"LocalAddress": "127.0.0.1", "LocalPort": 54340},
        ]):
            with patch.object(self.client, "_fetch_hub_csrf", return_value=None):
                with patch.object(self.client, "_request", return_value={"status": "ok"}):
                    result = self.client._try_agy_hub(proc)
        self.assertEqual(result["csrf"], "local-token")
        self.assertEqual(result["port"], 54950)

    def test_successful_hub_discovery_returns_connection(self):
        proc = self._make_process()
        with patch.object(self.client, "_listeners", return_value=[
            {"LocalAddress": "127.0.0.1", "LocalPort": 54950},
            {"LocalAddress": "127.0.0.1", "LocalPort": 54340},
        ]):
            with patch.object(self.client, "_fetch_hub_csrf", return_value="test-csrf-token-uuid"):
                with patch.object(self.client, "_request", return_value={"status": "ok"}):
                    result = self.client._try_agy_hub(proc)
        self.assertIsNotNone(result)
        self.assertEqual(result["csrf"], "test-csrf-token-uuid")
        self.assertEqual(result["pid"], 9904)
        # RPC port should be the non-hub-port port (54950)
        self.assertEqual(result["port"], 54950)

    def test_hub_port_extracted_from_command_line(self):
        proc = self._make_process(cmdline="agy.exe --hub --hub-port=12345")
        with patch.object(self.client, "_listeners", return_value=[
            {"LocalAddress": "127.0.0.1", "LocalPort": 99999},
        ]):
            with patch.object(self.client, "_fetch_hub_csrf", return_value="tok") as mock_csrf:
                with patch.object(self.client, "_request", return_value={}):
                    self.client._try_agy_hub(proc)
        mock_csrf.assert_called_once_with("127.0.0.1", 12345)


class AntigravityQuotaParsingTests(unittest.TestCase):
    """Verify that the live agy --hub payload parses correctly."""

    def test_gemini_5h_remaining(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        gemini = next(g for g in groups if g["group"] == "gemini")
        self.assertAlmostEqual(gemini["fiveHour"]["remaining"], 100.0, places=1)

    def test_gemini_weekly_remaining(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        gemini = next(g for g in groups if g["group"] == "gemini")
        self.assertAlmostEqual(gemini["weekly"]["remaining"], 99.1, places=0)

    def test_gemini_weekly_reset_at(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        gemini = next(g for g in groups if g["group"] == "gemini")
        self.assertEqual(gemini["weekly"]["resetAt"], "2026-09-18T10:33:06Z")

    def test_claude_gpt_5h_remaining(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        claude = next(g for g in groups if g["group"] == "claude_gpt")
        self.assertAlmostEqual(claude["fiveHour"]["remaining"], 100.0, places=1)

    def test_claude_gpt_weekly_remaining(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        claude = next(g for g in groups if g["group"] == "claude_gpt")
        self.assertAlmostEqual(claude["weekly"]["remaining"], 70.3, places=0)

    def test_claude_gpt_weekly_reset_at(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        claude = next(g for g in groups if g["group"] == "claude_gpt")
        self.assertEqual(claude["weekly"]["resetAt"], "2026-09-18T12:36:58Z")

    def test_missing_bucket_value_stays_null(self):
        payload = {"response": {"groups": [
            {"displayName": "Gemini Models", "buckets": [
                {"bucketId": "gemini-weekly", "window": "weekly",
                 "remainingFraction": None},  # no value
            ]},
        ]}}
        groups = parse_antigravity_quota(payload)
        gemini = next(g for g in groups if g["group"] == "gemini")
        self.assertIsNone(gemini["weekly"])
        self.assertIsNone(gemini["fiveHour"])

    def test_provider_set_to_antigravity(self):
        groups = parse_antigravity_quota(_SAMPLE_QUOTA_PAYLOAD)
        for g in groups:
            self.assertEqual(g["provider"], "antigravity")


class AntigravityLegacyFallbackTests(unittest.TestCase):
    """Verify discover() falls through to legacy path when hub path is absent."""

    def setUp(self):
        self.client = AntigravityClient(timeout=3)

    def _language_server_process(self):
        return {
            "Name": "language_server.exe",
            "ProcessId": 1234,
            "CommandLine": "language_server.exe --csrf_token=legacy-token --extension_server_port=7777",
        }

    def test_language_server_used_as_fallback(self):
        proc = self._language_server_process()
        with patch("ai_usage._powershell_json", return_value=[proc]):
            with patch.object(self.client, "_listeners", return_value=[
                {"LocalAddress": "127.0.0.1", "LocalPort": 7777},
            ]):
                with patch.object(self.client, "_request", return_value={"ok": True}):
                    connection = self.client.discover()
        self.assertEqual(connection["port"], 7777)
        self.assertEqual(connection["csrf"], "legacy-token")

    def test_401_from_no_csrf_does_not_block_hub_discovery(self):
        """A 401 on a legacy port should not prevent the hub path from being tried."""
        agy_proc = {
            "Name": "agy.exe", "ProcessId": 9904,
            "CommandLine": "agy.exe --hub --hub-port=54340",
        }
        with patch("ai_usage._powershell_json", return_value=[agy_proc]):
            with patch.object(self.client, "_try_agy_hub", return_value={
                "host": "127.0.0.1", "port": 54950, "pid": 9904, "csrf": "tok",
            }) as mock_hub:
                connection = self.client.discover()
        mock_hub.assert_called_once()
        self.assertEqual(connection["port"], 54950)


if __name__ == "__main__":
    unittest.main()

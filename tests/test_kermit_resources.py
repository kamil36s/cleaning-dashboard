"""Synthetic admission tests: independent of the developer machine's free RAM."""

import inspect
import hashlib
import io
import json
from pathlib import Path
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

from kermit_model.config import configured
from kermit_model.__main__ import main
from kermit_model.fake_provider import FakeProvider
from kermit_model.ollama_provider import OllamaProvider
from kermit_model.resources import MemoryObservation, preflight, profile_for, read_physical_memory
from kermit_model.service import generate_draft
from kermit_retrieval import retrieve


class SpyProvider:
    def __init__(self, state="sleeping"):
        self.state = state
        self.calls = 0

    def health(self, config):
        return {"state": self.state, "modelAvailable": True}

    def generate(self, messages, config):
        self.calls += 1
        return FakeProvider().generate(messages, config)


class ResourceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = retrieve({"contractVersion": 1, "question": "What does the Quote widget do?"})
        cls.config = configured(provider="ollama", environ={})

    def check(self, available, state="sleeping", *, override=False):
        spy = SpyProvider(state)
        result = generate_draft(self.pack, config=self.config, provider=spy,
                                allow_memory_pressure=override,
                                memory_reader=lambda: MemoryObservation(16000, available))
        return result, spy

    def test_green_starts_and_retains_safe_observations(self):
        result, spy = self.check(6600)
        self.assertEqual((result["status"], spy.calls), ("draft", 1))
        self.assertEqual(result["resource"]["state"], "green")
        self.assertEqual(result["resource"]["availableAfterMb"], 6600)
        self.assertEqual(result["resource"]["generationDurationMs"], 0)

    def test_yellow_requires_explicit_override(self):
        blocked, spy = self.check(5700)
        self.assertEqual((blocked["status"], spy.calls), ("confirmation_required", 0))
        self.assertEqual(blocked["resource"]["deficitToRecommendedMb"], 900)
        self.assertIn("5.7 GB", blocked["answer"])
        allowed, spy = self.check(5700, override=True)
        self.assertEqual((allowed["status"], spy.calls), ("draft", 1))
        self.assertEqual(allowed["resource"]["state"], "yellow")

    def test_red_cannot_be_overridden_and_deficits_exact(self):
        result, spy = self.check(3380, override=True)
        self.assertEqual((result["status"], spy.calls), ("waiting_for_memory", 0))
        resource = result["resource"]
        self.assertEqual((resource["minimumMb"], resource["recommendedMb"]), (5200, 6600))
        self.assertEqual((resource["deficitToMinimumMb"], resource["deficitToRecommendedMb"]), (1820, 3220))
        self.assertEqual(resource["event"]["type"], "RESOURCE_GATE_BLOCKED")
        self.assertIn("1.8 GB", result["answer"])
        self.assertIn("1820 MiB", result["answer"])

    def test_red_sends_no_ollama_chat_request(self):
        provider = OllamaProvider()
        paths = []
        def request(_, path, payload=None, **kwargs):
            paths.append(path)
            return ({"models": [{"name": self.config.model}]} if path == "/api/tags"
                    else {"models": []}), 0
        with patch.object(provider, "_request", request):
            result = generate_draft(self.pack, config=self.config, provider=provider,
                                    memory_reader=lambda: MemoryObservation(16000, 3380))
        self.assertEqual(result["status"], "waiting_for_memory")
        self.assertEqual(paths, ["/api/tags", "/api/ps"])

    def test_resident_uses_smaller_incremental_headroom(self):
        result, spy = self.check(2500, "ready")
        self.assertEqual((result["status"], spy.calls), ("draft", 1))
        self.assertTrue(result["resource"]["modelResident"])
        self.assertEqual((result["resource"]["minimumMb"], result["resource"]["recommendedMb"]), (1200, 2000))
        result, spy = self.check(1100, "ready", override=True)
        self.assertEqual((result["status"], spy.calls), ("waiting_for_memory", 0))

    def test_fake_provider_does_not_observe_memory(self):
        with patch("kermit_model.resources.read_physical_memory", side_effect=AssertionError("RAM read")):
            result = generate_draft(self.pack, config=configured(provider="fake", environ={}),
                                    provider=FakeProvider())
        self.assertEqual(result["status"], "draft")

    def test_model_mapping_and_trusted_configuration(self):
        self.assertEqual(profile_for("qwen3.5:4b", {}).recommended_available_before_load_mb, 6600)
        self.assertIsNone(profile_for("unknown:tag", {}))
        override = {"future:8b": {"minimum_available_before_load_mb": 9000,
                                    "recommended_available_before_load_mb": 11000,
                                    "minimum_available_resident_mb": 1500,
                                    "recommended_available_resident_mb": 2500,
                                    "safety_margin_mb": 2000, "observed_peak_private_mb": 9000,
                                    "sample_count": 4, "last_calibrated_at": "2026-09-29T12:00:00Z"}}
        config = configured(provider="ollama", environ={"KERMIT_LLM_MODEL_DEEP": "future:8b"}, profile="deep")
        env = {"KERMIT_RESOURCE_PROFILES_JSON": json.dumps(override)}
        result = preflight(config, SpyProvider(), memory_reader=lambda: MemoryObservation(16000, 10000), environ=env)
        self.assertEqual((result["state"], result["recommendedMb"]), ("yellow", 11000))
        unknown = preflight(config, SpyProvider(), memory_reader=lambda: MemoryObservation(16000, 15000), environ={})
        self.assertEqual((unknown["state"], unknown["reason"]), ("red", "unknown_model"))
        with self.assertRaises(ValueError):
            profile_for("future:8b", {"KERMIT_RESOURCE_PROFILES_JSON": json.dumps({"future:8b": {**override["future:8b"], "minimum_available_before_load_mb": -1}})})

    def test_actual_model_tag_controls_gate_after_profile_switch(self):
        self.assertEqual({profile_for(tag, {}).recommended_available_before_load_mb for tag in
                          ("qwen3.5:4b", "gemma3:4b", "phi4-mini:3.8b", "mistral:7b")},
                         {6600, 7000, 6500, 8200})
        profiles = {"gemma3:4b": {"minimum_available_before_load_mb": 5500,
                                     "recommended_available_before_load_mb": 7000,
                                     "minimum_available_resident_mb": 1300,
                                     "recommended_available_resident_mb": 2200,
                                     "safety_margin_mb": 1500}}
        env = {"KERMIT_LLM_MODEL_QUICK": "gemma3:4b", "KERMIT_RESOURCE_PROFILES_JSON": json.dumps(profiles)}
        gemma = configured("quick", "ollama", env)
        qwen = configured("normal", "ollama", env)
        memory = lambda: MemoryObservation(16000, 5300)
        self.assertEqual(preflight(gemma, SpyProvider(), memory_reader=memory, environ=env)["reason"], "below_minimum")
        self.assertEqual(preflight(qwen, SpyProvider(), memory_reader=memory, environ=env)["state"], "yellow")

    def test_unreadable_memory_fails_closed(self):
        result = preflight(self.config, SpyProvider(), memory_reader=lambda: (_ for _ in ()).throw(OSError("read failed")), environ={})
        self.assertEqual((result["state"], result["reason"]), ("red", "memory_unavailable"))

    def test_cli_distinct_exit_codes(self):
        for available, expected in ((3380, 3), (5700, 4), (8000, 0)):
            result, _ = self.check(available)
            with self.subTest(available=available), patch("sys.argv", ["kermit_model", "ask", "--provider", "ollama", "--format", "json", "why"]), patch("kermit_model.__main__.ask", return_value=result), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), expected)
                self.assertEqual(json.loads(output.getvalue())["status"], result["status"])

    def test_gate_does_not_mutate_index_sources_or_runtime_databases(self):
        root = Path(__file__).resolve().parents[1]
        artifacts = [root / "data/generated/kermit-index" / name for name in
                     ("manifest.json", "sources.jsonl", "entities.jsonl", "relationships.jsonl", "documents.jsonl", "conflicts.jsonl")]
        artifacts.append(root / "docs/kermit/knowledge/subsystems/quote.md")
        databases = [root / "data/finance.sqlite", root / "data/language-learning.sqlite"]
        def snapshot():
            return ([hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts],
                    [(path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None for path in databases])
        before = snapshot()
        self.check(3380)
        self.check(8000)
        self.assertEqual(snapshot(), before)

    def test_no_process_control_or_shell_in_resource_module(self):
        source = inspect.getsource(__import__("kermit_model.resources", fromlist=["resources"]))
        for forbidden in ("subprocess", "taskkill", "TerminateProcess", ".kill(", "Popen", "os.system"):
            self.assertNotIn(forbidden, source)

    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows memory API")
    def test_windows_memory_observation(self):
        observed = read_physical_memory()
        self.assertGreater(observed.total_mb, 0)
        self.assertGreaterEqual(observed.available_mb, 0)
        self.assertLessEqual(observed.available_mb, observed.total_mb)


if __name__ == "__main__":
    unittest.main()

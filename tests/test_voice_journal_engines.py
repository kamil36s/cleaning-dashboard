import unittest
from unittest import mock

import voice_journal
import voice_journal_engines


class VoiceJournalEngineTests(unittest.TestCase):
    def test_openai_remains_default_and_existing_models_remain(self):
        self.assertEqual(voice_journal_engines.DEFAULT_ENGINE, "openai-whisper")
        self.assertEqual(voice_journal.SUPPORTED_MODELS, ("small", "medium", "turbo"))

    def test_faster_whisper_is_optional(self):
        with mock.patch("voice_journal_engines.importlib.metadata.version", side_effect=Exception("missing")):
            status = voice_journal_engines.faster_whisper_health()
        self.assertFalse(status["available"])
        self.assertIn("Faster-Whisper", status["error"])

    def test_faster_options_are_whitelisted_and_cpu_combinations_are_rejected(self):
        options, compute_type = voice_journal_engines.validate_faster_options(
            {"temperature": 0, "beam_size": 5, "best_of": 3, "vad_filter": False, "word_timestamps": True},
            device="cpu",
            compute_type="int8",
        )
        self.assertEqual(compute_type, "int8")
        self.assertNotIn("best_of", options)
        self.assertTrue(options["word_timestamps"])
        with self.assertRaises(ValueError):
            voice_journal_engines.validate_faster_options({"unknown": 1}, device="cpu")
        with self.assertRaises(ValueError):
            voice_journal_engines.validate_faster_options({}, device="cpu", compute_type="float16")


if __name__ == "__main__":
    unittest.main()

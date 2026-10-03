import unittest

from voice_journal_eta import estimate_eta


class VoiceJournalEtaTests(unittest.TestCase):
    def test_historical_eta_returns_a_coarse_range(self):
        eta = estimate_eta(
            duration_seconds=120,
            historical_rtfs=[0.8, 1.0, 1.1, 1.2],
        )

        self.assertTrue(eta["available"])
        self.assertTrue(eta["approximate"])
        self.assertEqual(eta["source"], "history")
        self.assertEqual(eta["sampleSize"], 4)
        self.assertLess(eta["minSeconds"], eta["maxSeconds"])
        self.assertEqual(eta["minSeconds"] % 15, 0)
        self.assertEqual(eta["maxSeconds"] % 15, 0)

    def test_historical_eta_reduces_only_by_elapsed_transcription_time(self):
        initial = estimate_eta(duration_seconds=120, historical_rtfs=[1.0, 1.1, 0.9])
        later = estimate_eta(
            duration_seconds=120,
            historical_rtfs=[1.0, 1.1, 0.9],
            transcription_elapsed_seconds=45,
        )

        self.assertLess(later["maxSeconds"], initial["maxSeconds"])
        self.assertEqual(later["source"], "history")

    def test_live_eta_uses_real_processed_audio_and_smooths_against_history(self):
        eta = estimate_eta(
            duration_seconds=100,
            historical_rtfs=[1.0],
            transcription_elapsed_seconds=40,
            processed_audio_seconds=20,
        )

        self.assertEqual(eta["source"], "live")
        self.assertEqual(eta["basisRtf"], 1.2)
        self.assertLess(eta["maxSeconds"], 160)
        self.assertGreater(eta["maxSeconds"], eta["minSeconds"])

    def test_reports_insufficient_history_without_live_progress(self):
        eta = estimate_eta(duration_seconds=60, historical_rtfs=[])

        self.assertFalse(eta["available"])
        self.assertEqual(eta["reason"], "insufficient_history")
        self.assertNotIn("minSeconds", eta)
        self.assertNotIn("maxSeconds", eta)


if __name__ == "__main__":
    unittest.main()

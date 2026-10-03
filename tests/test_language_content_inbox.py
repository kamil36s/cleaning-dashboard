from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from language_learning.content_inbox import (
    MAX_MEDIA_BYTES,
    canonical_external_url,
    map_cues_to_sentences,
    parse_srt,
    parse_vtt,
    sniff_audio,
)
from language_learning.errors import LanguageValidationError
from language_learning.jobs import LanguageJobManager
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for, wait_for_job


class ContentInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        analyzer = FakeAnalyzer()
        self.service = LanguageService(
            self.store,
            analyzer_registry=registry_for(analyzer),
            frequency_provider=FakeFrequencyProvider(),
        )
        self.service.initialize()
        self.manager = LanguageJobManager(self.service, poll_interval=0.01)
        self.manager.start()
        self.profile = self.service.ensure_bokmal_profile()["profile"]

    def tearDown(self):
        self.manager.stop()
        self.temp.cleanup()

    def _wait_current_job(self, content_id):
        detail = self.service.content_detail(content_id)["data"]
        wait_for_job(self.service, detail["latestJob"]["id"])
        return self.service.content_detail(content_id)["data"]

    def test_pasted_text_reuses_canonical_analysis_and_is_idempotent(self):
        created = self.service.create_content(self.profile["id"], {
            "sourceType": "PASTED_TEXT", "title": "Nyheter", "text": "Jeg har en jobb.",
        })["data"]
        ready = self._wait_current_job(created["item"]["id"])
        self.assertEqual(ready["item"]["status"], "READY_READER")
        self.assertEqual(ready["document"]["sourceType"], "CONTENT_PASTED_TEXT")
        self.assertIsNotNone(ready["coverage"])
        repeated = self.service.create_content(self.profile["id"], {
            "sourceType": "PASTED_TEXT", "title": "Duplicate", "text": "Jeg har en jobb.",
        })["data"]
        self.assertEqual(repeated["item"]["id"], created["item"]["id"])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)

    def test_audio_srt_alignment_versioning_and_authentic_exposure_gate(self):
        audio = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40
        imported = self.service.import_content_audio(
            self.profile["id"], data=audio, title="Lokal lyd", original_name="owned.wav", mime_type="audio/wav",
        )["data"]
        self.assertEqual(imported["item"]["status"], "NEEDS_TRANSCRIPT")
        attached = self.service.add_content_transcript(imported["item"]["id"], {
            "format": "SRT",
            "transcriptText": "1\n00:00:00,000 --> 00:00:02,000\nJeg har en jobb.\n",
        })["data"]
        ready = self._wait_current_job(attached["item"]["id"])
        self.assertEqual(ready["item"]["status"], "READY_LISTENING")
        self.assertEqual(len(ready["alignments"]), 1)
        alignment = ready["alignments"][0]
        self.assertEqual(alignment["method"], "IMPORTED_SRT")
        self.assertEqual(alignment["confidenceBasis"], "CONFIDENCE_NOT_REPORTED")
        self.service.refresh_content_alignment(ready["document"]["id"])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sentence_alignments WHERE transcript_id=?", (ready["currentTranscript"]["id"],)
            ).fetchone()[0], 1)

        corrected = self.service.correct_content_alignment(alignment["id"], {
            "startMs": 100, "endMs": 1900,
        })["data"]
        current = corrected["alignments"][0]
        self.assertEqual(current["method"], "USER_CORRECTED")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sentence_alignments WHERE sentence_id=?", (current["sentenceId"],)
            ).fetchone()[0], 2)

        session = self.service.start_listening_session(ready["document"]["id"], {
            "languageProfileId": self.profile["id"], "clientSessionId": "authentic-one", "mode": "LISTENING_ONLY",
        })["data"]["session"]
        event = self.service.record_listening_sentence_event(session["id"], {
            "textDocumentId": ready["document"]["id"], "sentenceId": current["sentenceId"],
            "alignmentId": current["id"], "idempotencyKey": "authentic-event", "outcome": "ENDED",
            "playbackSource": "AUTHENTIC_MEDIA", "activeMs": 1700, "coverageMs": 1500, "durationMs": 999999,
            "metadata": {"seekGapsExcluded": True},
        })["data"]
        self.assertTrue(event["event"]["qualified"])
        self.assertTrue(event["event"]["exposureAwarded"])
        self.assertEqual(event["event"]["durationMs"], 1800)
        self.assertEqual(event["event"]["coverageMs"], 1500)
        statistics = self.service.statistics(self.profile["id"], range_name="7d")["data"]
        self.assertEqual(statistics["listening"]["byPlaybackSource"]["AUTHENTIC_MEDIA"]["events"], 1)
        self.assertEqual(statistics["listening"]["byPlaybackSource"]["AUTHENTIC_MEDIA"]["activeMs"], 1700)

        with self.store.connection() as connection:
            connection.execute("UPDATE sentence_alignments SET exposure_eligible=0 WHERE id=?", (current["id"],))
        second = self.service.start_listening_session(ready["document"]["id"], {
            "languageProfileId": self.profile["id"], "clientSessionId": "authentic-two", "mode": "READ_LISTEN",
        })["data"]["session"]
        guarded = self.service.record_listening_sentence_event(second["id"], {
            "textDocumentId": ready["document"]["id"], "sentenceId": current["sentenceId"],
            "alignmentId": current["id"], "idempotencyKey": "low-confidence", "outcome": "ENDED",
            "playbackSource": "AUTHENTIC_MEDIA", "activeMs": 1800, "coverageMs": 1800,
        })["data"]
        self.assertTrue(guarded["event"]["qualified"])
        self.assertFalse(guarded["event"]["exposureAwarded"])

    def test_reference_rights_fail_closed_and_no_fetch_contract(self):
        reference = self.service.create_content(self.profile["id"], {
            "sourceType": "NRK_REFERENCE", "title": "NRK episode", "sourceUri": "https://radio.nrk.no/podkast/test",
        })["data"]
        self.assertEqual(reference["item"]["status"], "REFERENCE_ONLY")
        self.assertEqual(reference["item"]["rightsStatus"], "STORAGE_NOT_AUTHORIZED")
        with self.assertRaises(Exception):
            self.service.add_content_transcript(reference["item"]["id"], {
                "format": "PLAIN", "transcriptText": "Copyright text",
            })
        for unsafe in ("http://127.0.0.1/admin", "http://[::1]/", "http://localhost/test"):
            with self.assertRaises(LanguageValidationError):
                canonical_external_url(unsafe, "ARTICLE_REFERENCE")
        with self.assertRaises(LanguageValidationError):
            canonical_external_url("https://example.com/not-nrk", "NRK_REFERENCE")

    def test_transcript_parsers_unicode_overlap_gap_and_rejections(self):
        projection, cues = parse_srt(
            "1\n00:00:00,000 --> 00:00:02,000\nFørste linje\nog jobb.\n\n"
            "2\n00:00:01,500 --> 00:00:03,000\nBlåbær og språk.\n\n"
            "3\n00:00:05,000 --> 00:00:06,000\nEtter gapet."
        )
        self.assertIn("Første linje\nog jobb.", projection)
        self.assertEqual(len(cues), 3)
        self.assertLess(cues[1].start_ms, cues[0].end_ms)
        self.assertGreater(cues[2].start_ms, cues[1].end_ms)
        vtt, vtt_cues = parse_vtt("WEBVTT\n\n00:01.000 --> 00:02.500\nÆrø og blåbær")
        self.assertEqual(vtt, "Ærø og blåbær")
        self.assertEqual(vtt_cues[0].start_ms, 1000)
        with self.assertRaises(LanguageValidationError):
            parse_srt("1\nnot-a-time --> 00:00:02,000\nBad")
        with self.assertRaises(LanguageValidationError):
            parse_srt("1\n00:00:02,000 --> 00:00:03,000\nLater\n\n2\n00:00:01,000 --> 00:00:02,000\nEarlier")

    def test_media_sniffing_mismatch_and_size_contract(self):
        self.assertEqual(sniff_audio(b"OggS" + b"\x00" * 20, "audio/ogg", "x.ogg")[0], "audio/ogg")
        with self.assertRaises(LanguageValidationError):
            sniff_audio(b"OggS" + b"\x00" * 20, "audio/mpeg", "x.mp3")
        self.assertEqual(MAX_MEDIA_BYTES, 64 * 1024 * 1024)

    def test_alignment_mapping_splits_and_merges_cues_without_inventing_unaligned_rows(self):
        sentences = [
            {"id": "s1", "source_start": 0, "source_end": 10},
            {"id": "s2", "source_start": 10, "source_end": 20},
            {"id": "s3", "source_start": 30, "source_end": 40},
        ]
        cues = [{"id": "c1", "text_start": 0, "text_end": 20, "start_ms": 0, "end_ms": 2000}]
        mapped = map_cues_to_sentences(sentences, cues)
        self.assertEqual([(row["start_ms"], row["end_ms"]) for row in mapped], [(0, 1000), (1000, 2000)])
        merged = map_cues_to_sentences(
            [{"id": "whole", "source_start": 0, "source_end": 20}],
            [
                {"id": "c1", "text_start": 0, "text_end": 10, "start_ms": 0, "end_ms": 900},
                {"id": "c2", "text_start": 10, "text_end": 20, "start_ms": 1100, "end_ms": 2000},
            ],
        )
        self.assertEqual((merged[0]["start_ms"], merged[0]["end_ms"]), (0, 2000))
        self.assertNotIn("s3", {row["sentence_id"] for row in mapped})

    def test_media_limit_and_managed_path_traversal_are_enforced(self):
        with self.assertRaisesRegex(LanguageValidationError, "64 MiB"):
            self.service.import_content_audio(
                self.profile["id"], data=b"x" * (MAX_MEDIA_BYTES + 1), title="Too large",
                original_name="large.wav", mime_type="audio/wav",
            )
        audio = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40
        imported = self.service.import_content_audio(
            self.profile["id"], data=audio, title="Safe", original_name="safe.wav", mime_type="audio/wav",
        )["data"]
        artifact_id = imported["media"]["id"]
        with self.store.connection() as connection:
            connection.execute("UPDATE content_artifacts SET managed_relpath='../outside.wav' WHERE id=?", (artifact_id,))
        with self.assertRaises(Exception):
            self.service.content_media_file(artifact_id)
        with self.assertRaises(Exception):
            self.service.content_media_file("not-an-artifact")


if __name__ == "__main__":
    unittest.main()

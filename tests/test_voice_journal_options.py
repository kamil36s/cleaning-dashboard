import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import whisper

from scripts import voice_journal_worker
from voice_journal_options import (
    TranscriptionOptionsError,
    supported_transcription_option_names,
    validate_transcription_options,
)


EXPECTED_OPTIONS = [
    "temperature",
    "beam_size",
    "best_of",
    "patience",
    "length_penalty",
    "condition_on_previous_text",
    "initial_prompt",
    "no_speech_threshold",
    "logprob_threshold",
    "compression_ratio_threshold",
    "suppress_tokens",
    "word_timestamps",
    "fp16",
]


class VoiceJournalOptionsTests(unittest.TestCase):
    def test_detects_only_options_supported_by_installed_openai_whisper(self):
        supported = supported_transcription_option_names(whisper)

        self.assertEqual(supported, EXPECTED_OPTIONS)
        self.assertNotIn("vad_filter", supported)
        self.assertNotIn("compute_type", supported)

    def test_validates_and_normalizes_whitelisted_options(self):
        effective = validate_transcription_options(
            {
                "temperature": [0, 0.2, 0.4],
                "beam_size": 5,
                "patience": 1.2,
                "length_penalty": 0.6,
                "condition_on_previous_text": False,
                "initial_prompt": "  Kraków, Aleja Pokoju  ",
                "suppress_tokens": "-1, 503",
                "word_timestamps": True,
                "fp16": True,
            },
            supported_names=EXPECTED_OPTIONS,
            device="cpu",
        )

        self.assertEqual(effective["temperature"], [0.0, 0.2, 0.4])
        self.assertEqual(effective["initial_prompt"], "Kraków, Aleja Pokoju")
        self.assertEqual(effective["suppress_tokens"], "-1,503")
        self.assertFalse(effective["fp16"])

    def test_rejects_unknown_types_ranges_and_invalid_dependencies(self):
        cases = [
            {"vad_filter": True},
            {"temperature": 1.5},
            {"beam_size": 2.5},
            {"length_penalty": -0.1},
            {"condition_on_previous_text": "true"},
            {"suppress_tokens": "abc"},
            {"patience": 1.0},
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(TranscriptionOptionsError):
                validate_transcription_options(raw, supported_names=EXPECTED_OPTIONS, device="cuda")


class FakeModel:
    def __init__(self):
        self.options = None

    def transcribe(self, audio, **options):
        self.options = options
        return {"text": "Test ustawień"}


class VoiceJournalWorkerOptionsTests(unittest.TestCase):
    def test_worker_passes_validated_options_to_openai_whisper_library(self):
        with tempfile.TemporaryDirectory(prefix="voice-journal-options-") as directory:
            root = Path(directory)
            audio = root / "memo.webm"
            audio.write_bytes(b"audio")
            options_file = root / "options.json"
            options_file.write_text(json.dumps({
                "temperature": 0.0,
                "beam_size": 5,
                "condition_on_previous_text": True,
                "fp16": False,
            }), encoding="utf-8")
            args = argparse.Namespace(
                audio=str(audio), model="turbo", language="pl", task="transcribe", device="cpu",
                allow_model_download="true",
                options_file=str(options_file), status_file=str(root / "status.json"),
                result_file=str(root / "result.json"),
            )
            model = FakeModel()

            with mock.patch.object(voice_journal_worker, "_get_model", return_value=model) as get_model:
                code = voice_journal_worker.run(args)

        self.assertEqual(code, 0)
        get_model.assert_called_once_with("turbo", "cpu", allow_download=True)
        self.assertEqual(model.options, {
            "language": "pl",
            "task": "transcribe",
            "verbose": None,
            "temperature": 0.0,
            "beam_size": 5,
            "condition_on_previous_text": True,
            "fp16": False,
        })


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server as dashboard_server
import voice_journal


def multipart_body(*, filename="memo.webm", mime="audio/webm", content=b"audio", fields=None):
    boundary = "VoiceJournalTestBoundary"
    chunks = []
    for name, value in (fields or {"model": "turbo"}).items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


class FakeWhisperModel:
    def __init__(self):
        self.path_seen = None
        self.options_seen = None

    def transcribe(self, path, **options):
        self.path_seen = Path(path)
        self.options_seen = options
        if not self.path_seen.is_file():
            raise AssertionError("temporary audio file was not created")
        return {
            "text": "  To jest test.  ",
            "segments": [
                {"start": 0.24, "end": 1.4, "text": " To jest"},
                {"start": 1.4, "end": 2.45, "text": " test. "},
            ],
        }


class VoiceJournalServiceTests(unittest.TestCase):
    def test_accepts_audio_up_to_ninety_minutes(self):
        def ffprobe_result(duration):
            return mock.Mock(
                returncode=0,
                stdout=json.dumps({
                    "streams": [{"codec_name": "opus", "sample_rate": "48000", "channels": 1}],
                    "format": {"format_name": "matroska,webm", "duration": str(duration)},
                }),
            )

        with (
            mock.patch.object(voice_journal.shutil, "which", return_value="ffprobe"),
            mock.patch.object(voice_journal.subprocess, "run", return_value=ffprobe_result(90 * 60)),
        ):
            metadata = voice_journal.probe_audio(Path("memo.webm"))
        self.assertEqual(metadata["durationSeconds"], 90 * 60)

        with (
            mock.patch.object(voice_journal.shutil, "which", return_value="ffprobe"),
            mock.patch.object(voice_journal.subprocess, "run", return_value=ffprobe_result(90 * 60 + 0.1)),
            self.assertRaises(voice_journal.VoiceJournalError) as caught,
        ):
            voice_journal.probe_audio(Path("memo.webm"))
        self.assertEqual(caught.exception.code, "audio_too_long")

    def test_accepts_aac_extension_and_mime_types(self):
        for mime in (
            "audio/aac",
            "audio/x-aac",
            "audio/vnd.dlna.adts",
            "audio/aacp",
            "application/octet-stream",
        ):
            with self.subTest(mime=mime):
                suffix = voice_journal.validate_audio_part({
                    "filename": "memo.aac",
                    "mime": mime,
                    "content": b"aac-bytes",
                })
                self.assertEqual(suffix, ".aac")
        with self.assertRaises(voice_journal.VoiceJournalError) as caught:
            voice_journal.validate_audio_part({
                "filename": "memo.aac",
                "mime": "text/plain",
                "content": b"not-audio",
            })
        self.assertEqual(caught.exception.code, "mime_mismatch")

    def test_missing_model_download_requires_explicit_permission(self):
        previous_model = voice_journal._LOADED_MODEL
        previous_key = voice_journal._LOADED_MODEL_KEY
        voice_journal._LOADED_MODEL = None
        voice_journal._LOADED_MODEL_KEY = None
        self.addCleanup(setattr, voice_journal, "_LOADED_MODEL", previous_model)
        self.addCleanup(setattr, voice_journal, "_LOADED_MODEL_KEY", previous_key)
        with tempfile.TemporaryDirectory(prefix="voice-journal-model-") as directory:
            checkpoint = Path(directory) / "small.pt"
            marker = Path(directory) / ".small.download-pending"

            class FakeWhisper:
                def __init__(self):
                    self.calls = []

                def load_model(self, name, **options):
                    self.calls.append((name, options))
                    checkpoint.write_bytes(b"checkpoint")
                    return "loaded-small"

            fake_whisper = FakeWhisper()
            with (
                mock.patch.object(voice_journal, "_whisper_module", return_value=fake_whisper),
                mock.patch.object(voice_journal, "_checkpoint_path", return_value=(checkpoint, "")),
                mock.patch.object(voice_journal, "_model_download_marker", return_value=marker),
            ):
                with self.assertRaises(voice_journal.VoiceJournalError) as denied:
                    voice_journal._get_model("small", "cpu")
                self.assertEqual(denied.exception.code, "model_not_cached")
                self.assertEqual(fake_whisper.calls, [])

                loaded = voice_journal._get_model("small", "cpu", allow_download=True)

            self.assertEqual(loaded, "loaded-small")
            self.assertEqual(fake_whisper.calls[0][0], "small")
            self.assertFalse(marker.exists())

    def test_accepts_automatic_language_detection(self):
        model, language, task, device = voice_journal._validate_options({
            "model": "turbo",
            "language": "auto",
        })
        self.assertEqual(model, "turbo")
        self.assertIsNone(language)
        self.assertEqual(task, "transcribe")
        self.assertEqual(device, "auto")

    def test_transcribes_with_mocked_whisper_and_cleans_temporary_file(self):
        content_type, body = multipart_body(fields={
            "model": "turbo",
            "language": "pl",
            "task": "transcribe",
            "device": "auto",
        })
        model = FakeWhisperModel()
        metadata = {
            "durationSeconds": 2.5,
            "format": "matroska,webm",
            "codec": "opus",
            "sampleRate": 48000,
            "channels": 1,
        }

        with (
            mock.patch.object(voice_journal, "probe_audio", return_value=metadata),
            mock.patch.object(voice_journal, "resolve_device", return_value="cpu"),
            mock.patch.object(voice_journal, "_get_model", return_value=model),
        ):
            result = voice_journal.transcribe_multipart(content_type, body)

        self.assertEqual(result["transcript"], "To jest test.")
        self.assertEqual(result["transcriptSegments"], [
            {"start": 0.24, "end": 1.4, "text": "To jest"},
            {"start": 1.4, "end": 2.45, "text": "test."},
        ])
        self.assertEqual(result["model"], "turbo")
        self.assertEqual(result["device"], "cpu")
        self.assertEqual(result["durationSeconds"], 2.5)
        self.assertEqual(result["format"], "matroska,webm")
        self.assertEqual(result["codec"], "opus")
        self.assertEqual(result["sampleRate"], 48000)
        self.assertEqual(result["channels"], 1)
        self.assertEqual(result["sizeBytes"], 5)
        self.assertIn("transcriptionDurationSeconds", result)
        self.assertIn("realTimeFactor", result)
        self.assertEqual(model.options_seen, {
            "language": "pl",
            "task": "transcribe",
            "fp16": False,
        })
        self.assertFalse(model.path_seen.exists())

    def test_rejects_path_traversal_filename(self):
        content_type, body = multipart_body(filename="../memo.webm")
        with self.assertRaises(voice_journal.VoiceJournalError) as caught:
            voice_journal.transcribe_multipart(content_type, body)
        self.assertEqual(caught.exception.code, "unsafe_filename")

    def test_rejects_mime_extension_mismatch(self):
        content_type, body = multipart_body(filename="memo.wav", mime="audio/webm")
        with self.assertRaises(voice_journal.VoiceJournalError) as caught:
            voice_journal.transcribe_multipart(content_type, body)
        self.assertEqual(caught.exception.status, 415)
        self.assertEqual(caught.exception.code, "mime_mismatch")


class VoiceJournalEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log_patch = mock.patch.object(dashboard_server, "log_line", return_value=None)
        cls.log_patch.start()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.log_patch.stop()

    def test_health_endpoint_reports_local_runtime(self):
        with urllib.request.urlopen(f"{self.base_url}/api/voice-journal/health", timeout=15) as response:
            payload = json.load(response)

        self.assertEqual(response.status, 200)
        self.assertIn(payload["status"], {"ok", "degraded"})
        self.assertEqual(payload["recommendedModel"], "small")
        self.assertEqual(payload["supportedModels"], ["small", "medium", "turbo"])
        self.assertEqual(payload["supportedLanguages"], ["auto", "pl"])
        self.assertEqual(payload["supportedTasks"], ["transcribe", "translate"])
        self.assertEqual(payload["maxUploadBytes"], 250 * 1024 * 1024)
        self.assertEqual(payload["maxDurationSeconds"], 90 * 60)
        self.assertIn("auto", payload["supportedDevices"])
        self.assertIn("cpu", payload["supportedDevices"])
        self.assertIn("whisperVersion", payload)
        self.assertIn("ffmpeg", payload)
        self.assertIn("pytorch", payload)
        self.assertIn("cpu", payload)
        self.assertIn("gpu", payload)

    def test_transcribe_endpoint_dispatches_multipart(self):
        content_type, body = multipart_body()
        expected = {
            "transcript": "Test endpointu",
            "durationSeconds": 1.0,
            "format": "matroska,webm",
            "codec": "opus",
            "sampleRate": 48000,
            "channels": 1,
            "sizeBytes": 5,
            "model": "turbo",
            "device": "cpu",
            "transcriptionDurationSeconds": 0.2,
            "realTimeFactor": 0.2,
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/voice-journal/transcribe",
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        with (
            mock.patch.object(dashboard_server, "transcribe_voice_journal_multipart", return_value=expected) as transcribe,
            urllib.request.urlopen(request, timeout=10) as response,
        ):
            payload = json.load(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload, expected)
        transcribe.assert_called_once_with(content_type, body)


if __name__ == "__main__":
    unittest.main()

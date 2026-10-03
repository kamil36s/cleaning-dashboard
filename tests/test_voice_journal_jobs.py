import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server as dashboard_server
import voice_journal_jobs


METADATA = {
    "durationSeconds": 12.0,
    "format": "matroska,webm",
    "codec": "opus",
    "sampleRate": 48000,
    "channels": 1,
}


def multipart_body(content=b"audio", fields=None):
    boundary = "VoiceJournalJobBoundary"
    fields = fields or {"model": "turbo", "language": "pl", "task": "transcribe", "device": "auto"}
    chunks = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode(),
            value.encode(),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"memo.webm\"\r\n".encode(),
        b"Content-Type: audio/webm\r\n\r\n",
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def command_value(command, option):
    return command[command.index(option) + 1]


class FakeProcess:
    def __init__(self, command, release, *, succeeds=True, started=None):
        self.command = command
        self.release = release
        self.succeeds = succeeds
        self.returncode = None
        self.terminated = False
        self.done = threading.Event()
        self.status_path = Path(command_value(command, "--status-file"))
        self.result_path = Path(command_value(command, "--result-file"))
        self.status_path.write_text(json.dumps({"stage": "transcribing"}), encoding="utf-8")
        started and started.set()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.release.wait(3)
        if self.terminated:
            self.done.set()
            return
        payload = ({
            "ok": True,
            "transcript": "Treść zadania.",
            "transcriptSegments": [
                {"start": 0.0, "end": 3.0, "text": "Treść zadania."},
            ],
            "transcriptionDurationSeconds": 3.0,
        } if self.succeeds else {"ok": False, "error": "mock whisper failure"})
        self.result_path.write_text(json.dumps(payload), encoding="utf-8")
        self.returncode = 0 if self.succeeds else 1
        self.done.set()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.release.set()
        self.done.set()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise TimeoutError()
        return self.returncode


def wait_for_status(manager, job_id, statuses, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["status"] in statuses:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {statuses}: {manager.get(job_id)}")


class VoiceJournalQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="voice-journal-jobs-")
        self.root = Path(self.temporary.name)
        self.release = threading.Event()
        self.started = threading.Event()
        self.processes = []
        self.resolve_patch = mock.patch.object(voice_journal_jobs, "resolve_device", return_value="cpu")
        self.probe_patch = mock.patch.object(voice_journal_jobs, "probe_audio", return_value=METADATA)
        self.resolve_patch.start()
        self.probe_patch.start()

    def tearDown(self):
        manager = getattr(self, "manager", None)
        if manager:
            self.release.set()
            manager.stop()
        self.probe_patch.stop()
        self.resolve_patch.stop()
        self.temporary.cleanup()

    def make_manager(self, outcomes=None):
        outcomes = list(outcomes or [True])

        def factory(command):
            succeeds = outcomes.pop(0) if outcomes else True
            process = FakeProcess(command, self.release, succeeds=succeeds, started=self.started)
            self.processes.append(process)
            return process

        self.manager = voice_journal_jobs.VoiceJournalJobManager(
            self.root / "voice-journal.sqlite",
            self.root / "jobs",
            Path(__file__).resolve().parents[1],
            process_factory=factory,
            poll_interval=0.01,
        )
        return self.manager

    def submit(self, manager):
        content_type, body = multipart_body()
        return manager.submit(content_type, body)

    def test_runs_only_one_heavy_job_and_reports_no_fake_progress(self):
        manager = self.make_manager([True, True])
        first = self.submit(manager)
        self.assertTrue(self.started.wait(1))
        running = wait_for_status(manager, first["id"], {"running"})
        second = self.submit(manager)

        self.assertEqual(len(self.processes), 1)
        self.assertEqual(manager.get(second["id"])["queuePosition"], 1)
        self.assertIsNone(running["progressPercent"])
        self.assertIsNone(running["processedAudioSeconds"])
        self.assertFalse(running["eta"]["available"])
        self.assertEqual(running["eta"]["reason"], "insufficient_history")

        self.release.set()
        completed_first = wait_for_status(manager, first["id"], {"completed"})
        completed_second = wait_for_status(manager, second["id"], {"completed"})
        self.assertEqual(completed_first["progressPercent"], 100)
        self.assertEqual(completed_first["processedAudioSeconds"], 12.0)
        self.assertEqual(completed_second["status"], "completed")
        self.assertEqual(manager.result(first["id"])["transcript"], "Treść zadania.")
        self.assertEqual(manager.result(first["id"])["transcriptSegments"][0]["start"], 0.0)

        with sqlite3.connect(manager.db_path) as connection:
            performance = connection.execute(
                "SELECT model, device, audio_duration_seconds, transcription_duration_seconds, real_time_factor "
                "FROM voice_journal_performance ORDER BY id"
            ).fetchall()
            columns = [row[1] for row in connection.execute("PRAGMA table_info(voice_journal_performance)")]
        self.assertEqual(len(performance), 2)
        self.assertNotIn("transcript", columns)

    def test_uses_similar_performance_history_for_eta(self):
        manager = self.make_manager()
        manager.initialize()
        with manager._connect() as connection:
            connection.execute(
                """
                INSERT INTO voice_journal_performance (
                    job_id, model, device, audio_duration_seconds,
                    transcription_duration_seconds, real_time_factor, completed_at
                ) VALUES (?, 'turbo', 'cpu', 10, 8, 0.8, ?)
                """,
                ("h" * 32, voice_journal_jobs.utc_now()),
            )
        job = self.submit(manager)
        self.assertTrue(self.started.wait(1))

        deadline = time.monotonic() + 2
        status = manager.get(job["id"])
        while not status["eta"]["available"] and time.monotonic() < deadline:
            time.sleep(0.01)
            status = manager.get(job["id"])
        self.assertTrue(status["eta"]["available"])
        self.assertEqual(status["eta"]["source"], "history")
        self.assertEqual(status["eta"]["sampleSize"], 1)

        self.release.set()
        wait_for_status(manager, job["id"], {"completed"})

    def test_cancels_running_job_and_cleans_temporary_files(self):
        manager = self.make_manager()
        job = self.submit(manager)
        self.assertTrue(self.started.wait(1))
        wait_for_status(manager, job["id"], {"running"})
        manager.cancel(job["id"])
        cancelled = wait_for_status(manager, job["id"], {"cancelled"})

        self.assertEqual(cancelled["stage"], "cancelled")
        self.assertTrue(self.processes[0].terminated)
        self.assertEqual(list(manager.job_dir.iterdir()), [])

    def test_cancels_queued_job_before_whisper_starts(self):
        manager = self.make_manager([True, True])
        first = self.submit(manager)
        self.assertTrue(self.started.wait(1))
        second = self.submit(manager)

        cancelled = manager.cancel(second["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(len(self.processes), 1)
        self.assertFalse(any(path.name.startswith(second["id"]) for path in manager.job_dir.iterdir()))

        self.release.set()
        wait_for_status(manager, first["id"], {"completed"})

    def test_worker_error_does_not_stop_the_queue(self):
        manager = self.make_manager([False, True])
        first = self.submit(manager)
        self.release.set()
        failed = wait_for_status(manager, first["id"], {"failed"})
        self.assertIn("mock whisper failure", failed["error"])

        second = self.submit(manager)
        completed = wait_for_status(manager, second["id"], {"completed"})
        self.assertEqual(completed["status"], "completed")

    def test_job_endpoint_validation_rejects_non_whitelisted_options(self):
        manager = self.make_manager()
        content_type, body = multipart_body(fields={
            "model": "turbo",
            "device": "auto",
            "options": json.dumps({"vad_filter": True}),
        })

        with self.assertRaises(voice_journal_jobs.VoiceJournalError) as caught:
            manager.submit(content_type, body)
        self.assertEqual(caught.exception.code, "invalid_transcription_options")
        self.assertIn("Unsupported transcription options", str(caught.exception))
        self.assertEqual(list(manager.job_dir.iterdir()), [])

    def test_accepts_large_valid_options_json_and_explicit_model_download_confirmation(self):
        manager = self.make_manager()
        prompt = "Kraków " * 120
        content_type, body = multipart_body(fields={
            "model": "small",
            "device": "auto",
            "allowModelDownload": "true",
            "options": json.dumps({"initial_prompt": prompt}),
        })

        job = manager.submit(content_type, body)
        self.assertTrue(job["allowModelDownload"])
        self.assertEqual(job["transcriptionOptions"]["initial_prompt"], prompt.strip())

        self.release.set()
        wait_for_status(manager, job["id"], {"completed"})

    def test_startup_marks_active_jobs_interrupted_and_cleans_files(self):
        manager = self.make_manager()
        manager.initialize()
        audio_path = manager.job_dir / ("a" * 32 + ".webm")
        audio_path.write_bytes(b"audio")
        now = voice_journal_jobs.utc_now()
        with manager._connect() as connection:
            connection.execute(
                """
                INSERT INTO voice_journal_jobs (
                    id, status, stage, model, language, task, device, original_filename,
                    mime_type, size_bytes, temp_audio_path, created_at, updated_at
                ) VALUES (?, 'running', 'transcribing', 'turbo', 'pl', 'transcribe', 'cpu',
                    'memo.webm', 'audio/webm', 5, ?, ?, ?)
                """,
                ("a" * 32, str(audio_path), now, now),
            )
        restarted = voice_journal_jobs.VoiceJournalJobManager(
            manager.db_path, manager.job_dir, Path(__file__).resolve().parents[1]
        )
        restarted.initialize()

        recovered = restarted.get("a" * 32)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertFalse(audio_path.exists())


class FakeHttpJobManager:
    def submit(self, content_type, body):
        return {"id": "a" * 32, "status": "queued", "stage": "queued"}

    def get(self, job_id):
        return {"id": job_id, "status": "running", "stage": "transcribing", "progressPercent": None}

    def cancel(self, job_id):
        return {"id": job_id, "status": "cancelling", "stage": "cancelling"}

    def result(self, job_id):
        return {"transcript": "HTTP result"}


class VoiceJournalJobEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [
            mock.patch.object(dashboard_server, "log_line", return_value=None),
            mock.patch.object(dashboard_server, "VOICE_JOURNAL_JOBS", FakeHttpJobManager()),
        ]
        for patcher in cls.patches:
            patcher.start()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        for patcher in reversed(cls.patches):
            patcher.stop()

    def request_json(self, path, *, data=None, content_type=None):
        headers = {"Content-Type": content_type} if content_type else {}
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.load(response)

    def test_job_routes(self):
        content_type, body = multipart_body()
        status, created = self.request_json("/api/voice-journal/jobs", data=body, content_type=content_type)
        self.assertEqual(status, 202)
        job_id = created["id"]
        self.assertEqual(self.request_json(f"/api/voice-journal/jobs/{job_id}")[1]["progressPercent"], None)
        self.assertEqual(self.request_json(f"/api/voice-journal/jobs/{job_id}/cancel", data=b"")[1]["status"], "cancelling")
        self.assertEqual(self.request_json(f"/api/voice-journal/jobs/{job_id}/result")[1]["transcript"], "HTTP result")


if __name__ == "__main__":
    unittest.main()

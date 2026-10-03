import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

import journal_store
from journal_htr_core import (
    HtrValidationError,
    calculate_next_step,
    character_error_rate,
    filter_review_lines,
    line_eligible_for_training,
    split_pages,
    validate_status,
    word_error_rate,
)
from journal_htr_provider import EscriptoriumProvider, FakeHtrProvider
from journal_htr_service import JournalHtrService
from journal_store import JournalStore


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def multipart(fields, files):
    boundary = "----journal-htr-test"
    chunks = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        chunks.append(str(value).encode())
        chunks.append(b"\r\n")
    for name, filename, mime, data in files:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        chunks.append(f"Content-Type: {mime}\r\n\r\n".encode())
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


class JournalHtrCoreTests(unittest.TestCase):
    def test_escriptorium_training_reports_are_grouped_by_celery_task(self):
        provider = EscriptoriumProvider(
            "http://localhost:8081",
            "token",
            project_slug="project",
            main_script="Latin",
        )
        provider._list_all = lambda path, query=None: [
            {
                "method": "core.tasks.train",
                "label": "Report for celery task 11111111-1111-1111-1111-111111111111 of type core.tasks.train",
                "workflow_state": 3,
                "queued_at": "2026-07-23T10:00:00Z",
                "started_at": "2026-07-23T10:01:00Z",
                "done_at": "2026-07-23T11:00:00Z",
                "messages": "",
            },
            {
                "method": "core.tasks.train",
                "label": "Report for celery task 11111111-1111-1111-1111-111111111111 of type core.tasks.train",
                "workflow_state": 3,
                "queued_at": "2026-07-23T10:00:00Z",
                "started_at": "2026-07-23T10:01:00Z",
                "done_at": "2026-07-23T11:00:00Z",
                "messages": "",
            },
        ]

        jobs = provider.list_training_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["workflowState"], 3)
        self.assertEqual(
            jobs[0]["taskId"], "11111111-1111-1111-1111-111111111111"
        )

    def test_next_step_priority(self):
        state = {
            "enabled": True,
            "providerConfigured": True,
            "providerOnline": True,
            "totalPages": 3,
            "pendingSegmentation": 2,
            "pendingTranscription": 1,
            "unreviewedLines": 20,
        }
        self.assertEqual(calculate_next_step(state)["priority"], 5)
        self.assertIn("segmentację", calculate_next_step(state)["title"])

    def test_next_step_does_not_skip_running_segmentation(self):
        state = {
            "enabled": True,
            "providerConfigured": True,
            "providerOnline": True,
            "totalPages": 17,
            "pendingSegmentation": 0,
            "segmentingPages": 17,
            "pendingTranscription": 0,
            "transcribingPages": 0,
            "groundTruthLines": 0,
            "approvedLines": 0,
            "correctedLines": 0,
        }

        step = calculate_next_step(state)

        self.assertEqual(step["priority"], 5)
        self.assertIn("trwa", step["title"])
        self.assertIn("#jobs", step["actionUrl"])

    def test_training_eligibility(self):
        self.assertTrue(line_eligible_for_training("approved", None, "tekst", True))
        self.assertTrue(line_eligible_for_training("corrected", "tekst", "", True))
        self.assertFalse(line_eligible_for_training("uncertain", "tekst", "", True))
        self.assertFalse(line_eligible_for_training("approved", "tekst", "", False))

    def test_page_split_is_stable_and_disjoint(self):
        pages = [f"page-{index}" for index in range(20)]
        first = split_pages(pages)
        second = split_pages(reversed(pages), fixed_test_pages=first["test"])
        self.assertEqual(first, second)
        self.assertFalse(set(first["train"]) & set(first["test"]))
        self.assertFalse(set(first["validation"]) & set(first["test"]))

    def test_cer_and_wer(self):
        self.assertAlmostEqual(character_error_rate("kot", "koc"), 1 / 3)
        self.assertAlmostEqual(word_error_rate("to jest test", "to test"), 1 / 3)
        self.assertEqual(character_error_rate("", ""), 0)

    def test_status_validation(self):
        self.assertEqual(validate_status("approved", {"approved"}), "approved")
        with self.assertRaises(HtrValidationError):
            validate_status("invented", {"approved"})

    def test_review_filter_priority(self):
        lines = [
            {
                "id": "old",
                "reviewStatus": "approved",
                "confidence": 0.9,
                "predictedText": "plain",
                "modelId": "old",
                "lineOrder": 3,
            },
            {
                "id": "low",
                "reviewStatus": "unreviewed",
                "confidence": 0.2,
                "predictedText": "plain",
                "modelId": "active",
                "lineOrder": 2,
            },
            {
                "id": "high",
                "reviewStatus": "unreviewed",
                "confidence": 0.8,
                "predictedText": "plain",
                "modelId": "active",
                "lineOrder": 1,
            },
        ]
        result = filter_review_lines(lines, {"activeModelId": "active"})
        self.assertEqual([line["id"] for line in result[:2]], ["low", "high"])


class JournalHtrWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JournalHtrService(
            root, provider=FakeHtrProvider(), storage_path=root / "htr"
        )
        self.service.initialize()
        self.previous_journal_store = journal_store.JOURNAL_STORE
        journal_store.JOURNAL_STORE = JournalStore(root / "journal.sqlite")

    def tearDown(self):
        journal_store.JOURNAL_STORE = self.previous_journal_store
        self.service.stop()
        self.temp.cleanup()

    def wait_job(self, job_id, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.service._require_store().get_job(job_id)
            if job["status"] in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.02)
        self.fail(f"Job {job_id} did not finish")

    def test_upload_recognize_review_train_promote_and_export(self):
        content_type, body = multipart(
            {
                "notebookName": "Test notebook",
                "language": "pl",
                "datePrecision": "unknown",
            },
            [("files", "page.png", "image/png", ONE_PIXEL_PNG)],
        )
        upload = self.service.upload(content_type, body)
        self.assertEqual(len(upload["pages"]), 1)
        self.assertEqual(self.wait_job(upload["job"]["id"])["status"], "completed")
        page_id = upload["pages"][0]["id"]

        sync = self.service.sync()
        self.assertEqual(self.wait_job(sync["id"])["status"], "completed")
        model = next(
            model
            for model in self.service._require_store().list_models()
            if model["type"] == "recognition"
        )

        segment = self.service.start_segmentation([page_id])
        self.assertEqual(self.wait_job(segment["id"])["status"], "completed")
        self.assertEqual(
            self.service._require_store().get_page(page_id)["status"], "segmented"
        )

        transcribe = self.service.start_transcription([page_id], model["id"])
        self.assertEqual(self.wait_job(transcribe["id"])["status"], "completed")
        lines = self.service._require_store().list_lines(page_id=page_id)
        self.assertEqual(len(lines), 3)

        for line in lines:
            updated = self.service.update_line(
                line["id"],
                {
                    "correctedText": line["predictedText"],
                    "reviewStatus": "approved",
                    "useForTraining": True,
                },
            )
            self.assertEqual(updated["reviewStatus"], "approved")
        self.assertEqual(
            len(self.service._require_store().line_revisions(lines[0]["id"])), 1
        )

        dataset = self.service._require_store().create_dataset(
            {
                "name": "test-ground-truth",
                "ratios": {"train": 0.8, "validation": 0.1, "test": 0.1},
            }
        )
        self.assertEqual(dataset["lineCount"], 3)

        training = self.service.start_training(
            {
                "type": "recognition",
                "datasetId": dataset["id"],
                "baseModelId": model["id"],
                "name": "Test handwriting v1",
            }
        )
        self.assertEqual(self.wait_job(training["job"]["id"])["status"], "completed")
        candidate = self.service._require_store().get_model(training["model"]["id"])
        self.assertEqual(candidate["status"], "ready")
        self.assertTrue(self.service.activate_model(candidate["id"])["isActive"])

        entry = self.service.export_to_journal(
            {"pageIds": [page_id], "title": "Imported handwriting"}
        )
        self.assertEqual(entry["sourceType"], "journal-htr")
        self.assertEqual(entry["title"], "Imported handwriting")
        self.assertIn("faithfulTranscription", entry["sourceMetadata"])

    def test_manual_geometry_edit_and_merge_keep_stable_line_id(self):
        content_type, body = multipart(
            {
                "notebookName": "Geometry notebook",
                "language": "pl",
                "datePrecision": "unknown",
            },
            [("files", "geometry.png", "image/png", ONE_PIXEL_PNG)],
        )
        upload = self.service.upload(content_type, body)
        self.assertEqual(self.wait_job(upload["job"]["id"])["status"], "completed")
        page_id = upload["pages"][0]["id"]
        sync = self.service.sync()
        self.assertEqual(self.wait_job(sync["id"])["status"], "completed")
        model = next(
            model
            for model in self.service._require_store().list_models()
            if model["type"] == "recognition"
        )
        segment = self.service.start_segmentation([page_id])
        self.assertEqual(self.wait_job(segment["id"])["status"], "completed")
        transcribe = self.service.start_transcription([page_id], model["id"])
        self.assertEqual(self.wait_job(transcribe["id"])["status"], "completed")
        lines = self.service._require_store().list_lines(page_id=page_id)

        stable_id = lines[0]["id"]
        edited = self.service.update_line(
            stable_id,
            {
                "geometry": {
                    **lines[0]["geometry"],
                    "mask": [[10, 10], [900, 10], [900, 80], [10, 80]],
                }
            },
        )
        self.assertEqual(edited["id"], stable_id)
        self.assertTrue(edited["geometry"]["manuallyEdited"])

        merged = self.service.merge_lines(stable_id, lines[1]["id"])
        self.assertEqual(merged["id"], stable_id)
        self.assertTrue(merged["geometry"]["merged"])
        self.assertEqual(
            self.service._require_store().get_line(lines[1]["id"])["reviewStatus"],
            "excluded",
        )

    def test_training_status_comes_from_provider_task_and_archive_persists(self):
        store = self.service._require_store()
        dataset = {"name": "ground-truth", "version": 1}
        model = store.create_candidate_model(
            {"name": "Queued duplicate", "type": "recognition"}, dataset
        )
        remote_id = "fake-queued-model"
        store.update_model(model["id"], external_model_id=remote_id)
        self.service.provider.models.append(
            {
                "pk": remote_id,
                "name": model["name"],
                "job": "Recognize",
                "training": False,
                "versions": [],
            }
        )
        job = store.create_job(
            "training",
            {"modelId": model["id"], "datasetId": "dataset", "baseModelId": None},
        )
        task_id = "22222222-2222-2222-2222-222222222222"
        store.update_job(job["id"], status="running", provider_task_id=task_id)

        def provider_jobs(state):
            return [{
                "taskId": task_id,
                "workflowState": state,
                "queuedAt": job["createdAt"],
                "startedAt": job["createdAt"] if state != 0 else None,
                "doneAt": job["createdAt"] if state in {2, 3, 4} else None,
                "messages": ["training failed"] if state == 2 else [],
            }]

        self.service.provider.list_training_jobs = lambda document_id=None: provider_jobs(0)
        self.service.reconcile_provider_models()
        self.assertEqual(store.get_model(model["id"])["status"], "queued")
        self.assertEqual(store.get_job(job["id"])["status"], "pending")

        self.service.provider.list_training_jobs = lambda document_id=None: provider_jobs(1)
        self.service.reconcile_provider_models()
        self.assertEqual(store.get_model(model["id"])["status"], "training")
        self.assertEqual(store.get_job(job["id"])["status"], "running")

        self.service.provider.list_training_jobs = lambda document_id=None: provider_jobs(2)
        self.service.reconcile_provider_models()
        self.assertEqual(store.get_model(model["id"])["status"], "failed")
        self.assertEqual(store.get_job(job["id"])["status"], "failed")

        store.archive_model(model["id"])
        self.service.reconcile_provider_models()
        self.assertEqual(store.get_model(model["id"])["status"], "archived")

    def test_delete_non_active_duplicate_removes_provider_model_and_local_job(self):
        store = self.service._require_store()
        model = store.create_candidate_model(
            {"name": "Duplicate", "type": "recognition"},
            {"name": "ground-truth", "version": 2},
        )
        remote_id = "fake-duplicate"
        store.update_model(
            model["id"], external_model_id=remote_id, status="failed"
        )
        self.service.provider.models.append(
            {
                "pk": remote_id,
                "name": model["name"],
                "job": "Recognize",
                "training": False,
            }
        )
        job = store.create_job(
            "training",
            {"modelId": model["id"], "datasetId": "dataset", "baseModelId": None},
        )
        store.update_job(job["id"], status="failed")

        result = self.service.delete_model(model["id"])

        self.assertTrue(result["ok"])
        with self.assertRaises(Exception):
            store.get_model(model["id"])
        with self.assertRaises(Exception):
            store.get_job(job["id"])
        self.assertFalse(
            any(str(item.get("pk")) == remote_id for item in self.service.provider.models)
        )
class JournalHtrOfflineUploadTests(unittest.TestCase):
    def test_upload_is_kept_local_until_provider_is_provisioned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = JournalHtrService(
                root,
                provider=EscriptoriumProvider(
                    "http://127.0.0.1:8081",
                    "",
                    project_slug="journal-htr",
                ),
                storage_path=root / "htr",
            )
            service.initialize()
            try:
                content_type, body = multipart(
                    {
                        "notebookName": "Offline notebook",
                        "language": "mixed",
                        "datePrecision": "unknown",
                    },
                    [("files", "page.png", "image/png", ONE_PIXEL_PNG)],
                )
                result = service.upload(content_type, body)
                self.assertIsNone(result["job"])
                self.assertEqual(result["pages"][0]["status"], "uploaded")
                self.assertEqual(service._require_store().list_jobs(), [])
            finally:
                service.stop()


if __name__ == "__main__":
    unittest.main()

from types import SimpleNamespace
from unittest.mock import patch

from celery import states
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError

from core.models import OcrModel
from core.tests.factory import CoreFactoryTestCase
from reporting.models import TaskReport
from reporting.tasks import end_task_reporting, update_client_state


class ReportingDeletedPartTests(CoreFactoryTestCase):
    def test_existing_part_updates_client_state(self):
        part = self.factory.make_part()

        with patch("reporting.tasks.send_event") as send_event:
            update_client_state(
                {"part_pks": [part.pk]},
                "core.tasks.train",
                "done",
                task_id="task-existing",
            )

        send_event.assert_called_once_with(
            "document",
            part.document.pk,
            "part:workflow",
            {
                "id": part.pk,
                "process": "train",
                "status": "done",
                "task_id": "task-existing",
                "data": {},
            },
        )

    def test_deleted_part_is_warned_and_does_not_update_another_part(self):
        deleted_part = self.factory.make_part()
        other_part = self.factory.make_part(document=deleted_part.document)
        deleted_pk = deleted_part.pk
        type(deleted_part).objects.filter(pk=deleted_pk).delete()

        with self.assertLogs("reporting.tasks", level="WARNING") as logs:
            with patch("reporting.tasks.send_event") as send_event:
                update_client_state(
                    {"part_pks": [deleted_pk]},
                    "core.tasks.train",
                    "done",
                    task_id="task-deleted",
                )

        send_event.assert_not_called()
        self.assertTrue(type(other_part).objects.filter(pk=other_part.pk).exists())
        warning = "\n".join(logs.output)
        self.assertIn(f"DocumentPart {deleted_pk} no longer exists", warning)
        self.assertIn("task_id=task-deleted", warning)
        self.assertIn("task_name=core.tasks.train", warning)

    def test_missing_part_identifiers_are_a_noop(self):
        with patch("reporting.tasks.send_event") as send_event:
            update_client_state({}, "core.tasks.train", "done")
            update_client_state({"part_pks": []}, "core.tasks.train", "done")

        send_event.assert_not_called()

    def test_database_errors_other_than_does_not_exist_propagate(self):
        part = self.factory.make_part()

        with patch(
            "core.models.DocumentPart.objects.get",
            side_effect=OperationalError("database unavailable"),
        ):
            with self.assertRaises(OperationalError):
                update_client_state(
                    {"part_pks": [part.pk]},
                    "core.tasks.train",
                    "done",
                    task_id="task-db-error",
                )

    def test_successful_training_report_and_model_survive_deleted_part(self):
        part = self.factory.make_part()
        deleted_pk = part.pk
        model = OcrModel.objects.create(
            name="trained-test-model",
            owner=part.document.owner,
            job=OcrModel.MODEL_JOB_RECOGNIZE,
            training=False,
            file=SimpleUploadedFile("trained.mlmodel", b"trained-model"),
            file_size=len(b"trained-model"),
        )
        report = TaskReport.objects.create(
            user=part.document.owner,
            label="training",
            document=part.document,
            document_part=part,
            ocr_model=model,
            task_id="task-training-success",
            method="core.tasks.train",
        )
        type(part).objects.filter(pk=deleted_pk).delete()

        with self.assertLogs("reporting.tasks", level="WARNING"):
            end_task_reporting(
                task_id="task-training-success",
                task=SimpleNamespace(name="core.tasks.train"),
                state=states.SUCCESS,
                kwargs={"part_pks": [deleted_pk], "model_pk": model.pk},
                result=None,
            )

        report.refresh_from_db()
        model.refresh_from_db()
        self.assertEqual(report.workflow_state, TaskReport.WORKFLOW_STATE_DONE)
        self.assertIsNotNone(report.done_at)
        self.assertFalse(model.training)
        self.assertEqual(model.file_size, len(b"trained-model"))
        self.assertTrue(model.file.storage.exists(model.file.name))

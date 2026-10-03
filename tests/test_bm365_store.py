import json
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from bm365_sheets_syncer import Bm365SheetsSyncer
from bm365_store import Bm365Error, Bm365Store


def album(row_id, day, **overrides):
    value = {
        "rowId": row_id,
        "date": day,
        "artist": f"Artist {row_id}",
        "album": f"Album {row_id}",
        "listened": "",
        "rating": None,
        "minutes": 40,
        "year": 1995,
        "description": f"Description {row_id}",
    }
    value.update(overrides)
    return value


class FakeResponse:
    def __init__(self, payload):
        self.buffer = BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.buffer.read()


class Bm365StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Bm365Store(Path(self.temp_dir.name) / "bm365.sqlite")
        self.store.replace_all(
            [
                album(2, "2026-01-01", listened="TAK", rating=4),
                album(3, "2026-01-02"),
                album(4, "2026-01-03"),
            ],
            expected_count=3,
        )

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_state_is_built_from_local_rows_with_original_payload_shape(self):
        with mock.patch.object(self.store, "_cross_lists", side_effect=lambda rows: rows):
            state = self.store.get_state("2026-01-02")

        self.assertEqual(state["albumToday"]["rowId"], 3)
        self.assertEqual(state["stats"]["total"], 3)
        self.assertEqual(state["stats"]["done"], 1)
        self.assertEqual([row["rowId"] for row in state["catchUp"]], [3])
        self.assertEqual(state["rows"][0]["listened"], "TAK")
        self.assertEqual(state["rows"][0]["year"], "1995")

    def test_mark_and_rate_commit_locally_and_enqueue_sheet_push(self):
        marked = self.store.mark_listened({"rowId": 3}, True)
        with mock.patch.object(self.store, "_propagate_rating") as propagate:
            rated = self.store.rate_album({"date": "2026-01-03"}, 4.5)

        self.assertEqual(marked["listened"], "TAK")
        self.assertEqual(rated["rating"], 4.5)
        self.assertEqual(rated["listened"], "TAK")
        propagate.assert_called_once()
        tasks = self.store.pending_sync_tasks()
        self.assertEqual([task["action"] for task in tasks], ["mark", "rate"])
        self.assertEqual(tasks[1]["rating"], 4.5)

    def test_metadata_update_keeps_existing_description_when_only_year_changes(self):
        updated = self.store.update_metadata(2, year=1994)
        self.assertEqual(updated["year"], "1994")
        self.assertEqual(updated["description"], "Description 2")

    def test_import_validation_is_atomic(self):
        broken = [album(2, "2026-01-01"), album(2, "2026-01-02")]
        with self.assertRaises(Bm365Error):
            self.store.replace_all(broken, expected_count=2)
        self.assertEqual(self.store.count(), 3)

    def test_sheet_sync_success_marks_queue_item_synced(self):
        self.store.mark_listened({"rowId": 3}, True)
        requests = []

        def opener(request, timeout):
            requests.append((request.full_url, timeout))
            return FakeResponse({"ok": True})

        syncer = Bm365SheetsSyncer(self.store, "https://example.test/exec", opener=opener)
        result = syncer.flush_once(force=True)

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["queue"]["synced"], 1)
        self.assertIn("action=bm365_mark", requests[0][0])
        self.assertIn("rowId=3", requests[0][0])

    def test_sheet_sync_failure_is_durable_and_retryable(self):
        with mock.patch.object(self.store, "_propagate_rating"):
            self.store.rate_album({"rowId": 3}, 3.5)
        opener = mock.Mock(side_effect=OSError("offline"))
        syncer = Bm365SheetsSyncer(self.store, "https://example.test/exec", opener=opener)

        failed = syncer.flush_once(force=True)
        self.assertEqual(failed["queue"]["failed"], 1)
        syncer._opener = lambda _request, timeout: FakeResponse({"ok": True})
        retried = syncer.flush_once(force=True)
        self.assertEqual(retried["queue"]["synced"], 1)
        self.assertEqual(retried["queue"]["failed"], 0)

    def test_background_worker_flushes_after_local_write_notification(self):
        self.store.mark_listened({"rowId": 3}, True)
        delivered = threading.Event()

        def opener(_request, timeout):
            delivered.set()
            return FakeResponse({"ok": True})

        syncer = Bm365SheetsSyncer(self.store, "https://example.test/exec", opener=opener)
        try:
            syncer.start()
            syncer.notify()
            self.assertTrue(delivered.wait(timeout=1))
        finally:
            syncer.stop()
        self.assertEqual(self.store.sync_queue_stats()["synced"], 1)


if __name__ == "__main__":
    unittest.main()

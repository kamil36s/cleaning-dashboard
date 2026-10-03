import json
import tempfile
import threading
import unittest
from pathlib import Path

from todo_phone import active_items, update_file


class TodoPhoneTest(unittest.TestCase):
    def test_phone_only_sees_open_tasks_and_shopping(self):
        items = [
            {"id": "a", "title": "Task", "bucket": "now", "done": False},
            {"id": "b", "title": "Milk", "bucket": "shopping", "done": False},
            {"id": "c", "title": "Secret project", "bucket": "projects", "done": False},
            {"id": "d", "title": "Old", "bucket": "now", "done": True},
        ]
        self.assertEqual([item["id"] for item in active_items(items)], ["a", "b"])

    def test_action_keeps_other_buckets_and_existing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "todo.json"
            project = {"id": "project", "title": "Project", "bucket": "projects", "subtasks": [{"id": "one"}]}
            path.write_text(json.dumps([project, {"id": "task", "title": "Task", "bucket": "now", "done": False}]), encoding="utf-8")
            lock = threading.Lock()
            def temp_path(target): return target.with_suffix(".tmp")
            def replace(source, target): source.replace(target)
            update_file(path, {"action": "complete", "id": "task"}, lambda _: lock, temp_path, replace)
            items = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(items[0], project)
            self.assertTrue(items[1]["done"])
            self.assertIsInstance(items[1]["completedAt"], int)
            update_file(path, {"action": "add", "bucket": "shopping", "title": "Milk"}, lambda _: lock, temp_path, replace)
            items = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(items[2]["bucket"], "shopping")
            self.assertEqual([item["title"] for item in active_items(items)], ["Milk"])

    def test_rejects_project_edits(self):
        from todo_phone import apply_action
        with self.assertRaises(ValueError):
            apply_action([{"id": "p", "bucket": "projects"}], {"action": "complete", "id": "p"})
        with self.assertRaises(ValueError):
            apply_action([], {"action": "add", "bucket": "projects", "title": "No"})


if __name__ == "__main__": unittest.main()

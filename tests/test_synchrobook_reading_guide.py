import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import synchrobook_backend.reading_guide as module


BOOK_ID = "a" * 32


class ReadingGuideTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "synchrobook"
        self.books = self.root / "books"
        self.db = self.root / "library.db"
        self.root.mkdir(parents=True)
        with sqlite3.connect(self.db) as connection:
            connection.execute("""CREATE TABLE books (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
                cover_file TEXT, epub_file TEXT NOT NULL, audiobook_file TEXT NOT NULL,
                playback_file TEXT, language TEXT, duration REAL,
                imported_at TEXT NOT NULL, processing_state TEXT NOT NULL, error TEXT
            )""")
            connection.execute("INSERT INTO books VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (BOOK_ID, "Ethics", "Spinoza", None, "source.epub", "source.m4b", "playback.m4a", "en", 100, "now", "READY", None))
        book_dir = self.books / BOOK_ID / "text"
        book_dir.mkdir(parents=True)
        book = {
            "title": "Ethics", "author": "Baruch Spinoza", "sourceFormat": "epub", "language": "en", "extractionVersion": 4,
            "chapters": [
                {"id": "ch01", "title": "Definitions", "paragraphs": [{"id": "ch01-p001", "sentences": [
                    {"id": "ch01-p001-s001", "originalText": "First definition."},
                    {"id": "ch01-p001-s002", "originalText": "Second definition."},
                ]}]},
                {"id": "ch02", "title": "Propositions I-VIII", "paragraphs": [{"id": "ch02-p001", "sentences": [
                    {"id": "ch02-p001-s001", "originalText": "Proposition one."},
                    {"id": "ch02-p001-s002", "originalText": "Its proof."},
                    {"id": "ch02-p001-s003", "originalText": "Proposition two."},
                    {"id": "ch02-p001-s004", "originalText": "Its longer proof."},
                ]}]},
                {"id": "ch03", "title": "Following propositions", "paragraphs": [{"id": "ch03-p001", "sentences": [
                    {"id": "ch03-p001-s001", "originalText": "What follows."},
                ]}]},
            ],
        }
        (book_dir / "book.json").write_text(json.dumps(book), encoding="utf-8")
        self.patchers = [
            patch.object(module, "DATA_ROOT", self.root),
            patch.object(module, "BOOKS_ROOT", self.books),
            patch.object(module, "DB_PATH", self.db),
        ]
        for patcher in self.patchers: patcher.start()
        self.engine = module.ReadingGuideEngine()
        self.engine.initialize()
        self.engine.state(BOOK_ID)
        self.engine.execute(BOOK_ID, {"action": "save_set", "data": {"id": "guide-one", "name": "Guide One", "profile_id": "spinoza-guided-first-reading"}})

    def tearDown(self):
        for patcher in reversed(self.patchers): patcher.stop()
        self.temporary.cleanup()

    def prompt(self):
        return self.engine.execute(BOOK_ID, {"action": "build_prompt", "data": {
            "mode": "selected_section", "chapter_id": "ch02", "commentary_set_id": "guide-one",
        }})

    def valid_import(self, generated):
        return {
            "schema_version": "1.0", "operation": "section_commentary", "book_id": BOOK_ID,
            "commentary_set_id": "guide-one", "reading_profile_id": "spinoza-guided-first-reading",
            "section_id": "ch02", "source_fingerprint": generated["sourceFingerprint"],
            "source_normalization_version": 1,
            "section_guide": {"before_reading": "Prepare.", "section_summary": "Done.", "section_terminology": [{"term": "substance", "definition": "That which is in itself."}], "argument_map": None},
            "commentary_chunks": [
                {"id": "llm-range-a", "start_source_id": "ch02-p001-s001", "end_source_id": "ch02-p001-s003", "title": "First logical movement", "blocks": [{"type": "explanation", "renderer": "prose", "content": "Explanation."}, {"type": "terminology", "renderer": "terminology", "data": [{"term": "substance", "definition": "That which is in itself.", "source_anchor_id": "ch02-p001-s001"}]}]},
                {"id": "llm-range-b", "start_source_id": "ch02-p001-s004", "end_source_id": "ch02-p001-s004", "title": "Second movement", "blocks": [{"type": "watch_for", "renderer": "short_note", "content": "Notice this."}]},
            ],
            "memory_update": {key: [] for key in module._default_memory()},
        }

    def test_generation_creates_target_but_no_commentary_chunks(self):
        generated = self.prompt()
        state = self.engine.state(BOOK_ID)
        self.assertEqual(state["chunks"], [])
        self.assertIn("[ch02-p001-s001]", generated["prompt"])
        self.assertIn("Read the entire TARGET before deciding chunk boundaries.", generated["prompt"])
        self.assertNotIn('"start_source_id": "ch02-p001-s001"', generated["prompt"])
        self.assertIn("First definition.", generated["prompt"])
        self.assertIn("What follows.", generated["prompt"])
        enabled = {"explanation", "argument_analysis", "terminology", "watch_for", "cross_reference", "historical_context", "importance"}
        for commentary_type in module.BUILTIN_COMMENTARY_TYPES:
            if commentary_type["id"] in enabled:
                self.assertIn(commentary_type["generation_instruction"], generated["prompt"])

    def test_import_accepts_llm_chosen_ranges_and_builds_glossary(self):
        generated = self.prompt()
        result = self.engine.execute(BOOK_ID, {"action": "import_json", "data": {"json": self.valid_import(generated), "destination_set_id": "guide-one"}})
        self.assertTrue(result["valid"])
        self.assertEqual([(row["start_source_id"], row["end_source_id"]) for row in result["state"]["chunks"]], [("ch02-p001-s001", "ch02-p001-s003"), ("ch02-p001-s004", "ch02-p001-s004")])
        self.assertEqual(result["state"]["glossary"][0]["term"], "substance")

    def test_import_rejects_invalid_ranges_fingerprint_and_schema(self):
        generated = self.prompt(); payload = self.valid_import(generated)
        payload["commentary_chunks"][0]["start_source_id"] = "missing"
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertFalse(result["valid"]); self.assertTrue(any("does not exist" in row for row in result["errors"]))
        payload = self.valid_import(generated); payload["commentary_chunks"][0]["start_source_id"] = "ch01-p001-s001"
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertTrue(any("outside TARGET" in row for row in result["errors"]))
        payload = self.valid_import(generated); payload["commentary_chunks"][1]["start_source_id"] = "ch02-p001-s002"
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertTrue(any("overlaps" in row for row in result["errors"]))
        payload = self.valid_import(generated); payload["commentary_chunks"][0]["start_source_id"] = "ch02-p001-s003"; payload["commentary_chunks"][0]["end_source_id"] = "ch02-p001-s001"
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertTrue(any("reversed range" in row for row in result["errors"]))
        payload = self.valid_import(generated); payload["source_fingerprint"] = "sha256:wrong"
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertTrue(any("different version" in row for row in result["errors"]))
        payload = self.valid_import(generated); payload["schema_version"] = "999"
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertIn("Unsupported schema_version", result["errors"])

    def test_book_analysis_import_and_later_prompt_include_intelligence_and_memory(self):
        generated = self.engine.execute(BOOK_ID, {"action": "build_prompt", "data": {"mode": "book_analysis", "commentary_set_id": "guide-one"}})
        intelligence = {
            "overview": "A geometric ethical system.", "structure": [], "major_arguments": [], "core_concepts": [],
            "important_cross_references": [], "reading_progression": [], "historical_context": [], "likely_difficulties": [], "global_glossary_seed": [],
        }
        imported = self.engine.execute(BOOK_ID, {"action": "import_json", "data": {"destination_set_id": "guide-one", "json": {
            "schema_version": "1.0", "operation": "book_analysis", "book_id": BOOK_ID,
            "source_fingerprint": generated["sourceFingerprint"], "book_intelligence": intelligence,
        }}})
        self.assertTrue(imported["valid"])
        section = self.prompt()
        self.assertIn("A geometric ethical system.", section["prompt"])
        self.assertIn("COMMENTARY MEMORY", section["prompt"])
        self.assertTrue(section["context"]["bookIntelligenceIncluded"])

    def test_previous_imported_summary_is_used_as_previous_context(self):
        generated = self.engine.execute(BOOK_ID, {"action": "build_prompt", "data": {"mode": "selected_section", "chapter_id": "ch01", "commentary_set_id": "guide-one"}})
        payload = self.valid_import(generated)
        payload["section_id"] = "ch01"
        payload["section_guide"]["section_summary"] = "Definitions now established."
        payload["commentary_chunks"] = [{"id": "definitions", "start_source_id": "ch01-p001-s001", "end_source_id": "ch01-p001-s002", "title": "Definitions", "blocks": [{"type": "explanation", "renderer": "prose", "content": "Definitions explained."}]}]
        self.engine.execute(BOOK_ID, {"action": "import_json", "data": {"json": payload, "destination_set_id": "guide-one"}})
        next_prompt = self.prompt()
        self.assertIn("Definitions now established.", next_prompt["prompt"])

    def test_import_rechecks_current_source_fingerprint(self):
        generated = self.prompt(); payload = self.valid_import(generated)
        book_path = self.books / BOOK_ID / "text" / "book.json"
        book = json.loads(book_path.read_text(encoding="utf-8"))
        book["chapters"][1]["paragraphs"][0]["sentences"][0]["originalText"] = "Changed proposition."
        book_path.write_text(json.dumps(book), encoding="utf-8")
        result = self.engine.execute(BOOK_ID, {"action": "validate_import", "data": {"json": payload, "destination_set_id": "guide-one"}})
        self.assertTrue(any("different version" in row for row in result["errors"]))

    def test_custom_type_context_profile_order_and_set_independence(self):
        self.engine.execute(BOOK_ID, {"action": "save_type", "data": {"id": "my_company", "name": "My Company", "generation_instruction": "Compare workplace structures.", "custom_context": "PRIVATE WORKPLACE CONTEXT", "default_renderer": "prose", "default_scope": "chunk"}})
        self.engine.execute(BOOK_ID, {"action": "save_profile", "data": {"id": "custom-profile", "name": "Custom", "enabled_chunk_types": ["my_company", "explanation"], "type_order": ["my_company", "explanation"], "enabled_section_types": [], "enabled_book_types": []}})
        self.engine.execute(BOOK_ID, {"action": "save_set", "data": {"id": "guide-two", "name": "Guide Two", "profile_id": "custom-profile"}})
        generated = self.engine.execute(BOOK_ID, {"action": "build_prompt", "data": {"mode": "selected_section", "chapter_id": "ch02", "commentary_set_id": "guide-two"}})
        prompt = generated["prompt"]
        self.assertLess(prompt.index("TYPE:\nmy_company"), prompt.index("TYPE:\nexplanation"))
        self.assertIn("PRIVATE WORKPLACE CONTEXT", prompt)
        self.assertNotIn("TYPE:\nwatch_for", prompt)
        self.assertEqual(self.engine.state(BOOK_ID)["chunks"], [])
        custom_payload = self.valid_import(generated)
        custom_payload["commentary_set_id"] = "guide-two"
        custom_payload["reading_profile_id"] = "custom-profile"
        custom_payload["commentary_chunks"] = [{"id": "company-range", "start_source_id": "ch02-p001-s001", "end_source_id": "ch02-p001-s004", "title": "Workplace lens", "blocks": [{"type": "my_company", "renderer": "prose", "content": "A careful comparison."}]}]
        custom_result = self.engine.execute(BOOK_ID, {"action": "import_json", "data": {"json": custom_payload, "destination_set_id": "guide-two"}})
        self.assertTrue(custom_result["valid"])
        self.engine.execute(BOOK_ID, {"action": "activate_set", "data": {"id": "guide-one"}})
        imported = self.engine.execute(BOOK_ID, {"action": "import_json", "data": {"json": self.valid_import(self.prompt()), "destination_set_id": "guide-one"}})
        self.assertEqual(len(imported["state"]["chunks"]), 2)
        other = self.engine.execute(BOOK_ID, {"action": "activate_set", "data": {"id": "guide-two"}})
        self.assertEqual([row["id"] for row in other["chunks"]], ["company-range"])

    def test_duplicate_set_copies_guide_data_without_linking_future_changes(self):
        generated = self.prompt()
        self.engine.execute(BOOK_ID, {"action": "import_json", "data": {"json": self.valid_import(generated), "destination_set_id": "guide-one"}})
        duplicated = self.engine.execute(BOOK_ID, {"action": "duplicate_set", "data": {"id": "guide-one", "name": "Guide Copy"}})
        copy_set = next(row for row in duplicated["sets"] if row["name"] == "Guide Copy")
        activated = self.engine.execute(BOOK_ID, {"action": "activate_set", "data": {"id": copy_set["id"]}})
        self.assertEqual(len(activated["chunks"]), 2)
        self.engine.execute(BOOK_ID, {"action": "reset_memory", "data": {"commentary_set_id": copy_set["id"]}})
        original = self.engine.execute(BOOK_ID, {"action": "activate_set", "data": {"id": "guide-one"}})
        self.assertEqual(len(original["chunks"]), 2)


if __name__ == "__main__":
    unittest.main()

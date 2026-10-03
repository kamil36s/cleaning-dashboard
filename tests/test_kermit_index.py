"""Synthetic, source-only Phase 3 acceptance tests."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from kermit_index.builder import (
    CORE_NAMES,
    IndexErrorClosed,
    build,
    build_data,
    encoded_artifacts,
    safe_path,
    validate,
)


FAKE_SECRET = "FAKE_KERMIT_TOKEN_DO_NOT_INDEX_9d2c1a"


class KermitIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "data/generated/kermit-index"
        self.manifest = self.root / "admission.json"
        entries = []
        for slug in ("quote", "finance", "language-learning", "weather"):
            path = f"docs/kermit/knowledge/subsystems/{slug}.md"
            self.write(path, f"# {slug}\n## Identity and verification\n- ID: `{slug}`\n## Data flow\n1. Inspect admitted source.\n## Metrics and calculations\n| Metric | Rule |\n| --- | --- |\n| {slug} count | one |\n")
            entries.append({"path": path, "group": "documentation", "subsystem": slug})
        gaps = "# Findings\n" + "\n".join(f"## {code}\n- **Type:** gap\n- **Description:** synthetic finding\n- **Impact on future Kermit answers:** unknown\n- **Blocks Phase 3?** No\n" for code in ("Q-01", "W-01", "W-02", "F-01", "F-02", "F-03", "F-04", "L-01"))
        self.write("docs/kermit/knowledge/GAPS_AND_CONFLICTS.md", gaps)
        entries.append({"path": "docs/kermit/knowledge/GAPS_AND_CONFLICTS.md", "group": "documentation", "subsystem": "shared"})
        self.write("kermit_index/finding_sides.json", json.dumps({"schemaVersion": 1, "findings": {
            code: {"category": "UNKNOWN_BEHAVIOR",
                   "sideA": {"description": "Synthetic uncertainty.", "refs": []},
                   "sideB": {"description": "No second factual side.", "refs": []}}
            for code in ("Q-01", "W-01", "W-02", "F-01", "F-02", "F-03", "F-04", "L-01")}}))
        self.write("pilot.py", "def current():\n    return 1\n")
        entries.append({"path": "pilot.py", "group": "source", "subsystem": "quote"})
        self.spec = {"schemaVersion": 1, "sourcePolicy": "docs/kermit/SOURCE_POLICY.md", "defaults": {"documentation": {"sourceClass": "reviewed_documentation", "expectedRole": "evidence", "privacyClassification": "public_project_knowledge", "parserMode": "markdown", "contentMode": "sections", "maxBytes": 300000}, "source": {"sourceClass": "project_source", "expectedRole": "implementation_metadata", "privacyClassification": "internal_implementation", "parserMode": "static", "contentMode": "metadata_only", "maxBytes": 2000000}}, "entries": entries}
        self.save_manifest()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.spec), encoding="utf-8")

    def core(self):
        return {name: (self.output / name).read_bytes() for name in CORE_NAMES}

    def test_deterministic_build_stale_missing_and_rebuild(self):
        before = {item["path"]: hashlib.sha256((self.root / item["path"]).read_bytes()).hexdigest() for item in self.spec["entries"]}
        build(self.root, self.manifest, self.output)
        first = self.core()
        build(self.root, self.manifest, self.output)
        self.assertEqual(first, self.core())
        self.assertEqual(first["entities.jsonl"], encoded_artifacts(build_data(self.root, self.manifest))["entities.jsonl"])
        self.write("unlisted.py", FAKE_SECRET)
        self.assertEqual(first, encoded_artifacts(build_data(self.root, self.manifest)))
        for item in self.spec["entries"]:
            self.assertEqual(before[item["path"]], hashlib.sha256((self.root / item["path"]).read_bytes()).hexdigest())
        self.write("pilot.py", "def current():\n    return 2\n")
        self.assertNotEqual(first["sources.jsonl"], encoded_artifacts(build_data(self.root, self.manifest))["sources.jsonl"])
        with self.assertRaisesRegex(IndexErrorClosed, "stale"):
            validate(self.root, self.manifest, self.output)
        build(self.root, self.manifest, self.output)
        self.assertIn("Stale: 0", validate(self.root, self.manifest, self.output))
        (self.root / "pilot.py").unlink()
        with self.assertRaises((IndexErrorClosed, FileNotFoundError)):
            build(self.root, self.manifest, self.output)
        self.write("pilot.py", "def current():\n    return 2\n")
        for name in CORE_NAMES + ("build.json", "report.txt"):
            (self.output / name).unlink()
        build(self.root, self.manifest, self.output)
        validate(self.root, self.manifest, self.output)

    def test_finding_side_cannot_admit_an_unlisted_source(self):
        path = self.root / "kermit_index/finding_sides.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        spec["findings"]["F-01"]["sideA"]["refs"] = [
            {"path": "data/private.sqlite", "start": 1, "end": 1, "anchor": "secret"}]
        path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(IndexErrorClosed, "not admitted"):
            build_data(self.root, self.manifest)

    def test_denied_paths_and_fake_secret_absence(self):
        denied = ("../escape.py", "C:/outside.py", ".env", ".env.local", "secrets/token.py", "credentials/key.py", "api-key.py", "data/personal.sqlite", "db.sqlite-wal", "db.sqlite-shm", "old.bak", "server.log", ".tmp-test.py", "node_modules/pkg/index.js", "dist/bundle.js", "reports/scan.md", "data/raw/input.py", "ChatGPT-history/archive.md", "private_config.py")
        for path in denied:
            with self.subTest(path=path):
                with self.assertRaises((IndexErrorClosed, OSError)):
                    safe_path(self.root, path, "source", 10000)
        self.write("oversized.py", "x" * 101)
        with self.assertRaises(IndexErrorClosed):
            safe_path(self.root, "oversized.py", "source", 100)
        self.write("binary.py", "ok").write_bytes(b"\x00" + FAKE_SECRET.encode())
        self.spec["entries"].append({"path": "binary.py", "group": "source", "subsystem": "quote"})
        self.save_manifest()
        with self.assertRaises(IndexErrorClosed):
            build(self.root, self.manifest, self.output)
        self.spec["entries"].pop()
        self.save_manifest()
        for path in (".env", "data/personal.sqlite", "server.log", "secrets/token.py", "db.sqlite-wal"):
            self.write(path, FAKE_SECRET)
            self.spec["entries"].append({"path": path, "group": "source", "subsystem": "quote"})
            self.save_manifest()
            with self.assertRaises(IndexErrorClosed):
                build(self.root, self.manifest, self.output)
            self.spec["entries"].pop()
            self.save_manifest()
        build(self.root, self.manifest, self.output)
        for artifact in CORE_NAMES + ("build.json", "report.txt"):
            self.assertNotIn(FAKE_SECRET, (self.output / artifact).read_text(encoding="utf-8"))
        self.write("unlisted.py", FAKE_SECRET)
        build(self.root, self.manifest, self.output)
        self.assertNotIn(FAKE_SECRET, "".join((self.output / artifact).read_text(encoding="utf-8") for artifact in CORE_NAMES))

    def test_symlink_escape_and_output_boundary(self):
        outside = Path(self.temp.name).parent / (self.root.name + "-outside.py")
        outside.write_text(FAKE_SECRET, encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        link = self.root / "linked.py"
        try:
            link.symlink_to(outside)
        except OSError:
            pass  # Windows user accounts without symlink privilege cannot create this fixture.
        else:
            with self.assertRaises(IndexErrorClosed):
                safe_path(self.root, "linked.py", "source", 10000)
        with self.assertRaises(IndexErrorClosed):
            build(self.root, self.manifest, self.root / "outside-output")

    def test_artifact_identity_survives_description_edit(self):
        path = "docs/kermit/knowledge/subsystems/quote.md"
        original = (self.root / path).read_text(encoding="utf-8")
        table = "\n## Persistence and source of truth\n| Artifact/entity | Owner | Role |\n| --- | --- | --- |\n| Quote preference | QuoteStore | **browser-only** setting |\n"
        self.write(path, original + table)
        first = {e["id"] for e in build_data(self.root, self.manifest)["entities.jsonl"] if e["type"] == "data_artifact"}
        self.write(path, original + table.replace("setting", "visual setting"))
        second = {e["id"] for e in build_data(self.root, self.manifest)["entities.jsonl"] if e["type"] == "data_artifact"}
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

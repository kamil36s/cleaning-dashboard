import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from language_learning.reference_core import (
    REFERENCE_SCHEMA_VERSION,
    ReferenceResolver,
    ReferenceStore,
    ResolverStatus,
    VocabularyLemmaIdentity,
    resolve_reference_paths,
)
from language_learning.reference_core.fixture_importer import import_fixture
from language_learning.reference_core.schema import MIGRATIONS


FIXTURE = Path(__file__).parent / "fixtures" / "language" / "reference" / "reference_v1.json"
MANIFESTS = Path(__file__).parents[1] / "language_learning" / "reference_core" / "manifests"


class LanguageReferenceCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "reference.sqlite"
        self.store = ReferenceStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def import_fixture(self):
        return import_fixture(self.store, FIXTURE)

    def test_fresh_schema_and_repeat_initialization(self):
        self.store.initialize()
        self.store.initialize()
        with sqlite3.connect(self.path) as connection:
            ledger = connection.execute(
                "SELECT version,checksum FROM reference_schema_migrations ORDER BY version"
            ).fetchall()
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
        self.assertEqual(ledger, [(item.version, item.checksum) for item in MIGRATIONS])
        self.assertEqual(REFERENCE_SCHEMA_VERSION, 3)
        self.assertIn("reference_lexical_units", tables)
        self.assertIn("reference_frequency_observations", tables)
        self.assertIn("reference_sentences", tables)
        self.assertIn("reference_sentence_occurrences", tables)
        self.assertIn("reference_sentence_translations", tables)
        self.assertNotIn("vocabulary_lemmas", tables)

    def test_fixture_import_provenance_identity_forms_and_evidence(self):
        result = self.import_fixture()
        self.assertEqual(result["lexicalUnits"], 7)
        sources = self.store.table_rows("reference_sources")
        runs = self.store.table_rows("reference_import_runs")
        units = self.store.table_rows("reference_lexical_units")
        forms = self.store.table_rows("reference_forms")
        links = self.store.table_rows("reference_form_links")
        frequency = self.store.table_rows("reference_frequency_observations")
        cefr = self.store.table_rows("reference_cefr_evidence")
        components = self.store.table_rows("reference_mwe_components")
        associations = self.store.table_rows("reference_association_evidence")
        self.assertEqual(len(sources), 5)
        self.assertTrue(all(row["status"] == "COMPLETED" for row in runs))
        self.assertEqual(len({row["stable_key"] for row in units}), len(units))
        self.assertGreaterEqual(len(forms), 4)
        self.assertGreaterEqual(len(links), 5)
        self.assertEqual(len(frequency), 3)
        self.assertEqual({row["source_id"] for row in frequency if row["rank"]}, {"fixture-newspaper"})
        self.assertEqual({row["evidence_type"] for row in cefr}, {"LEARNER_CORPUS_DISTRIBUTION", "ESTIMATED"})
        self.assertEqual(len(components), 8)
        self.assertEqual(associations[0]["metric_name"], "LOGDICE")
        self.assertTrue(all(row["source_id"] for row in frequency + cefr + associations))

    def test_resolver_matched_ambiguous_and_unmatched(self):
        self.import_fixture()
        resolver = ReferenceResolver(self.store)
        matched = resolver.resolve(VocabularyLemmaIdentity("nb", "arbeidsgiver", "NOUN"))
        ambiguous = resolver.resolve(VocabularyLemmaIdentity("nb", "så", None))
        unmatched = resolver.resolve(VocabularyLemmaIdentity("nb", "xylophonisk", "ADJ"))
        wrong_pos = resolver.resolve(VocabularyLemmaIdentity("nb", "arbeidsgiver", "VERB"))
        self.assertEqual(matched.status, ResolverStatus.MATCHED)
        self.assertEqual(ambiguous.status, ResolverStatus.AMBIGUOUS)
        self.assertEqual(len(ambiguous.candidates), 2)
        self.assertEqual(unmatched.status, ResolverStatus.UNMATCHED)
        self.assertEqual(wrong_pos.status, ResolverStatus.UNMATCHED)
        self.assertEqual(len(wrong_pos.candidates), 1)

    def test_configurable_path_and_no_user_database_mutation(self):
        main_db = Path(self.temp.name) / "language-learning.sqlite"
        configured = Path(self.temp.name) / "elsewhere" / "reference.db"
        source_dir = Path(self.temp.name) / "corpora"
        paths = resolve_reference_paths(
            environment={"LANGUAGE_REFERENCE_DB": str(configured), "LANGUAGE_REFERENCE_SOURCE_DIR": str(source_dir)},
            project_root=Path(self.temp.name) / "project",
        )
        self.assertEqual(paths.database, configured)
        self.assertEqual(paths.source_directory, source_dir)
        import_fixture(ReferenceStore(paths.database), FIXTURE)
        self.assertTrue(configured.exists())
        self.assertFalse(main_db.exists())

    def test_accepted_manifests_follow_versioned_format(self):
        schema = json.loads((MANIFESTS / "manifest.schema.json").read_text(encoding="utf-8"))
        required = set(schema["required"])
        manifests = [path for path in MANIFESTS.glob("*.json") if path.name != "manifest.schema.json"]
        self.assertGreaterEqual(len(manifests), 5)
        for path in manifests:
            item = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(item["manifestVersion"], "language-reference-source-manifest/v1")
            self.assertFalse(required - set(item), path.name)
            self.assertIn(item["decision"], {"ACCEPT_PHASE_7_5B", "ACCEPT_PHASE_9A", "DEFER", "REJECT", "NEEDS_VERIFICATION"})
            self.assertIsInstance(item["expectedFiles"], list)
            self.assertTrue(item["parser"]["id"])


if __name__ == "__main__":
    unittest.main()

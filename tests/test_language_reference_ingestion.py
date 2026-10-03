import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

from language_learning.reference_core.artifacts import VerifiedArtifact, acquire_artifact
from language_learning.reference_core.build import (
    canonical_fingerprint,
    validate_reference_database,
)
from language_learning.reference_core.manifest import ArtifactManifest, SourceManifest
from language_learning.reference_core.production_importer import (
    CLARINO_ID,
    IDIOM_ID,
    KELLY_ID,
    ORDBANK_ID,
    ProductionImporter,
    UNIGRAM_ID,
)
from language_learning.reference_core.store import ReferenceStore


FIXTURES = Path(__file__).parent / "fixtures" / "language" / "reference" / "production"


SOURCE_META = {
    ORDBANK_ID: ("Ordbank fixture", "LEXICON_MORPHOLOGY", "CC-BY-4.0", "norsk-ordbank-nob"),
    KELLY_ID: ("KELLY fixture", "LEARNER_ORIENTED_RANKED_LEMMA_LIST", "CC-BY-SA-4.0", "norwegian-kelly-json"),
    CLARINO_ID: ("CLARINO fixture", "RANKED_SURFACE_FREQUENCY", "CC-BY-3.0", "clarino-newspaper-surface-frequency"),
    IDIOM_ID: ("Idiom fixture", "IDIOMS_AND_PHRASES", "CC0-1.0", "nb-norwegian-idioms"),
    UNIGRAM_ID: ("Unigram fixture", "NGRAM_1_TO_6", "CC0-1.0", "nb-bokmal-ngram"),
}


def _sha(path):
    raw = Path(path).read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _add_tar_member(archive, name, text):
    raw = text.encode("latin-1")
    info = tarfile.TarInfo(name)
    info.size = len(raw)
    archive.addfile(info, io.BytesIO(raw))


def make_artifacts(root):
    root = Path(root)
    ordbank = root / "ordbank.tar.gz"
    with tarfile.open(ordbank, "w:gz") as archive:
        _add_tar_member(archive, "lemma.txt", (FIXTURES / "ordbank-lemma.tsv").read_text(encoding="utf-8"))
        _add_tar_member(archive, "fullformsliste.txt", (FIXTURES / "ordbank-fullforms.tsv").read_text(encoding="utf-8"))
        _add_tar_member(archive, "leddanalyse.txt", (FIXTURES / "ordbank-compounds.tsv").read_text(encoding="utf-8"))

    kelly = root / "kelly.json"
    shutil.copyfile(FIXTURES / "kelly.json", kelly)
    clarino = root / "clarino.tsv"
    shutil.copyfile(FIXTURES / "clarino.tsv", clarino)

    idioms = root / "idioms.zip"
    with zipfile.ZipFile(idioms, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(FIXTURES / "idiom-nob.json", "Norwegian_idioms/idiom_freqs/nob_idioms_freq.json")
        archive.write(FIXTURES / "idiom-nno.json", "Norwegian_idioms/idiom_freqs/nno_idioms_freq.json")
        archive.write(FIXTURES / "idiom-both.json", "Norwegian_idioms/idiom_freqs/both_freqs.json")
        archive.write(FIXTURES / "idiom-data.jsonl", "Norwegian_idioms/data.jsonl")

    unigram = root / "unigram.zip"
    with zipfile.ZipFile(unigram, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "1gram_nob_f1_freq.frk",
            (FIXTURES / "unigram.frk").read_text(encoding="utf-8").encode("latin-1"),
        )
    return {
        ORDBANK_ID: ordbank,
        KELLY_ID: kelly,
        CLARINO_ID: clarino,
        IDIOM_ID: idioms,
        UNIGRAM_ID: unigram,
    }


def make_manifests(paths, *, parser_suffix="1.0.0"):
    manifests = []
    artifacts = {}
    for source_id, path in paths.items():
        title, resource_type, license_id, parser_id = SOURCE_META[source_id]
        size, checksum = _sha(path)
        artifact = ArtifactManifest(
            name=path.name,
            url=f"https://example.invalid/{path.name}",
            size_bytes=size,
            sha256=checksum,
            format="tiny fixture",
            required=True,
            retrieved_at="2026-09-16T00:00:00Z",
            http_metadata={"fixture": "true"},
        )
        payload = {
            "sourceId": source_id,
            "title": title,
            "provider": "Fixture provider",
            "resourceType": resource_type,
            "language": "nb+nn" if source_id == IDIOM_ID else "nb",
            "version": "fixture-v1",
            "releaseDate": None,
            "landingUrl": "https://example.invalid/source",
            "license": {"id": license_id, "url": "https://example.invalid/license"},
            "attribution": "Fixture attribution",
            "notes": [],
            "parser": {"id": parser_id, "version": parser_suffix},
            "priority": "TIER_2" if source_id == UNIGRAM_ID else "TIER_1",
        }
        manifests.append(SourceManifest(path=path, payload=payload, artifacts=(artifact,)))
        artifacts[source_id] = (
            VerifiedArtifact(
                source_id=source_id,
                manifest=artifact,
                path=path,
                size_bytes=size,
                sha256=checksum,
                retrieved_at="2026-09-16T00:00:00Z",
                http_metadata={"fixture": "true"},
            ),
        )
    return tuple(manifests), artifacts


class LanguageReferenceProductionIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = make_artifacts(self.root)
        self.manifests, self.artifacts = make_manifests(self.paths)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, name):
        database = self.root / name
        ReferenceStore(database).initialize()
        with sqlite3.connect(database) as connection, mock.patch.multiple(
            "language_learning.reference_core.production_importer",
            ORDBANK_EXPECTED_LEMMAS=5,
            ORDBANK_EXPECTED_FORMS=7,
            CLARINO_EXPECTED_ROWS=4,
            IDIOM_EXPECTED_FREQUENCY={"nob": 2, "nno": 1, "both": 1},
            IDIOM_EXPECTED_PROMPTS=3,
            IDIOM_EXPECTED_MULTI_COMPLETION=1,
        ):
            connection.execute("PRAGMA foreign_keys=ON")
            importer = ProductionImporter(connection, self.manifests, self.artifacts)
            importer.register_sources()
            quality = importer.import_all()
        return database, quality

    def test_tiny_tier_1_and_2_import_preserves_raw_mapping_and_empty_cefr(self):
        database, quality = self.build("reference.sqlite")
        validation = validate_reference_database(database, expected_sources=5)
        self.assertEqual(validation["integrityCheck"], ["ok"])
        self.assertEqual(validation["foreignKeyViolations"], [])
        self.assertEqual(validation["cefrRows"], 0)
        self.assertEqual(validation["domainRows"], 0)
        self.assertEqual(validation["associationRows"], 0)
        self.assertEqual(quality[ORDBANK_ID]["lexicalUnitsCreated"], 5)
        self.assertEqual(quality[ORDBANK_ID]["formRowsAccepted"], 6)
        self.assertEqual(quality[ORDBANK_ID]["orphanFormRows"], 1)
        self.assertEqual(quality[ORDBANK_ID]["homographSpellings"], 1)
        self.assertEqual(quality[ORDBANK_ID]["multiwordLemmas"], 1)
        self.assertEqual(quality[KELLY_ID]["mapping"]["MATCHED"], 2)
        self.assertEqual(quality[KELLY_ID]["mapping"]["AMBIGUOUS"], 1)
        self.assertEqual(quality[KELLY_ID]["mapping"]["UNMATCHED"], 1)
        self.assertEqual(quality[CLARINO_ID]["mapping"]["EXCLUDED_NONLEXICAL"], 1)
        self.assertEqual(quality[CLARINO_ID]["derived"]["lemmaCount"], 1)
        self.assertEqual(quality[IDIOM_ID]["nynorskOnlyImportedAsBokmal"], 0)
        self.assertEqual(quality[IDIOM_ID]["completionVariants"], 3)
        self.assertEqual(quality[UNIGRAM_ID]["mapping"]["MATCHED"], 1)
        self.assertEqual(quality[UNIGRAM_ID]["mapping"]["AMBIGUOUS"], 1)
        self.assertEqual(quality[UNIGRAM_ID]["mapping"]["UNMATCHED"], 1)
        with sqlite3.connect(database) as connection:
            unknown_pos = connection.execute(
                "SELECT part_of_speech FROM reference_lexical_units WHERE canonical_form='på grunn av'"
            ).fetchone()[0]
            raw_tags = connection.execute(
                "SELECT morphology_json FROM reference_form_links WHERE source_local_id='2'"
            ).fetchone()[0]
            cefr = connection.execute("SELECT COUNT(*) FROM reference_cefr_evidence").fetchone()[0]
        self.assertIsNone(unknown_pos)
        self.assertIn("subst normert", raw_tags)
        self.assertEqual(cefr, 0)

    def test_identical_fixture_rebuild_has_identical_canonical_fingerprint(self):
        first, _quality = self.build("first.sqlite")
        second, _quality = self.build("second.sqlite")
        self.assertEqual(canonical_fingerprint(first), canonical_fingerprint(second))

    def test_existing_artifact_checksum_change_is_rejected(self):
        path = self.root / "changed.bin"
        path.write_bytes(b"changed")
        artifact = ArtifactManifest(
            name=path.name,
            url="https://example.invalid/changed.bin",
            size_bytes=len(b"changed"),
            sha256="0" * 64,
            format="fixture",
            required=True,
            retrieved_at=None,
            http_metadata={},
        )
        with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
            acquire_artifact("fixture", artifact, path)

    def test_parser_version_is_visible_in_import_provenance(self):
        manifests, artifacts = make_manifests(self.paths, parser_suffix="9.9.9-test")
        database = self.root / "parser.sqlite"
        ReferenceStore(database).initialize()
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            importer = ProductionImporter(connection, manifests, artifacts)
            importer.register_sources()
            run_id = importer._start_run(KELLY_ID)
            row = connection.execute(
                "SELECT importer_version,source_checksum FROM reference_import_runs WHERE id=?", (run_id,)
            ).fetchone()
        self.assertEqual(row[0], "9.9.9-test")
        self.assertTrue(row[1].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()

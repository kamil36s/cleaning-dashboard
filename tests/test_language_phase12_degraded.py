"""Local study remains readable when optional Language dependencies fail."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from language_learning.cloze import ClozeService
from language_learning.grammar_parser import GrammarParser
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for


AUDIO = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40


class LanguageDegradedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = LanguageStore(root / "language-learning.sqlite")
        self.service = LanguageService(
            self.store, analyzer_registry=registry_for(FakeAnalyzer()),
            frequency_provider=FakeFrequencyProvider(),
            grammar_parser=GrammarParser(model_dir=root / "missing-grammar-models"),
        )
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]["id"]
        self.text = self.service.create_text_draft({
            "languageProfileId": self.profile, "title": "Local Reader", "rawText": "Jeg har en jobb."
        })["data"]["text"]["id"]
        self.lemma = self.service.upsert_lemma(self.profile, "jobb", part_of_speech="NOUN")["lemma"]["id"]

    def test_grammar_reference_and_anki_unavailable_leave_local_reads(self):
        missing = Path(self.temp.name) / "missing-reference.sqlite"
        cloze = ClozeService(self.service, missing)
        self.service.attach_cloze_service(cloze)
        self.assertEqual(self.service.grammar_summary(self.profile)["data"]["parser"]["state"],
                         "UNAVAILABLE")
        self.assertEqual(self.service.cloze_tracks(self.profile)["data"]["fastTrackStatus"],
                         "UNAVAILABLE")
        self.assertEqual(self.service.get_text(self.text)["data"]["document"]["id"], self.text)
        self.assertEqual(self.service.get_lemma(self.lemma)["data"]["lemma"]["id"], self.lemma)
        self.assertEqual(self.service.anki_sync_service.status(self.profile, probe=False)["status"],
                         "NOT_CONFIGURED")
        self.assertIn("segments", self.service.study_session(self.profile, 10)["data"])

    def test_one_missing_media_file_does_not_block_other_content(self):
        first = self.service.import_content_audio(self.profile, data=AUDIO, title="One",
            original_name="one.wav", mime_type="audio/wav")["data"]
        second = self.service.create_content(self.profile, {
            "sourceType": "NRK_REFERENCE", "title": "Other",
            "sourceUri": "https://radio.nrk.no/podkast/test",
        })["data"]
        artifact = first["media"]["id"]
        self.service.content_media_file(artifact)[0].unlink()
        with self.assertRaises(Exception) as missing:
            self.service.content_media_file(artifact)
        self.assertEqual(getattr(missing.exception, "code", None), "managed_media_not_found")
        self.assertEqual(self.service.content_detail(second["item"]["id"])["data"]["item"]["title"],
                         "Other")
        self.assertEqual(self.service.get_text(self.text)["data"]["document"]["id"], self.text)

    def test_wrong_version_and_corrupt_reference_do_not_disable_local_study(self):
        future = Path(self.temp.name) / "future-reference.sqlite"
        with sqlite3.connect(future) as connection:
            connection.execute("CREATE TABLE reference_schema_migrations(version INTEGER)")
            connection.execute("INSERT INTO reference_schema_migrations VALUES(99)")
            connection.execute("CREATE TABLE reference_sentences(id TEXT)")
        corrupt = Path(self.temp.name) / "corrupt-reference.sqlite"
        corrupt.write_bytes(b"not a SQLite database")
        for path, expected in ((future, "UNSUPPORTED_SCHEMA"), (corrupt, "UNAVAILABLE")):
            with self.subTest(path=path.name):
                cloze = ClozeService(self.service, path)
                self.assertEqual(cloze.reference.health()["status"], expected)
                self.service.attach_cloze_service(cloze)
                self.assertEqual(self.service.get_lemma(self.lemma)["data"]["lemma"]["id"], self.lemma)
                self.assertEqual(self.service.get_text(self.text)["data"]["document"]["id"], self.text)


if __name__ == "__main__":
    unittest.main()

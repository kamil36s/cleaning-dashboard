import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from language_learning.reference_core import ReferenceStore, VocabularyLemmaIdentity
from language_learning.reference_core.fixture_importer import import_fixture
from language_learning.reference_core.service import (
    EXPRESSION_DETECTOR_VERSION,
    REFERENCE_PROFILE_VERSION,
    ReferenceLexiconService,
)


FIXTURE = Path(__file__).parent / "fixtures" / "language" / "reference" / "reference_v1.json"


def token(surface, order, start, *, sentence="s1", lemma=None, pos=None, kind="WORD", ambiguity="NOT_REPORTED"):
    return {
        "id": f"token-{sentence}-{order}",
        "sentenceId": sentence,
        "tokenOrder": order,
        "surface": surface,
        "normalizedLookup": surface.casefold() if kind == "WORD" else None,
        "selectedLemmaNormalized": (lemma or surface).casefold() if kind == "WORD" else None,
        "selectedLemmaPos": pos,
        "partOfSpeech": pos,
        "sourceStart": start,
        "sourceEnd": start + len(surface),
        "tokenKind": kind,
        "ambiguityState": ambiguity,
    }


class ReferenceLexiconServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "reference.sqlite"
        self.store = ReferenceStore(self.path)
        import_fixture(self.store, FIXTURE)
        self.service = ReferenceLexiconService(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_safe_health_is_read_only_bounded_and_path_free(self):
        before = self.path.stat().st_mtime_ns
        health = self.service.health()
        after = self.path.stat().st_mtime_ns
        self.assertTrue(health["configured"])
        self.assertTrue(health["available"])
        self.assertEqual(health["schemaVersion"], 3)
        self.assertEqual(health["lexicalUnitsAvailable"], 7)
        self.assertTrue(health["frequencyAvailable"])
        self.assertTrue(health["idiomsAvailable"])
        self.assertFalse(health["sentenceBankAvailable"])
        self.assertEqual(before, after)
        serialized = json.dumps(health)
        self.assertNotIn(str(self.path), serialized)
        self.assertNotIn(self.temp.name, serialized)
        with self.assertRaises(RuntimeError):
            self.service.store.initialize()

    def test_missing_database_degrades_without_creating_it(self):
        missing = Path(self.temp.name) / "missing" / "reference.sqlite"
        health = ReferenceLexiconService(missing).health()
        self.assertFalse(health["available"])
        self.assertEqual(health["reason"], "REFERENCE_DATABASE_MISSING")
        self.assertFalse(missing.exists())

    def test_batch_resolver_keeps_exact_v1_semantics(self):
        results = self.service.resolve_user_lemmas([
            VocabularyLemmaIdentity("nb", "arbeidsgiver", "NOUN", "one"),
            VocabularyLemmaIdentity("nb", "så", None, "two"),
            VocabularyLemmaIdentity("nb", "arbeidsgiver", "VERB", "three"),
            VocabularyLemmaIdentity("nb", "arbeidsgiverr", "NOUN", "four"),
        ])
        self.assertEqual([item["status"] for item in results], ["MATCHED", "AMBIGUOUS", "UNMATCHED", "UNMATCHED"])
        self.assertEqual(results[0]["ruleVersion"], "reference-resolver/v1")
        self.assertEqual(results[0]["candidates"][0]["matchBasis"], "LANGUAGE_LEMMA_POS")
        self.assertEqual(len(results[1]["candidates"]), 2)
        self.assertEqual(len(results[2]["candidates"]), 1)
        self.assertEqual(results[3]["candidates"], [])

    def test_reference_profile_separates_source_metrics_and_provenance(self):
        payload = self.service.get_reference_profile(
            VocabularyLemmaIdentity("nb", "arbeidsgiver", "NOUN", "user-lemma")
        )
        self.assertEqual(payload["resolution"]["status"], "MATCHED")
        reference = payload["reference"]
        self.assertEqual(reference["unit"]["canonicalForm"], "arbeidsgiver")
        evidence = reference["frequencyEvidence"]
        source_form = next(item for item in evidence if item["metricType"] == "SOURCE_FORM_RANK")
        self.assertEqual(source_form["label"], "Source form rank")
        self.assertEqual(source_form["scope"], "SOURCE_SURFACE_FORM")
        self.assertEqual(source_form["rank"], 4832)
        self.assertTrue(reference["forms"])
        self.assertTrue(all(item["sourceId"] for item in evidence))
        self.assertTrue(all("database" not in key.casefold() for key in reference))

    def test_expression_detector_exact_spans_longest_overlap_case_inflection_and_punctuation(self):
        longer = self.store.upsert_lexical_unit(
            language_code="nb", unit_type="PHRASE", canonical_form="ta hensyn til",
            identity_qualifier="fixture-longer",
        )
        self.store.link_source(longer.id, source_id="fixture-ordbank", source_local_id="mwe-longer")
        self.store.add_mwe_components(longer.id, [
            {"text": "ta", "lemmaConstraint": "ta", "posConstraint": "VERB"},
            {"text": "hensyn", "lemmaConstraint": "hensyn", "posConstraint": "NOUN"},
            {"text": "til"},
        ])
        duplicate = self.store.upsert_lexical_unit(
            language_code="nb", unit_type="IDIOM", canonical_form="ugler i mosen",
            identity_qualifier="fixture-duplicate",
        )
        self.store.link_source(duplicate.id, source_id="fixture-ordbank", source_local_id="idiom-duplicate")
        self.store.add_mwe_components(duplicate.id, [
            {"text": "ugler", "lemmaConstraint": "ugle", "posConstraint": "NOUN"},
            {"text": "i"},
            {"text": "mosen", "lemmaConstraint": "mose", "posConstraint": "NOUN"},
        ])

        raw = "PÅ grunn av. ta hensyn til. ugler i mosen. på, grunn av."
        specs = [
            ("PÅ", "på", None, "WORD"), ("grunn", "grunn", "NOUN", "WORD"),
            ("av", "av", None, "WORD"), (".", None, None, "PUNCTUATION"),
            ("ta", "ta", "VERB", "WORD"), ("hensyn", "hensyn", "NOUN", "WORD"),
            ("til", "til", None, "WORD"), (".", None, None, "PUNCTUATION"),
            ("ugler", "ugle", "NOUN", "WORD"), ("i", "i", None, "WORD"),
            ("mosen", "mose", "NOUN", "WORD"), (".", None, None, "PUNCTUATION"),
            ("på", "på", None, "WORD"), (",", None, None, "PUNCTUATION"),
            ("grunn", "grunn", "NOUN", "WORD"), ("av", "av", None, "WORD"),
            (".", None, None, "PUNCTUATION"),
        ]
        tokens = []
        cursor = 0
        for order, (surface, lemma, pos, kind) in enumerate(specs):
            start = raw.index(surface, cursor)
            cursor = start + len(surface)
            tokens.append(token(surface, order, start, lemma=lemma, pos=pos, kind=kind))
        occurrences = self.service.detect_expressions(
            raw_text=raw, sentences=[{"id": "s1"}], tokens=tokens
        )
        forms = [item["canonicalForm"] for item in occurrences]
        self.assertIn("på grunn av", forms)
        self.assertIn("ta hensyn", forms)
        self.assertIn("ta hensyn til", forms)
        idioms = [item for item in occurrences if item["canonicalForm"] == "ugler i mosen"]
        self.assertEqual(len(idioms), 2)
        self.assertTrue(all(item["ambiguous"] for item in idioms))
        longer_match = next(item for item in occurrences if item["canonicalForm"] == "ta hensyn til")
        nested = next(item for item in occurrences if item["canonicalForm"] == "ta hensyn")
        self.assertEqual(longer_match["selectionState"], "LONGEST_PREFERRED")
        self.assertEqual(nested["selectionState"], "OVERLAP_RETAINED")
        self.assertEqual(longer_match["surfaceText"], "ta hensyn til")
        self.assertEqual(longer_match["detectorVersion"], EXPRESSION_DETECTOR_VERSION)
        self.assertIn("LEMMA_CONSTRAINT", idioms[0]["matchBasis"])
        self.assertEqual(sum(item["canonicalForm"] == "på grunn av" for item in occurrences), 1)
        self.assertTrue(all(item["sourceProvenance"] for item in occurrences))

        multi_raw = "På grunn av. På grunn av."
        multi_tokens = [
            token("På", 0, 0, sentence="multi-1", lemma="på"),
            token("grunn", 1, 3, sentence="multi-1", lemma="grunn", pos="NOUN"),
            token("av", 2, 9, sentence="multi-1", lemma="av"),
            token("På", 0, 13, sentence="multi-2", lemma="på"),
            token("grunn", 1, 16, sentence="multi-2", lemma="grunn", pos="NOUN"),
            token("av", 2, 22, sentence="multi-2", lemma="av"),
        ]
        multi_occurrences = self.service.detect_expressions(
            raw_text=multi_raw,
            sentences=[{"id": "multi-1"}, {"id": "multi-2"}],
            tokens=multi_tokens,
        )
        self.assertEqual(
            [item["sentenceId"] for item in multi_occurrences if item["canonicalForm"] == "på grunn av"],
            ["multi-1", "multi-2"],
        )

    def test_text_profile_is_independent_from_user_coverage(self):
        raw = "ugler i mosen"
        tokens = [
            token("ugler", 0, 0, lemma="ugle", pos="NOUN"),
            token("i", 1, 6, lemma="i"),
            token("mosen", 2, 8, lemma="mose", pos="NOUN"),
        ]
        profile = self.service.text_reference_profile(
            language_code="nb", raw_text=raw, sentences=[{"id": "s1"}], tokens=tokens
        )
        self.assertEqual(profile["profileVersion"], REFERENCE_PROFILE_VERSION)
        self.assertEqual(profile["mweOccurrences"], 1)
        self.assertNotIn("coveredTokens", profile)
        self.assertEqual(profile["frequencyProfile"]["label"], "Reference learner-rank and source-frequency profile (not user coverage)")


if __name__ == "__main__":
    unittest.main()

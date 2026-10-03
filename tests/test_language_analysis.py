from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from language_learning.analysis.base import normalize_lookup
from language_learning.analysis.norwegian_bokmal import (
    NorwegianBokmalStanzaAnalyzer,
    classify_token,
)
from language_learning.reference import (
    DictionarySenseResult,
    FrequencyResult,
    LexicalReferenceResult,
    ReferenceSource,
)
from language_learning.schemas import (
    AmbiguityState,
    AnalysisDocument,
    AnalyzedSentence,
    AnalyzedToken,
    AnalyzerHealthState,
    AnalyzerProvenance,
    CoverageReportContract,
    ErrorEnvelopeContract,
    KnowledgeCommandContract,
    LemmaCandidate,
    LemmaFormMappingContract,
    LexicalStatus,
    ResolutionState,
    SchemaValidationError,
    TokenKind,
    text_fingerprint,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FIXTURE = ROOT / "tests" / "fixtures" / "language" / "contracts" / "phase0_contracts_v1.json"
BOKMAL_FIXTURE = ROOT / "tests" / "fixtures" / "language" / "nb" / "phase0_bokmal_cases.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tokens(document: AnalysisDocument) -> list[AnalyzedToken]:
    return [token for sentence in document.sentences for token in sentence.tokens]


def _expected_token(document: AnalysisDocument, expected: dict) -> AnalyzedToken:
    matches = [token for token in _tokens(document) if token.surface == expected["surface"]]
    occurrence = int(expected.get("occurrence", 1))
    if len(matches) < occurrence:
        raise AssertionError(
            f"missing occurrence {occurrence} of {expected['surface']!r}; "
            f"available: {[item.surface for item in _tokens(document)]}"
        )
    return matches[occurrence - 1]


class AnalysisContractTests(unittest.TestCase):
    def test_committed_json_contract_round_trips_and_validates(self) -> None:
        payload = _load_json(CONTRACT_FIXTURE)["analysisDocument"]
        document = AnalysisDocument.from_dict(payload)
        self.assertEqual(payload, document.to_dict())
        self.assertEqual("jobb.", document.original_text)
        self.assertEqual("UNICODE_CODE_POINT", document.offset_unit)
        self.assertEqual("jobb", document.sentences[0].tokens[0].selected_lemma)

    def test_source_span_mismatch_is_rejected(self) -> None:
        payload = _load_json(CONTRACT_FIXTURE)["analysisDocument"]
        payload["sentences"][0]["tokens"][0]["surface"] = "Jobb"
        with self.assertRaisesRegex(SchemaValidationError, "does not match source span"):
            AnalysisDocument.from_dict(payload)

    def test_fingerprint_mismatch_is_rejected(self) -> None:
        payload = _load_json(CONTRACT_FIXTURE)["analysisDocument"]
        payload["originalTextFingerprint"] = "sha256:wrong"
        with self.assertRaisesRegex(SchemaValidationError, "fingerprint"):
            AnalysisDocument.from_dict(payload)

    def test_ambiguity_and_unknown_are_first_class_states(self) -> None:
        provenance = AnalyzerProvenance(
            analyzer_id="fixture",
            implementation_version="1",
            package_name="fixture",
            package_version="1",
            model_package="fixture",
            model_version="1",
            processors=("lemma",),
        )
        candidates = tuple(
            LemmaCandidate(
                lemma=lemma,
                normalized_lemma=lemma,
                pos=pos,
                source_id="fixture",
                source_version="1",
            )
            for lemma, pos in (("se", "VERB"), ("så", "ADV"))
        )
        ambiguous = AnalyzedToken(
            surface="så",
            start=0,
            end=2,
            kind=TokenKind.WORD,
            normalized_lookup="så",
            lemma_candidates=candidates,
            selected_lemma=None,
            pos=None,
            morphology={},
            resolution_state=ResolutionState.AMBIGUOUS,
            ambiguity_state=AmbiguityState.AMBIGUOUS,
            lexical_status=LexicalStatus.NOT_ASSESSED,
            confidence=None,
            confidence_basis="not_selected",
            provenance="fixture",
        )
        unknown = AnalyzedToken(
            surface="glorp",
            start=3,
            end=8,
            kind=TokenKind.WORD,
            normalized_lookup="glorp",
            lemma_candidates=(),
            selected_lemma=None,
            pos=None,
            morphology={},
            resolution_state=ResolutionState.UNRESOLVED,
            ambiguity_state=AmbiguityState.NOT_REPORTED,
            lexical_status=LexicalStatus.UNKNOWN,
            confidence=None,
            confidence_basis="lexicon_miss",
            provenance="fixture",
        )
        document = AnalysisDocument(
            language_code="nb",
            original_text="så glorp",
            original_text_fingerprint=text_fingerprint("så glorp"),
            analyzer=provenance,
            sentences=(AnalyzedSentence(0, 8, "så glorp", (ambiguous, unknown)),),
        )
        document.validate()
        self.assertIsNone(ambiguous.selected_lemma)
        self.assertEqual(LexicalStatus.UNKNOWN, unknown.lexical_status)

    def test_lookup_normalization_preserves_norwegian_letters(self) -> None:
        self.assertEqual("ærlig øl på", normalize_lookup("ÆRLIG ØL PÅ"))
        self.assertEqual("o'neill-blå", normalize_lookup("O’NEILL‑BLÅ"))

    def test_nonlexical_classification(self) -> None:
        cases = {
            ".": TokenKind.PUNCTUATION,
            "15.09.2026": TokenKind.NUMBER,
            "https://example.no/øl": TokenKind.URL,
            "😊": TokenKind.EMOJI,
            "+": TokenKind.SYMBOL,
            "blå-grønn": TokenKind.WORD,
        }
        for surface, expected in cases.items():
            with self.subTest(surface=surface):
                self.assertEqual(expected, classify_token(surface))

    def test_other_phase_zero_contracts_are_versioned_and_validate(self) -> None:
        payload = _load_json(CONTRACT_FIXTURE)
        mapping = LemmaFormMappingContract.from_dict(payload["lemmaFormMapping"])
        coverage = CoverageReportContract.from_dict(payload["coverageReport"])
        command = KnowledgeCommandContract.from_dict(payload["knowledgeCommand"])
        error = ErrorEnvelopeContract.from_dict(payload["errorEnvelope"])
        self.assertTrue(mapping.contract_version.endswith("/v1"))
        self.assertEqual(10, coverage.eligible_tokens)
        self.assertTrue(command.command_version.endswith("/v1"))
        self.assertFalse(error.ok)
        self.assertEqual(payload["lemmaFormMapping"], mapping.to_dict())
        self.assertEqual(payload["coverageReport"], coverage.to_dict())
        self.assertEqual(payload["knowledgeCommand"], command.to_dict())
        self.assertEqual(payload["errorEnvelope"], error.to_dict())

    def test_reference_contracts_keep_provenance_and_no_user_state(self) -> None:
        source = ReferenceSource(
            source_id="fixture-source",
            source_version="2026-01",
            retrieval_or_import_version="import/v1",
            license_id="TEST-ONLY",
            attribution="Synthetic fixture",
            confidence=0.8,
        )
        frequency = FrequencyResult("nb", "jobb", "zipf", 5.5, None, source)
        sense = DictionarySenseResult("nb", "jobb", "NOUN", "fixture", None, None, source)
        lexical = LexicalReferenceResult("nb", "jobb", "NOUN", None, (), source)
        self.assertIsNone(frequency.rank)
        self.assertEqual(source, sense.source)
        self.assertIsNone(lexical.cefr)
        for result in (frequency, sense, lexical):
            self.assertFalse(hasattr(result, "knowledge_status"))


@unittest.skipUnless(importlib.util.find_spec("stanza"), "Stanza package is explicitly provisioned")
class StanzaOfflineBehaviorTests(unittest.TestCase):
    def test_missing_model_is_unavailable_and_never_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analyzer = NorwegianBokmalStanzaAnalyzer(model_dir=directory)
            with mock.patch("stanza.download") as stanza_download, mock.patch(
                "stanza.pipeline.core.download_resources_json"
            ) as resources_download, mock.patch(
                "stanza.pipeline.core.download_models"
            ) as models_download:
                health = analyzer.health(verify_load=True)
                self.assertEqual(AnalyzerHealthState.UNAVAILABLE, health.state)
                with self.assertRaisesRegex(Exception, "explicit setup command"):
                    analyzer.analyze("En jobb.", language_code="nb")
                stanza_download.assert_not_called()
                resources_download.assert_not_called()
                models_download.assert_not_called()

    def test_pipeline_is_constructed_with_downloads_disabled(self) -> None:
        analyzer = NorwegianBokmalStanzaAnalyzer()
        if analyzer.health().state is not AnalyzerHealthState.AVAILABLE:
            self.skipTest("The explicit Bokmål model is not provisioned")

        captured: dict = {}

        class EmptyPipeline:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def __call__(self, _text):
                return type("Document", (), {"sentences": ()})()

        analyzer = NorwegianBokmalStanzaAnalyzer(pipeline_factory=EmptyPipeline)
        analyzer.analyze("", language_code="nb")
        self.assertEqual("NONE", captured["download_method"].name)
        self.assertEqual({"tokenize", "pos", "lemma"}, set(captured["processors"]))
        self.assertNotIn("depparse", captured["processors"])
        self.assertNotIn("mwt", captured["processors"])

    def test_provisioned_pipeline_runs_with_download_paths_blocked(self) -> None:
        analyzer = NorwegianBokmalStanzaAnalyzer()
        if analyzer.health().state is not AnalyzerHealthState.AVAILABLE:
            self.skipTest("The explicit Bokmål model is not provisioned")
        with mock.patch(
            "stanza.pipeline.core.download_resources_json",
            side_effect=AssertionError("resource download attempted"),
        ), mock.patch(
            "stanza.pipeline.core.download_models",
            side_effect=AssertionError("model download attempted"),
        ), mock.patch(
            "socket.create_connection",
            side_effect=AssertionError("network attempted"),
        ):
            document = analyzer.analyze("Jeg har en jobb.", language_code="nb")
        self.assertEqual("jobb", document.sentences[0].tokens[3].selected_lemma)


class BokmalStanzaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = _load_json(BOKMAL_FIXTURE)
        cls.analyzer = NorwegianBokmalStanzaAnalyzer()
        if cls.analyzer.health().state is not AnalyzerHealthState.AVAILABLE:
            raise unittest.SkipTest("The explicit Bokmål Stanza model is not provisioned")
        cls.documents = {
            case["id"]: cls.analyzer.analyze(case["text"], language_code="nb")
            for case in cls.fixture["cases"]
        }

    def test_every_token_preserves_exact_source_offsets(self) -> None:
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                document = self.documents[case["id"]]
                document.validate()
                self.assertEqual(case["text"], document.original_text)
                for token in _tokens(document):
                    self.assertEqual(
                        token.surface,
                        case["text"][token.start : token.end],
                        (case["id"], token.surface, token.start, token.end),
                    )

    def test_manual_fixture_oracle_matches_except_documented_model_deviation(self) -> None:
        known_deviations: list[tuple[str, str, str]] = []
        for case in self.fixture["cases"]:
            document = self.documents[case["id"]]
            if "expectedSentenceTexts" in case:
                self.assertEqual(
                    case["expectedSentenceTexts"],
                    [sentence.text for sentence in document.sentences],
                    case["id"],
                )
            for expected in case.get("expectedTokens", []):
                token = _expected_token(document, expected)
                checks = {
                    "kind": token.kind.value,
                    "lemma": token.selected_lemma,
                    "pos": token.pos,
                    "normalizedLookup": token.normalized_lookup,
                    "lexicalStatus": token.lexical_status.value,
                    "confidenceIsNull": token.confidence is None,
                }
                expected_checks = {
                    key: expected[key]
                    for key in checks
                    if key in expected
                }
                for key, expected_value in expected_checks.items():
                    self.assertEqual(expected_value, checks[key], (case["id"], expected, checks))
                if "posAnyOf" in expected:
                    self.assertIn(token.pos, expected["posAnyOf"], (case["id"], expected, checks))
                for key, expected_value in expected.get("morphologyContains", {}).items():
                    path = f"morphology.{key}"
                    actual_value = token.morphology.get(key)
                    if actual_value != expected_value and path in expected.get(
                        "knownAnalyzerDeviations", []
                    ):
                        known_deviations.append((case["id"], token.surface, path))
                    else:
                        self.assertEqual(
                            expected_value,
                            actual_value,
                            (case["id"], token.surface, path),
                        )
                if expected.get("mustRemainSingleToken"):
                    self.assertEqual(1, len([item for item in _tokens(document) if item.surface == token.surface]))
        self.assertEqual(
            [("jobb_noun_inflection", "Jobbene", "morphology.Gender")],
            known_deviations,
        )

    def test_unicode_whitespace_linebreaks_and_punctuation_survive(self) -> None:
        case = next(item for item in self.fixture["cases"] if item["id"] == "unicode_offsets_and_nonlexical")
        document = self.documents[case["id"]]
        for substring in case["requiredSourceSubstrings"]:
            self.assertIn(substring, document.original_text)
        surfaces = {token.surface: token for token in _tokens(document)}
        self.assertEqual("ærlig", surfaces["Ærlig"].normalized_lookup)
        self.assertEqual("øyvind", surfaces["Øyvind"].normalized_lookup)
        self.assertEqual(TokenKind.URL, surfaces["https://example.no/a-b?q=øl"].kind)
        self.assertEqual(TokenKind.EMOJI, surfaces["😊"].kind)
        self.assertGreater(surfaces["Slutt"].start, surfaces["😊"].end)
        self.assertEqual(
            "Slutt",
            document.original_text[surfaces["Slutt"].start : surfaces["Slutt"].end],
        )

    def test_ambiguous_and_unknown_inputs_are_not_presented_as_confident_lexicon_facts(self) -> None:
        for case_id in ("contextual_ambiguity", "unknown_proper_abbreviation_foreign"):
            for token in _tokens(self.documents[case_id]):
                if token.kind is TokenKind.WORD:
                    self.assertEqual(AmbiguityState.NOT_REPORTED, token.ambiguity_state)
                    self.assertEqual(LexicalStatus.NOT_ASSESSED, token.lexical_status)
                    self.assertIsNone(token.confidence)
                    self.assertIn("ambiguity=not_reported", token.provenance)

    def test_analyzer_provenance_is_complete_and_versioned(self) -> None:
        document = self.documents["jobb_noun_inflection"]
        provenance = document.analyzer
        self.assertEqual("stanza-nb-bokmaal", provenance.analyzer_id)
        self.assertTrue(provenance.package_version)
        self.assertTrue(provenance.model_version.startswith("stanza-resources-"))
        self.assertTrue(provenance.model_fingerprint.startswith("sha256:"))
        self.assertEqual(("tokenize", "pos", "lemma"), provenance.processors)


@unittest.skipUnless(importlib.util.find_spec("simplemma"), "Simplemma comparison dependency is absent")
class SimplemmaComparisonTests(unittest.TestCase):
    def test_same_fixture_oracle_is_used_for_lemma_comparison(self) -> None:
        import simplemma

        fixture = _load_json(BOKMAL_FIXTURE)
        comparisons = []
        for case in fixture["cases"]:
            for expected in case.get("expectedTokens", []):
                if "lemma" not in expected:
                    continue
                actual = normalize_lookup(simplemma.lemmatize(expected["surface"], lang="nb"))
                comparisons.append((normalize_lookup(expected["lemma"]), actual))
        self.assertGreaterEqual(len(comparisons), 30)
        self.assertTrue(any(expected != actual for expected, actual in comparisons))


@unittest.skipUnless(importlib.util.find_spec("wordfreq"), "wordfreq dependency is absent")
class WordfreqCapabilityTests(unittest.TestCase):
    def test_nb_zipf_scores_are_available_but_no_rank_is_inferred(self) -> None:
        import wordfreq

        self.assertIn("nb", wordfreq.available_languages())
        scores = {
            word: wordfreq.zipf_frequency(word, "nb")
            for word in ("jobb", "jobben", "jobber", "jobbene", "ærlig", "øl")
        }
        self.assertTrue(all(score > 0 for score in scores.values()), scores)
        result = FrequencyResult(
            language_code="nb",
            lookup="jobb",
            metric="zipf_frequency",
            score=scores["jobb"],
            rank=None,
            source=ReferenceSource(
                source_id="wordfreq",
                source_version="3.1.1",
                retrieval_or_import_version="runtime-lookup/v1",
            ),
        )
        self.assertIsNone(result.rank)


if __name__ == "__main__":
    unittest.main()

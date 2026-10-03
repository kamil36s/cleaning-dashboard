import bz2
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

import server
from language_learning import LanguageService, LanguageStore
from language_learning.cloze import ClozeService, FAST_TRACK_BANDS, FAST_TRACK_VERSION
from language_learning.reference_core.models import ReferenceSourceRecord
from language_learning.reference_core.store import ReferenceStore, utc_now
from language_learning.reference_core.tatoeba_importer import (
    ORDBANK_SOURCE_ID,
    TatoebaArtifact,
    TatoebaTranslationArtifacts,
    fast_track_coverage,
    import_tatoeba_artifact,
    import_tatoeba_translations,
)


KELLY_ID = "uio-norwegian-kelly-shu-wang"
TATOEBA_ID = "tatoeba-fixture"


def word(index):
    return "øve" + chr(97 + (index // 26)) + chr(97 + (index % 26))


def source(source_id, name, license_id="CC0-1.0"):
    return ReferenceSourceRecord(
        source_id=source_id, canonical_name=name, provider="Fixture", resource_type="FIXTURE",
        language_code="nb", version="v1", landing_url="https://example.invalid",
        license_id=license_id, license_url="https://example.invalid/license",
        attribution_text="Fixture attribution",
    )


def build_reference(root, count=60, *, include_edge_rows=False):
    root = Path(root)
    store = ReferenceStore(root / "reference.sqlite")
    store.initialize()
    store.register_source(source(ORDBANK_SOURCE_ID, "Ordbank"))
    store.register_source(source(KELLY_ID, "KELLY", "CC-BY-SA-4.0"))
    rows = []
    targets = []
    for index in range(count):
        display = word(index)
        unit = store.upsert_lexical_unit(
            language_code="nb", unit_type="LEMMA", canonical_form=display,
            part_of_speech="VERB", identity_qualifier=f"fixture-{index}",
        )
        store.link_form(
            unit.id, source_id=ORDBANK_SOURCE_ID, display_form=display,
            source_local_id=f"form-{index}", form_type="INFLECTED",
            morphology={"rawTag": "verb pres normert", "paradigmId": str(index)},
        )
        store.add_frequency(
            unit.id, source_id=KELLY_ID, metric_type="SOURCE_LEARNER_RANK",
            observation_key=f"rank-{index + 1}", rank=index + 1,
        )
        rows.append(f"{1000 + index}\tnob\tJeg {display} på et lager nå.\n")
        targets.append(unit)
    if include_edge_rows:
        first = word(0)
        ambiguous_a = store.upsert_lexical_unit(
            language_code="nb", unit_type="LEMMA", canonical_form="bank",
            part_of_speech="NOUN", identity_qualifier="bank-a",
        )
        ambiguous_b = store.upsert_lexical_unit(
            language_code="nb", unit_type="LEMMA", canonical_form="bank",
            part_of_speech="VERB", identity_qualifier="bank-b",
        )
        for index, unit in enumerate((ambiguous_a, ambiguous_b)):
            store.link_form(
                unit.id, source_id=ORDBANK_SOURCE_ID, display_form="bank",
                source_local_id=f"bank-{index}", morphology={"rawTag": "fixture"},
            )
        rows.extend([
            "9001\tnob\tBlåbær, øl og språk er fint.\n",
            "9002\tnob\tDette er en bank.\n",
            f"9003\tnob\t{first} og {first} igjen.\n",
            "9004\tnob\t<script>alert</script> er synlig tekst.\n",
            f"9005\tnob\t{'veldig ' * 100}lang.\n",
            "9004\tnob\tduplicate id should be ignored.\n",
        ])
    artifact_path = root / "nob.tsv.bz2"
    with bz2.open(artifact_path, "wt", encoding="utf-8", newline="") as handle:
        handle.writelines(rows)
    artifact = TatoebaArtifact(
        source_id=TATOEBA_ID, title="Tatoeba fixture", version="fixture-v1", path=artifact_path,
        download_url="https://example.invalid/nob.tsv.bz2", landing_url="https://tatoeba.org/en/downloads",
        license_id="CC0-1.0", license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        attribution="Tatoeba fixture", retrieved_at="2026-09-16T00:00:00Z",
        http_metadata={"fixture": "true"},
    )
    report = import_tatoeba_artifact(store, artifact)
    links_path = root / "nob-eng_links.tsv.bz2"
    english_path = root / "eng.tsv.bz2"
    with bz2.open(links_path, "wt", encoding="utf-8", newline="") as handle:
        handle.writelines(f"{1000 + index}\t{5000 + index}\n" for index in range(count))
    with bz2.open(english_path, "wt", encoding="utf-8", newline="") as handle:
        handle.writelines(f"{5000 + index}\teng\tI practice item {index} at the warehouse.\n" for index in range(count))
    translation_report = import_tatoeba_translations(store, TatoebaTranslationArtifacts(
        source_id="tatoeba-translations-fixture", title="Tatoeba translations fixture", version="fixture-v1",
        links_path=links_path, english_sentences_path=english_path,
        links_url="https://example.invalid/nob-eng.tsv.bz2", english_sentences_url="https://example.invalid/eng.tsv.bz2",
        landing_url="https://tatoeba.org/en/downloads", license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        attribution="Tatoeba translations fixture", retrieved_at="2026-09-16T00:00:00Z",
        artifacts_metadata={links_path.name: {"fixture": "true"}, english_path.name: {"fixture": "true"}},
    ))
    report["translationImport"] = translation_report
    return store, targets, report


class ReferenceSentenceImportTests(unittest.TestCase):
    def test_streamed_bokmal_import_preserves_provenance_unicode_and_mapping_states(self):
        with tempfile.TemporaryDirectory() as temp:
            store, targets, report = build_reference(temp, 4, include_edge_rows=True)
            self.assertEqual(report["rowsRead"], 10)
            self.assertEqual(report["duplicates"], 1)
            self.assertEqual(report["license"], "CC0-1.0")
            with store._connect() as connection:
                unicode_row = connection.execute(
                    "SELECT * FROM reference_sentences WHERE source_sentence_id='9001'"
                ).fetchone()
                self.assertIn("Blåbær", unicode_row["sentence_text"])
                self.assertEqual(unicode_row["license_id"], "CC0-1.0")
                ambiguous = connection.execute(
                    "SELECT resolution_status,candidate_count FROM reference_sentence_occurrences "
                    "WHERE sentence_id=(SELECT id FROM reference_sentences WHERE source_sentence_id='9002') "
                    "AND normalized_form='bank'"
                ).fetchone()
                self.assertEqual((ambiguous[0], ambiguous[1]), ("AMBIGUOUS", 2))
                repeated = connection.execute(
                    "SELECT COUNT(*) FROM reference_sentence_occurrences WHERE sentence_id="
                    "(SELECT id FROM reference_sentences WHERE source_sentence_id='9003') AND lexical_unit_id=?",
                    (targets[0].id,),
                ).fetchone()[0]
                self.assertEqual(repeated, 2)
                html_row = connection.execute(
                    "SELECT sentence_text,quality_flags_json FROM reference_sentences WHERE source_sentence_id='9004'"
                ).fetchone()
                self.assertIn("<script>", html_row["sentence_text"])
                self.assertIn("HTML_LIKE_TEXT", json.loads(html_row["quality_flags_json"]))
                long_row = connection.execute(
                    "SELECT usable,quality_flags_json FROM reference_sentences WHERE source_sentence_id='9005'"
                ).fetchone()
                self.assertEqual(long_row["usable"], 0)
                self.assertIn("TOO_LONG", json.loads(long_row["quality_flags_json"]))
                translation = connection.execute(
                    "SELECT translation_text,translation_sentence_id,license_id FROM reference_sentence_translations "
                    "WHERE sentence_id=(SELECT id FROM reference_sentences WHERE source_sentence_id='1000')"
                ).fetchone()
                self.assertEqual(tuple(translation), ("I practice item 0 at the warehouse.", "5000", "CC0-1.0"))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reference_schema_v3_and_fast_track_coverage_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, _ = build_reference(temp, 8)
            first = fast_track_coverage(store)
            second = fast_track_coverage(store)
            self.assertEqual(first, second)
            self.assertEqual(first["bands"]["FAST_TRACK_1"]["withAtLeastOne"], 8)
            with store._connect() as connection:
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM reference_schema_migrations"
                ).fetchone()[0], 3)


class ClozeFastTrackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.reference, self.targets, _ = build_reference(self.temp.name, 60)
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.cloze = ClozeService(self.service, self.reference.database_path)
        self.service.attach_cloze_service(self.cloze)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, count=10, seed="stable-seed", mode="FAST_TRACK"):
        return self.service.start_cloze_session(self.profile["id"], {
            "trackKey": "FAST_TRACK_1", "itemCount": count, "seed": seed, "mode": mode,
        })["data"]

    def internal_items(self, session_id):
        return json.loads(self.store.get_cloze_session(session_id)["session"]["items_json"])

    def submit(self, session, index, *, action="ANSWER", option_index=None, key=None, response_ms=250):
        item = session["currentItem"]
        payload = {
            "itemIndex": item["index"], "itemFingerprint": item["fingerprint"], "action": action,
            "responseMs": response_ms, "idempotencyKey": key or f"attempt-{index}",
        }
        if option_index is not None:
            payload["optionIndex"] = option_index
        return self.service.submit_cloze_attempt(session["id"], payload)["data"]

    def test_band_boundaries_and_priority_are_stable(self):
        self.assertEqual(FAST_TRACK_BANDS["FAST_TRACK_1"], (1, 500))
        self.assertEqual(FAST_TRACK_BANDS["FAST_TRACK_2"], (501, 1000))
        target = {"rank": 10, "stable_key": "a"}
        never = self.cloze._priority(target, None)
        incorrect = self.cloze._priority(target, {"lastOutcome": "INCORRECT", "attemptCount": 1})
        learning = self.cloze._priority(target, {"lastOutcome": "CORRECT", "attemptCount": 1, "knowledgeStatus": "LEARNING", "totalExposures": 0})
        weak = self.cloze._priority(target, {"lastOutcome": "CORRECT", "attemptCount": 1, "knowledgeStatus": "KNOWN", "recognition": 2, "totalExposures": 5})
        underexposed = self.cloze._priority(target, {"lastOutcome": "CORRECT", "attemptCount": 1, "knowledgeStatus": "KNOWN", "recognition": 4, "totalExposures": 1})
        self.assertLess(never, incorrect)
        self.assertLess(incorrect, learning)
        self.assertLess(learning, weak)
        self.assertLess(weak, underexposed)
        self.assertEqual(self.cloze._priority(target, None), self.cloze._priority(target, None))
        self.assertLess(
            self.cloze._priority({"rank": 10, "stable_key": "a"}, None),
            self.cloze._priority({"rank": 10, "stable_key": "b"}, None),
        )

        missing = self.reference.upsert_lexical_unit(
            language_code="nb", unit_type="LEMMA", canonical_form="mangler",
            part_of_speech="ADJ", identity_qualifier="no-sentence",
        )
        missing_target = {
            "id": missing.id, "stable_key": missing.stable_key, "canonical_form": "mangler",
            "normalized_form": "mangler", "part_of_speech": "ADJ", "rank": 1,
        }
        self.assertIsNone(self.cloze._item(missing_target, self.profile["id"], "seed", 0, {}))
        self.assertEqual(self.cloze._distractors(missing_target, "mangler", "seed"), [])

    def test_session_sizes_seed_order_and_distractors(self):
        first = self.start(10, "same-seed")
        second_service = LanguageService(LanguageStore(Path(self.temp.name) / "language-two.sqlite"))
        second_service.initialize(); second_profile = second_service.ensure_bokmal_profile()["profile"]
        second_cloze = ClozeService(second_service, self.reference.database_path)
        second_service.attach_cloze_service(second_cloze)
        second = second_service.start_cloze_session(second_profile["id"], {
            "trackKey": "FAST_TRACK_1", "itemCount": 10, "seed": "same-seed",
        })["data"]
        self.assertEqual(first["session"]["actualItemCount"], 10)
        self.assertEqual(
            [item["fingerprint"] for item in self.internal_items(first["session"]["id"])],
            [item["fingerprint"] for item in json.loads(second_service.store.get_cloze_session(second["session"]["id"])["session"]["items_json"])],
        )
        first_items = self.internal_items(first["session"]["id"])
        self.assertGreater(len({item["correctIndex"] for item in first_items}), 1)
        for item in first_items:
            self.assertEqual(len(item["options"]), 4)
            self.assertEqual(len(set(map(str.casefold, item["options"]))), 4)
            self.assertEqual(item["options"].count(item["expectedSurfaceForm"]), 1)
            self.assertEqual(item["translation"]["languageCode"], "en")
            self.assertTrue(item["translation"]["text"].startswith("I practice item"))
            self.assertEqual(item["displayOptions"].count(item["displayExpectedSurfaceForm"]), 1)
            self.assertTrue(all(option.startswith("øve") for option in item["options"]))
        twenty = self.start(20, "twenty")
        fifty = self.start(50, "fifty")
        self.assertEqual(twenty["session"]["actualItemCount"], 20)
        self.assertEqual(fifty["session"]["actualItemCount"], 50)

    def test_attempt_outcomes_idempotency_completion_and_domain_invariants(self):
        started = self.start(10)
        session = started["session"]
        internal = self.internal_items(session["id"])
        with self.store.connection() as connection:
            baseline_anki = connection.execute("SELECT COUNT(*) FROM anki_note_links").fetchone()[0]
            baseline_exposures = connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0]
        outcomes = []
        for index in range(10):
            correct_index = internal[index]["correctIndex"]
            if index == 0:
                option = (correct_index + 1) % 4
                result = self.submit(session, index, option_index=option, response_ms=432)
                duplicate = self.submit(session, index, option_index=option, key="attempt-0", response_ms=432)
                self.assertFalse(duplicate["created"])
            elif index == 1:
                result = self.submit(session, index, option_index=correct_index)
            elif index == 2:
                result = self.submit(session, index, action="REVEAL")
            elif index == 3:
                result = self.submit(session, index, action="SKIP")
            else:
                result = self.submit(session, index, option_index=correct_index)
            outcomes.append(result["feedback"]["outcome"])
            session = result["session"]
        self.assertEqual(outcomes[:4], ["INCORRECT", "CORRECT", "REVEALED", "SKIPPED"])
        self.assertEqual(session["status"], "COMPLETED")
        self.assertEqual(session["answeredCount"], 10)
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cloze_attempts").fetchone()[0], 10)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_events WHERE source='CLOZE'").fetchone()[0], 10)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM anki_note_links").fetchone()[0], baseline_anki)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], baseline_exposures)
            states = {row[0] for row in connection.execute("SELECT knowledge_status FROM lemma_knowledge")}
            self.assertEqual(states, {"NEW"})

    def test_mistakes_recycle_and_reported_pair_is_suppressed(self):
        started = self.start(10, "mistake-seed")
        session = started["session"]
        first_internal = self.internal_items(session["id"])[0]
        wrong = (first_internal["correctIndex"] + 1) % 4
        result = self.submit(session, 0, option_index=wrong)
        mistake_key = result["attempt"]["referenceTargetStableKey"]
        recycled = self.start(10, "recycle-seed", mode="RECYCLE_MISTAKES")
        recycled_items = self.internal_items(recycled["session"]["id"])
        self.assertEqual(recycled_items[0]["referenceTargetStableKey"], mistake_key)
        report = self.service.report_cloze_item(recycled["session"]["id"], {
            "itemIndex": 0, "reason": "BAD_DISTRACTORS",
        })["data"]
        self.assertTrue(report["created"])
        report_again = self.service.report_cloze_item(recycled["session"]["id"], {
            "itemIndex": 0, "reason": "BAD_DISTRACTORS",
        })["data"]
        self.assertFalse(report_again["created"])
        with self.assertRaises(Exception):
            self.start(10, "recycle-after-report", mode="RECYCLE_MISTAKES")

    def test_reference_import_does_not_create_user_vocabulary(self):
        fresh = LanguageStore(Path(self.temp.name) / "empty-user.sqlite")
        fresh.initialize()
        with fresh.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0], 0)
        self.assertEqual(self.reference.health()["schemaVersion"], 3)
        self.assertEqual(FAST_TRACK_VERSION, "language.cloze-fast-track/v1")

    def test_option_capitalization_does_not_reveal_a_sentence_initial_answer(self):
        sentence = {"sentence_text": "Jobber jeg her?", "start_offset": 0}
        options, expected = self.cloze._present_options(
            sentence, ["jobber", "sover", "leser", "venter"], "Jobber",
        )
        self.assertEqual(expected, "Jobber")
        self.assertEqual(options, ["Jobber", "Sover", "Leser", "Venter"])

    def test_legacy_active_item_gets_translation_and_safe_display_without_rewriting_snapshot(self):
        started = self.start(10, "legacy-display")
        legacy = self.internal_items(started["session"]["id"])[0]
        legacy.pop("translation")
        legacy.pop("displayOptions")
        legacy.pop("displayExpectedSurfaceForm")
        public = self.cloze._public_item(legacy, 0)
        self.assertEqual(public["translation"]["languageCode"], "en")
        self.assertEqual(len(public["options"]), 4)
        self.assertEqual(public["options"].count(self.cloze._display_forms(legacy)[1]), 1)

    def test_http_vertical_slice_tracks_session_attempt_reload_and_report(self):
        previous_service = server.LANGUAGE_SERVICE
        server.LANGUAGE_SERVICE = self.service
        httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def request(method, path, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            headers = {} if body is None else {"Content-Type": "application/json"}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read().decode("utf-8"))
            connection.close()
            return result

        try:
            status, tracks = request("GET", f"/api/language/profiles/{self.profile['id']}/cloze/tracks")
            self.assertEqual(status, 200)
            self.assertEqual(tracks["data"]["status"], "READY")
            status, started = request("POST", f"/api/language/profiles/{self.profile['id']}/cloze/sessions", {
                "trackKey": "FAST_TRACK_1", "itemCount": 10, "seed": "http-seed",
            })
            self.assertEqual(status, 201)
            active = started["data"]["session"]
            self.assertNotIn("correctIndex", active["currentItem"])
            internal = self.internal_items(active["id"])[0]
            status, answered = request("POST", f"/api/language/cloze/sessions/{active['id']}/attempts", {
                "itemIndex": 0, "itemFingerprint": active["currentItem"]["fingerprint"],
                "action": "ANSWER", "optionIndex": internal["correctIndex"],
                "responseMs": 321, "idempotencyKey": "http-attempt-1",
            })
            self.assertEqual((status, answered["data"]["feedback"]["outcome"]), (201, "CORRECT"))
            status, reloaded = request("GET", f"/api/language/cloze/sessions/{active['id']}")
            self.assertEqual((status, reloaded["data"]["session"]["answeredCount"]), (200, 1))
            status, reported = request("POST", f"/api/language/cloze/sessions/{active['id']}/report", {
                "itemIndex": 1, "reason": "UNNATURAL_SENTENCE",
            })
            self.assertEqual((status, reported["data"]["created"]), (201, True))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server.LANGUAGE_SERVICE = previous_service


if __name__ == "__main__":
    unittest.main()

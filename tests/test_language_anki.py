import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from language_learning.anki_sync import AnkiSyncService
from language_learning.errors import LanguageConflictError, LanguageValidationError
from language_learning.providers.anki import AnkiCapabilities, AnkiTimeoutError
from language_learning.schemas import text_fingerprint
from language_learning.service import LanguageService
from language_learning.store import LanguageStore


class FakeAnki:
    def __init__(self, endpoint=None, **kwargs):
        self.endpoint = endpoint
        self.version = 6
        self.decks = ["Language Test"]
        self.models = {"Dashboard": ["Front", "Lemma", "Context", "DashboardKey", "Notes"]}
        self.notes = {}
        self.cards = {}
        self.next_note_id = 100
        self.next_card_id = 1000
        self.write_calls = []
        self.timeout_after_success = False
        self.fail_card_ids = set()

    def capabilities(self):
        return AnkiCapabilities(self.version)

    def deck_names(self):
        return list(self.decks)

    def deck_stats(self, deck_name):
        cards = [card for card in self.cards.values() if card.get("deckName") == deck_name
                 or card.get("deckName", "").startswith(deck_name + "::")]
        return {"new": 0, "learn": 0, "due": sum(bool(card.get("isDue")) for card in cards)}

    def deck_config(self, deck_name):
        return {"new": {"perDay": 20}, "rev": {"perDay": 100}}

    def card_reviews(self, deck_name, start_id=0):
        return []

    def sync_web(self):
        self.write_calls.append("sync")

    def model_names(self):
        return list(self.models)

    def model_field_names(self, model_name):
        if model_name not in self.models:
            raise RuntimeError("model missing")
        return list(self.models[model_name])

    def find_notes(self, query):
        return [note_id for note_id, note in self.notes.items() if any(
            str(field.get("value", "")) in query and str(field.get("value", ""))
            for field in note["fields"].values()
        ) or any(tag in query for tag in note.get("tags", []))]

    def notes_info(self, note_ids):
        return [self.notes[note_id] for note_id in note_ids if note_id in self.notes]

    def find_cards(self, query):
        if query == "is:due":
            return [card_id for card_id, card in self.cards.items() if card.get("isDue")]
        if query.startswith('deck:"'):
            deck_name = query.split('"', 2)[1]
            return [card_id for card_id, card in self.cards.items()
                    if (card.get("deckName") == deck_name
                        or card.get("deckName", "").startswith(deck_name + "::")) and (
                        query.endswith("is:due") and card.get("isDue")
                        or query.endswith("rated:1 -introduced:1") and card.get("answeredToday") and not card.get("introducedToday")
                        or query.endswith(" introduced:1") and card.get("introducedToday")
                           and "-introduced:1" not in query
                        or query.endswith("rated:1") and card.get("answeredToday")
                        or query.endswith('"')
                    )]
        if query.startswith("nid:"):
            note_id = int(query.split(":", 1)[1])
            return [card_id for card_id, card in self.cards.items() if card["note"] == note_id]
        return []

    def cards_info(self, card_ids):
        if any(card_id in self.fail_card_ids for card_id in card_ids):
            raise RuntimeError("synthetic card failure")
        return [self.cards[card_id] for card_id in card_ids if card_id in self.cards]

    def can_add_note(self, note):
        front = note["fields"].get("Front")
        return all(existing["fields"].get("Front", {}).get("value") != front for existing in self.notes.values())

    def add_note(self, note):
        self.write_calls.append("addNote")
        note_id = self.next_note_id
        self.next_note_id += 1
        self.notes[note_id] = {
            "noteId": note_id, "modelName": note["modelName"], "deckName": note["deckName"],
            "fields": {name: {"value": value, "order": index} for index, (name, value) in enumerate(note["fields"].items())},
            "tags": list(note.get("tags", [])),
        }
        card_id = self.next_card_id
        self.next_card_id += 1
        self.cards[card_id] = {
            "cardId": card_id, "note": note_id, "deckName": note["deckName"],
            "queue": 2, "type": 2, "due": 10, "interval": 5, "factor": 2500,
            "reviews": 2, "reps": 2, "lapses": 0, "isDue": True,
            "fields": self.notes[note_id]["fields"],
        }
        if self.timeout_after_success:
            self.timeout_after_success = False
            raise AnkiTimeoutError()
        return note_id

    def update_note_fields(self, note_id, fields):
        self.write_calls.append("updateNoteFields")
        for name, value in fields.items():
            self.notes[note_id]["fields"].setdefault(name, {})["value"] = value

    def add_tags(self, note_ids, tags):
        self.write_calls.append("addTags")
        for note_id in note_ids:
            self.notes[note_id].setdefault("tags", []).extend(tag for tag in tags if tag not in self.notes[note_id]["tags"])

    def remove_tags(self, note_ids, tags):
        self.write_calls.append("removeTags")
        for note_id in note_ids:
            self.notes[note_id]["tags"] = [tag for tag in self.notes[note_id].get("tags", []) if tag not in tags]


class LanguageAnkiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.fake = FakeAnki()
        sync = AnkiSyncService(self.store, adapter_factory=lambda *args, **kwargs: self.fake)
        self.service = LanguageService(self.store, anki_sync_service=sync)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.lemma = self.service.upsert_lemma(
            self.profile["id"], "jobb", part_of_speech="NOUN", user_notes="Own note"
        )["lemma"]
        self.service.update_anki_config(self.profile["id"], {
            "enabled": True,
            "endpoint": "http://127.0.0.1:8765",
            "deckName": "Language Test",
            "modelName": "Dashboard",
            "fieldMap": {
                "target": "Front", "lemma": "Lemma", "context": "Context",
                "dashboardKey": "DashboardKey", "notes": "Notes",
            },
        })

    def tearDown(self):
        self.temp.cleanup()

    def test_status_includes_all_current_decks(self):
        self.fake.decks.append("New Norwegian Deck")
        self.fake.add_note({"deckName": "New Norwegian Deck", "modelName": "Dashboard",
                            "fields": {"Front": "ny"}, "tags": []})
        status = self.service.anki_status(self.profile["id"])["data"]
        self.assertEqual([deck["name"] for deck in status["decks"]],
                         ["Language Test", "New Norwegian Deck"])
        self.assertEqual(status["decks"][1]["due"], 1)

    def test_vocabulary_card_states_lists_each_deck_and_queue_separately(self):
        self.fake.decks.extend(["Language Test::Grammar", "Other Norwegian Deck"])
        self.fake.add_note({"deckName": "Language Test", "modelName": "Dashboard",
                            "fields": {"Front": "jobb"}, "tags": []})
        self.fake.add_note({"deckName": "Language Test::Grammar", "modelName": "Dashboard",
                            "fields": {"Front": "jobb"}, "tags": []})
        self.fake.add_note({"deckName": "Other Norwegian Deck", "modelName": "Dashboard",
                            "fields": {"Front": "jobb"}, "tags": []})
        self.fake.cards[1000]["queue"] = 1
        self.fake.cards[1001]["queue"] = 2
        self.fake.cards[1002]["queue"] = -2
        result = self.service.vocabulary_anki_status(self.profile["id"], [self.lemma["id"]])["data"]
        self.assertEqual(result["status"], "CURRENT")
        self.assertEqual(result["lemmas"][self.lemma["id"]], [
            {"deckName": "Language Test", "statuses": ["LEARNING"]},
            {"deckName": "Language Test::Grammar", "statuses": ["REVIEW"]},
            {"deckName": "Other Norwegian Deck", "statuses": ["SUSPENDED"]},
        ])
        self.assertIsNotNone(result["observedAt"])

    def test_status_week_counts_reviews_once_across_parent_and_child_decks(self):
        self.fake.decks = ["Default", "Language Test", "Language Test::Words"]
        today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        yesterday = today - timedelta(days=1)
        review_id = int(datetime.combine(yesterday, datetime.min.time(), ZoneInfo("Europe/Warsaw")).timestamp() * 1000) + 1000
        review = [review_id, 1000, 0, 3, 0, 0, 0, 1000, 1]
        self.fake.card_reviews = lambda name, start_id=0: [review] if name != "Default" and review_id >= start_id else []
        status = self.service.anki_status(self.profile["id"])["data"]
        self.assertEqual(len(status["week"]), 7)
        self.assertEqual(status["week"][-2]["date"], yesterday.isoformat())
        self.assertEqual((status["week"][-2]["answers"], status["week"][-2]["cards"]), (1, 1))
        self.assertIsNone(status["week"][-2]["complete"])
        self.assertEqual(status["week"][-1]["date"], today.isoformat())
        self.assertEqual(status["week"][-1]["answers"], 0)

    def test_status_marks_a_previous_day_complete_against_its_saved_plan(self):
        yesterday = datetime.now(ZoneInfo("Europe/Warsaw")).date() - timedelta(days=1)
        self.store.observe_anki_daily_plans(self.profile["id"], yesterday.isoformat(), [
            {"name": "Language Test", "newCompletedToday": 0, "new": 0,
             "reviewsCompletedToday": 0, "due": 2},
        ])
        first_id = int(datetime.combine(yesterday, datetime.min.time(), ZoneInfo("Europe/Warsaw")).timestamp() * 1000) + 1000
        reviews = [[first_id + index, 1000 + index, 0, 3, 0, 0, 0, 1000, 1]
                   for index in range(2)]
        self.fake.card_reviews = lambda name, start_id=0: [row for row in reviews if row[0] >= start_id]
        status = self.service.anki_status(self.profile["id"])["data"]
        self.assertEqual(status["week"][-2]["planned"], 2)
        self.assertTrue(status["week"][-2]["complete"])

    def test_status_counts_daily_progress_for_reader_story_and_child_deck(self):
        self.fake.decks = ["Default", "Language Test", "Reader Stories", "Reader Stories::01 Words"]
        self.fake.add_note({"deckName": "Reader Stories::01 Words", "modelName": "Dashboard",
                            "fields": {"Front": "ny"}, "tags": []})
        self.fake.add_note({"deckName": "Reader Stories::01 Words", "modelName": "Dashboard",
                            "fields": {"Front": "gammel"}, "tags": []})
        self.fake.cards[1000].update(isDue=False, answeredToday=True, introducedToday=True)
        self.fake.cards[1001].update(isDue=False, answeredToday=True, introducedToday=False)
        self.fake.add_note({"deckName": "Reader Stories::01 Words", "modelName": "Dashboard",
                            "fields": {"Front": "venter"}, "tags": []})
        self.fake.deck_stats = lambda name: {"new": 2, "learn": 0, "due": 1} if name.startswith("Reader Stories") else {"new": 0, "learn": 0, "due": 0}
        status = self.service.anki_status(self.profile["id"])["data"]
        self.assertEqual(status["status"], "CONNECTED")
        self.assertEqual([deck["name"] for deck in status["decks"]],
                         ["Default", "Language Test", "Reader Stories", "Reader Stories::01 Words"])
        for deck in status["decks"][2:]:
            self.assertEqual((deck["reviewsCompletedToday"], deck["reviewsPlannedToday"]), (1, 2))
            self.assertEqual((deck["newCompletedToday"], deck["newPlannedToday"]), (1, 3))

    def test_daily_plan_tracks_current_anki_queue_after_reviews_and_day_change(self):
        for front in ("scheduled", "extra"):
            self.fake.add_note({"deckName": "Language Test", "modelName": "Dashboard",
                                "fields": {"Front": front}, "tags": []})
        first = self.service.anki_status(self.profile["id"])["data"]["deck"]
        self.assertEqual((first["reviewsCompletedToday"], first["reviewsPlannedToday"]), (0, 2))
        for card in self.fake.cards.values():
            card.update(isDue=False, answeredToday=True)
        second = self.service.anki_status(self.profile["id"])["data"]["deck"]
        self.assertEqual(second["reviewsCompletedToday"], 2)
        self.assertEqual(second["reviewsPlannedToday"], 2)
        for card in self.fake.cards.values():
            card["answeredToday"] = False
        third = self.service.anki_status(self.profile["id"])["data"]["deck"]
        self.assertEqual((third["reviewsCompletedToday"], third["reviewsPlannedToday"]), (0, 0))

    def test_manual_reader_status_is_reflected_as_anki_note_tag_without_rescheduling(self):
        note_id = self.fake.add_note({
            "deckName": "Language Test", "modelName": "Dashboard",
            "fields": {"Front": "jobb", "Lemma": "jobb"}, "tags": [],
        })
        result = self.service.update_knowledge(self.lemma["id"], {"knowledgeStatus": "KNOWN"})["data"]
        self.assertEqual(result["ankiReflection"]["state"], "TAGGED")
        self.assertEqual(result["ankiReflection"]["schedulingChanged"], False)
        self.assertIn("dashboard_status_known", self.fake.notes[note_id]["tags"])
        self.assertEqual(self.fake.cards[1000]["interval"], 5)
        self.service.update_knowledge(self.lemma["id"], {"knowledgeStatus": "LEARNING"})
        self.assertEqual(self.fake.notes[note_id]["tags"].count("dashboard_status_learning"), 1)
        self.assertNotIn("dashboard_status_known", self.fake.notes[note_id]["tags"])

    def test_story_parent_insights_include_child_deck_cards_and_reviews(self):
        parent = "Reader Stories::Test"
        first = parent + "::01 Words"
        second = parent + "::03 Sentences"
        self.fake.decks = ["Language Test", parent, first, second]
        self.service.update_anki_config(self.profile["id"], {"deckName": "Language Test"})
        self.fake.add_note({"deckName": first, "modelName": "Dashboard", "fields": {"Front": "jobb"}, "tags": []})
        self.fake.add_note({"deckName": second, "modelName": "Dashboard", "fields": {"Front": "Han har en jobb."}, "tags": []})
        self.fake.card_reviews = lambda deck, start_id=0: (
            [[1_780_000_000_000, 1000, 0, 3, 3, 1, 2500, 1000, 1]] if deck == first else []
        )
        self.fake.deck_stats = lambda deck: {"new": 0, "learn": 0, "due": 1 if deck == parent else 2}
        result = self.service.anki_insights(self.profile["id"], deck_name=parent)["data"]
        self.assertEqual(result["inventory"]["totalCards"], 2)
        self.assertEqual(result["today"]["reviewsDue"], 1)
        self.assertEqual(result["cards"]["items"][0]["knowledge"]["lastRating"], 3)
        self.assertIn(parent, result["availableDecks"])

    def add_context(self):
        text = self.service.create_text_draft({
            "languageProfileId": self.profile["id"], "title": "Real reader source",
            "rawText": "Jeg liker jobben.", "sourceType": "PASTED",
        })["data"]["text"]
        sentence_id = "1" * 32
        form = self.service.upsert_surface_form(self.profile["id"], "jobben")["form"]
        self.service.upsert_form_lemma_mapping(self.profile["id"], form["id"], self.lemma["id"])
        self.store.insert_text_structure(text["id"], sentences=[{
            "id": sentence_id, "sentence_order": 0, "source_start": 0, "source_end": 17,
            "exact_text": "Jeg liker jobben.", "fingerprint": text_fingerprint("Jeg liker jobben."),
        }], tokens=[{
            "id": "2" * 32, "sentence_id": sentence_id, "token_order": 0,
            "surface": "jobben", "source_start": 10, "source_end": 16,
            "token_kind": "WORD", "normalized_lookup": "jobben", "surface_form_id": form["id"],
            "selected_lemma_id": self.lemma["id"],
        }], analysis_run={
            "id": "3" * 32, "analyzer_id": "test", "analyzer_version": "1",
            "contract_version": "language.analysis/v1", "state": "COMPLETED",
        })
        return sentence_id

    def preview(self, sentence_id=None):
        payload = {"sentenceId": sentence_id} if sentence_id else {}
        return self.service.preview_anki_note(self.lemma["id"], payload)["data"]

    def commit(self, preview, sentence_id=None):
        return self.service.commit_anki_note(self.lemma["id"], {
            "confirm": True, "previewFingerprint": preview["previewFingerprint"],
            "sentenceId": sentence_id,
        })["data"]

    def test_status_discovery_and_preview_are_read_only(self):
        self.assertEqual(self.service.anki_status(self.profile["id"])["data"]["status"], "CONNECTED")
        self.fake.version = 5
        self.assertEqual(self.service.anki_status(self.profile["id"])["data"]["status"], "VERSION_UNSUPPORTED")
        self.fake.version = 6
        self.assertEqual(self.service.anki_decks(self.profile["id"])["data"]["items"], ["Language Test"])
        self.assertEqual(self.service.anki_models(self.profile["id"])["data"]["items"], ["Dashboard"])
        preview = self.preview()
        self.assertEqual(preview["action"], "CREATE")
        self.assertEqual(preview["logicalFields"]["translation"], "")
        self.assertEqual(preview["logicalFields"]["definition"], "")
        self.assertEqual(self.fake.write_calls, [])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM anki_note_links").fetchone()[0], 0)

    def test_create_repeat_and_timeout_after_success_are_idempotent(self):
        sentence_id = self.add_context()
        preview = self.preview(sentence_id)
        self.assertEqual(preview["mappedFields"]["Context"], "Jeg liker jobben.")
        self.fake.timeout_after_success = True
        created = self.commit(preview, sentence_id)
        self.assertEqual(created["action"], "RECONCILED_AFTER_TIMEOUT")
        again = self.preview(sentence_id)
        self.assertEqual(again["action"], "NO_CHANGE")
        self.commit(again, sentence_id)
        self.assertEqual(len(self.fake.notes), 1)
        self.assertEqual(self.fake.write_calls.count("addNote"), 1)

    def test_stale_link_reconciles_by_stable_key_without_duplicate(self):
        first = self.preview()
        self.commit(first)
        old_id = next(iter(self.fake.notes))
        note = self.fake.notes.pop(old_id)
        note["noteId"] = 777
        self.fake.notes[777] = note
        preview = self.preview()
        self.assertTrue(preview["staleLocalLink"])
        self.assertEqual(preview["matchBasis"], "STABLE_KEY")
        self.commit(preview)
        self.assertEqual(len(self.fake.notes), 1)
        self.assertEqual(self.service.get_lemma_anki(self.lemma["id"])["data"]["link"]["externalNoteId"], 777)

    def test_conflict_detection_and_explicit_resolutions(self):
        self.commit(self.preview())
        note_id = next(iter(self.fake.notes))
        self.assertEqual(self.preview()["conflictState"], "NONE")
        self.service.update_lemma(self.lemma["id"], {"userNotes": "Local changed"})
        self.assertEqual(self.preview()["conflictState"], "LOCAL_CHANGED")
        self.fake.notes[note_id]["fields"]["Notes"]["value"] = "Remote changed"
        preview = self.preview()
        self.assertEqual(preview["conflictState"], "BOTH_CHANGED")
        self.assertTrue(any(item["field"] == "Notes" for item in preview["conflicts"]))
        with self.assertRaises(LanguageConflictError):
            self.commit(preview)
        resolved = self.service.resolve_anki_conflict(
            self.lemma["id"], {"resolution": "DASHBOARD_WINS"}
        )["data"]
        self.assertEqual(resolved["link"]["conflictState"], "NONE")
        self.fake.notes[note_id]["fields"]["Notes"]["value"] = "Anki accepted"
        self.assertEqual(self.preview()["conflictState"], "REMOTE_CHANGED")
        accepted = self.service.resolve_anki_conflict(
            self.lemma["id"], {"resolution": "ANKI_WINS"}
        )["data"]
        self.assertEqual(accepted["link"]["conflictState"], "NONE")

    def test_explicit_link_preview_then_commit(self):
        note_id = self.fake.add_note({
            "deckName": "Language Test", "modelName": "Dashboard",
            "fields": {"Front": "edited visible text", "Lemma": "", "Context": "", "DashboardKey": "", "Notes": ""},
            "tags": [],
        })
        self.fake.write_calls.clear()
        preview = self.service.link_anki_note(self.lemma["id"], {"externalNoteId": note_id})["data"]
        self.assertFalse(preview["mutated"])
        linked = self.service.link_anki_note(
            self.lemma["id"], {"externalNoteId": note_id, "confirm": True}
        )["data"]
        self.assertTrue(linked["mutated"])
        self.assertEqual(linked["link"]["externalNoteId"], note_id)
        self.assertEqual(self.fake.write_calls, ["updateNoteFields"])

    def test_pull_snapshots_and_evidence_without_scheduling_writes(self):
        self.commit(self.preview())
        self.fake.write_calls.clear()
        pulled = self.service.pull_anki(self.profile["id"])["data"]
        self.assertEqual(pulled["dueCount"], 1)
        state = self.service.get_lemma_anki(self.lemma["id"])["data"]
        self.assertEqual(len(state["cards"]), 1)
        self.assertEqual(state["cards"][0]["reviews"], 2)
        self.assertEqual(self.fake.write_calls, [])
        plan = self.service.learning_plan(self.profile["id"])["data"]
        self.assertTrue(any(item["kind"] == "ANKI_DUE" for item in plan["items"]))
        overview = self.service.overview(self.profile["id"])["data"]
        self.assertEqual(overview["anki"]["dueCount"], 1)
        detail = self.service.get_lemma(self.lemma["id"])["data"]
        event = [item for item in detail["events"] if item["source"] == "ANKI"]
        self.assertEqual(len(event), 1)
        self.assertEqual(detail["knowledge"]["knowledgeStatus"], "NEW")
        self.service.pull_anki(self.profile["id"])
        detail = self.service.get_lemma(self.lemma["id"])["data"]
        self.assertEqual(len([item for item in detail["events"] if item["source"] == "ANKI"]), 1)

    def test_selected_deck_status_and_throttled_web_sync(self):
        self.commit(self.preview())
        self.fake.cards[1000]["answeredToday"] = True
        self.fake.cards[2000] = {"deckName": "Another deck", "isDue": True, "answeredToday": True}
        self.service.update_anki_config(self.profile["id"], {"autoSync": True})
        status = self.service.anki_status(self.profile["id"])["data"]
        self.assertEqual(status["deck"]["name"], "Language Test")
        self.assertEqual(status["deck"]["due"], 1)
        self.assertEqual(status["deck"]["answeredCardsToday"], 1)
        self.fake.write_calls.clear()
        first = self.service.sync_anki_web(self.profile["id"])["data"]
        second = self.service.sync_anki_web(self.profile["id"])["data"]
        self.assertIsNotNone(first["syncedAt"])
        self.assertEqual(second["skipped"], "RECENT_SYNC")
        self.assertEqual(self.fake.write_calls, ["sync"])
        self.service.sync_anki_web(self.profile["id"], force=True)
        self.assertEqual(self.fake.write_calls, ["sync", "sync"])

    def test_partial_pull_is_truthful_and_retry_idempotent(self):
        first = self.commit(self.preview())
        other = self.service.upsert_lemma(self.profile["id"], "hus", part_of_speech="NOUN")["lemma"]
        second_preview = self.service.preview_anki_note(other["id"], {})["data"]
        self.service.commit_anki_note(other["id"], {
            "confirm": True, "previewFingerprint": second_preview["previewFingerprint"]
        })
        failing_card = max(self.fake.cards)
        self.fake.fail_card_ids.add(failing_card)
        partial = self.service.pull_anki(self.profile["id"])["data"]["run"]
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertEqual(partial["counts"]["succeeded"], 1)
        self.fake.fail_card_ids.clear()
        retried = self.service.pull_anki(self.profile["id"])["data"]["run"]
        self.assertEqual(retried["status"], "COMPLETED")
        self.assertEqual(len(self.fake.notes), 2)

    def test_configuration_rejects_remote_endpoint_and_invalid_mapping(self):
        with self.assertRaises(LanguageValidationError):
            self.service.update_anki_config(self.profile["id"], {"endpoint": "http://example.com:8765"})
        with self.assertRaises(LanguageValidationError):
            self.service.update_anki_config(self.profile["id"], {"fieldMap": {"target": "Front", "lemma": "Front"}})
        self.fake.decks = []
        with self.assertRaises(LanguageValidationError) as missing_deck:
            self.preview()
        self.assertEqual(missing_deck.exception.code, "anki_deck_missing")
        self.fake.decks = ["Language Test"]
        self.fake.models = {}
        with self.assertRaises(LanguageValidationError) as missing_model:
            self.preview()
        self.assertEqual(missing_model.exception.code, "anki_model_missing")
        exported = self.service.export_data()["data"]
        serialized = str(exported)
        self.assertNotIn("LANGUAGE_ANKI_CONNECT_API_KEY", serialized)


if __name__ == "__main__":
    unittest.main()

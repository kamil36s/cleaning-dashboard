import unittest
from pathlib import Path
from datetime import datetime
import tempfile
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from language_learning.anki_insights import build_insights, knowledge_estimate, lexical_key
from language_learning.story_anki import StoryAnkiService
from language_learning.errors import LanguageValidationError


class AnkiInsightsPolicyTests(unittest.TestCase):
    def test_exact_simple_words_only_link_to_vocabulary(self):
        self.assertEqual(lexical_key("en jobb [sound:word.mp3]"), "jobb")
        self.assertEqual(lexical_key("<b>huset</b>"), "huset")
        self.assertIsNone(lexical_key("Han gikk hjem."))
        self.assertIsNone(lexical_key("en lang dag"))

    def test_latest_again_caps_knowledge_even_after_long_interval(self):
        card = {"interval": 45, "reps": 10, "lapses": 1}
        reviews = [[1000, 10, 0, 4, 30, 15, 2500, 2000, 1],
                   [2000, 10, 0, 1, 0, 45, 2500, 3000, 1]]
        estimate = knowledge_estimate(card, reviews)
        self.assertEqual(estimate["status"], "LEARNING")
        self.assertLessEqual(estimate["score"], 39)
        self.assertEqual(estimate["lastRating"], 1)

    def test_story_phrases_are_source_substrings(self):
        sentences = [{"id": "one", "exact_text": "På lørdag våknet Jonas litt senere enn vanlig, og det var fint."},
                     {"id": "two", "exact_text": "Han gikk hjem."}]
        phrases = StoryAnkiService._phrase_candidates(sentences)
        self.assertEqual(phrases, [("På lørdag våknet Jonas litt senere enn vanlig", "one")])

    def test_history_separates_first_introductions_from_review_answers(self):
        now = int(datetime.now(ZoneInfo("Europe/Warsaw")).timestamp() * 1000)
        result = build_insights(
            deck_name="Test", counts={"new": 3, "learn": 1, "due": 2},
            options={"new": {"perDay": 5}, "rev": {"perDay": 30}},
            cards=[{"cardId": 1, "note": 10, "queue": 2, "interval": 8, "reps": 2,
                    "fields": {"Front": {"value": "hund", "order": 0}, "Back": {"value": "dog", "order": 1}}}],
            reviews=[[now - 100, 1, 0, 3, 1, 0, 2500, 1000, 0],
                     [now, 1, 0, 3, 8, 1, 2500, 2000, 1]],
            forecast_ids=[set() for _ in range(14)], vocabulary={}, observed_at="now",
        )
        self.assertEqual(result["today"]["newIntroduced"], 1)
        self.assertEqual(result["today"]["reviewAnswers"], 1)
        self.assertEqual(result["today"]["answered"], 2)
        self.assertEqual(result["forecast"][0]["possibleNew"], 0)

    def test_material_progress_classifies_every_card_once_with_suspension_first(self):
        cards = [
            {"cardId": 1, "type": 2, "queue": 2, "interval": 21, "reps": 3},
            {"cardId": 2, "type": 2, "queue": -3, "interval": 45, "reps": 5},
            {"cardId": 3, "type": 2, "queue": 2, "interval": 20, "reps": 2},
            {"cardId": 4, "type": 1, "queue": 1, "interval": 0, "reps": 1},
            {"cardId": 5, "type": 0, "queue": 0, "interval": 0, "reps": 0},
            {"cardId": 6, "type": 0, "queue": -1, "interval": 0, "reps": 0},
            {"cardId": 7, "type": 2, "queue": -2, "interval": 90, "reps": 10},
            {"cardId": 8, "type": 0, "queue": -2, "interval": 0, "reps": 0},
        ]
        result = build_insights(
            deck_name="Test", counts={"new": 0, "learn": 0, "due": 0}, options={},
            cards=cards, reviews=[], forecast_ids=[set() for _ in range(14)],
            vocabulary={}, observed_at="now",
        )
        distribution = result["inventory"]["materialProgress"]
        self.assertEqual(distribution, {"mature": 2, "learningYoung": 2, "unseen": 2, "suspended": 2})
        self.assertEqual(sum(distribution.values()), result["inventory"]["totalCards"])

    def test_story_creation_is_staged_and_retry_does_not_duplicate_cards_or_media(self):
        class FakeAdapter:
            def __init__(self):
                self.decks = []
                self.notes = []
                self.media = []
                self.syncs = 0

            def capabilities(self):
                return SimpleNamespace(version=6)

            def create_deck(self, name):
                self.decks.append(name)
                return len(self.decks)

            def can_add_notes(self, notes):
                existing = {item["fields"]["Front"] for item in self.notes}
                return [item["fields"]["Front"] not in existing for item in notes]

            def store_media_file(self, filename, data):
                self.media.append(filename)
                return filename

            def add_notes(self, notes):
                self.notes.extend(notes)
                return list(range(1, len(notes) + 1))

            def sync_web(self):
                self.syncs += 1

        with tempfile.TemporaryDirectory() as folder:
            sound = Path(folder) / "sound.mp3"
            sound.write_bytes(b"mp3")
            adapter = FakeAdapter()
            sync = SimpleNamespace(_adapter=lambda *args, **kwargs: adapter, _insights_cache=None)
            store = SimpleNamespace(get_text=lambda _id: {"document": {
                "processing_state": "ANALYZED", "language_profile_id": "profile", "content_fingerprint": "hash",
            }})
            service = SimpleNamespace(store=store, anki_sync_service=sync,
                                      _require_generated_audio=lambda: SimpleNamespace(
                                          generate=lambda *args: {"cacheKey": "audio"}),
                                      generated_audio_file=lambda _key: (sound, "audio/mpeg"))
            story = StoryAnkiService(service)
            plan = {"textId": "text", "profileId": "profile", "contentFingerprint": "hash",
                    "deckName": "Reader Stories::Example", "order": ["01 Words", "02 Phrases", "03 Sentences"],
                    "cards": [
                        {"stage": "words", "source": "hund", "english": "dog", "sentenceId": "one"},
                        {"stage": "phrases", "source": "en liten hund", "english": "a small dog", "sentenceId": "one"},
                        {"stage": "sentences", "source": "Han så en hund.", "english": "He saw a dog.", "sentenceId": "one"},
                    ]}
            story._plans["preview"] = (time.monotonic(), plan)
            with self.assertRaises(LanguageValidationError):
                story.create("text", "preview", {"9": "invalid"})
            with self.assertRaises(LanguageValidationError):
                story.create("text", "preview", source_overrides={"2": "Different sentence"})
            first = story.create("text", "preview", {"0": "a dog"}, {"0": "en hund"})
            second = story.create("text", "preview", {"0": "a dog"}, {"0": "en hund"})
            self.assertEqual(first["created"], 3)
            self.assertEqual(second["created"], 0)
            self.assertEqual(second["skippedDuplicates"], 3)
            self.assertEqual(len(adapter.media), 1)
            self.assertEqual([item["deckName"].split("::")[-1] for item in adapter.notes],
                             ["01 Words", "02 Phrases", "03 Sentences"])
            self.assertIn("[sound:dashboard_story_", adapter.notes[-1]["fields"]["Back"])
            self.assertEqual(adapter.notes[0]["fields"]["Back"], "a dog")
            self.assertEqual(adapter.notes[0]["fields"]["Front"], "en hund")


if __name__ == "__main__":
    unittest.main()

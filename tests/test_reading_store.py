import tempfile
import unittest
from pathlib import Path

from reading_store import ReadingError, ReadingStore


class ReadingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ReadingStore(Path(self.temp_dir.name) / "reading.sqlite")
        self.store.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def legacy_sources():
        primary = {
            "books": [{
                "row": 7,
                "title": "Testowa książka",
                "author": "Jan Autor",
                "pagesRead": 10,
                "pagesAll": 200,
                "returnDate": "2099-09-20",
            }],
            "stats": {"updated": "2026-08-27"},
        }
        remote = {
            "activeBooks": [{
                "book_id": "testowa_ksiazka",
                "title": "Testowa książka",
                "author": "Jan Autor",
                "pagesRead": 12,
                "pagesTotal": 200,
                "dueDate": "2099-09-20",
            }],
            "dailyStats": {"todayRead": 5},
        }
        history = {
            "log": {
                "2026-08-26": {
                    "total": 5,
                    "books": {"Testowa książka - Jan Autor": 5},
                    "progress": {
                        "remote:testowa_ksiazka": {
                            "key": "remote:testowa_ksiazka",
                            "label": "Testowa książka - Jan Autor",
                            "title": "Testowa książka",
                            "author": "Jan Autor",
                            "start": 7,
                            "current": 12,
                            "trackingVersion": 2,
                            "saveCount": 1,
                        },
                    },
                },
            },
            "startKey": "2026-08-26",
            "forecastPlan": None,
        }
        settings = {
            "activeMap": {"remote:testowa_ksiazka": True},
            "ownershipMap": {"remote:testowa_ksiazka": "library"},
            "selectedBook": {"remoteId": "testowa_ksiazka", "key": "remote:testowa_ksiazka"},
            "remotePages": {"testowa_ksiazka": 12},
            "updatedAt": 123,
        }
        return primary, remote, history, settings

    def test_import_preserves_books_history_and_settings(self):
        result = self.store.import_initial(*self.legacy_sources())

        self.assertEqual(result["books"], 1)
        self.assertEqual(result["activeBooks"], 1)
        self.assertEqual(result["historyDays"], 1)
        self.assertEqual(result["historyPages"], 5)
        book = self.store.get_book("testowa_ksiazka")
        self.assertEqual(book["pagesRead"], 12)
        self.assertEqual(book["source"], "library")
        self.assertEqual(self.store.history(), self.legacy_sources()[2])
        self.assertEqual(self.store.get_settings(), self.legacy_sources()[3])

    def test_progress_update_is_transactional_and_can_record_history(self):
        self.store.import_initial(*self.legacy_sources())
        result = self.store.update_progress(
            "testowa_ksiazka",
            19,
            record_history=True,
            day="2026-08-27",
        )

        self.assertEqual(result["previous_page"], 12)
        self.assertEqual(result["page_current"], 19)
        today = self.store.history()["log"]["2026-08-27"]
        self.assertEqual(today["total"], 7)
        self.assertEqual(today["progress"]["remote:testowa_ksiazka"]["start"], 12)
        self.assertEqual(today["progress"]["remote:testowa_ksiazka"]["current"], 19)

        self.store.update_progress("testowa_ksiazka", 15, record_history=False, day="2026-08-27")
        self.assertEqual(self.store.get_book("testowa_ksiazka")["pagesRead"], 15)
        self.assertEqual(self.store.history()["log"]["2026-08-27"]["total"], 7)

    def test_import_refuses_to_overwrite_existing_data(self):
        sources = self.legacy_sources()
        self.store.import_initial(*sources)
        with self.assertRaises(ReadingError) as caught:
            self.store.import_initial(*sources)
        self.assertEqual(caught.exception.code, "database_not_empty")

    def test_import_rolls_back_books_when_history_is_invalid(self):
        primary, remote, history, settings = self.legacy_sources()
        history["log"] = {"not-a-date": {"total": 1, "books": {"Test": 1}}}

        with self.assertRaises(ReadingError):
            self.store.import_initial(primary, remote, history, settings)

        self.assertEqual(self.store.count_books(), 0)
        self.assertEqual(self.store.history()["log"], {})

    def test_create_book_validates_page_range(self):
        with self.assertRaises(ReadingError):
            self.store.create_book({
                "title": "Błędna",
                "author": "Autorka",
                "pagesRead": 101,
                "pagesTotal": 100,
            })

    def test_update_book_edits_metadata_without_changing_id(self):
        created = self.store.create_book({
            "title": "Stary tytuł",
            "author": "Stary autor",
            "pagesRead": 10,
            "pagesTotal": 100,
            "source": "owned",
        })

        updated = self.store.update_book(created["book_id"], {
            "title": "Nowy tytuł",
            "author": "Nowy autor",
            "pagesRead": 25,
            "pagesTotal": 120,
            "source": "library",
            "returnDate": "2026-09-30",
        })

        self.assertEqual(updated["book_id"], created["book_id"])
        self.assertEqual(updated["title"], "Nowy tytuł")
        self.assertEqual(updated["author"], "Nowy autor")
        self.assertEqual(updated["pagesRead"], 25)
        self.assertEqual(updated["pagesTotal"], 120)
        self.assertEqual(updated["source"], "library")
        self.assertEqual(updated["returnDate"], "2026-09-30")

        returned = self.store.update_book(created["book_id"], {"returnDate": None})
        self.assertEqual(returned["source"], "library")
        self.assertIsNone(returned["returnDate"])


if __name__ == "__main__":
    unittest.main()

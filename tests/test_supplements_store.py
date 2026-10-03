import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from habits_store import HabitsStore
from supplements_store import SupplementsStore


class SupplementsStoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        seed = Path(self.folder.name) / "seed.json"
        names = ("Biotyna/B complex", "Vitamin D", "Omega 3", "Creatine", "Magnesium", "Zinc")
        old_day = int(datetime(2026, 9, 28, tzinfo=timezone.utc).timestamp() * 1000)
        seed.write_text(json.dumps({"habits": [
            {"id": i, "name": name, "type": 1 if name == "Creatine" else 0,
             "unit": "mg" if name == "Creatine" else "",
             "points": [[old_day, 5000 if name == "Creatine" else 2]]}
            for i, name in enumerate(names)
        ]}), encoding="utf-8")
        self.store = HabitsStore(Path(self.folder.name) / "habits.sqlite")
        self.store.initialize(seed)
        self.supplements = SupplementsStore(self.store)

    def test_dated_products_and_daily_schedule(self):
        old = self.supplements.snapshot("2026-09-28")
        self.assertEqual([], old["items"])
        self.assertEqual(6, len(old["catalog"]))
        tuesday = {item["displayName"]: item for item in self.supplements.snapshot("2026-09-29")["items"]}
        self.assertEqual(("morning", 2, "OstroVit"),
                         (tuesday["Omega-3"]["slot"], tuesday["Omega-3"]["unitsPerIntake"], tuesday["Omega-3"]["product"]["brand"]))
        self.assertEqual("Vitamin D3 + K2", tuesday["Vitamin D3 + K2"]["displayName"])
        self.assertTrue(tuesday["Vitamin B Complex"]["due"])
        self.assertTrue(tuesday["Vitamin D3 + K2"]["due"])
        self.assertFalse(tuesday["Magnesium"]["due"])
        self.assertFalse(tuesday["Zinc"]["due"])
        self.assertEqual((5, "g"), (tuesday["Creatine"]["unitsPerIntake"], tuesday["Creatine"]["unit"]))
        wednesday = {item["displayName"]: item for item in self.supplements.snapshot("2026-09-30")["items"]}
        self.assertTrue(wednesday["Magnesium"]["due"])
        self.assertTrue(wednesday["Zinc"]["due"])
        with self.store._connect() as connection:
            self.assertEqual(5000, connection.execute("""SELECT e.value_milli FROM entries e
                JOIN habits h ON h.id=e.habit_id WHERE h.name='Creatine' AND e.date='2026-09-28'""").fetchone()[0])

    def test_taken_time_and_product_change_leave_old_logs_untouched(self):
        habit = next(h for h in self.store.snapshot()["habits"] if h["name"] == "Omega 3")
        day = "2026-09-29"
        mutation = {"mutationId": str(uuid.uuid4()), "entityType": "ENTRY", "entityId": f"{habit['id']}:{day}",
                    "operation": "UPSERT", "baseRevision": None,
                    "payload": {"habitId": habit["id"], "date": day, "status": "DONE", "valueMilli": None}}
        result = self.store.sync({"schemaVersion": 1, "deviceId": "test", "mutations": [mutation]})
        self.assertEqual([mutation["mutationId"]], result["acknowledgedMutationIds"])
        before = next(e for e in self.store.snapshot(day, day)["entries"] if e["habitId"] == habit["id"])
        self.assertIsNotNone(before["takenAt"])
        self.supplements.change_product({"habitId": habit["id"], "validFrom": "2026-12-10",
            "brand": "New brand", "productName": "New Omega", "form": "softgel", "unitName": "softgel",
            "ingredients": [{"name": "EPA", "amount": 300, "unit": "mg"}]})
        september = next(i for i in self.supplements.snapshot(day)["items"] if i["habitId"] == habit["id"])
        december = next(i for i in self.supplements.snapshot("2026-12-10")["items"] if i["habitId"] == habit["id"])
        self.assertEqual("OstroVit", september["product"]["brand"])
        self.assertEqual("New brand", december["product"]["brand"])
        after = next(e for e in self.store.snapshot(day, day)["entries"] if e["habitId"] == habit["id"])
        self.assertEqual(before, after)
        self.store.initialize()
        self.assertEqual(2, len(next(c for c in self.supplements.snapshot()["catalog"]
                                     if c["habitId"] == habit["id"])["products"]))

    def test_schedule_can_be_changed_without_touching_entries(self):
        catalog = next(c for c in self.supplements.snapshot()["catalog"] if c["displayName"] == "Magnesium")
        self.supplements.save_regimen({"habitId": catalog["habitId"], "effectiveFrom": "2026-10-01",
                                       "slot": "evening", "weekdaysMask": 127, "unitsPerIntake": 1})
        old = next(i for i in self.supplements.snapshot("2026-09-30")["items"] if i["habitId"] == catalog["habitId"])
        new = next(i for i in self.supplements.snapshot("2026-10-01")["items"] if i["habitId"] == catalog["habitId"])
        self.assertEqual("2026-09-29", old["product"]["validFrom"])
        self.assertTrue(old["due"])
        self.assertTrue(new["due"])
        self.assertEqual(2, len(next(c for c in self.supplements.snapshot()["catalog"]
                                     if c["habitId"] == catalog["habitId"])["regimens"]))


if __name__ == "__main__":
    unittest.main()

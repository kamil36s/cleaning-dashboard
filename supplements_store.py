"""Small, dated supplement catalog layered on the canonical Habits database."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone


START_DATE = "2026-09-29"
ALL_DAYS = 127  # Monday is bit 0.
MON_WED_FRI = 21
DEFAULTS = (
    ("Biotyna/B complex", "Vitamin B Complex", "Nature Pharm Polska", "Witamina B Complex", "tablet", "tablet", [
        ("Niacin / nicotinamide", 40, "mg"), ("Pantothenic acid", 5, "mg"),
        ("Vitamin B6", 5, "mg"), ("Riboflavin / B2", 5, "mg"), ("Thiamine / B1", 3, "mg"),
    ], "morning", ALL_DAYS, 1),
    ("Vitamin D", "Vitamin D3 + K2", "OstroVit", "Vitamin D3 + K2", "tablet", "tablet", [
        ("Vitamin D3", 50, "µg"), ("Vitamin D3", 2000, "IU"), ("Vitamin K2", 100, "µg"),
    ], "morning", ALL_DAYS, 1),
    ("Omega 3", "Omega-3", "OstroVit", "Omega 3 Extreme", "softgel", "softgel", [
        ("Fish oil", 1000, "mg"), ("EPA", 500, "mg"), ("DHA", 250, "mg"),
    ], "morning", ALL_DAYS, 2),
    ("Creatine", "Creatine", None, None, None, "g", [], "morning", ALL_DAYS, 5),
    ("Magnesium", "Magnesium", "Zenement", "Magnesium Citrate", "tablet", "tablet", [
        ("Elemental magnesium", 360, "mg"), ("Bamboo extract", 10, "mg"), ("L-leucine", 20, "mg"),
    ], "evening", MON_WED_FRI, 1),
    ("Zinc", "Zinc", "OstroVit", "Zinc Picolinate 15 mg", "tablet", "tablet", [
        ("Zinc", 15, "mg"),
    ], "evening", MON_WED_FRI, 1),
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _day(value):
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("Date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("Date must use YYYY-MM-DD")
    return parsed


def initialize_supplements(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS supplement_catalog (
            habit_id TEXT PRIMARY KEY REFERENCES habits(id), display_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplement_products (
            id TEXT PRIMARY KEY, habit_id TEXT NOT NULL REFERENCES habits(id),
            brand TEXT NOT NULL, product_name TEXT NOT NULL, form TEXT NOT NULL,
            unit_name TEXT NOT NULL, ingredients_json TEXT NOT NULL,
            valid_from TEXT NOT NULL, valid_to TEXT, created_at TEXT NOT NULL,
            UNIQUE(habit_id, valid_from)
        );
        CREATE TABLE IF NOT EXISTS supplement_regimens (
            id TEXT PRIMARY KEY, habit_id TEXT NOT NULL REFERENCES habits(id),
            product_id TEXT REFERENCES supplement_products(id),
            units_per_intake REAL NOT NULL, slot TEXT NOT NULL CHECK(slot IN ('morning','evening')),
            weekdays_mask INTEGER NOT NULL, effective_from TEXT NOT NULL,
            effective_to TEXT, created_at TEXT NOT NULL,
            UNIQUE(habit_id, effective_from)
        );
        CREATE TABLE IF NOT EXISTS supplement_slots (
            slot TEXT PRIMARY KEY CHECK(slot IN ('morning','evening')),
            local_time TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplement_slot_claims (
            local_date TEXT NOT NULL, slot TEXT NOT NULL, claimed_at TEXT NOT NULL,
            PRIMARY KEY(local_date, slot)
        );
        CREATE INDEX IF NOT EXISTS supplement_products_period_idx ON supplement_products(habit_id, valid_from);
        CREATE INDEX IF NOT EXISTS supplement_regimens_period_idx ON supplement_regimens(habit_id, effective_from);
    """)
    connection.execute("INSERT OR IGNORE INTO supplement_slots VALUES ('morning','09:00')")
    connection.execute("INSERT OR IGNORE INTO supplement_slots VALUES ('evening','20:00')")
    for name, display, brand, product, form, unit, ingredients, slot, mask, quantity in DEFAULTS:
        habit = connection.execute(
            "SELECT id FROM habits WHERE name=? AND category='SUPPLEMENT' AND deleted_at IS NULL", (name,)
        ).fetchone()
        if not habit:
            continue
        habit_id = habit[0]
        connection.execute("INSERT OR IGNORE INTO supplement_catalog VALUES (?,?)", (habit_id, display))
        product_id = None
        if brand:
            product_id = f"{habit_id}:product:{START_DATE}"
            connection.execute("""INSERT OR IGNORE INTO supplement_products
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                product_id, habit_id, brand, product, form, unit,
                json.dumps([{"name": n, "amount": v, "unit": u} for n, v, u in ingredients], ensure_ascii=False),
                START_DATE, None, _now(),
            ))
        connection.execute("""INSERT OR IGNORE INTO supplement_regimens
            VALUES (?,?,?,?,?,?,?,?,?)""", (
            f"{habit_id}:regimen:{START_DATE}", habit_id, product_id, quantity,
            slot, mask, START_DATE, None, _now(),
        ))


class SupplementsStore:
    def __init__(self, habits_store):
        self.habits_store = habits_store

    def snapshot(self, day=None):
        day = _day(day or date.today().isoformat()).isoformat()
        with self.habits_store._lock, self.habits_store._connect() as connection:
            connection.row_factory = sqlite3.Row
            slots = {r["slot"]: r["local_time"] for r in connection.execute("SELECT * FROM supplement_slots")}
            catalog = []
            items = []
            for row in connection.execute("""SELECT c.habit_id,c.display_name,h.name,h.type,h.unit,h.archived
                    FROM supplement_catalog c JOIN habits h ON h.id=c.habit_id
                    WHERE h.deleted_at IS NULL ORDER BY h.position"""):
                habit_id = row["habit_id"]
                products = [self._product(p) for p in connection.execute(
                    "SELECT * FROM supplement_products WHERE habit_id=? ORDER BY valid_from", (habit_id,))]
                regimens = [self._regimen(r) for r in connection.execute(
                    "SELECT * FROM supplement_regimens WHERE habit_id=? ORDER BY effective_from", (habit_id,))]
                catalog.append({"habitId": habit_id, "name": row["name"],
                                "displayName": row["display_name"], "products": products,
                                "regimens": regimens})
                regimen = next((r for r in reversed(regimens) if r["effectiveFrom"] <= day and
                                (r["effectiveTo"] is None or r["effectiveTo"] >= day)), None)
                if not regimen:
                    continue
                product = next((p for p in products if p["id"] == regimen["productId"] and
                                p["validFrom"] <= day and (p["validTo"] is None or p["validTo"] >= day)), None)
                entry = connection.execute("""SELECT status,value_milli,taken_at FROM entries
                    WHERE habit_id=? AND date=? AND deleted_at IS NULL""", (habit_id, day)).fetchone()
                due = bool(regimen["weekdaysMask"] & (1 << _day(day).weekday())) and not row["archived"]
                taken = bool(entry and (entry["status"] == "DONE" or
                              (row["type"] == "NUMERIC" and (entry["value_milli"] or 0) > 0)))
                items.append({"habitId": habit_id, "displayName": row["display_name"],
                              "type": row["type"], "unit": row["unit"], "slot": regimen["slot"],
                              "unitsPerIntake": regimen["unitsPerIntake"], "unitName": product["unitName"] if product else row["unit"],
                              "due": due, "status": "TAKEN" if taken else "MISSED" if entry else "NO_ENTRY",
                              "valueMilli": entry["value_milli"] if entry else None,
                              "takenAt": entry["taken_at"] if entry else None,
                              "product": product, "regimenId": regimen["id"]})
        return {"date": day, "slots": slots, "catalog": catalog, "items": items}

    @staticmethod
    def _product(row):
        return {"id": row["id"], "habitId": row["habit_id"], "brand": row["brand"],
                "productName": row["product_name"], "form": row["form"],
                "unitName": row["unit_name"], "ingredients": json.loads(row["ingredients_json"]),
                "validFrom": row["valid_from"], "validTo": row["valid_to"]}

    @staticmethod
    def _regimen(row):
        return {"id": row["id"], "habitId": row["habit_id"], "productId": row["product_id"],
                "unitsPerIntake": row["units_per_intake"], "slot": row["slot"],
                "weekdaysMask": row["weekdays_mask"], "effectiveFrom": row["effective_from"],
                "effectiveTo": row["effective_to"]}

    def save_slots(self, payload):
        import re
        times = payload.get("slots") if isinstance(payload, dict) else None
        if not isinstance(times, dict) or set(times) != {"morning", "evening"} or any(
            not isinstance(v, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", v) for v in times.values()
        ):
            raise ValueError("Both slot times must use HH:MM")
        with self.habits_store._lock, self.habits_store._connect() as connection:
            connection.executemany("UPDATE supplement_slots SET local_time=? WHERE slot=?",
                                   [(value, slot) for slot, value in times.items()])
        return self.snapshot()

    def save_regimen(self, payload):
        habit_id = str(payload.get("habitId") or "")
        start = _day(payload.get("effectiveFrom")).isoformat()
        slot = payload.get("slot")
        mask = payload.get("weekdaysMask")
        units = payload.get("unitsPerIntake")
        if slot not in ("morning", "evening") or not isinstance(mask, int) or not 1 <= mask <= ALL_DAYS:
            raise ValueError("Invalid slot or weekdays")
        try:
            units = float(units)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid quantity") from exc
        if not 0 < units <= 10000:
            raise ValueError("Invalid quantity")
        with self.habits_store._lock, self.habits_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("""SELECT * FROM supplement_regimens
                WHERE habit_id=? AND effective_to IS NULL ORDER BY effective_from DESC LIMIT 1""", (habit_id,)).fetchone()
            if not current or start < current["effective_from"]:
                raise ValueError("No active regimen for this supplement and date")
            if start == current["effective_from"]:
                connection.execute("""UPDATE supplement_regimens SET slot=?,weekdays_mask=?,units_per_intake=?
                    WHERE id=?""", (slot, mask, units, current["id"]))
            else:
                previous_day = (_day(start) - timedelta(days=1)).isoformat()
                connection.execute("UPDATE supplement_regimens SET effective_to=? WHERE id=?",
                                   (previous_day, current["id"]))
                connection.execute("""INSERT INTO supplement_regimens VALUES (?,?,?,?,?,?,?,?,?)""",
                                   (f"{habit_id}:regimen:{start}", habit_id, current["product_id"],
                                    units, slot, mask, start, None, _now()))
        return self.snapshot(start)

    def change_product(self, payload):
        habit_id = str(payload.get("habitId") or "")
        start = _day(payload.get("validFrom")).isoformat()
        brand = str(payload.get("brand") or "").strip()
        name = str(payload.get("productName") or "").strip()
        form = str(payload.get("form") or "").strip()
        unit = str(payload.get("unitName") or "").strip()
        ingredients = payload.get("ingredients")
        if not all((brand, name, form, unit)) or not isinstance(ingredients, list) or len(ingredients) > 30:
            raise ValueError("Product details and ingredients are required")
        for item in ingredients:
            if not isinstance(item, dict) or not item.get("name") or not item.get("unit") or not isinstance(item.get("amount"), (int, float)):
                raise ValueError("Invalid ingredient")
        with self.habits_store._lock, self.habits_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("""SELECT * FROM supplement_products
                WHERE habit_id=? AND valid_to IS NULL ORDER BY valid_from DESC LIMIT 1""", (habit_id,)).fetchone()
            regimen = connection.execute("""SELECT * FROM supplement_regimens
                WHERE habit_id=? AND effective_to IS NULL ORDER BY effective_from DESC LIMIT 1""", (habit_id,)).fetchone()
            if not current or not regimen or start <= current["valid_from"] or start <= regimen["effective_from"]:
                raise ValueError("New product must start after the current product and regimen")
            previous_day = (_day(start) - timedelta(days=1)).isoformat()
            connection.execute("UPDATE supplement_products SET valid_to=? WHERE id=?", (previous_day, current["id"]))
            connection.execute("UPDATE supplement_regimens SET effective_to=? WHERE id=?", (previous_day, regimen["id"]))
            product_id = f"{habit_id}:product:{start}"
            connection.execute("INSERT INTO supplement_products VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (product_id, habit_id, brand, name, form, unit,
                                json.dumps(ingredients, ensure_ascii=False), start, None, _now()))
            connection.execute("INSERT INTO supplement_regimens VALUES (?,?,?,?,?,?,?,?,?)",
                               (f"{habit_id}:regimen:{start}", habit_id, product_id,
                                regimen["units_per_intake"], regimen["slot"], regimen["weekdays_mask"],
                                start, None, _now()))
        return self.snapshot(start)

    def claim_slot(self, payload):
        slot = payload.get("slot")
        day = _day(payload.get("date")).isoformat()
        if slot not in ("morning", "evening"):
            raise ValueError("Invalid slot")
        if not any(item["slot"] == slot and item["due"] and item["status"] != "TAKEN"
                   for item in self.snapshot(day)["items"]):
            return {"claimed": False}
        with self.habits_store._lock, self.habits_store._connect() as connection:
            cursor = connection.execute("INSERT OR IGNORE INTO supplement_slot_claims VALUES (?,?,?)",
                                        (day, slot, _now()))
        return {"claimed": cursor.rowcount == 1}

import base64
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from finance_receipt_parser import detect_sections, normalize_ocr, parse_polish_receipt
from finance_receipts import ReceiptImporter
from finance_service import FinanceService
from tests.test_finance_pack_d1 import UnavailableOcr


SYNTHETIC_RECEIPT = """PEPCO
PARAGON FISKALNY
Koszyk na owoce
Opis: kwadratowy
1 x 9,00 9,00A
Słoik
2 x 6,00 12,00 B
RABAT
-1,00
SUMA PTU
PTU A 23% 3,93
SUMA PLN 20,00
ROZLICZENIE PŁATNOŚCI
Karta 20,00
03/03/2026 15:45
Numer transakcji 12345
Promocje i regulamin zwrotów na stronie sklepu
"""


def parsed(text=SYNTHETIC_RECEIPT, structure=None):
    return parse_polish_receipt(
        text, source_type="image", source_format="synthetic_d2", ocr_structure=structure,
    )


class FinanceReceiptParserD2Tests(unittest.TestCase):
    def test_contextual_normalization_preserves_traceability(self):
        result = normalize_ocr("SUMA PLH 2O, O0A\nKod OIL", None)
        self.assertEqual(result["lines"][0]["text"], "SUMA PLN 20,00A")
        self.assertGreaterEqual(len(result["lines"][0]["corrections"]), 1)
        self.assertEqual(result["lines"][1]["text"], "Kod OIL")

    def test_sections_total_payment_items_discount_and_footer(self):
        result = parsed()
        self.assertEqual(result["total_minor"], 2000)
        self.assertEqual(result["purchase_date"], "2026-03-03")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["raw_evidence"]["taxGroup"], "A")
        self.assertEqual(result["items"][1]["discount_minor"], 100)
        self.assertNotIn("Promocje", " ".join(item["raw_name"] for item in result["items"]))
        self.assertEqual(result["field_evidence"]["total"]["confidence"], "exact")
        self.assertEqual(result["diagnostics"]["reconciliation"]["differenceMinor"], 0)

    def test_total_due_wins_over_vat_amount(self):
        result = parsed("""Sklep
PARAGON FISKALNY
Produkt
1 x 39,99 39,99A
SUMA PTU
PTU A 23% 7,48
DO ZAPŁATY PLN 39,99
Płatność 39,99
2026-09-17
""")
        self.assertEqual(result["total_minor"], 3999)

    def test_supported_date_forms_are_canonical_iso(self):
        for source in ("2026-03-03", "03-03-2026", "03.03.2026", "03/03/2026"):
            with self.subTest(source=source):
                result = parsed(f"Sklep\nPARAGON FISKALNY\nSUMA PLN 1,00\nKarta 1,00\n{source}")
                self.assertEqual(result["purchase_date"], "2026-03-03")

    def test_weighted_multiline_item_and_reconciliation(self):
        result = parsed("""Sklep
PARAGON FISKALNY
Jabłka polskie
0,532 kg x 12,99 6,91C
DO ZAPŁATY 6,91
Gotówka 6,91
15.06.2026
""")
        self.assertEqual(result["items"][0]["quantity"], "0.532")
        self.assertEqual(result["items"][0]["unit"], "kg")
        self.assertEqual(result["items"][0]["total_price_minor"], 691)
        self.assertEqual(result["diagnostics"]["reconciliation"]["state"], "exact")

    def test_mismatch_remains_reviewable(self):
        result = parsed("""Sklep
PARAGON FISKALNY
Produkt
1 x 9,00 9,00A
SUMA PLN 21,00
Karta 21,00
2026-03-03
""")
        self.assertEqual(result["diagnostics"]["reconciliation"]["state"], "mismatch")
        self.assertNotEqual(result["diagnostics"]["reconciliation"]["differenceMinor"], 0)

    def test_geometry_is_sanitized_and_used(self):
        structure = {"pages": [{"pageNumber": 1, "width": 1000, "height": 2000, "lines": [
            {"text": line, "box": {"x": .1, "y": index / 20, "width": .8, "height": .04}}
            for index, line in enumerate(SYNTHETIC_RECEIPT.splitlines())
        ]}]}
        result = parsed(SYNTHETIC_RECEIPT, structure)
        self.assertTrue(result["diagnostics"]["hasGeometry"])
        self.assertIsNotNone(result["items"][0]["raw_evidence"]["box"])


class FinanceReceiptD2ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = FinanceService(self.root / "finance.sqlite")
        self.service.ensure_ready()
        self.service.receipts.importer = ReceiptImporter(UnavailableOcr())

    def tearDown(self):
        self.temp.cleanup()

    def test_product_taxonomy_has_practical_top_level_categories(self):
        roots = {
            item["name"]: item for item in self.service.receipt_product_categories()
            if item["parentId"] is None
        }
        self.assertGreaterEqual(len(roots), 19)
        for name in (
            "Zdrowie i leki", "Elektronika i AGD", "Odzież i obuwie",
            "Motoryzacja", "Ogród i rośliny",
            "Sport i rekreacja", "Książki i papiernicze", "Narzędzia i remont",
            "Zabawki i gry", "Tytoń i nikotyna", "Usługi",
        ):
            with self.subTest(name=name):
                self.assertIn(name, roots)
        self.assertNotIn("Dzieci i niemowlęta", roots)

    def test_structured_android_evidence_and_crop_are_canonical(self):
        image = Image.new("RGB", (1000, 2000), "white")
        buffer = BytesIO(); image.save(buffer, "JPEG")
        lines = SYNTHETIC_RECEIPT.splitlines()
        evidence = {
            "provider": "android_mlkit", "text": SYNTHETIC_RECEIPT,
            "pages": [{"pageNumber": 1, "width": 1000, "height": 2000, "lines": [
                {"text": line, "box": {"x": .1, "y": index / 20, "width": .8, "height": .04},
                 "elements": [{"text": line.split()[0], "box": {"x": .1, "y": index / 20, "width": .2, "height": .04}}]}
                for index, line in enumerate(lines)
            ]}],
        }
        receipt = self.service.import_receipt({
            "filename": "synthetic.jpg", "mimeType": "image/jpeg",
            "contentBase64": base64.b64encode(buffer.getvalue()).decode(), "pageNumber": 1,
            "ocrEvidence": evidence,
        })
        self.assertEqual(receipt["total"], 20.0)
        self.assertTrue(receipt["items"][0]["cropUrl"].endswith("/crop"))
        self.assertTrue(receipt["items"][0]["reviewGroupId"])
        self.assertEqual(receipt["items"][0]["reviewGroupItemCount"], 1)
        crop = self.service.receipt_item_crop(receipt["items"][0]["id"])
        self.assertEqual(crop["mimeType"], "image/jpeg")
        self.assertGreater(len(crop["content"]), 100)
        sources = self.service.receipt_sources(receipt["id"])
        self.assertTrue(sources[0]["diagnostics"]["hasGeometry"])
        with self.service.repository.read_connection() as connection:
            stored = json.loads(connection.execute(
                "SELECT ocr_structure_json FROM receipt_sources WHERE receipt_id=?", (receipt["id"],),
            ).fetchone()[0])
        self.assertEqual(stored["pages"][0]["width"], 1000)

    def test_guided_total_decision_is_audited_and_reruns_matching(self):
        image = Image.new("RGB", (10, 10), "white")
        buffer = BytesIO(); image.save(buffer, "JPEG")
        receipt = self.service.import_receipt({
            "filename": "review.jpg", "mimeType": "image/jpeg",
            "contentBase64": base64.b64encode(buffer.getvalue()).decode(),
            "ocrEvidence": {"provider": "android_mlkit", "text": "Sklep\nPARAGON FISKALNY\n03/03/2026"},
        })
        updated = self.service.apply_receipt_parse_review(receipt["id"], {"field": "total", "valueMinor": 2199})
        self.assertEqual(updated["total"], 21.99)
        self.assertEqual(updated["fieldEvidence"]["total"]["confidence"], "manual")
        with self.service.repository.read_connection() as connection:
            correction = connection.execute(
                "SELECT source FROM receipt_parse_corrections WHERE receipt_id=? AND field_name='total'", (receipt["id"],),
            ).fetchone()
        self.assertEqual(correction["source"], "guided_review")

    def test_delete_receipt_removes_private_sources_without_touching_transactions(self):
        payload = json.dumps({
            "schemaVersion": "finance-receipt-1",
            "receipt": {
                "retailer": "Fixture",
                "purchasedAt": "2026-09-17T12:00:00",
                "totalMinor": 399,
                "currency": "PLN",
                "items": [{"name": "Fixture", "quantity": "1", "unit": "szt", "totalMinor": 399}],
            },
        }).encode("utf-8")
        receipt = self.service.import_receipt({
            "filename": "delete-me.json", "mimeType": "application/json",
            "contentBase64": base64.b64encode(payload).decode("ascii"),
        })
        source_directory = self.service.receipts.storage_directory / receipt["id"]
        self.assertTrue(source_directory.is_dir())
        with self.service.repository.read_connection() as connection:
            transaction_count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        result = self.service.delete_receipt(receipt["id"])

        self.assertTrue(result["deleted"])
        self.assertTrue(result["transactionPreserved"])
        self.assertFalse(source_directory.exists())
        with self.service.repository.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM receipt_sources").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], transaction_count)

    def test_finished_product_review_clears_pending_receipt_state(self):
        payload = json.dumps({
            "schemaVersion": "finance-receipt-1",
            "receipt": {
                "retailer": "Fixture", "purchasedAt": "2026-09-17T12:00:00",
                "totalMinor": 399, "currency": "PLN",
                "items": [{"name": "Kubek", "quantity": "1", "unit": "szt", "totalMinor": 399}],
            },
        }).encode("utf-8")
        receipt = self.service.import_receipt({
            "filename": "complete.json", "mimeType": "application/json",
            "contentBase64": base64.b64encode(payload).decode("ascii"),
        })
        self.service.update_receipt_metadata(receipt["id"], {
            "merchant": "Fixture", "purchaseDate": "2026-09-17", "total": "3.99",
        })
        pending = self.service.receipt_detail(receipt["id"])
        self.assertEqual(pending["processingState"], "needs_review")
        group = self.service.receipt_item_groups()[0]
        category = next(item for item in self.service.receipt_product_categories() if item["name"] == "Dom")

        self.service.receipt_item_apply(group["id"], {
            "canonicalName": "Kubek", "productCategoryId": category["id"],
        })

        completed = self.service.receipt_detail(receipt["id"])
        self.assertEqual(completed["processingState"], "parsed")
        self.assertEqual(completed["status"], "inbox")
        self.assertNotIn("items", completed["parseReview"]["unresolved"])


if __name__ == "__main__":
    unittest.main()

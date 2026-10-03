import base64
import json
import tempfile
import unittest
from pathlib import Path

from finance_receipts import ReceiptImporter
from finance_service import FinanceService


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


def receipt_json(*, retailer="Biedronka", purchased="2026-09-14T10:00:00", total=1547,
                 receipt_id="fixture-1", name="MLEKO UHT 3,2", quantity="1", unit="szt",
                 unit_price=1547, discount=0, fiscal=None, product_code=None, barcode=None):
    payload = {
        "schemaVersion": "finance-receipt-1",
        "receipt": {
            "retailer": retailer,
            "purchasedAt": purchased,
            "totalMinor": total,
            "currency": "PLN",
            "externalReceiptId": receipt_id,
            "items": [{
                "name": name, "quantity": quantity, "unit": unit,
                "unitPriceMinor": unit_price, "totalMinor": total + discount,
                "discountMinor": discount, "productCode": product_code, "barcode": barcode,
            }],
        },
    }
    if fiscal:
        payload["receipt"]["fiscalIdentifier"] = fiscal
    return json.dumps(payload, ensure_ascii=False).encode()


class FinancePackDTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.service = FinanceService(self.root / "finance.sqlite")
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_receipt(self, content, filename="receipt.json", mime="application/json"):
        return self.service.import_receipt({
            "filename": filename, "mimeType": mime,
            "contentBase64": base64.b64encode(content).decode(),
        })

    def test_schema_is_additive_and_source_files_are_private(self):
        self.assertEqual(self.service.repository.schema_versions()[-1], 11)
        imported = self.import_receipt(receipt_json())
        self.assertTrue((self.root / "finance-receipts" / imported["id"]).is_dir())
        with self.service.repository.read_connection() as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"receipts", "receipt_sources", "receipt_items", "products", "retailer_product_aliases"}.issubset(tables))

    def test_biedronka_verified_shape_discount_and_deposit_reconcile(self):
        payload = {
            "protoVersion": "000",
            "header": [{"headerText": {"headerTextLines": "<div>BIEDRONKA</div>"}},
                       {"headerData": {"date": "2026-09-14T07:46:20Z"}}],
            "body": [
                {"sellLine": {"name": "Mydło", "vatId": "A", "price": 649, "total": 649, "quantity": "1", "isStorno": False}},
                {"discountLine": {"value": 150, "isDiscount": True, "vatId": "A"}},
                {"sellLine": {"name": "Napój", "vatId": "C", "price": 500, "total": 500, "quantity": "1", "isStorno": False}},
                {"pack": {"name": "But Plastik kaucja", "total": 50, "quantity": "1", "isNegative": False}},
                {"sumInCurrency": {"totalWithPacks": 1049, "currency": "PLN"}},
                {"fiscalFooter": {"billNumber": 47, "uniqueNumber": "EAZSYNTHETIC", "date": "2026-09-14T07:46:20Z"}},
            ],
        }
        result = self.import_receipt(json.dumps(payload).encode())
        self.assertEqual(result["sourceFormat"], "biedronka_eparagon_json_v1")
        self.assertEqual(result["validationState"], "valid_with_adjustments")
        self.assertEqual(result["items"][0]["discount"], 1.5)
        self.assertEqual(result["adjustments"][0]["kind"], "deposit")

    def test_text_receipt_parser_handles_zabka_discount_deposits_and_total(self):
        text = """Sklep Żabka nr ZF620
PARAGON FISKALNY
NAPOJ ENERGET RED BULL 0,25l
P-A
1szt. x7.99 7.99A
WODA ZYWIEC 1,5l-A
2szt. x4.20 8.40A
OPUST WODA ZYWIEC 1,5l-A
-2.42A
SUMA PLN
13.97
KAUCJA ZA PUSZKE
0.50
KAUCJA ZA BUT. PLASTIKOWA
1.00
DO ZAPŁATY
15.47 PLN
2026-09-17 11:30
EAZSYNTHETIC2
"""
        candidate = ReceiptImporter()._parse_receipt_text(text, "pdf", "polish_text_pdf_v1")
        state, difference = self.service.receipts._validation(candidate)
        self.assertEqual((state, difference), ("valid_with_adjustments", 0))
        self.assertEqual(candidate["items"][1]["discount_minor"], 242)
        self.assertEqual(sum(item["amount_minor"] for item in candidate["adjustments"]), 150)

    def test_duplicate_and_cross_representation_source_priority(self):
        structured = receipt_json(retailer="Żabka", fiscal="EAZSAME123", receipt_id="same")
        first = self.import_receipt(structured)
        duplicate = self.import_receipt(structured)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["id"], duplicate["id"])

        try:
            import pymupdf
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((50, 50), "Sklep Zabka\nPARAGON FISKALNY\nMLEKO UHT\n1szt. x15.47 15.47A\nDO ZAPLATY\n15.47 PLN\n2026-09-14 10:00\nEAZSAME123")
        pdf = document.tobytes()
        document.close()
        second_source = self.import_receipt(pdf, "same.pdf", "application/pdf")
        self.assertEqual(second_source["id"], first["id"])
        self.assertEqual(second_source["sourceFormat"], "generic_polish_receipt_json_v1")
        self.assertEqual(second_source["sourceCount"], 2)

    def test_image_without_local_ocr_is_preserved_for_review(self):
        result = self.import_receipt(b"\xff\xd8\xffsynthetic", "paper.jpg", "image/jpeg")
        self.assertEqual(result["sourceType"], "image")
        self.assertEqual(result["validationState"], "needs_review")
        self.assertEqual(result["itemCount"], 0)

    def test_exact_ambiguous_and_manual_transaction_matching(self):
        csv = "\n".join((HEADER,
            "14.09.2026;BIEDRONKA;Konto;Zakupy;-15,47;100,00",
            "14.09.2026;BIEDRONKA DRUGA KASA;Konto;Zakupy;-15,47;84,53", ""))
        self.service.import_csv(csv.encode(), "matching.csv")
        result = self.import_receipt(receipt_json())
        self.assertEqual(result["match"]["state"], "ambiguous")
        self.assertIsNone(result["transactionId"])
        selected = result["match"]["candidates"][0]["transactionId"]
        manual = self.service.match_receipt(result["id"], selected)
        self.assertEqual((manual["state"], manual["transactionId"]), ("manual", selected))

    def test_retailer_alias_learning_is_bulk_previewed_and_isolated(self):
        first = self.import_receipt(receipt_json(receipt_id="one"))
        group = self.service.receipt_item_groups()[0]
        food = next(item for item in self.service.receipt_product_categories() if item["name"] == "Nabiał")
        preview = self.service.receipt_item_preview(group["id"], {"canonicalName": "Mleko UHT 3,2%", "productCategoryId": food["id"], "remember": True})
        self.assertEqual(preview["changes"]["items"], 1)
        applied = self.service.receipt_item_apply(group["id"], {"canonicalName": "Mleko UHT 3,2%", "productCategoryId": food["id"], "remember": True})
        self.assertTrue(applied["remembered"])
        second = self.import_receipt(receipt_json(purchased="2026-09-15T10:00:00", receipt_id="two"))
        self.assertEqual(second["items"][0]["classificationSource"], "retailer_alias")
        third = self.import_receipt(receipt_json(retailer="Lidl", purchased="2026-09-16T10:00:00", receipt_id="three"))
        self.assertEqual(third["items"][0]["reviewState"], "unresolved")
        self.assertEqual(self.service.undo_receipt_item_review()["restored"], 1)

    def test_weighted_return_and_price_history_keep_raw_units(self):
        first = self.import_receipt(receipt_json(name="POMIDORY", quantity="0.532", unit="kg", total=1063, unit_price=1998, receipt_id="weighted"))
        item = first["items"][0]
        self.assertEqual((item["quantity"], item["unit"], item["unitPrice"]), ("0.532", "kg", 19.98))
        negative = receipt_json(name="ZWROT BUTELKI", quantity="1", unit="szt", total=-50, unit_price=-50, receipt_id="return", purchased="2026-09-15T10:00:00")
        returned = self.import_receipt(negative)
        self.assertEqual(returned["items"][0]["totalPrice"], -0.5)

    def test_product_code_barcode_learning_and_price_history(self):
        first = self.import_receipt(receipt_json(
            receipt_id="coded-one", product_code="SKU-42", barcode="5901234123457",
            total=500, unit_price=600, discount=100,
        ))
        group = self.service.receipt_item_groups()[0]
        category = next(item for item in self.service.receipt_product_categories() if item["name"] == "Nabiał")
        self.service.receipt_item_apply(group["id"], {
            "canonicalName": "Mleko testowe", "productCategoryId": category["id"], "remember": True,
        })
        product_id = self.service.receipt_detail(first["id"])["items"][0]["productId"]
        second = self.import_receipt(receipt_json(
            receipt_id="coded-two", purchased="2026-09-15T10:00:00", name="INNA NAZWA",
            product_code="SKU-42", barcode="5901234123457", total=550, unit_price=550,
        ))
        self.assertEqual(second["items"][0]["classificationSource"], "retailer_alias")
        detail = self.service.receipt_product(product_id)
        self.assertEqual((detail["barcode"], detail["purchaseCount"]), ("5901234123457", 2))
        self.assertEqual([item["effectivePrice"] for item in detail["priceHistory"]], [5.5, 5.0])
        alias = detail["retailerAliases"][0]
        self.assertEqual((alias["retailer_key"], alias["retailer_code"]), ("biedronka", "SKU-42"))

    def test_split_analytics_replace_transaction_category_without_double_counting(self):
        csv = "\n".join((HEADER, "14.09.2026;BIEDRONKA;Konto;Zakupy;-10,00;90,00", ""))
        self.service.import_csv(csv.encode(), "analytics.csv")
        imported = self.import_receipt(receipt_json(total=1000, unit_price=1000, receipt_id="analytics"))
        group = self.service.receipt_item_groups()[0]
        food = next(item for item in self.service.receipt_product_categories() if item["name"] == "Nabiał")
        self.service.receipt_item_apply(group["id"], {"canonicalName": "Mleko", "productCategoryId": food["id"], "remember": True})
        breakdown = self.service.analytics_payload("categories", {"period": "date_range", "dateFrom": "2026-09-01", "dateTo": "2026-09-30"})
        self.assertAlmostEqual(sum(item["amount"] for item in breakdown), 10.0)
        self.assertTrue(any(item["source"] == "receipt_items" for item in breakdown))
        self.assertEqual(self.service.receipt_detail(imported["id"])["transactionId"] is not None, True)

    def test_device_pairing_lookup_pending_and_revocation(self):
        device = self.service.pair_companion_device("Fixture phone")
        self.assertTrue(self.service.validate_companion_token(device["token"]))
        pending = self.service.save_pending_receipt_barcode({"barcode": "5901234123457", "name": "Produkt testowy"})
        self.assertTrue(pending["pending"])
        self.assertTrue(self.service.lookup_receipt_barcode("5901234123457")["known"])
        self.service.revoke_companion_device(device["id"])
        self.assertFalse(self.service.validate_companion_token(device["token"]))

    def test_receipts_never_change_transaction_amounts(self):
        csv = "\n".join((HEADER, "14.09.2026;BIEDRONKA;Konto;Zakupy;-15,47;100,00", ""))
        self.service.import_csv(csv.encode(), "safety.csv")
        with self.service.repository.read_connection() as connection:
            before = [tuple(row) for row in connection.execute("SELECT id,amount_minor,currency FROM transactions ORDER BY id")]
        self.import_receipt(receipt_json())
        with self.service.repository.read_connection() as connection:
            after = [tuple(row) for row in connection.execute("SELECT id,amount_minor,currency FROM transactions ORDER BY id")]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()

import base64
import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from finance_receipts import LocalTesseractOcr, ReceiptImporter, _empty_candidate
from finance_service import FinanceService


OCR_TEXT = """Sklep Zabka
PARAGON FISKALNY
MLEKO UHT
1szt. x15.47 15.47A
DO ZAPLATY
15.47 PLN
2026-09-14 10:00
EAZSYNTHETIC2
"""


class UnavailableOcr:
    def health(self):
        return {
            "available": False, "polishAvailable": False, "code": "tesseract_missing",
            "message": "Tesseract OCR is not installed or configured.", "languages": [],
            "commandSource": None,
        }

    def recognize(self, _content):
        return {"ok": False, "text": None, "state": "ocr_unavailable", **self.health()}


class FailingImporter:
    ocr_engine = UnavailableOcr()

    def parse(self, *_args, **_kwargs):
        candidate = _empty_candidate("json", "reprocess_failed")
        candidate.update({
            "processing_state": "ocr_failed", "processing_code": "fixture_failure",
            "processing_message": "Fixture retry failed.",
        })
        return candidate


def structured_receipt():
    return json.dumps({
        "schemaVersion": "finance-receipt-1",
        "receipt": {
            "retailer": "Zabka", "purchasedAt": "2026-09-14T10:00:00",
            "totalMinor": 1547, "currency": "PLN", "externalReceiptId": "d1-fixture",
            "items": [{"name": "MLEKO UHT", "quantity": "1", "unit": "szt",
                       "unitPriceMinor": 1547, "totalMinor": 1547}],
        },
    }).encode()


class FinancePackD1Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.service = FinanceService(self.root / "finance.sqlite")
        self.service.ensure_ready()
        self.service.receipts.importer = ReceiptImporter(UnavailableOcr())

    def tearDown(self):
        self.temp_dir.cleanup()

    def upload(self, content, filename, mime, **extra):
        payload = {
            "filename": filename, "mimeType": mime,
            "contentBase64": base64.b64encode(content).decode(), **extra,
        }
        return self.service.import_receipt(payload)

    def test_unavailable_ocr_is_explicit_and_unknown_total_stays_null(self):
        receipt = self.upload(b"\xff\xd8\xfffixture", "paper.jpg", "image/jpeg")
        self.assertEqual(receipt["processingState"], "ocr_unavailable")
        self.assertEqual(receipt["processingCode"], "tesseract_missing")
        self.assertIsNone(receipt["total"])
        health = self.service.receipt_processing_health()
        self.assertFalse(health["serverOcr"]["available"])
        self.assertEqual(health["serverOcr"]["code"], "tesseract_missing")

    def test_tesseract_health_distinguishes_missing_polish_and_ready(self):
        engine = LocalTesseractOcr()
        with mock.patch.object(engine, "_command_candidates", return_value=[]):
            self.assertEqual(engine.health()["code"], "tesseract_missing")
        with mock.patch.object(engine, "_command_candidates", return_value=[("tesseract", "path")]), mock.patch(
            "finance_receipts.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"List of languages\neng\n", stderr=b""),
        ):
            self.assertEqual(engine.health()["code"], "polish_language_missing")
        with mock.patch.object(engine, "_command_candidates", return_value=[("tesseract", "path")]), mock.patch(
            "finance_receipts.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"eng\npol\n", stderr=b""),
        ):
            self.assertTrue(engine.health()["polishAvailable"])

    def test_tesseract_reports_execution_failure_empty_and_success(self):
        from PIL import Image
        image = Image.new("RGB", (10, 10), "white")
        buffer = BytesIO(); image.save(buffer, format="PNG"); content = buffer.getvalue()
        engine = LocalTesseractOcr()
        ready = {"available": True, "polishAvailable": True, "code": None, "message": None,
                 "commandSource": "path", "languages": ["eng", "pol"], "command": "tesseract"}
        with mock.patch.object(engine, "health", return_value=ready), mock.patch(
            "finance_receipts.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"failure"),
        ):
            self.assertEqual(engine.recognize(content)["code"], "ocr_execution_failed")
        with mock.patch.object(engine, "health", return_value=ready), mock.patch(
            "finance_receipts.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"tiny", stderr=b""),
        ):
            self.assertEqual(engine.recognize(content)["code"], "ocr_empty")
        with mock.patch.object(engine, "health", return_value=ready), mock.patch(
            "finance_receipts.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=OCR_TEXT.encode(), stderr=b""),
        ):
            result = engine.recognize(content)
            self.assertTrue(result["ok"])
            self.assertIn(result["pageSegmentationMode"], {4, 6})
            self.assertEqual(set(result["candidateScores"]), {"4", "6"})

    def test_tesseract_ensemble_selects_layout_with_more_receipt_facts(self):
        from PIL import Image
        image = Image.new("RGB", (10, 10), "white")
        buffer = BytesIO(); image.save(buffer, format="PNG")
        engine = LocalTesseractOcr()
        ready = {"available": True, "polishAvailable": True, "code": None, "message": None,
                 "commandSource": "path", "languages": ["eng", "pol"], "command": "tesseract"}
        weak = b"PARAGON FISKALNY\nDO ZAPLATY\n15.47 PLN\n"
        with mock.patch.object(engine, "health", return_value=ready), mock.patch(
            "finance_receipts.subprocess.run",
            side_effect=[
                SimpleNamespace(returncode=0, stdout=OCR_TEXT.encode(), stderr=b""),
                SimpleNamespace(returncode=0, stdout=weak, stderr=b""),
            ],
        ):
            result = engine.recognize(buffer.getvalue())
        self.assertEqual(result["pageSegmentationMode"], 4)
        self.assertGreater(result["candidateScores"]["4"], result["candidateScores"]["6"])

    def test_android_ocr_evidence_is_parsed_by_the_canonical_backend(self):
        receipt = self.upload(
            b"\xff\xd8\xfffixture", "page-1.jpg", "image/jpeg",
            ocrEvidence={"provider": "android_mlkit", "text": OCR_TEXT},
        )
        self.assertEqual(receipt["sourceFormat"], "android_mlkit_ocr_v1")
        self.assertEqual(receipt["processingState"], "parsed")
        self.assertEqual((receipt["total"], receipt["itemCount"]), (15.47, 1))
        sources = self.service.receipt_sources(receipt["id"])
        self.assertEqual(sources[0]["ocrProvenance"], "android_mlkit")

    def test_image_import_keeps_better_android_evidence_when_desktop_ocr_is_weaker(self):
        from PIL import Image
        image = Image.new("RGB", (40, 80), "white")
        buffer = BytesIO(); image.save(buffer, format="JPEG")
        weak = "PARAGON FISKALNY\nDO ZAPLATY\n15.47 PLN"
        engine = SimpleNamespace(recognize=lambda _content: {
            "ok": True, "text": weak, "code": None, "pageSegmentationMode": 6,
            "candidateScores": {"4": 10, "6": 20},
        })
        importer = ReceiptImporter(engine)
        candidate = importer.parse(
            "page.jpg", "image/jpeg", buffer.getvalue(), OCR_TEXT, "android_mlkit",
        )
        self.assertEqual(candidate["source_format"], "android_mlkit_ocr_v1")
        self.assertEqual(candidate["diagnostics"]["selectedOcr"], "android_mlkit")
        self.assertIn("server_tesseract", candidate["diagnostics"]["ocrCandidateScores"])

    def test_scan_bundle_preserves_ordered_pages_and_archival_pdf(self):
        pdf = b"%PDF-1.4\n%fixture"
        receipt = self.upload(
            b"\xff\xd8\xffpage-one", "page-1.jpg", "image/jpeg",
            ocrEvidence={"provider": "android_mlkit", "text": OCR_TEXT},
            sourceRole="page", pageNumber=1,
            attachments=[
                {"filename": "page-2.jpg", "mimeType": "image/jpeg",
                 "contentBase64": base64.b64encode(b"\xff\xd8\xffpage-two").decode(),
                 "sourceRole": "page", "pageNumber": 2},
                {"filename": "scan.pdf", "mimeType": "application/pdf",
                 "contentBase64": base64.b64encode(pdf).decode(), "sourceRole": "archive"},
            ],
        )
        sources = self.service.receipt_sources(receipt["id"])
        self.assertEqual([(item["sourceRole"], item["pageNumber"]) for item in sources],
                         [("page", 1), ("page", 2), ("archive", None)])
        source = self.service.receipt_source_content(receipt["id"], sources[0]["id"])
        self.assertEqual(hashlib.sha256(source["content"]).hexdigest(),
                         hashlib.sha256(b"\xff\xd8\xffpage-one").hexdigest())

    def test_failed_reprocess_keeps_existing_facts_and_items(self):
        receipt = self.upload(structured_receipt(), "receipt.json", "application/json")
        self.service.receipts.importer = FailingImporter()
        retried = self.service.reprocess_receipt(receipt["id"])
        self.assertEqual((retried["total"], retried["itemCount"]), (15.47, 1))
        self.assertEqual(retried["processingCode"], "fixture_failure")

    def test_reprocess_is_idempotent_and_preserves_manual_metadata_and_classification(self):
        receipt = self.upload(structured_receipt(), "receipt.json", "application/json")
        categories = self.service.receipt_product_categories()
        category = categories[0]
        self.service.classify_receipt_item(receipt["items"][0]["id"], {"productCategoryId": category["id"]})
        self.service.update_receipt_metadata(receipt["id"], {"merchant": "Sklep reczny", "total": "16.00"})
        first = self.service.reprocess_receipt(receipt["id"])
        second = self.service.reprocess_receipt(receipt["id"])
        sources = self.service.receipt_sources(receipt["id"])
        self.assertEqual(first["id"], receipt["id"])
        self.assertEqual(len(sources), 1)
        self.assertEqual((first["retailer"], first["total"]), ("Sklep reczny", 16.0))
        self.assertEqual(second["itemCount"], 1)
        self.assertEqual(second["items"][0]["classificationSource"], "guided_review")
        self.assertEqual(second["fieldSources"]["merchant"], "manual")
        self.assertEqual(second["fieldSources"]["total"], "manual")

    def test_android_ocr_parse_reruns_deterministic_transaction_match(self):
        csv = "\n".join((
            "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji",
            "14.09.2026;ZABKA;Konto;Zakupy;-15,47;100,00", "",
        ))
        self.service.import_csv(csv.encode(), "matching.csv")
        receipt = self.upload(
            b"\xff\xd8\xfffixture", "page.jpg", "image/jpeg",
            ocrEvidence={"provider": "android_mlkit", "text": OCR_TEXT},
        )
        self.assertIn(receipt["match"]["state"], {"exact", "strong"})
        self.assertIsNotNone(receipt["transactionId"])

    def test_manual_transaction_link_survives_reprocessing(self):
        csv = "\n".join((
            "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji",
            "14.09.2026;INNY SKLEP;Konto;Zakupy;-99,00;100,00", "",
        ))
        self.service.import_csv(csv.encode(), "manual.csv")
        with self.service.repository.read_connection() as connection:
            transaction_id = connection.execute("SELECT id FROM transactions LIMIT 1").fetchone()["id"]
        receipt = self.upload(structured_receipt(), "receipt.json", "application/json")
        self.service.match_receipt(receipt["id"], transaction_id)
        retried = self.service.reprocess_receipt(receipt["id"])
        self.assertEqual((retried["transactionId"], retried["matchState"]), (transaction_id, "manual"))


if __name__ == "__main__":
    unittest.main()

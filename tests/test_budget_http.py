import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server
from finance_service import FinanceService


class BudgetHttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_service = server.FINANCE_SERVICE
        server.FINANCE_SERVICE = FinanceService(
            Path(cls.temp_dir.name) / "finance.sqlite"
        )
        server.FINANCE_SERVICE.ensure_ready()
        cls.httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        server.FINANCE_SERVICE = cls.original_service
        cls.temp_dir.cleanup()

    def request(self, path, *, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:8000",
            },
        )
        return urllib.request.urlopen(request, timeout=5)

    def test_budget_page_widget_and_api_open(self):
        with self.request("/budget.html") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"finance-csv-input", response.read())
        with self.request("/index.html") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'data-widget="budget"', response.read())
        with self.request("/api/budget") as response:
            payload = json.load(response)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["storage"], "sqlite")

    def test_private_finance_files_are_404(self):
        for path in ("/data/budget.json", "/data/finance.sqlite", "/data/finance-receipts/private.pdf"):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.request(path)
                self.assertEqual(raised.exception.code, 404)

    def test_import_is_idempotent_and_full_snapshot_write_is_gone(self):
        csv_data = (
            "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota\n"
            "01.01.2026;HTTP fixture;TEST 1234;Test;-1,00\n"
        ).encode("utf-8")
        payload = {
            "filename": "fixture.csv",
            "contentBase64": base64.b64encode(csv_data).decode("ascii"),
        }
        with self.request("/api/budget/import-csv", payload=payload) as response:
            first = json.load(response)
        with self.request("/api/budget/import-csv", payload=payload) as response:
            second = json.load(response)
        self.assertEqual(first["importResult"]["imported"], 1)
        self.assertEqual(second["importResult"]["duplicates"], 1)

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/budget/save", payload={"data": {"transactions": []}})
        self.assertEqual(raised.exception.code, 410)

    def test_pack_b_resources_rules_review_queries_and_analytics(self):
        with self.request("/api/budget/categories", payload={"name": "HTTP Food"}) as response:
            category = json.load(response)["category"]
        with self.request("/api/budget/rules", payload={
            "name": "HTTP deterministic",
            "priority": 10,
            "conditions": [{"field": "raw_description", "operator": "contains", "value": "PACK B HTTP"}],
            "actions": [
                {"field": "category", "valueId": category["id"]},
                {"field": "transaction_kind", "value": "expense"},
            ],
            "application": "future_only",
        }) as response:
            rule = json.load(response)["rule"]
        csv_data = (
            "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota\n"
            "02.01.2026;PACK B HTTP ITEM;TEST 1234;Raw;-2,00\n"
        ).encode("utf-8")
        with self.request("/api/budget/import-csv", payload={
            "filename": "pack-b.csv", "contentBase64": base64.b64encode(csv_data).decode("ascii"),
        }):
            pass
        with self.request("/api/budget/transactions?limit=1&transactionKind=expense&text=PACK%20B") as response:
            page = json.load(response)
        self.assertEqual(page["limit"], 1)
        self.assertGreaterEqual(page["total"], 1)
        transaction = page["transactions"][0]
        self.assertEqual(transaction["category"], "HTTP Food")
        with self.request(f"/api/budget/transactions/{transaction['id']}/classification") as response:
            explanation = json.load(response)["classification"]
        self.assertTrue(any(field["rule"] and field["rule"]["id"] == rule["id"] for field in explanation["fields"]))
        with self.request(f"/api/budget/rules/{rule['id']}/preview", payload={}) as response:
            preview = json.load(response)["preview"]
        self.assertEqual(preview["matched"], 1)
        with self.request("/api/budget/review?status=open") as response:
            self.assertIn("items", json.load(response))
        with self.request("/api/budget/review/groups?scope=selected_month&month=2026-01") as response:
            review = json.load(response)["data"]
        self.assertIn("groups", review)
        self.assertIn("allHistory", review["metrics"])
        self.assertIn("selectedPeriod", review["metrics"])
        if review["groups"]:
            with self.request(f"/api/budget/review/groups/{review['groups'][0]['id']}/transactions") as response:
                self.assertIn("transactions", json.load(response))
        with self.request("/api/budget/analytics/summary?period=date_range&dateFrom=2026-01-01&dateTo=2026-01-31") as response:
            analytics = json.load(response)
        self.assertIn("expenses", analytics["data"])
        with self.request("/api/budget/periods?period=latest_data_month") as response:
            period = json.load(response)["period"]
        self.assertNotEqual(period["period_start"], "")

    def test_pack_c_planning_routes_and_mutations_resolve(self):
        for resource in (
            "overview", "data-quality", "accounts", "obligations", "subscriptions", "bills", "upcoming",
            "recurring-candidates", "budgets", "planned-items", "goals", "safe-to-spend",
            "forecast", "report", "trends", "category-trends", "merchant-trends", "recurring-trends", "insights",
        ):
            with self.subTest(resource=resource):
                with self.request(f"/api/budget/{resource}") as response:
                    payload = json.load(response)
                self.assertTrue(payload["ok"])
                self.assertIn("data", payload)

        with self.request("/api/budget/goals", payload={
            "name": "HTTP emergency fund", "kind": "emergency_fund", "target": 50000,
            "allocated": 1000, "monthlyContribution": 500, "primary": True,
        }) as response:
            goal = json.load(response)["data"]
        self.assertEqual(goal["progressPercent"], 2)

        with self.request("/api/budget/obligations", payload={
            "name": "HTTP rent", "kind": "rent", "amount": 1000, "cadence": "monthly",
            "startDate": "2026-09-20", "nextExpectedDate": "2026-09-20", "confirmed": True,
        }) as response:
            obligation = json.load(response)["data"]
        self.assertEqual(obligation["kind"], "rent")

    def test_pack_d_receipt_routes_and_companion_remote_auth(self):
        receipt = {
            "schemaVersion": "finance-receipt-1",
            "receipt": {
                "retailer": "Biedronka",
                "purchasedAt": "2026-09-17T12:00:00",
                "totalMinor": 399,
                "currency": "PLN",
                "externalReceiptId": "http-pack-d",
                "items": [{"name": "Fixture", "quantity": "1", "unit": "szt", "unitPriceMinor": 399, "totalMinor": 399}],
            },
        }
        content = json.dumps(receipt, ensure_ascii=False).encode("utf-8")
        with self.request("/api/budget/receipts/import", payload={
            "filename": "fixture.json", "mimeType": "application/json",
            "contentBase64": base64.b64encode(content).decode("ascii"),
        }) as response:
            imported = json.load(response)["receipt"]
        with self.request("/api/budget/receipts") as response:
            self.assertTrue(any(item["id"] == imported["id"] for item in json.load(response)["receipts"]))
        with self.request(f"/api/budget/receipts/{imported['id']}") as response:
            self.assertEqual(json.load(response)["receipt"]["total"], 3.99)
        with self.request(f"/api/budget/receipts/{imported['id']}/sources") as response:
            sources = json.load(response)["sources"]
        self.assertEqual(len(sources), 1)
        with self.request(sources[0]["contentUrl"]) as response:
            self.assertEqual(response.read(), content)
            self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with self.request("/api/budget/receipts/processing-health") as response:
            self.assertIn("serverOcr", json.load(response)["health"])
        with self.request(f"/api/budget/receipts/{imported['id']}/reprocess", payload={}) as response:
            self.assertTrue(json.load(response)["receipt"]["reprocessed"])

        device = server.FINANCE_SERVICE.pair_companion_device("HTTP phone")

        class RemoteRequest:
            client_address = ("192.0.2.10", 12345)
            headers = {}
            _cors_origin = None

            def send_json(self, payload, status=200, **_kwargs):
                self.response = payload
                self.status = status

            def request_origin(self):
                return self.headers.get("Origin", "")

            def request_referer_origin(self):
                return server.origin_from_url(self.headers.get("Referer", ""))

        missing = RemoteRequest()
        self.assertFalse(server.Handler.authorize_api_request(missing, "/api/budget/receipts/import", require_origin=True))
        self.assertEqual(missing.status, 401)
        authorized = RemoteRequest()
        authorized.headers = {"Authorization": f"Bearer {device['token']}"}
        self.assertTrue(server.Handler.authorize_api_request(authorized, "/api/budget/receipts/import", require_origin=True))
        admin = RemoteRequest()
        self.assertFalse(server.Handler.authorize_api_request(admin, "/api/budget/companion/pair", require_origin=True))
        self.assertEqual(admin.status, 403)
        preview_path = f"/api/budget/receipts/{imported['id']}/sources/{sources[0]['id']}/content"
        companion_preview = RemoteRequest()
        companion_preview.headers = {"Authorization": f"Bearer {device['token']}"}
        self.assertFalse(server.Handler.authorize_api_request(companion_preview, preview_path))
        self.assertEqual(companion_preview.status, 403)
        same_origin_preview = RemoteRequest()
        same_origin_preview.headers = {"Host": "dashboard.example", "Referer": "https://dashboard.example/budget.html"}
        self.assertTrue(server.Handler.authorize_api_request(same_origin_preview, preview_path))
        crop_path = "/api/budget/receipt-items/item_fixture/crop"
        companion_crop = RemoteRequest()
        companion_crop.headers = {"Authorization": f"Bearer {device['token']}"}
        self.assertFalse(server.Handler.authorize_api_request(companion_crop, crop_path))
        self.assertEqual(companion_crop.status, 403)
        same_origin_crop = RemoteRequest()
        same_origin_crop.headers = {"Host": "dashboard.example", "Origin": "https://dashboard.example"}
        self.assertTrue(server.Handler.authorize_api_request(same_origin_crop, crop_path))

        with self.request(f"/api/budget/receipts/{imported['id']}/delete", payload={}) as response:
            deleted = json.load(response)["delete"]
        self.assertTrue(deleted["deleted"])
        self.assertTrue(deleted["transactionPreserved"])
        with self.request("/api/budget/receipts") as response:
            self.assertFalse(any(item["id"] == imported["id"] for item in json.load(response)["receipts"]))


if __name__ == "__main__":
    unittest.main()

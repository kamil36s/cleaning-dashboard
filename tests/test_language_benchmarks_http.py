import unittest

from tests import test_language_api


class BenchmarkHttpTests(unittest.TestCase):
    setUp = test_language_api.LanguageApiTests.setUp
    tearDown = test_language_api.LanguageApiTests.tearDown
    request = test_language_api.LanguageApiTests.request
    def test_benchmark_routes_auth_ownership_and_no_keys(self):
        root = f"/api/language/profiles/{self.profile['id']}/benchmarks"
        self.assertEqual(self.request("POST", root, {}, headers={"Origin": "https://evil.example"})[0], 403)
        status, body = self.request("POST", root, {})
        self.assertEqual(status, 201)
        run = body["data"]
        self.assertNotIn('"answer"', str(run))
        self.assertEqual(self.request("GET", root)[0], 200)
        other = self.service.create_profile({
            "languageCode": "nb", "locale": "nb-SE", "displayName": "Other"
        })["data"]["profile"]["id"]
        foreign = f"/api/language/profiles/{other}/benchmarks/{run['id']}"
        self.assertEqual(self.request("GET", foreign)[0], 404)
        self.assertEqual(self.request("POST", foreign + "/responses", {"itemId": run["items"][0]["id"], "response": "work"})[0], 404)
        own = f"{root}/{run['id']}"
        item = run["items"][0]
        self.assertEqual(self.request("POST", own + "/responses", {"itemId": item["id"], "response": item["options"][0]})[0], 200)
        self.assertEqual(self.request("GET", own)[1]["data"]["status"], "ACTIVE")
        self.assertEqual(self.request("POST", own + "/complete", {})[0], 409)
        self.assertEqual(self.request("GET", f"/api/language/profiles/{self.profile['id']}/norway-preparation")[0], 200)
        connection = __import__("http.client", fromlist=["HTTPConnection"]).HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", "/language_learning/benchmark_content/v1.json")
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 404)
        connection.close()


if __name__ == "__main__":
    unittest.main()

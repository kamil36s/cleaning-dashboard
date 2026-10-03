import unittest

from tests import test_language_api


class StudySessionHttpTests(unittest.TestCase):
    setUp = test_language_api.LanguageApiTests.setUp
    tearDown = test_language_api.LanguageApiTests.tearDown
    request = test_language_api.LanguageApiTests.request

    def test_read_only_preview_validates_duration_and_profile(self):
        root = f"/api/language/profiles/{self.profile['id']}/study-session"
        for minutes in (10, 20, 30):
            status, body = self.request("GET", f"{root}?minutes={minutes}")
            self.assertEqual(status, 200)
            self.assertLessEqual(body["data"]["plannedMinutes"], minutes)
            self.assertEqual(body["data"]["requestedMinutes"], minutes)
            self.assertEqual(body, self.request("GET", f"{root}?minutes={minutes}")[1])
        for query in ("", "?minutes=11", "?minutes=1000", "?minutes=20&minutes=30", "?minutes=20&extra=1"):
            self.assertEqual(self.request("GET", root + query)[0], 400)
        self.assertEqual(self.request("GET", f"/api/language/profiles/{'f' * 32}/study-session?minutes=20")[0], 404)


if __name__ == "__main__":
    unittest.main()

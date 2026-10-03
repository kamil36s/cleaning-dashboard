import unittest
from unittest import mock

import server


class FeelingsRemoteAuthTests(unittest.TestCase):
    def make_handler(self, token=""):
        handler = object.__new__(server.Handler)
        handler.headers = {"Authorization": f"Bearer {token}"} if token else {}
        handler.client_address = ("192.0.2.10", 12345)
        handler._cors_origin = None
        handler.send_json = mock.Mock()
        return handler

    def test_phone_token_allows_remote_read_and_write(self):
        with mock.patch.dict(server.os.environ, {"DASHBOARD_FEELINGS_TOKEN": "phone-secret"}, clear=False):
            read = self.make_handler("phone-secret")
            write = self.make_handler("phone-secret")
            self.assertTrue(read.authorize_api_request("/api/feelings/emotions"))
            self.assertTrue(write.authorize_api_request("/api/feelings/checkins", require_origin=True))

    def test_existing_habits_phone_token_can_be_reused(self):
        with mock.patch.dict(server.os.environ, {"DASHBOARD_HABITS_TOKEN": "existing-phone-secret"}, clear=False):
            handler = self.make_handler("existing-phone-secret")
            self.assertTrue(handler.authorize_api_request("/api/feelings/checkins", require_origin=True))

    def test_remote_feelings_request_rejects_missing_token(self):
        with mock.patch.dict(server.os.environ, {"DASHBOARD_FEELINGS_TOKEN": "phone-secret"}, clear=False):
            handler = self.make_handler()
            self.assertFalse(handler.authorize_api_request("/api/feelings/checkins", require_origin=True))
            handler.send_json.assert_called_once_with(
                {"error": "Authorization: Bearer token is required", "code": "missing_bearer_token"},
                status=401,
            )


if __name__ == "__main__":
    unittest.main()

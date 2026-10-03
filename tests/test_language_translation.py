import json
import unittest
from unittest.mock import patch

from language_learning.errors import LanguageError
from language_learning.providers.translation import GooglePublicTranslationProvider, ReaderTranslationProvider


class TranslationFallbackTests(unittest.TestCase):
    def test_google_public_response_joins_translation_segments(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return json.dumps([[['On Saturday', 'P\u00e5 l\u00f8rdag'], [' Jonas woke up.', ' v\u00e5knet Jonas.']]]).encode()

        with patch('language_learning.providers.translation.urllib.request.urlopen', return_value=FakeResponse()):
            result = GooglePublicTranslationProvider().translate('P\u00e5 l\u00f8rdag v\u00e5knet Jonas.', 'en')
        self.assertEqual(result, 'On Saturday Jonas woke up.')

    def test_failed_public_provider_falls_back_and_cools_down(self):
        class BrokenProvider:
            provider_id = 'BROKEN'
            calls = 0

            def translate(self, *_args):
                self.calls += 1
                raise LanguageError('unavailable', code='unavailable', status=502)

        class GoodProvider:
            provider_id = 'GOOD'

            def translate(self, *_args):
                return 'actually'

        broken = BrokenProvider()
        provider = ReaderTranslationProvider(cloud=broken, public=broken, public_fallback=GoodProvider())
        self.assertEqual(provider.translate('egentlig', 'en'), ('actually', 'GOOD'))
        self.assertEqual(provider.translate('egentlig', 'en'), ('actually', 'GOOD'))
        self.assertEqual(broken.calls, 2)


if __name__ == '__main__':
    unittest.main()

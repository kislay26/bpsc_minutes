import json
from pathlib import Path
import tempfile
import unittest

import gemini_quota as quota


class QuotaTests(unittest.TestCase):
    def test_structured_retry_delay(self):
        self.assertEqual(quota.retry_seconds({'details': [
            {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '48200.25s'}]}), 48200.25)

    def test_message_duration(self):
        self.assertEqual(quota.retry_seconds({'message': 'Please retry in 13h25m52.2s.'}), 48352.2)

    def test_cooldown_is_scoped_and_expires(self):
        with tempfile.TemporaryDirectory() as folder:
            quota.remember(folder, 'private-test-key', 'model-a', {'message': 'retry in 2m1s'}, now=100)
            self.assertEqual(quota.remaining(folder, 'private-test-key', 'model-a', now=120), 101)
            self.assertEqual(quota.remaining(folder, 'private-test-key', 'model-a', now=222), 0)
            self.assertEqual(quota.remaining(folder, 'another-key', 'model-a', now=120), 0)
            self.assertEqual(quota.remaining(folder, 'private-test-key', 'model-b', now=120), 0)
            for path in Path(folder).iterdir():
                self.assertNotIn('private-test-key', path.name + path.read_text())

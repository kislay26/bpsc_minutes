import unittest
import tempfile
import json
from pathlib import Path
from newspaper_batch import parse_pages, page_passed


class BatchTests(unittest.TestCase):
    def test_draft_or_wrong_source_is_never_accepted(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder/'crop_preview.pdf').write_bytes(b'draft')
            report = {'source_sha256': 'source', 'source_page': 1,
                      'native_geometry_checks_passed': True}
            (folder/'response.json').write_text(json.dumps(report))
            self.assertFalse(page_passed(folder, 0, 'source', 1))
            report['visual_audit_passed'] = True
            (folder/'response.json').write_text(json.dumps(report))
            self.assertTrue(page_passed(folder, 0, 'source', 1))
            self.assertFalse(page_passed(folder, 1, 'source', 1))
            self.assertFalse(page_passed(folder, 0, 'different', 1))
            self.assertFalse(page_passed(folder, 0, 'source', 2))

    def test_page_selection(self):
        self.assertEqual(parse_pages('3,1-3', 4), [1, 2, 3])
        self.assertEqual(parse_pages('all', 2), [1, 2])

    def test_invalid_pages(self):
        for value in ('0', '5', '3-1', '', '1-2-3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_pages(value, 4)

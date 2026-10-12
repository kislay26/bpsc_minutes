import json
import os
from pathlib import Path
import tempfile
import hashlib
import fitz
import unittest
from unittest.mock import patch

from core import Config, FlowError
from gemini_native import NativeGeminiVision, PageAssessment, printed_page_from_source
from gemini_budget import consume
from pdf_flow import Identity, Repair


class Reply:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
            {'text': '{"paper":"TH","edition_date":"2026-09-27"}'}]}}]}).encode()


class GeminiTests(unittest.TestCase):
    def test_printed_page_comes_from_unique_small_edge_marker(self):
        blocks = [
            {'bbox': [1347, 8, 1376, 31], 'text': '16'},
            {'bbox': [500, 1000, 600, 1020], 'text': '12'},
        ]
        self.assertEqual(printed_page_from_source(blocks, (0, 0, 1500, 2384)), '16')
        self.assertIsNone(printed_page_from_source(
            blocks + [{'bbox': [5, 8, 25, 31], 'text': '17'}], (0, 0, 1500, 2384)))

    def test_metadata_cannot_replace_native_crop_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source.pdf'
            with fitz.open() as doc:
                doc.new_page(width=200, height=300).insert_text((20, 30), 'Sample article')
                doc.save(source)
            target = root/'native-pages/TH-001'
            target.mkdir(parents=True)
            (target/'response.json').write_text(json.dumps({
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'source_page': 1, 'visual_audit_passed': True,
                'articles': {'A1': 'Sample article'}, 'owners': {'0': 'A1'},
                'regions': {'A1': [[20, 60, 100, 150]]}}))
            (target/'blocks.json').write_text(json.dumps([{'id': 0, 'text': 'Source text', 'bbox': [20, 60, 100, 150]}]))
            evidence = {'kind': 'noise', 'status': 'reported', 'pattern_ids': [], 'pyq_ids': [],
                        'syllabus_links': [], 'event_hook': '', 'prelim_facts': [], 'mains_angles': [],
                        'bihar_link': '', 'match_explanation': '', 'noise_reason': 'no_exam_substance'}
            metadata = PageAssessment.model_validate({'printed_page': 'II', 'articles': [{
                'article_id': 'A1', 'subject': 'Other GS', 'reason': 'No exam substance',
                'text_hint': 'Source text', 'continued_from': '', 'continues_to': [], 'evidence': evidence}]})
            omitted = PageAssessment.model_validate({'printed_page': 'II', 'articles': []})
            with_unrequested = PageAssessment.model_validate({
                'printed_page': 'II',
                'articles': [metadata.articles[0].model_dump(),
                             {**metadata.articles[0].model_dump(),
                              'article_id': 'Page 2 - Bureau of Energy Efficiency'}]})
            cfg = Config(root=root, provider='gemini', model='gemini-3.1-flash-lite', api_key='private-test-key')
            ai = NativeGeminiVision(cfg, root, {'TH': source})
            with patch('gemini_native.subprocess.run') as run, patch.object(
                    ai, 'ask', side_effect=[omitted, with_unrequested]) as ask, fitz.open(source) as doc:
                run.return_value.returncode = 0
                scan = ai.scan_page('TH', 1, doc[0])
            self.assertEqual(scan.printed_page, 'II')
            self.assertEqual(ask.call_count, 2)
            self.assertIn('one assessment for every supplied article ID',
                          ask.call_args_list[1].args[1])
            self.assertEqual([article.title for article in scan.articles], ['Sample article'])
            self.assertEqual(scan.articles[0].boxes[0].model_dump(), {'x0': 100, 'y0': 200, 'x1': 500, 'y1': 500})

    def test_evidence_schema_constrains_ids_to_policy_catalog(self):
        from news_selection import NewsSelector
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = Config(root=root, provider='gemini', api_key='private-test-key', model='gemini-3.5-flash-lite')
            ai = NativeGeminiVision(cfg, root, {})
            with patch('gemini_native.urllib.request.urlopen', return_value=Reply()) as network:
                with self.assertRaises(FlowError):
                    ai.ask(PageAssessment, 'Assess source')
            payload = json.loads(network.call_args.args[0].data)
            fields = payload['generationConfig']['responseJsonSchema']['$defs']['SelectionEvidence']['properties']
            policy = NewsSelector(Path(__file__).resolve().parents[1]/'selection_skill')
            self.assertEqual(set(fields['pattern_ids']['items']['enum']), set(policy.patterns))
            self.assertEqual(set(fields['pyq_ids']['items']['enum']), set(policy.evidence))
            self.assertFalse(set(policy.patterns) & set(policy.evidence))

    def test_config_uses_private_gemini_key(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'private-test-key'}, clear=True), patch('core.load_env'):
            cfg = Config.from_env()
            cfg.require(telegram=False)
            self.assertEqual(cfg.api_key, 'private-test-key')
            self.assertEqual(cfg.model, 'gemini-3.1-flash-lite')
            self.assertIn('googleapis.com', cfg.ai_base)

    def test_request_cache_and_shared_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = Config(root=root, provider='gemini', api_key='private-test-key',
                         model='gemini-3.1-flash-lite', max_calls=1)
            ai = NativeGeminiVision(cfg, root, {})
            with patch('gemini_native.urllib.request.urlopen', return_value=Reply()) as network:
                self.assertEqual(ai.ask(Identity, 'read date').paper, 'TH')
                self.assertEqual(ai.ask(Identity, 'read date').paper, 'TH')
                self.assertEqual(network.call_count, 1)
                req = network.call_args.args[0]
                self.assertNotIn('private-test-key', req.full_url)
                self.assertNotIn('private-test-key', req.data.decode())
                with self.assertRaises(FlowError):
                    consume(ai.budget, 1)
                with self.assertRaises(FlowError):
                    ai.ask(Repair, 'invent new coordinates')
            for path in root.rglob('*.json'):
                self.assertNotIn('private-test-key', path.read_text(encoding='utf-8'))

    def test_printed_page_label_normalization_no_conflict(self):
        """Batch assessments with 'page 9' vs '9' vs 'PAGE 9' must not raise FlowError."""
        import re
        def _norm_label(s: str) -> str:
            return re.sub(r'^(?:page|p\.?)\s*', '', s.strip(), flags=re.I).upper()
        labels = ['9', 'page 9', 'PAGE 9', 'p. 9', 'P.9']
        for a in labels:
            for b in labels:
                self.assertEqual(_norm_label(a), _norm_label(b),
                                 f'{a!r} and {b!r} should normalize equally')

    def test_network_timeout_retries_and_succeeds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = Config(root=root, provider='gemini', api_key='private-test-key',
                         model='gemini-3.1-flash-lite', max_calls=5)
            ai = NativeGeminiVision(cfg, root, {})
            with patch('gemini_native.urllib.request.urlopen', side_effect=[TimeoutError('timed out'), Reply()]) as network, \
                 patch('gemini_native.time.sleep') as mock_sleep:
                result = ai.ask(Identity, 'read date')
                self.assertEqual(result.paper, 'TH')
                self.assertEqual(network.call_count, 2)
                mock_sleep.assert_called_once_with(5)


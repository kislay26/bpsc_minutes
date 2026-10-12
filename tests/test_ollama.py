"""Provider contract tests. A local HTTP stub is not a real Ollama model."""
import base64
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from core import Config, FlowError, runner_lock
from pdf_flow import Check, Identity, Vision
from bot import check_model, ModelProbe


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.requests = []
        self.answer = {'done': True, 'done_reason': 'stop', 'message': {
            'content': '{"paper":"TH","edition_date":"2026-09-22"}'}}
        self.model_info = {'capabilities': ['completion', 'vision']}
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                case.requests.append((self.path, payload, dict(self.headers)))
                result = case.model_info if self.path == '/api/show' else case.answer
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.cfg = Config(self.root, provider='ollama', model='qwen3-vl:4b',
                          api_key='must-not-be-sent',
                          ai_base=f'http://127.0.0.1:{self.server.server_port}')

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_http_image_schema_contract_and_cached_retry(self):
        vision = Vision(self.cfg, self.root)
        images = [('Original', b'first-image'), ('Cutting', b'second-image')]
        answer = vision.ask(Identity, 'Read the masthead.', images)
        self.assertEqual(answer.paper, 'TH')
        path, body, headers = self.requests[-1]
        self.assertEqual(path, '/api/chat')
        self.assertNotIn('Authorization', headers)
        self.assertFalse(body['stream'])
        self.assertEqual(body['format'], Identity.model_json_schema())
        self.assertEqual(body['options']['num_ctx'], 32768)
        self.assertEqual([m['content'] for m in body['messages'][2:]], ['Original', 'Cutting'])
        self.assertEqual(base64.b64decode(body['messages'][2]['images'][0]), b'first-image')
        vision.ask(Identity, 'Read the masthead.', images)
        self.assertEqual(len(self.requests), 2)  # show + chat, then cache
        self.assertEqual(vision.calls, 1)

    def test_cached_newspaper_unicode_survives_restart(self):
        issue = 'Bihar \u2014 \u20b9500 crore; headline\u2019s final column missing'
        self.answer['message']['content'] = json.dumps({'ok': False, 'issues': [issue]})
        Vision(self.cfg, self.root).ask(Check, 'Check the cutting.')
        cached = Vision(self.cfg, self.root).ask(Check, 'Check the cutting.')
        self.assertEqual(cached.issues, [issue])
        self.assertEqual(sum(path == '/api/chat' for path, _, _ in self.requests), 1)

    def test_supported_optional_thinking_is_disabled(self):
        self.model_info['thinking'] = {'values': [False, True], 'default': True}
        Vision(self.cfg, self.root).ask(Identity, 'Read masthead.')
        self.assertIs(self.requests[-1][1]['think'], False)

    def test_qwen_thinking_disabled_when_server_omits_metadata(self):
        Vision(self.cfg, self.root).ask(Identity, 'Read masthead.')
        self.assertIs(self.requests[-1][1]['think'], False)

    def test_explicit_thinking_levels_are_respected(self):
        self.model_info['thinking'] = {'values': ['low', 'high'], 'default': 'low'}
        Vision(self.cfg, self.root).ask(Identity, 'Read masthead.')
        self.assertNotIn('think', self.requests[-1][1])

    def test_truncated_reply_reports_reason_without_caching_content(self):
        self.answer.update(done_reason='length', eval_count=128)
        with self.assertRaisesRegex(FlowError, 'length'):
            Vision(self.cfg, self.root).ask(Identity, 'Read masthead.')
        status = json.loads((self.root / 'last_response_status.json').read_text(encoding='utf-8'))
        self.assertEqual(status['eval_count'], 128)
        self.assertNotIn('message', status)
        self.assertEqual(list((self.root / 'model_cache').glob('*.json')), [])

    def test_bad_or_truncated_outputs_are_not_cached(self):
        for response in [
            {'done': True, 'done_reason': 'length', 'message': {'content': '{}'}},
            {'done': False, 'message': {'content': '{}'}},
            {'done': True, 'done_reason': 'stop', 'message': {'content': 'not json'}},
            {'done': True, 'done_reason': 'stop', 'message': {'content': '{"paper":"FAKE"}'}},
        ]:
            self.answer = response
            with self.assertRaises(FlowError):
                Vision(self.cfg, self.root).ask(Identity, 'Read masthead.')
        self.assertEqual(list((self.root / 'model_cache').glob('*.json')), [])

    def test_nonvision_and_cloud_aliases_fail_before_generation(self):
        for info in [{'capabilities': ['completion']},
                     {'capabilities': ['vision'], 'remote_host': 'https://ollama.com'}]:
            self.model_info = info
            with self.assertRaises(FlowError):
                Vision(self.cfg, self.root).ask(Identity, 'Read.')
        self.assertTrue(all(path == '/api/show' for path, _, _ in self.requests))

    def test_limit_and_estimated_context_overflow_stop_generation(self):
        self.cfg.max_calls = 1
        vision = Vision(self.cfg, self.root)
        vision.ask(Identity, 'Read one.')
        with self.assertRaises(FlowError):
            vision.ask(Identity, 'Read two.')
        self.assertEqual(sum(path == '/api/chat' for path, _, _ in self.requests), 1)
        self.cfg.max_calls = 3
        with self.assertRaisesRegex(FlowError, 'OLLAMA_NUM_CTX'):
            vision.ask(Identity, 'x' * 100000)
        self.assertEqual(sum(path == '/api/chat' for path, _, _ in self.requests), 1)

    def test_model_change_invalidates_cache(self):
        Vision(self.cfg, self.root).ask(Identity, 'Same task')
        self.cfg.model = 'qwen3-vl:8b'
        Vision(self.cfg, self.root).ask(Identity, 'Same task')
        self.assertEqual(sum(path == '/api/chat' for path, _, _ in self.requests), 2)


class ConfigTests(unittest.TestCase):
    def test_probe_accepts_spacing_but_rejects_missing_or_extra_letters(self):
        cfg = Config(Path('.'), provider='ollama', model='qwen3-vl:4b-instruct',
                     ai_base='http://127.0.0.1:11434')
        for word, accepted in [('BPSC', True), (' BPS C\n', True),
                               ('b p s c', True), ('BPS', False),
                               ('BPSCX', False), ('BPS-C', False), ('', False)]:
            with self.subTest(word=word), patch('bot.Vision') as vision, patch('builtins.print'):
                vision.return_value.check_local_model.return_value = {}
                vision.return_value.ask.return_value = ModelProbe(word=word)
                if accepted:
                    check_model(cfg)
                else:
                    with self.assertRaisesRegex(FlowError, 'image-reading probe'):
                        check_model(cfg)

    def test_local_provider_needs_no_ai_key(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'qwen3-vl:4b',
                                     'OPENAI_API_KEY': 'unused'}, clear=True), patch('core.load_env'):
            cfg = Config.from_env()
        cfg.require(telegram=False)
        self.assertEqual(cfg.api_key, '')
        self.assertEqual(cfg.ai_base, 'http://127.0.0.1:11434')
        self.assertEqual(cfg.model_timeout, 1200)

    def test_openai_configuration_remains_supported(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'example-key', 'OPENAI_MODEL': 'test'}, clear=True), patch('core.load_env'):
            cfg = Config.from_env()
        cfg.require(telegram=False)
        self.assertEqual(cfg.provider, 'openai')
        self.assertEqual(cfg.ai_base, 'https://api.openai.com/v1')
        response = {'status': 'completed', 'output': [{'content': [
            {'type': 'output_text', 'text': '{"paper":"IE","edition_date":"2026-09-22"}'}]}]}
        with tempfile.TemporaryDirectory() as folder, patch('pdf_flow.request_json', return_value=response) as request:
            self.assertEqual(Vision(cfg, Path(folder)).ask(Identity, 'Read').paper, 'IE')
            self.assertTrue(request.call_args.args[0].endswith('/responses'))
            self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer example-key')

    def test_bad_provider_endpoint_and_cloud_model_rejected(self):
        for updates in [dict(provider='typo'), dict(ai_base='http://localhost:11434/api'),
                        dict(model='qwen3-vl:235b-cloud'), dict(ai_base='https://ollama.com'),
                        dict(context_tokens=1024)]:
            values = dict(root=Path('.'), provider='ollama', model='qwen3-vl:4b',
                          ai_base='http://localhost:11434')
            with self.assertRaises(FlowError):
                Config(**(values | updates)).require(telegram=False)

    def test_lock_blocks_second_worker_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            with runner_lock(Path(folder)):
                with self.assertRaises(FlowError):
                    with runner_lock(Path(folder)):
                        self.fail('Second worker acquired the lock')
            with runner_lock(Path(folder)):
                pass


if __name__ == '__main__':
    unittest.main()

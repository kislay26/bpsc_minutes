"""Private, low-friction Telegram conversation layer for Sol."""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

from core import Config, FlowError, Store
from transport import request_json
from web_curator import get_daily_brief

HOME = {'keyboard': [['Today', 'Ask Sol'], ['Practice 5', 'My Plan']],
        'resize_keyboard': True, 'is_persistent': True}
STAGES = {'keyboard': [['Prelims', 'Mains', 'Both']], 'resize_keyboard': True}
LANGUAGES = {'keyboard': [['English', 'Hindi', 'Hinglish']], 'resize_keyboard': True}


@dataclass
class Reply:
    chat_id: int
    text: str
    reply_markup: dict | None = None


class SolChat:
    def __init__(self, cfg: Config, store: Store):
        self.cfg, self.store = cfg, store

    def reply(self, update: dict) -> Reply | None:
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        if chat.get('type') != 'private' or not message.get('text'):
            return None
        chat_id, text = chat['id'], message['text'].strip()
        profile = self.store.profile(chat_id)
        lower = text.lower()
        if lower in ('/start', 'start', 'help', '/help'):
            return Reply(chat_id, 'Hi, I am Sol. I help you understand current affairs, practise BPSC questions, and plan revision.\n\nAre you preparing for Prelims, Mains, or both?', STAGES)
        if not profile['exam_stage']:
            if text.title() not in ('Prelims', 'Mains', 'Both'):
                return Reply(chat_id, 'Choose one option so I can personalise your study help.', STAGES)
            self.store.update_profile(chat_id, exam_stage=text.title())
            return Reply(chat_id, 'Which language should I use?', LANGUAGES)
        if not profile['language']:
            if text.title() not in ('English', 'Hindi', 'Hinglish'):
                return Reply(chat_id, 'Choose English, Hindi, or Hinglish.', LANGUAGES)
            profile = self.store.update_profile(chat_id, language=text.title())
            return Reply(chat_id, f"Done. I will help with {profile['exam_stage']} in {profile['language']}. What would you like to do?", HOME)
        if lower in ('ask sol', 'ask', '/ask'):
            return Reply(chat_id, 'Ask me anything about BPSC, a current-affairs topic, or a concept. For example: “Explain the Bihar budget in simple terms.”', HOME)
        if lower in ('today', '/today', 'brief', '/brief'):
            try:
                chunks = get_daily_brief(self.cfg)
                if chunks:
                    return Reply(chat_id, chunks[0], HOME)
            except Exception as exc:
                pass
            jobs = self.store.status()
            latest = jobs[0] if jobs else None
            if latest:
                return Reply(chat_id, f"Your latest saved newspaper edition is {latest['edition']} ({latest['status']}). Ask me a question, or choose Practice 5.", HOME)
            return Reply(chat_id, 'No live briefing could be retrieved right now. You can still ask a BPSC question or start Practice 5.', HOME)
        if lower in ('practice 5', 'practice', '/practice'):
            prompt = 'Create exactly five BPSC-style practice MCQs. Give four options, then an answer key with one-sentence explanations.'
            return Reply(chat_id, self._answer(profile, prompt), HOME)
        if lower in ('my plan', 'plan', '/plan'):
            prompt = 'Create a practical one-day BPSC study plan with three focused tasks, revision, and five practice questions. Keep it concise.'
            return Reply(chat_id, self._answer(profile, prompt), HOME)
        return Reply(chat_id, self._answer(profile, text), HOME)

    def _answer(self, profile: dict, question: str) -> str:
        if self.cfg.provider != 'gemini':
            return 'Sol chat needs the Gemini configuration currently used by this deployment. Your newspaper workflow is unaffected.'
        instruction = (
            'You are Sol, a concise and encouraging BPSC study assistant. Answer in the user’s chosen language. '
            'The user is preparing for ' + profile['exam_stage'] + '. Give correct, practical exam-oriented explanations. '
            'Do not claim to have checked today’s web or newspaper sources unless they are supplied. '
            'For factual claims that may change, say that a verified source check is needed. '
            'Use short headings and bullets only when they improve clarity.\n\nUser request: ' + question[:1800])
        url = self.cfg.ai_base + '/models/' + quote(self.cfg.model, safe='.-_') + ':generateContent'
        payload = {'contents': [{'role': 'user', 'parts': [{'text': instruction}]}],
                   'generationConfig': {'maxOutputTokens': 1200, 'temperature': 0.4}}
        result = request_json(url, payload, headers={'x-goog-api-key': self.cfg.api_key}, timeout=self.cfg.model_timeout)
        candidate = (result.get('candidates') or [{}])[0]
        text = ''.join(part.get('text', '') for part in candidate.get('content', {}).get('parts', []) if not part.get('thought')).strip()
        if not text:
            raise FlowError('Sol could not complete that answer. Please try again.')
        return text

"""Private and Channel Telegram conversation layer for Sol."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
    text: str = ""
    reply_markup: dict | None = None
    texts: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.texts and self.text:
            self.texts = [self.text]
        elif self.texts and not self.text:
            self.text = self.texts[0]


class SolChat:
    def __init__(self, cfg: Config, store: Store):
        self.cfg, self.store = cfg, store

    def reply(self, update: dict) -> Reply | None:
        message = update.get('message') or update.get('channel_post') or {}
        chat = message.get('chat') or {}
        if not message.get('text'):
            return None
        chat_id, text = chat.get('id'), message['text'].strip()
        if not chat_id:
            return None

        is_channel = (chat.get('type') == 'channel') or (chat_id == self.cfg.channel)
        lower = text.lower()

        # In channel, let PDF flow handle newspaper captions (#TH, #IE) and run commands
        if is_channel:
            if re.match(r'^(?:#th\b|#ie\b|run\b|#run\b|/run\b)', lower):
                return None
            profile = {'exam_stage': 'Both', 'language': 'English'}
            keyboard = None
        else:
            profile = self.store.profile(chat_id)
            keyboard = HOME

        if not is_channel and lower in ('/start', 'start', 'help', '/help'):
            return Reply(chat_id, text='Hi, I am Sol. I help you understand current affairs, practise BPSC questions, and plan revision.\n\nAre you preparing for Prelims, Mains, or both?', reply_markup=STAGES)
        if not is_channel and not profile['exam_stage']:
            if text.title() not in ('Prelims', 'Mains', 'Both'):
                return Reply(chat_id, text='Choose one option so I can personalise your study help.', reply_markup=STAGES)
            self.store.update_profile(chat_id, exam_stage=text.title())
            return Reply(chat_id, text='Which language should I use?', reply_markup=LANGUAGES)
        if not is_channel and not profile['language']:
            if text.title() not in ('English', 'Hindi', 'Hinglish'):
                return Reply(chat_id, text='Choose English, Hindi, or Hinglish.', reply_markup=LANGUAGES)
            profile = self.store.update_profile(chat_id, language=text.title())
            return Reply(chat_id, text=f"Done. I will help with {profile['exam_stage']} in {profile['language']}. What would you like to do?", reply_markup=HOME)
        if lower in ('ask sol', 'ask', '/ask'):
            return Reply(chat_id, text='Ask me anything about BPSC, a current-affairs topic, or a concept. For example: “Explain the Bihar budget in simple terms.”', reply_markup=keyboard)
        if lower in ('today', '/today', 'brief', '/brief'):
            try:
                # Force refresh to replace any old cached brief with the new 10-12 article rich format
                chunks = get_daily_brief(self.cfg, force=True)
                if chunks:
                    return Reply(chat_id, texts=chunks, reply_markup=keyboard)
            except Exception as exc:
                pass
            jobs = self.store.status()
            latest = jobs[0] if jobs else None
            if latest:
                return Reply(chat_id, text=f"Your latest saved newspaper edition is {latest['edition']} ({latest['status']}). Ask me a question, or choose Practice 5.", reply_markup=keyboard)
            return Reply(chat_id, text='No live briefing could be retrieved right now. You can still ask a BPSC question or start Practice 5.', reply_markup=keyboard)
        if lower in ('practice 5', 'practice', '/practice'):
            prompt = 'Create exactly five BPSC-style practice MCQs. Give four options, then an answer key with one-sentence explanations.'
            return Reply(chat_id, text=self._answer(profile, prompt), reply_markup=keyboard)
        if lower in ('my plan', 'plan', '/plan'):
            prompt = 'Create a practical one-day BPSC study plan with three focused tasks, revision, and five practice questions. Keep it concise.'
            return Reply(chat_id, text=self._answer(profile, prompt), reply_markup=keyboard)
        return Reply(chat_id, text=self._answer(profile, text), reply_markup=keyboard)

    def _answer(self, profile: dict, question: str) -> str:
        if self.cfg.provider != 'gemini':
            return 'Sol chat needs the Gemini configuration currently used by this deployment. Your newspaper workflow is unaffected.'
        instruction = (
            f"You are Sol, an elite BPSC (Bihar Public Service Commission) exam mentor and study companion.\n"
            f"Always reply in the user's chosen language: {profile.get('language', 'English')}.\n"
            f"The candidate is preparing for BPSC {profile.get('exam_stage', 'Both')}.\n\n"
            f"FORMATTING & ACADEMIC STANDARDS:\n"
            f"1. Structure your answer with clear sections:\n"
            f"   - 📌 <b>Core Concept & Context</b>\n"
            f"   - 🏛️ <b>BPSC Exam Significance</b> (Specify GS Paper 1, GS Paper 2, or Prelims facts)\n"
            f"   - 🎯 <b>Key Takeaways / Provisions / Data</b> (Bullet points with exact provisions, numbers, or Bihar connection)\n"
            f"2. Use clean HTML formatting (<b>bold</b>, <i>italic</i>, <code>tags</code>, and bullet points •). Do not use raw markdown asterisks.\n"
            f"3. ALWAYS conclude with an interactive section:\n"
            f"   ──────────────────────────\n"
            f"   💡 <b>Suggested Follow-Up for Your Preparation:</b>\n"
            f"   (Provide 1-2 thoughtful, exam-focused follow-up questions, e.g., a 38-mark Mains practice prompt, a related PYQ angle, or a topic deep-dive to test the candidate).\n\n"
            f"Candidate Question: {question[:1800]}"
        )
        url = self.cfg.ai_base + '/models/' + quote(self.cfg.model, safe='.-_') + ':generateContent'
        payload = {'contents': [{'role': 'user', 'parts': [{'text': instruction}]}],
                   'generationConfig': {'maxOutputTokens': 2048, 'temperature': 0.3}}
        result = request_json(url, payload, headers={'x-goog-api-key': self.cfg.api_key}, timeout=self.cfg.model_timeout)
        candidate = (result.get('candidates') or [{}])[0]
        text = ''.join(part.get('text', '') for part in candidate.get('content', {}).get('parts', []) if not part.get('thought')).strip()
        if not text:
            raise FlowError('Sol could not complete that answer. Please try again.')
        return text

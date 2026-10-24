"""Small HTTP clients. Errors never include token-bearing Telegram URLs."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from core import FlowError


class DeliveryUnknown(FlowError):
    pass


def request_json(url, payload=None, *, headers=None, timeout=90, data=None):
    headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not stringify urllib exceptions: their URL can contain a bot token.
        raise FlowError(f'HTTP request failed (status {exc.code}).') from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError):
        raise FlowError('Network request failed or returned an invalid response.') from None


class Telegram:
    def __init__(self, token):
        if not token:
            raise FlowError('Set TELEGRAM_BOT_TOKEN in .env.')
        self.base = 'https://api.telegram.org/bot' + token + '/'
        self.files = 'https://api.telegram.org/file/bot' + token + '/'

    def call(self, method, payload=None, *, timeout=90):
        result = request_json(self.base + method, payload or {}, timeout=timeout)
        if not result.get('ok'):
            raise FlowError(f'Telegram {method} failed (code {result.get("error_code", "unknown")}).')
        return result['result']

    def check(self, channel):
        me = self.call('getMe')
        chat = self.call('getChat', {'chat_id': channel})
        member = self.call('getChatMember', {'chat_id': channel, 'user_id': me['id']})
        if chat.get('type') != 'channel':
            raise FlowError('TELEGRAM_CHANNEL_ID must identify your channel.')
        if member.get('status') != 'administrator' or not member.get('can_post_messages'):
            raise FlowError('Add this bot as a channel administrator with Post Messages permission.')
        webhook = self.call('getWebhookInfo')
        if webhook.get('url'):
            raise FlowError('This bot already has a webhook. Use a dedicated bot, or deliberately remove its old integration first.')
        return {'bot': me['username'], 'channel': chat.get('title'), 'channel_id': chat['id']}

    def message(self, channel, text, reply_markup=None, parse_mode='HTML'):
        payload = {'chat_id': channel, 'text': text[:4000]}
        if parse_mode:
            payload['parse_mode'] = parse_mode
        if reply_markup:
            payload['reply_markup'] = reply_markup
        try:
            return self.call('sendMessage', payload)
        except FlowError:
            if parse_mode:
                payload.pop('parse_mode', None)
                return self.call('sendMessage', payload)
            raise

    def download(self, file_id, path: Path):
        info = self.call('getFile', {'file_id': file_id})
        if info.get('file_size', 0) > 20_000_000:
            raise FlowError('PDF exceeds the hosted Telegram Bot API download limit.')
        part = path.with_suffix('.part')
        try:
            with urllib.request.urlopen(self.files + info['file_path'], timeout=120) as response, part.open('wb') as out:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 20_000_000:
                        raise FlowError('Downloaded PDF exceeds the 20 MB limit.')
                    out.write(chunk)
            with part.open('rb') as stream:
                if b'%PDF-' not in stream.read(1024):
                    raise FlowError('Uploaded document is not a valid PDF.')
            part.replace(path)
        except FlowError:
            part.unlink(missing_ok=True)
            raise
        except (OSError, urllib.error.URLError, TimeoutError):
            part.unlink(missing_ok=True)
            raise FlowError('Newspaper download failed. Retry the edition.') from None

    def document(self, channel, path, caption):
        if path.stat().st_size > 50_000_000:
            raise FlowError('Cuttings PDF exceeds the hosted Telegram Bot API 50 MB upload limit.')
        boundary = 'bpsc' + uuid.uuid4().hex
        chunks = []
        for name, value in [('chat_id', str(channel)), ('caption', caption)]:
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\nContent-Type: application/pdf\r\n\r\n'.encode())
        chunks.extend([path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
        try:
            result = request_json(self.base + 'sendDocument', data=b''.join(chunks),
                                  headers={'Content-Type': 'multipart/form-data; boundary=' + boundary}, timeout=300)
        except FlowError:
            # Telegram has no sendDocument idempotency key. Never blindly retry.
            raise DeliveryUnknown('Delivery was not confirmed. Check the channel before retrying.') from None
        if not result.get('ok'):
            raise FlowError(f'Telegram rejected the PDF (code {result.get("error_code", "unknown")}).')
        return result['result']

"""Sol, the BPSC Telegram study agent. Run `python bot.py --help` for local commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import threading
from datetime import date
from dataclasses import replace

from core import Config, FlowError, Store, runner_lock
from pdf_flow import Strict, Vision, process_edition
from sol_chat import SolChat
from transport import DeliveryUnknown, Telegram

LOG = logging.getLogger('bpsc')


def perform_job(cfg, store, telegram, edition, uploads, processor=process_edition):
    folder = cfg.root / edition
    folder.mkdir(parents=True, exist_ok=True)
    output = ''
    try:
        paths = {}
        if not uploads:
            raise FlowError('Upload at least one newspaper PDF before running an edition.')
        for upload in uploads:
            ident = hashlib.sha256(upload['unique_id'].encode()).hexdigest()[:20]
            path = folder / f'{upload["paper"]}_{ident}.pdf'
            if not path.exists():
                telegram.download(upload['file_id'], path)
            paths[upload['paper']] = path
        output, count = processor(cfg, edition, paths)
        if output.stat().st_size > 50_000_000:
            raise FlowError('The final PDF is over 50 MB and cannot be posted through the hosted Bot API.')
        store.set_status(edition, 'sending', output=output)
        result = telegram.document(cfg.channel, output,
                                   f'#SOL_OUTPUT\nSol | BPSC newspaper cuttings | {edition}\n'
                                   f'{count} articles from the uploaded newspaper PDFs.')
        store.set_status(edition, 'done', output=output, message=result['message_id'])
        LOG.info('%s completed: %s articles', edition, count)
    except DeliveryUnknown as exc:
        store.set_status(edition, 'delivery_unknown', error=str(exc), output=output)
        store.notice(f'{edition}: {exc}')
    except FlowError as exc:
        store.set_status(edition, 'failed', error=str(exc), output=output)
        store.notice(f'{edition}: {exc}')
        LOG.error('%s failed: %s', edition, exc)
    except Exception as exc:
        # Failures after a send may be ambiguous; preserve that distinction.
        row = next((j for j in store.status() if j['edition'] == edition), {})
        state = 'delivery_unknown' if row.get('status') == 'sending' else 'failed'
        safe = f'Unexpected {type(exc).__name__}; inspect the local state before retrying.'
        store.set_status(edition, state, error=safe, output=output)
        store.notice(f'{edition}: {safe}')
        LOG.error('%s: %s', edition, safe)


def serve(cfg):
    cfg.require()
    with runner_lock(cfg.root):
        serve_locked(cfg)


def serve_locked(cfg):
    telegram = Telegram(cfg.token)
    LOG.info('Verified bot/channel: %s', telegram.check(cfg.channel))
    store = Store(cfg.root)
    sol = SolChat(cfg, store)
    store.recover()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    def collect():
        while not stop.is_set():
            try:
                updates = telegram.call('getUpdates', {'offset': store.offset(), 'timeout': 40,
                    'allowed_updates': ['channel_post', 'edited_channel_post', 'message']}, timeout=55)
                for update in updates:
                    store.ingest(update, cfg.channel)
                    try:
                        reply = sol.reply(update)
                        if reply:
                            telegram.message(reply.chat_id, reply.text, reply.reply_markup)
                    except FlowError as exc:
                        LOG.error('Sol chat: %s', exc)
                        chat = (update.get('message') or {}).get('chat') or {}
                        if chat.get('type') == 'private':
                            telegram.message(chat['id'], 'Sol could not complete that request right now. Please try again in a moment.')
            except FlowError as exc:
                LOG.error('Collector: %s', exc)
                stop.wait(10)
            except Exception as exc:
                LOG.error('Collector storage failure: %s', type(exc).__name__)
                stop.set()

    collector = threading.Thread(target=collect, name='telegram-collector', daemon=True)
    collector.start()
    LOG.info('Sol is listening. Upload #TH or #IE YYYY-MM-DD PDFs, then post run when ready.')
    try:
        while not stop.is_set():
            while message := store.pop_notice():
                try:
                    telegram.message(cfg.channel, message)
                except FlowError as exc:
                    LOG.error('Status notice could not be delivered: %s', exc)
            job = store.claim()
            if job:
                perform_job(cfg, store, telegram, *job)
            else:
                stop.wait(2)
    finally:
        stop.set()
        collector.join(timeout=58)


class ModelProbe(Strict):
    word: str


def check_model(cfg):
    """Local generated-image OCR + schema probe. No newspaper or Telegram I/O."""
    import tempfile
    from pathlib import Path
    import fitz
    cfg.require(telegram=False)
    if cfg.provider not in ('ollama', 'gemini'):
        raise FlowError('check-model supports AI_PROVIDER=ollama or gemini.')
    with tempfile.TemporaryDirectory() as temporary:
        # A one-word connectivity probe should not allocate a newspaper-sized
        # context or spend the full edition output budget on a small laptop.
        probe_cfg = replace(cfg, context_tokens=min(cfg.context_tokens, 4096),
                            output_tokens=min(cfg.output_tokens, 512),
                            model_timeout=min(cfg.model_timeout, 180))
        if cfg.provider == 'gemini':
            from gemini_native import NativeGeminiVision
            probe_cfg = replace(cfg, output_tokens=min(cfg.output_tokens, 8192))
            vision = NativeGeminiVision(probe_cfg, Path(temporary), {})
            report = {'provider': cfg.provider, 'model': cfg.model}
        else:
            vision = Vision(probe_cfg, Path(temporary))
            report = vision.check_local_model()
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=160)
            page.insert_text((45, 100), 'BPSC', fontsize=64)
            image = page.get_pixmap(alpha=False).tobytes('png')
        answer = vision.ask(ModelProbe, 'Read the large word in this image. Return it in the word field.',
                            [('Vision connectivity probe', image)])
        if ''.join(answer.word.split()).upper() != 'BPSC':
            raise FlowError('The model connected but failed the basic image-reading probe. '
                            f'Received {answer.word[:80]!r}; expected the letters BPSC. Check the vision model.')
        report['image_reading_raw'] = answer.word
        report['image_and_schema_probe'] = 'passed'
        report['newspaper_accuracy_tested'] = False
        if cfg.provider == 'ollama':
            report['edition_context_tokens'] = cfg.context_tokens
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Sol — BPSC current-affairs and newspaper-cuttings agent')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('serve', help='Listen continuously; process saved papers after a #RUN command')
    sub.add_parser('check', help='Read-only bot/channel permission check; does not send messages')
    sub.add_parser('check-model', help='Test configured Ollama or Gemini vision and JSON output; no Telegram posting')
    sub.add_parser('discover-channel', help='Read pending channel posts and print their channel IDs')
    sub.add_parser('status', help='Show local job states')
    retry = sub.add_parser('retry', help='Retry a failed edition, reusing cached model results')
    retry.add_argument('edition')
    retry.add_argument('--delivery-checked', action='store_true')
    local = sub.add_parser('process-local', help='Generate cuttings from local PDFs; no Telegram posting')
    local.add_argument('--date', required=True)
    local.add_argument('--th', required=True)
    local.add_argument('--ie', required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    cfg = Config.from_env()
    if args.command == 'serve':
        serve(cfg)
    elif args.command == 'check-model':
        check_model(cfg)
    elif args.command == 'check':
        cfg.require(ai=False)
        print(json.dumps(Telegram(cfg.token).check(cfg.channel), indent=2))
    elif args.command == 'discover-channel':
        telegram = Telegram(cfg.token)
        if telegram.call('getWebhookInfo').get('url'):
            raise FlowError('This bot has an existing webhook. Use a dedicated bot.')
        updates = telegram.call('getUpdates', {'timeout': 0, 'allowed_updates': ['channel_post', 'edited_channel_post']})
        channels = {}
        for update in updates:
            post = update.get('channel_post') or update.get('edited_channel_post') or {}
            chat = post.get('chat', {})
            if chat.get('type') == 'channel':
                channels[chat['id']] = chat.get('title', '')
        print(json.dumps(channels, indent=2) if channels else 'No new channel posts found. Add the bot as admin, then post a test message and retry.')
    elif args.command == 'status':
        print(json.dumps(Store(cfg.root).status(), indent=2))
    elif args.command == 'retry':
        Store(cfg.root).retry(args.edition, args.delivery_checked)
        print('Queued. The running service will pick up the edition.')
    elif args.command == 'process-local':
        cfg.require(telegram=False)
        date.fromisoformat(args.date)
        output, count = process_edition(cfg, args.date, {'TH': args.th, 'IE': args.ie})
        print(f'{output}\n{count} articles')


if __name__ == '__main__':
    try:
        main()
    except (FlowError, ValueError) as exc:
        print(f'Setup/processing error: {exc}')
        raise SystemExit(1) from None

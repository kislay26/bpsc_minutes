"""Input routing, configuration and durable job state. No network on import."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


class FlowError(Exception):
    """An actionable, safe-to-display processing error (never include credentials)."""


def load_env(path: Path = Path('.env')):
    if path.exists():
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if sep and re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                os.environ.setdefault(key, value.strip().strip('\"\''))


@dataclass
class Config:
    root: Path
    token: str = ''
    channel: int = 0
    api_key: str = ''
    model: str = ''
    ai_base: str = 'https://api.openai.com/v1'
    max_calls: int = 140
    provider: str = 'openai'
    context_tokens: int = 32768
    output_tokens: int = 12000
    model_timeout: int = 240

    @classmethod
    def from_env(cls):
        load_env()
        provider = os.getenv('AI_PROVIDER', 'openai').strip().lower()
        local = provider == 'ollama'
        gemini = provider == 'gemini'
        return cls(
            root=Path(os.getenv('DATA_DIR', './data')).resolve(),
            token=os.getenv('TELEGRAM_BOT_TOKEN', ''),
            channel=int(os.getenv('TELEGRAM_CHANNEL_ID', '0') or '0'),
            api_key='' if local else os.getenv('GEMINI_API_KEY' if gemini else 'OPENAI_API_KEY', ''),
            model=os.getenv('OLLAMA_MODEL' if local else 'GEMINI_MODEL' if gemini else 'OPENAI_MODEL',
                            'gemini-3.1-flash-lite' if gemini else '').strip(),
            ai_base=('https://generativelanguage.googleapis.com/v1beta' if gemini else
                     os.getenv('OLLAMA_BASE_URL' if local else 'OPENAI_BASE_URL',
                     'http://127.0.0.1:11434' if local else 'https://api.openai.com/v1').rstrip('/')),
            max_calls=int(os.getenv('MAX_MODEL_CALLS_PER_EDITION', '140')),
            provider=provider,
            context_tokens=int(os.getenv('OLLAMA_NUM_CTX', '32768')) if local else 32768,
            output_tokens=int(os.getenv('OLLAMA_NUM_PREDICT', '12000')) if local else int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS', '8192')) if gemini else 12000,
            model_timeout=int(os.getenv('OLLAMA_TIMEOUT_SECONDS', '1200')) if local else 240)

    def require(self, *, telegram=True, ai=True):
        missing = []
        if telegram:
            if not self.token:
                missing.append('TELEGRAM_BOT_TOKEN')
            if not self.channel:
                missing.append('TELEGRAM_CHANNEL_ID')
        if ai:
            if self.provider not in ('openai', 'ollama', 'gemini'):
                raise FlowError('AI_PROVIDER must be openai, ollama or gemini.')
            if self.provider in ('openai', 'gemini') and not self.api_key:
                missing.append('GEMINI_API_KEY' if self.provider == 'gemini' else 'OPENAI_API_KEY')
            if not self.model:
                missing.append('OLLAMA_MODEL' if self.provider == 'ollama' else 'GEMINI_MODEL' if self.provider == 'gemini' else 'OPENAI_MODEL')
            if self.max_calls < 1 or self.model_timeout < 1:
                raise FlowError('Model-call limit and timeout must be positive.')
            if self.provider == 'gemini':
                if self.output_tokens < 1:
                    raise FlowError('GEMINI_MAX_OUTPUT_TOKENS must be positive.')
                if self.model not in ('gemini-3.1-flash-lite', 'gemini-2.5-flash', 'gemini-3.8-flash',
                                      'gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite'):
                    raise FlowError('Choose a configured Gemini model with a documented free tier.')
            if self.provider == 'ollama':
                endpoint = urlsplit(self.ai_base)
                if (endpoint.scheme not in ('http', 'https') or not endpoint.hostname
                        or endpoint.username or endpoint.password or endpoint.query
                        or endpoint.fragment or endpoint.path not in ('', '/')):
                    raise FlowError('OLLAMA_BASE_URL must be the server root, e.g. http://127.0.0.1:11434 (no /api or /v1).')
                if (endpoint.hostname == 'ollama.com' or endpoint.hostname.endswith('.ollama.com')
                        or 'cloud' in self.model.lower()):
                    raise FlowError('This Ollama option requires a downloaded local model, not an Ollama Cloud model.')
                if not 0 < self.output_tokens < self.context_tokens:
                    raise FlowError('OLLAMA_NUM_CTX must exceed the positive OLLAMA_NUM_PREDICT value.')
        if missing:
            raise FlowError('Set ' + ', '.join(missing) + ' in .env.')


@contextmanager
def runner_lock(root: Path):
    """One worker per data directory, using native OS file locks."""
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / 'runner.lock').open('a+b')
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            if lock.seek(0, 2) == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise FlowError('A runner is already using this data directory, or it cannot be locked.') from None
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise FlowError('A runner is already using this data directory, or it cannot be locked.') from None
        acquired = True
        yield
    finally:
        if acquired and os.name == 'nt':
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def parse_upload(post: dict, channel: int):
    """Return (edition, paper, document), None for ignored posts, or a clear error.

    No dependence on from.is_bot: channel posts often have an anonymous sender.
    Explicit captions are recommended, and dates in filenames also work.
    """
    if post.get('chat', {}).get('id') != channel:
        return None
    doc = post.get('document')
    if not doc:
        return None
    caption = post.get('caption', '')
    filename = doc.get('file_name', '')
    if ('#BPSC_OUTPUT' in caption.upper() or '#SOL_OUTPUT' in caption.upper()
            or filename.upper().startswith('BPSC_')):
        return None
    if not (filename.lower().endswith('.pdf') or doc.get('mime_type') == 'application/pdf'):
        return None
    text = f'{caption}\n{filename}'
    papers = set()
    if re.search(r'(?i)(?:#TH\b|\bthe[ _.-]*hindu\b|\bhindu\b|\bTH\b)', text):
        papers.add('TH')
    if re.search(r'(?i)(?:#IE\b|\bindian[ _.-]*express\b|\bexpress\b|\bIE\b)', text):
        papers.add('IE')
    
    # If no explicit label, infer from filename or fallback
    paper = papers.pop() if len(papers) == 1 else None
    if not paper:
        # Fallback: check if 'hindu' is anywhere in name
        if 'hindu' in text.lower():
            paper = 'TH'
        elif 'express' in text.lower():
            paper = 'IE'

    raw_dates = set()
    raw_dates.update(re.findall(r'(?<!\d)(20\d{2})[-~_/.](\d{1,2})[-~_/.](\d{1,2})(?!\d)', text))
    raw_dates.update((y, m, d) for d, m, y in re.findall(r'(?<!\d)(\d{1,2})[-~_/.](\d{1,2})[-~_/.](20\d{2})(?!\d)', text))

    dates = set()
    try:
        for y, m, d in raw_dates:
            dates.add(date(int(y), int(m), int(d)).isoformat())
    except ValueError:
        raise FlowError('The newspaper date is invalid. Use YYYY-MM-DD in its caption.') from None

    if len(dates) > 1:
        raise FlowError('Use one consistent edition date in the PDF filename and caption.')
    elif len(dates) == 1:
        edition_date = dates.pop()
    else:
        edition_date = date.today().isoformat()

    if not paper:
        raise FlowError('Could not identify the newspaper. Include "Hindu" or "Express" in the filename or caption.')

    if doc.get('file_size', 0) > 20_000_000:
        raise FlowError('This PDF exceeds the hosted Telegram Bot API 20 MB download limit. Upload a smaller readable edition.')
    return edition_date, paper, doc


def parse_run_command(post: dict, channel: int):
    """Return an optional edition date for a channel run command, if present."""
    if post.get('chat', {}).get('id') != channel:
        return None
    text = post.get('text', '')
    match = re.fullmatch(r'\s*(?:#RUN|/run(?:@\w+)?|RUN|GO|/GO|#GO|START|/START|PROCESS)(?:\s+(20\d{2}-\d{2}-\d{2}))?\s*', text,
                         flags=re.IGNORECASE)
    if not match:
        return None
    if not match.group(1):
        return ''
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        raise FlowError('Use run, or use run followed by a valid date such as 2026-10-10.') from None


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'state.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
                CREATE TABLE IF NOT EXISTS seen(update_id INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS uploads(
                    edition TEXT, paper TEXT, message_id INTEGER,
                    file_id TEXT, unique_id TEXT, size INTEGER,
                    PRIMARY KEY(edition,paper));
                CREATE TABLE IF NOT EXISTS jobs(
                    edition TEXT PRIMARY KEY, status TEXT, error TEXT DEFAULT '',
                    output TEXT DEFAULT '', output_message INTEGER, attempts INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS notices(
                    id INTEGER PRIMARY KEY, text TEXT, sent INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sol_profiles(
                    chat_id INTEGER PRIMARY KEY, exam_stage TEXT DEFAULT '',
                    language TEXT DEFAULT '', daily_hours TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def offset(self):
        with self.connect() as db:
            row = db.execute("SELECT v FROM meta WHERE k='offset'").fetchone()
            return int(row[0]) if row else 0

    def ingest(self, update: dict, channel: int):
        """Persist routing and offset together, before acknowledging Telegram."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM seen WHERE update_id=?', (update['update_id'],)).fetchone():
                return
            post = update.get('channel_post') or update.get('edited_channel_post') or {}
            try:
                requested_edition = parse_run_command(post, channel)
                parsed = None if requested_edition is not None else parse_upload(post, channel)
            except FlowError as exc:
                db.execute('INSERT INTO notices(text) VALUES(?)', (str(exc),))
                parsed = None
                requested_edition = locals().get('requested_edition')
            if requested_edition is not None:
                if not requested_edition:
                    pending = db.execute("SELECT edition FROM jobs WHERE status='waiting' ORDER BY edition").fetchall()
                    if len(pending) == 1:
                        requested_edition = pending[0][0]
                    elif not pending:
                        db.execute('INSERT INTO notices(text) VALUES(?)',
                                   ('Nothing is waiting. Upload a newspaper PDF first.',))
                    else:
                        dates = ', '.join(row[0] for row in pending)
                        db.execute('INSERT INTO notices(text) VALUES(?)',
                                   (f'More than one edition is waiting: {dates}. Post run followed by the date you want.',))
                row = db.execute('SELECT status FROM jobs WHERE edition=?', (requested_edition,)).fetchone()
                count = db.execute('SELECT count(*) FROM uploads WHERE edition=?', (requested_edition,)).fetchone()[0]
                if not requested_edition:
                    pass
                elif not row or not count:
                    db.execute('INSERT INTO notices(text) VALUES(?)',
                               (f'{requested_edition}: no newspaper PDF is saved yet. Upload one first.',))
                elif row['status'] == 'waiting':
                    db.execute("UPDATE jobs SET status='ready',error='',output='' WHERE edition=?", (requested_edition,))
                    papers = ' and '.join('The Hindu' if item[0] == 'TH' else 'Indian Express'
                                          for item in db.execute('SELECT paper FROM uploads WHERE edition=? ORDER BY paper',
                                                                 (requested_edition,)))
                    db.execute('INSERT INTO notices(text) VALUES(?)',
                               (f'{requested_edition}: processing started for {papers}.',))
                else:
                    db.execute('INSERT INTO notices(text) VALUES(?)',
                               (f'{requested_edition}: cannot start because its status is {row["status"]}. Use status or retry if it failed.',))
            elif parsed:
                edition, paper, doc = parsed
                row = db.execute('SELECT status FROM jobs WHERE edition=?', (edition,)).fetchone()
                existing = db.execute('SELECT unique_id FROM uploads WHERE edition=? AND paper=?',
                                      (edition, paper)).fetchone()
                same = existing and existing[0] == doc['file_unique_id']
                frozen = row and row[0] in ('processing', 'sending', 'done', 'delivery_unknown')
                if not same and frozen:
                    db.execute('INSERT INTO notices(text) VALUES(?)',
                               (f'{edition}: a run is already in progress or completed. This replacement was not processed.',))
                elif not same:
                    db.execute('INSERT OR REPLACE INTO uploads VALUES(?,?,?,?,?,?)',
                               (edition, paper, post['message_id'], doc['file_id'],
                                doc['file_unique_id'], doc.get('file_size', 0)))
                    count = db.execute('SELECT count(*) FROM uploads WHERE edition=?', (edition,)).fetchone()[0]
                    status = 'waiting'
                    db.execute("INSERT INTO jobs(edition,status) VALUES(?,?) ON CONFLICT(edition) DO UPDATE SET status=excluded.status,error='',output=''",
                               (edition, status))
                    name = 'The Hindu' if paper == 'TH' else 'Indian Express'
                    if count == 2:
                        instruction = f'Both newspapers are saved. Post #RUN {edition} when you want processing to start.'
                    else:
                        instruction = (f'You can upload the other newspaper for this date, or post #RUN {edition} '
                                       'to process this PDF by itself.')
                    db.execute('INSERT INTO notices(text) VALUES(?)',
                               (f'{edition}: {name} saved. {instruction.replace("#RUN " + edition, "run")}',))
            db.execute('INSERT INTO seen VALUES(?)', (update['update_id'],))
            db.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)", (str(update['update_id'] + 1),))

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='ready' WHERE status='processing'")
            ambiguous = db.execute("SELECT edition FROM jobs WHERE status='sending'").fetchall()
            db.execute("UPDATE jobs SET status='delivery_unknown',error='Restart during delivery; inspect channel before retrying.' WHERE status='sending'")
            for row in ambiguous:
                db.execute('INSERT INTO notices(text) VALUES(?)',
                           (f'{row[0]}: delivery confirmation was interrupted. Check the channel before retrying to avoid a duplicate.',))

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT edition FROM jobs WHERE status='ready' ORDER BY edition LIMIT 1").fetchone()
            if not job:
                return None
            # Increment attempt count each time the job is claimed
            db.execute("UPDATE jobs SET status='processing', attempts = attempts + 1 WHERE edition=?", (job[0],))
            uploads = db.execute('SELECT * FROM uploads WHERE edition=? ORDER BY paper', (job[0],)).fetchall()
            return job[0], [dict(row) for row in uploads]

    def set_status(self, edition, status, *, error='', output='', message=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,error=?,output=?,output_message=? WHERE edition=?',
                       (status, error[:1000], str(output), message, edition))
            if status == 'failed':
                attempts_row = db.execute('SELECT attempts FROM jobs WHERE edition=?', (edition,)).fetchone()
                if attempts_row and attempts_row[0] < 3:
                    db.execute("UPDATE jobs SET status='ready' WHERE edition=?", (edition,))

    def notice(self, text):
        with self.connect() as db:
            db.execute('INSERT INTO notices(text) VALUES(?)', (text,))

    def pop_notice(self):
        with self.connect() as db:
            row = db.execute('SELECT id,text FROM notices WHERE sent=0 ORDER BY id LIMIT 1').fetchone()
            if row:
                # Status notices are best effort; a lost notice must not block the PDF.
                db.execute('UPDATE notices SET sent=1 WHERE id=?', (row[0],))
                return row[1]

    def retry(self, edition, delivery_checked=False):
        date.fromisoformat(edition)
        with self.connect() as db:
            row = db.execute('SELECT status FROM jobs WHERE edition=?', (edition,)).fetchone()
            allowed = ('failed', 'delivery_unknown') if delivery_checked else ('failed',)
            if not row or row[0] not in allowed:
                raise FlowError('Retry requires a failed run. For uncertain delivery, inspect the channel first and use --delivery-checked.')
            db.execute("UPDATE jobs SET status='ready',error='' WHERE edition=?", (edition,))

    def status(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY edition DESC LIMIT 30')]

    def profile(self, chat_id: int):
        with self.connect() as db:
            row = db.execute('SELECT * FROM sol_profiles WHERE chat_id=?', (chat_id,)).fetchone()
            if not row:
                db.execute('INSERT INTO sol_profiles(chat_id) VALUES(?)', (chat_id,))
                row = db.execute('SELECT * FROM sol_profiles WHERE chat_id=?', (chat_id,)).fetchone()
            return dict(row)

    def update_profile(self, chat_id: int, **changes):
        allowed = {'exam_stage', 'language', 'daily_hours'}
        changes = {key: str(value)[:100] for key, value in changes.items() if key in allowed}
        if not changes:
            return self.profile(chat_id)
        assignments = ', '.join(f'{key}=?' for key in changes)
        with self.connect() as db:
            db.execute('INSERT INTO sol_profiles(chat_id) VALUES(?) ON CONFLICT(chat_id) DO NOTHING', (chat_id,))
            db.execute(f'UPDATE sol_profiles SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE chat_id=?',
                       (*changes.values(), chat_id))
        return self.profile(chat_id)

"""Persistent request budget shared by edition metadata and page subprocesses."""
import json
from pathlib import Path
from core import runner_lock, FlowError


def consume(path, limit):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with runner_lock(path.parent / 'budget-lock'):
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'requests': 0}
        if state['requests'] >= limit:
            raise FlowError('Gemini edition request budget reached. Completed replies are cached; inspect the edition before increasing MAX_MODEL_CALLS_PER_EDITION.')
        state['requests'] += 1
        state['limit'] = limit
        path.write_text(json.dumps(state, indent=2), encoding='utf-8')

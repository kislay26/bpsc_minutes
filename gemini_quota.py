"""Remember server quota cooldowns without storing credentials."""
import hashlib
import json
import re
import time
from pathlib import Path


def retry_seconds(error):
    for detail in error.get('details', []):
        if detail.get('@type', '').endswith('RetryInfo'):
            value = detail.get('retryDelay', '')
            if re.fullmatch(r'\d+(?:\.\d+)?s', value):
                return max(1, float(value[:-1]))
    match = re.search(r'retry in\s+(?:(\d+)h)?(?:(\d+)m)?(\d+(?:\.\d+)?)s',
                      error.get('message', ''), re.I)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours or 0)*3600 + int(minutes or 0)*60 + float(seconds)
    return 60


def state_path(folder, key, model):
    digest = hashlib.sha256((key + '\0' + model).encode()).hexdigest()
    return Path(folder) / ('quota-' + digest + '.json')


def remember(folder, key, model, error, now=None):
    path = state_path(folder, key, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = (time.time() if now is None else now) + retry_seconds(error)
    path.write_text(json.dumps({'model': model, 'retry_after': deadline}), encoding='utf-8')


def remaining(folder, key, model, now=None):
    path = state_path(folder, key, model)
    if not path.is_file():
        return 0
    state = json.loads(path.read_text(encoding='utf-8'))
    return max(0, state['retry_after'] - (time.time() if now is None else now))

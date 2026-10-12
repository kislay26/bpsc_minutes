"""Build a secret-free Kaggle input bundle and an interactive trial notebook."""
import ast
import json
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'kaggle'
OUT.mkdir(exist_ok=True)
FILES = ['bot.py', 'core.py', 'pdf_flow.py', 'staged_scan.py', 'kaggle_page_trial.py', 'news_selection.py', 'transport.py',
         'requirements.txt', 'README.md', 'OLLAMA_SETUP.md']
FILES += ['selection_skill/' + name for name in
          ('selection_policy.json', 'question_evidence.json', 'sources.json', 'methodology.md')]
FILES += ['tests/' + name for name in ('test_ollama.py', 'test_selection.py', 'test_workflow.py', 'test_staged_scan.py')]
PAPERS = {
    'hindu.pdf': ROOT / 'Newspaper/THE HINDU HD Delhi Editable Full Edition 27~09~2026.pdf',
    'express.pdf': ROOT / 'Newspaper/INDIAN EXPRESS HD Delhi 27~09~2026.pdf',
}
with zipfile.ZipFile(OUT / 'BPSC_Kaggle_Input.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in FILES:
        archive.write(ROOT / name, 'bpsc-agent/' + name)
    for name, path in PAPERS.items():
        archive.write(path, 'newspapers/' + name)

cells = []
def cell(kind, source):
    source = textwrap.dedent(source).strip() + '\n'
    if kind == 'code':
        ast.parse(source)
    item = {'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code':
        item.update(execution_count=None, outputs=[])
    cells.append(item)

cell('markdown', '''
# BPSC original newspaper cuttings — Kaggle GPU trial

Keep this notebook and its newspaper input **private**. No payment details,
Telegram token or AI API key are required by this notebook. It does not contact
Telegram or run an unattended listener.

Before running: select a **GPU accelerator**, enable **Internet**, and attach
`BPSC_Kaggle_Input.zip` as a private input. Kaggle may unpack the ZIP for you;
both packed and unpacked inputs are supported. Run the cells in order.

This is a first live trial, not a proven accuracy or speed benchmark. The model
can miss news or produce bad crops. Review a successful PDF against both originals.
If a cell fails, stop there and read its error; do not bypass validation.
''')
cell('code', '''
# 1. Configuration and GPU check — no model download before this passes.
import os, sys, json, time, shutil, subprocess, urllib.request, zipfile
from pathlib import Path
from datetime import date
from IPython.display import display, FileLink

EDITION = '2026-09-27'  # Actual printed date of the two bundled newspapers.
MODEL = 'qwen3-vl:4b-instruct'  # Explicit non-thinking variant; accuracy still needs testing.
date.fromisoformat(EDITION)
WORK = Path('/kaggle/working')
TEMP = Path('/kaggle/temp/bpsc')
assert WORK.is_dir(), 'Run this notebook on Kaggle, not on your laptop.'
os.chdir(WORK)
TEMP.mkdir(parents=True, exist_ok=True)
assert shutil.which('nvidia-smi'), 'Select a GPU in Kaggle Settings, then restart this session.'
subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free',
                '--format=csv'], check=True)
print('The GPU check passed. Enable Internet before the installation cells.')
''')
cell('code', '''
# 2. Locate the private input and copy only the application files to writable storage.
INPUT = Path('/kaggle/input')
roots = sorted(p.parent for p in INPUT.rglob('bot.py')
               if (p.parent / 'selection_skill/selection_policy.json').is_file())
if not roots:
    bundles = sorted(INPUT.rglob('BPSC_Kaggle_Input.zip'))
    assert len(bundles) == 1, 'Upload one BPSC_Kaggle_Input.zip using Add Input / Upload.'
    extracted = TEMP / 'input'
    extracted.mkdir(exist_ok=True)
    with zipfile.ZipFile(bundles[0]) as z:
        for item in z.infolist():
            target = (extracted / item.filename).resolve()
            assert target.is_relative_to(extracted.resolve()), 'Unsafe ZIP path.'
        z.extractall(extracted)
    roots = [extracted / 'bpsc-agent']
    search_root = extracted
else:
    search_root = INPUT
assert len(roots) == 1, 'Multiple agent inputs found; detach the older input.'
assert (roots[0] / 'staged_scan.py').is_file(), 'Old input bundle: attach the new BPSC_Kaggle_Input.zip.'
APP = WORK / 'bpsc-agent'
shutil.copytree(roots[0], APP, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('.env', '.venv', '__pycache__', 'data'))
papers = {}
for key, name in [('TH', 'hindu.pdf'), ('IE', 'express.pdf')]:
    matches = sorted(search_root.rglob(name))
    assert len(matches) == 1, f'Expected exactly one {name}; found {len(matches)}.'
    papers[key] = matches[0]
print('Application:', APP)
print('Input PDFs:', {key: str(path) for key, path in papers.items()})
''')
cell('code', '''
# 3. Install into an isolated environment; do not change Kaggle's Python packages.
python_env = os.environ.copy()
for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE'):
    python_env.pop(key, None)
python_env['PYTHONNOUSERSITE'] = '1'
VENV = TEMP / 'venv'
PYTHON = VENV / 'bin/python'
# A failed ensurepip can leave bin/python present but pip absent. Test pip,
# not just the executable. PyPA's standalone virtualenv seeds its own pip
# and can repair that partial environment without changing system Python.
pip_ready = PYTHON.exists() and subprocess.run(
    [str(PYTHON), '-m', 'pip', '--version'], capture_output=True, text=True, env=python_env
).returncode == 0
if not pip_ready:
    bootstrap = TEMP / 'virtualenv.pyz'
    print('Preparing isolated Python with the official PyPA virtualenv bootstrap...')
    urllib.request.urlretrieve('https://bootstrap.pypa.io/virtualenv.pyz', bootstrap)
    subprocess.run([sys.executable, str(bootstrap), '--python', sys.executable,
                    '--no-periodic-update', str(VENV)], env=python_env, check=True)
subprocess.run([str(PYTHON), '-m', 'pip', '--version'], env=python_env, check=True)
subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', str(APP / 'requirements.txt')], env=python_env, check=True)
subprocess.run([str(PYTHON), '-m', 'pip', 'install', 'wrapt'], env=python_env, check=True)
if not shutil.which('tesseract') or not shutil.which('zstd'):
    subprocess.run(['apt-get', 'update', '-qq'], check=True)
    subprocess.run(['apt-get', 'install', '-y', '-qq', 'tesseract-ocr',
                    'tesseract-ocr-eng', 'zstd'], check=True)
languages = subprocess.check_output(['tesseract', '--list-langs'], text=True)
assert 'eng' in languages.splitlines(), 'Tesseract English language data is missing.'
print(languages)
subprocess.run([str(PYTHON), '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
               cwd=APP, env=python_env, check=True)
''')
cell('code', '''
# 4. Download official Ollama Linux binaries and launch a loopback-only server.
# Runtime binaries and model weights stay in /kaggle/temp, outside saved outputs.
OLLAMA_HOME = TEMP / 'ollama'
OLLAMA = OLLAMA_HOME / 'bin/ollama'
if not OLLAMA.exists():
    package = TEMP / 'ollama-linux-amd64.tar.zst'
    print('Downloading Ollama from its official website...')
    urllib.request.urlretrieve('https://ollama.com/download/ollama-linux-amd64.tar.zst', package)
    OLLAMA_HOME.mkdir(exist_ok=True)
    subprocess.run(['tar', '--zstd', '-xf', str(package), '-C', str(OLLAMA_HOME)], check=True)
    package.unlink()

BASE = 'http://127.0.0.1:11434'
env = os.environ.copy()
for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE'):
    env.pop(key, None)
env['PYTHONNOUSERSITE'] = '1'
env.update(OLLAMA_HOST='127.0.0.1:11434', OLLAMA_NO_CLOUD='1',
           OLLAMA_MODELS=str(TEMP / 'models'), OLLAMA_NUM_PARALLEL='1',
           AI_PROVIDER='ollama', OLLAMA_BASE_URL=BASE, OLLAMA_MODEL=MODEL,
           OLLAMA_NUM_CTX='32768', OLLAMA_NUM_PREDICT='4096',
           OLLAMA_TIMEOUT_SECONDS='600', MAX_MODEL_CALLS_PER_EDITION='2000',
           DATA_DIR=str(WORK / 'data-staged'), TELEGRAM_BOT_TOKEN='', TELEGRAM_CHANNEL_ID='',
           OPENAI_API_KEY='', PYTHONUNBUFFERED='1')

def api_get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)

try:
    api_get('/api/version')
except Exception:
    server_log = (WORK / 'ollama-server.log').open('a')
    server = subprocess.Popen([str(OLLAMA), 'serve'], env=env, stdout=server_log,
                              stderr=subprocess.STDOUT)
    for _ in range(60):
        if server.poll() is not None:
            raise RuntimeError('Ollama exited. Inspect /kaggle/working/ollama-server.log.')
        try:
            api_get('/api/version')
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError('Ollama did not start. Inspect ollama-server.log.')
print('Ollama:', api_get('/api/version'))
subprocess.run([str(OLLAMA), 'pull', MODEL], env=env, check=True)
''')
cell('code', '''
# 5. Test real vision + JSON output, then confirm Ollama used GPU memory.
PROBE_OK = False
started = time.monotonic()
subprocess.run([str(PYTHON), 'bot.py', 'check-model'], cwd=APP, env=env, check=True)
loaded = api_get('/api/ps').get('models', [])
assert any(m.get('size_vram', 0) > 0 for m in loaded), (
    'Ollama did not report GPU usage. Stop and inspect ollama-server.log before processing.')
print('GPU allocation:', [{k: m.get(k) for k in ('name', 'size', 'size_vram')} for m in loaded])
print(f'Basic model probe passed in {time.monotonic() - started:.1f} seconds.')
PROBE_OK = True
''')
cell('code', '''
# 6. Real first-page trial. Review the crop preview before processing the edition.
assert PROBE_OK, 'Run the model probe first.'
PAGE_REVIEWED = False
RESULT = WORK / 'data-staged' / EDITION
subprocess.run([str(PYTHON), '-u', 'kaggle_page_trial.py', '--date', EDITION,
                '--th', str(papers['TH'])], cwd=APP, env=env, check=True)
trial = json.loads((RESULT / 'page_trial.json').read_text(encoding='utf-8'))
assert trial['passed'], 'First-page extraction did not pass.'
display(FileLink(str((RESULT / 'page_trial_crops.pdf').relative_to(WORK))))
display(FileLink(str((RESULT / 'page_trial.json').relative_to(WORK))))
print('Compare the preview with Hindu page 1: all articles, columns, captions and endings.')
print('If crops are missing or include neighboring stories, stop and report the issue.')
''')
cell('code', '''
# 7. After inspecting the preview, change False to True and run this cell.
PAGE_REVIEWED = False
assert PAGE_REVIEWED, 'Inspect the first-page preview before enabling the full edition.'
''')
cell('code', '''
# 8. Process both full PDFs using staged extraction and existing validation.
assert PROBE_OK, 'Run and pass the model probe first.'
assert PAGE_REVIEWED, 'Review the first-page trial and run cell 7 first.'
RESULT = WORK / 'data-staged' / EDITION
OUTPUT = RESULT / f'BPSC_Cuttings_{EDITION}.pdf'
RUN_OK = False
log_path = WORK / f'processing-{EDITION}.log'
started = time.monotonic()
with log_path.open('w', encoding='utf-8') as log:
    process = subprocess.Popen([str(PYTHON), 'bot.py', 'process-local', '--date', EDITION,
                               '--th', str(papers['TH']), '--ie', str(papers['IE'])],
                              cwd=APP, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        while process.poll() is None:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print(f'{(time.monotonic()-started)/60:.1f} min | '
                      f'OCR pages: {len(list(RESULT.glob("ocr_*.txt")))} | '
                      f'cached model replies: {len(list((RESULT / "model_cache").glob("*.json")))}',
                      flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        subprocess.run([str(OLLAMA), 'stop', MODEL], env=env, timeout=60, check=False)
print(log_path.read_text(encoding='utf-8')[-12000:])
display(FileLink(str(log_path.relative_to(WORK))))
assert process.returncode == 0 and OUTPUT.is_file(), (
    'The edition failed validation or processing. No successful result is claimed. '
    'Inspect the log and data folder; share the error text for troubleshooting.')
RUN_OK = True
print(f'Completed in {(time.monotonic()-started)/60:.1f} minutes.')
''')
cell('code', '''
# 9. Download the finished original-cuttings PDF and review it against the papers.
assert RUN_OK, 'No successful newspaper run in this session.'
os.chdir(WORK)
display(FileLink(str(OUTPUT.relative_to(WORK))))
audit = RESULT / 'audit.json'
if audit.exists():
    display(FileLink(str(audit.relative_to(WORK))))
print('Download the PDF before ending the session. Keep notebook outputs private.')
print('Check missed stories, relevance, every column, pictures, captions and continuations.')
print('This notebook does not send anything to Telegram.')
''')
notebook = {'nbformat': 4, 'nbformat_minor': 5, 'cells': cells,
            'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python',
                                        'name': 'python3'},
                         'language_info': {'name': 'python', 'version': '3.12'},
                         'kaggle': {'isInternetEnabled': True, 'isGpuEnabled': True}}}
for i, item in enumerate(cells):
    item['id'] = f'bpsc-{i:02d}'
(OUT / 'BPSC_Kaggle_Trial.ipynb').write_text(json.dumps(notebook, indent=2), encoding='utf-8')
(OUT / 'KAGGLE_CELL_3.py').write_text(''.join(cells[3]['source']), encoding='utf-8')
with zipfile.ZipFile(OUT / 'BPSC_Kaggle_Input.zip') as archive:
    expected = {'bpsc-agent/' + name for name in FILES} | {'newspapers/' + name for name in PAPERS}
    assert set(archive.namelist()) == expected
    assert archive.testzip() is None
print('Built notebook: all Python cells compile.')
print('Built input ZIP: explicit file allowlist verified; no environment files or credentials.')
for path in OUT.iterdir():
    print(path.name, path.stat().st_size, 'bytes')

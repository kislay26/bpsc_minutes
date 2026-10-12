# Run your BPSC newspaper bot with Ollama

Ollama runs the AI model on your own computer. This project handles Telegram,
OCR, the BPSC selection policy, direct PDF cropping, state and delivery.
Ollama alone does not monitor Telegram or make newspaper-cutting PDFs.

The result contains the original newspaper regions, including their original
text, photographs and charts. Model-written explanations stay in internal JSON.
The included selection skill targets BPSC CCE General Studies.

## Cost and equipment

This local setup needs no model API key, AI subscription, rented server or
domain. You supply a computer, free disk space, electricity and internet for
Telegram. Installing software and downloading a model also need internet.
There is no paid-model fallback. Keep Ollama local and use a downloaded model.

Start by testing `qwen3-vl:4b-instruct`, a vision model. Its listed download is about
3.3 GB. `qwen3-vl:8b` is another candidate at about 6.1 GB. Download size is
not the required RAM/VRAM: image processing, context and other applications
need additional memory. No minimum-RAM or speed claim has been measured for
this newspaper workflow. CPU operation may be too slow for your desired
turnaround; choose the model after checking your RAM, GPU and a trial.

This is a starter integration. Neither model has been benchmarked for BPSC
selection or full newspaper layouts here. A small model can produce valid
JSON while choosing a wrong article or crop. Review the first real outputs.

## 1. Install Ollama and download the model

Download the native app from <https://ollama.com/download>. On Windows, run the
installer and open a new PowerShell window. Then run:

```powershell
ollama --version
ollama pull qwen3-vl:4b-instruct
ollama list
```

Use an up-to-date Ollama release; Qwen3-VL requires at least 0.12.7.
The native app normally serves at `http://127.0.0.1:11434`. On Linux, use the
official installation steps and start the Ollama service. Use `ollama serve`
only if an Ollama server is not already running.

For local-only operation, set the **user environment variable**
`OLLAMA_NO_CLOUD=1`, then quit and restart Ollama. On Windows you can set it
through “Edit environment variables for your account.” This must affect the
Ollama server; placing it only in the bot's `.env` does not do that.

If disk space is tight, set `OLLAMA_MODELS` to a folder on a drive with enough
space before downloading and restart Ollama. Do not download the 8B model
until you intend to test it. Avoid model names ending in `-cloud`.

## 2. Install Python and Tesseract

Install Python 3.12 from <https://www.python.org/downloads/>. Install Tesseract
5 and its English language data. The official Tesseract installation guide
links the Windows installer maintained by UB Mannheim:
<https://tesseract-ocr.github.io/tessdoc/Installation.html#windows>.

Add the installed Tesseract executable directory to your user `Path`, then
open a new terminal. Confirm:

```powershell
py -3.12 --version
tesseract --version
tesseract --list-langs
```

The languages must include `eng`. On Ubuntu/Debian the OCR packages are
`tesseract-ocr` and `tesseract-ocr-eng`; on macOS see the Homebrew/MacPorts
instructions in the same Tesseract guide.

## 3. Configure the extracted agent

Extract `BPSC_Telegram_Agent.zip`. Open PowerShell **inside its
`bpsc-telegram-agent` folder**, where `bot.py` is located:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.ollama.example .env
notepad .env
```

The supplied file starts with:

```dotenv
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3-vl:4b-instruct
OLLAMA_NUM_CTX=32768
OLLAMA_NUM_PREDICT=12000
OLLAMA_TIMEOUT_SECONDS=1200
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
DATA_DIR=./data
MAX_MODEL_CALLS_PER_EDITION=140
```

Leave Telegram values empty for the local trial. No `OPENAI_API_KEY` or
`OLLAMA_API_KEY` is needed. Keep the `.env` file private.

On macOS/Linux, use `python3.12 -m venv .venv`,
`.venv/bin/python -m pip install -r requirements.txt`, and
`cp .env.ollama.example .env`. Substitute `.venv/bin/python` for the Windows
Python path in the remaining commands.

## 4. Test the model before using Telegram

```powershell
.\.venv\Scripts\python.exe bot.py check-model
```

This checks that the installed model reports vision capability, reads a
generated test image and returns valid structured JSON. It contacts your local
Ollama only. A pass confirms connectivity and a basic image-reading check;
it does not establish newspaper accuracy or test OCR installation.

Place one matching pair of newspapers in the project folder as `hindu.pdf`
and `express.pdf`. Use the actual printed edition date; this example is for
the 22 September 2026 papers:

```powershell
.\.venv\Scripts\python.exe bot.py process-local --date 2026-09-22 --th hindu.pdf --ie express.pdf
```

This runs the full workflow without posting to Telegram. A successful run
prints the PDF path under `data/2026-09-22/`. Compare the selected stories,
headlines, columns, graphics and continuations with both original papers.

## 5. Connect your channel

1. Open the official <https://t.me/BotFather>, send `/newbot`, and create a
   dedicated bot. Put its token in `TELEGRAM_BOT_TOKEN` in your local `.env`.
2. Add that bot as an administrator of your own channel with **Post Messages**.
3. Post a new test message in the channel, then run:

```powershell
.\.venv\Scripts\python.exe bot.py discover-channel
```

Match the channel title and enter its numeric ID in `TELEGRAM_CHANNEL_ID`.
Then check permissions and start the listener:

```powershell
.\.venv\Scripts\python.exe bot.py check
.\.venv\Scripts\python.exe bot.py serve
```

Keep this process and Ollama running. Upload both PDFs to your channel with
captions using the same actual date, for example `#TH 2026-09-24` and
`#IE 2026-09-24`. After both arrive and checks pass, the bot sends the combined
original-cuttings PDF to the same channel. No scheduled cloud task is needed.

## 6. Daily operation

For a first run, keep the terminal open. Stop with Ctrl+C. Later you can use
Windows Task Scheduler to start the service at sign-in: select the full path
to `.venv\Scripts\python.exe`, arguments `bot.py serve`, and set **Start in**
to the extracted project folder. Configure it to keep running and not start
a second instance. Ollama must also start. This schedules the listener;
the arrival of both newspapers still triggers each edition.

The computer must be awake and online to receive/process uploads and send
results. Incoming downloadable PDFs are limited to 20 MB with the hosted
Telegram Bot API. Do not rely on catching uploads after a long shutdown:
Telegram retains pending updates for at most 24 hours. Re-upload missed papers.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Cannot inspect model | Open Ollama; check `ollama list`; use the exact model tag and server root URL. |
| Vision support missing | Update Ollama and use a vision model such as the documented Qwen3-VL tag. |
| Tesseract not found | Add its installation folder to `Path`, open a new terminal and confirm `eng` is installed. |
| Slow, out of memory or timeout | Check `ollama ps`, free RAM/VRAM and Ollama logs. Choose model/context settings for your hardware; the default request timeout is 20 minutes. |
| Context estimate exceeded | The request was not sent or shortened. A large edition may need `OLLAMA_NUM_CTX=65536` or more; that uses more memory. The estimate is approximate, not an exact tokenizer or a guarantee against server truncation. |
| Incomplete/invalid JSON | Check model quality and context/output limits. More output tokens also require enough context for the input. |
| Selection or crop check fails | Inspect the date's JSON diagnostics and originals. Do not disable validation to force publication. A stronger model may be necessary. |
| No channel detected | Add bot as admin, post a new message and retry discovery while the main listener is stopped. |
| Service stopped midway | Restart; persisted jobs and cached valid responses support recovery. See README for uncertain Telegram delivery. |

The comparison/planning request preserves every candidate ID but omits repeated
crop boxes and historical references to reduce context usage. It retains facts,
mains angles and continuation links. Very large editions can still exceed the
selected context. Temperature zero and schema validation do not prove factual
accuracy. No full-edition runtime or quality score is claimed.

## If you choose Docker later

The native Python setup above avoids container-to-host networking. Inside a
container, `127.0.0.1` refers to that container. Do not copy the native URL
unchanged into Docker. A Docker setup needs a reachable Ollama host address
or a separate Ollama service, plus `/data` for the bot's persistent volume.
Docker networking/GPU configuration was not tested here.

## Sources and validation

Official references checked on 24 September 2026:

- <https://docs.ollama.com/windows>
- <https://docs.ollama.com/capabilities/vision>
- <https://docs.ollama.com/capabilities/structured-outputs>
- <https://docs.ollama.com/api/chat>
- <https://docs.ollama.com/api/authentication>
- <https://docs.ollama.com/faq>
- <https://ollama.com/library/qwen3-vl>
- <https://tesseract-ocr.github.io/tessdoc/Installation.html>
- <https://core.telegram.org/bots/api>

See `VALIDATION.md` for the tested boundaries. The code is prepared; your
computer, model, Telegram token and channel are not connected by this download.

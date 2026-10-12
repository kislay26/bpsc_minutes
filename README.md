# Sol — BPSC current affairs in your Telegram channel

Upload one or both newspapers to a channel you own. This service saves the
PDFs until you post a `run` command, then selects BPSC-relevant
articles, crops the original PDF artwork, and posts the cuttings PDF back to
that channel.

## Chat with Sol

Open a private chat with the bot and send `/start`. Sol asks whether you are
preparing for prelims, mains, or both, then asks for English, Hindi, or
Hinglish. After that, its persistent Telegram menu offers **Today**, **Ask
Sol**, **Practice 5**, and **My Plan**. You can also type a normal question,
such as “Explain the Bihar budget in simple terms.” Sol saves only the exam
stage, language, and future study-preference fields needed for this experience.

The channel remains the place to upload newspapers and post `run`.

The code is prepared, but no bot, API account or hosted service has been
connected or activated. See VALIDATION.md for the exact checks performed.

## Run with local Ollama (no paid model API)

Start with **[OLLAMA_SETUP.md](OLLAMA_SETUP.md)**. It covers Windows without
Docker, a local model test, a newspaper trial, Telegram setup and daily use.
Copy `.env.ollama.example` to `.env` for this option. The Python service calls
Ollama's native local `/api/chat` endpoint with images and a JSON schema; it
does not require an OpenAI key. A computer must remain awake while processing.

The existing OpenAI option remains available. Its Docker instructions below
use `.env.example`; do not mix those settings with the native Ollama guide.

## What you will see

1. Upload one PDF with a caption such as `#TH 2026-09-23`.
2. Optionally upload the other paper with `#IE 2026-09-23`.
3. Post `run` as a text message in the same channel.
4. The bot processes the saved one-paper or two-paper edition.
5. After selection and crop checks pass, it posts
   `BPSC_Cuttings_2026-09-23.pdf` to the same channel.

Either newspaper may arrive first, including as separate items in an album. A
single uploaded paper can be processed; uploading both before `run` produces
one combined PDF.
Dates embedded in descriptive filenames also work, including `22~09~2026`.
Explicit captions are more reliable. Never pair two different edition dates.
Edit a wrong caption before processing starts, or upload corrected documents
with matching filenames/captions. Edits are recognized, but changing an
already registered date does not remove the old waiting entry; inspect status.

The output PDF has original text, photos, charts and layout, with subject and
source bookmarks. It has no generated cover, notes, relevance paragraphs or
rewritten articles. An irregular article may occupy several cutting pages to
preserve all its columns and continuations.

## One-time Telegram setup

1. Create a channel that you own. A private channel is suitable.
2. Open the official [@BotFather](https://t.me/BotFather), send `/newbot`, and
   create a dedicated bot. Save its token locally.
3. Add this bot to your channel as an administrator and enable **Post Messages**.
   The service does not need permission to add admins, invite users or delete posts.
4. Extract this project onto a computer or server with Docker and Docker Compose.
   It must stay running to receive uploads and process editions.
5. Copy `.env.example` to `.env`. Fill in `TELEGRAM_BOT_TOKEN`, your
   `OPENAI_API_KEY`, and `OPENAI_MODEL`. Choose a model available to your API
   account that supports image input and Responses API strict structured
   output. This project deliberately leaves the model name configurable.
   The model API and hosting can incur charges; no API credentials are included.
6. Build the container:

   ```bash
   docker compose build
   ```

7. Post a new test message in your channel, then run:

   ```bash
   docker compose run --rm bpsc-agent python bot.py discover-channel
   ```

   Match the displayed channel title and copy its numeric ID, usually starting
   with `-100`, into `TELEGRAM_CHANNEL_ID` in `.env`. This command does not send
   a message or start the cuttings flow. Stop any other runner before discovery.
8. Check the identity and permissions without posting:

   ```bash
   docker compose run --rm bpsc-agent python bot.py check
   ```

9. Once the printed bot and channel match your choices, start the service:

   ```bash
   docker compose up -d
   docker compose logs -f --tail=100
   ```

10. Upload one or both newspaper PDFs using the captions shown above, then post
    `run`. Inspect the first
    few outputs for article selection and complete cropping before relying on it
    for daily preparation. Model judgments are not guaranteed to be correct.

Do not paste tokens into your Telegram channel or commit `.env` to Git. Tokens
belong in your local configuration or hosting secret store. The service reads
only its configured channel. It does not sign in as your personal Telegram
account or access the original channel you subscribe to.

## How the flow works

- A long-polling collector receives `channel_post` and `edited_channel_post`
  updates. It keeps receiving while the processing worker is busy. An inbound
  public webhook or domain name is not required.
- SQLite records update IDs, document IDs, edition dates and job states on a
  persistent Docker volume. It starts an edition only after its `run` command.
- The worker downloads the documents and reads their mastheads/dates to check
  that upload labels match their contents.
- Each page is rendered for a vision model, with Tesseract OCR as supporting
  text/layout data. The model returns structured article selections and boxes.
- A second planning step groups continuations and removes redundant coverage.
  Every detected candidate must be accounted for. Unresolved continuations
  stop the run for inspection.
- PyMuPDF copies the selected regions directly from the original PDFs. Native
  text stays native where available, and scanned pages remain original images.
- Each assembled article is checked against its source pages. One bounded crop
  repair is attempted if necessary. Persistent problems stop the edition and
  post a notice instead of publishing an incomplete partial selection.
- The final PDF is posted with `#SOL_OUTPUT`. Both this marker and the output
  filename prefix are ignored by input routing, so the output cannot start a
  feedback loop even when channel posts have anonymous senders.

This is a command-triggered service. There is no fixed daily schedule in this
version; it starts only after you post `run` for a saved edition. If several
editions are waiting, post `run YYYY-MM-DD` to choose one. A fixed
delivery-time gate can be added later if you want it.

## BPSC relevance

The `select-bpsc-news` skill now runs during page inspection and before article
grouping. It replaces the original generic rubric with ten question-pattern
categories derived from a documented review of the 60th–62nd through 71st CCE
cycles in the 23 September 2016–23 September 2026 window.

The evidence ledger has 198 selected prelims and mains examples from 30 linked
documents. See `BPSC_PYQ_Research.md` for readable references and
`selection_skill/methodology.md` for source quality and limitations. This is a
representative evidence set, not an exhaustive frequency study. Official archive
retrieval failed, so booklet mirrors and labelled transcriptions were used.

The filter keeps prelims facts and mains analysis, gives substantive Bihar
material extra priority, and retains relevant short award, book and sports
briefs. It records exact past-question analogies where available. New issues
may qualify as clearly labelled syllabus extensions. It imposes no daily quota
or rigid age cutoff and never claims that an article will appear in the exam.

`news_selection.py` validates evidence IDs and returns include, exclude,
attach_only or review. A planner cannot discard a qualifying item without
identifying a retained duplicate. Referenced continuation pages must be present.
Unreadable potentially relevant material stops the edition for inspection.

The runtime snapshot is in `selection_skill/`; this folder and
`news_selection.py` must be deployed together. The old `bpsc_rubric.md` is now
a guide to that policy, not the active prompt. Changes to the runtime policy
or selector change its fingerprint and the model-selection cache keys. Updating
the personal ChatGPT skill alone does not update an already deployed server.

Selection explanations, extracted facts and question references stay in
`candidates.json`, `relevance_decisions.json`, `selection.json` and `audit.json`.
They are never printed on the cuttings. The PDF still contains only original
newspaper artwork. Crop positions are determined afresh for each edition.

## Operation and recovery

```bash
# Read local queue state
docker compose exec bpsc-agent python bot.py status

# Retry a failed date after fixing the cause
docker compose exec bpsc-agent python bot.py retry 2026-09-23

# Stop the service, preserving its database and downloaded files
docker compose down
```

Duplicate update deliveries and repeated uploads of the same document are
ignored. Replacement files are accepted while waiting, queued, or failed.
An edition already processing or completed is not automatically rerun.
Use a fresh date for the next edition, not a new date for an old paper.

If a send times out or the process restarts during sending, Telegram may have
received the file without returning confirmation. The job becomes
`delivery_unknown`; the service does not automatically send it again. Inspect
the channel. Only if the result is absent, run:

```bash
docker compose exec bpsc-agent python bot.py retry 2026-09-23 --delivery-checked
```

Model responses and OCR are cached by content. Retries reuse valid responses
and count uncached calls against the per-edition limit in `.env`. This limit is
not a monetary budget. If a quality failure repeats, inspect the model, rubric
and local diagnostics before clearing selected cache entries or raising limits.

Under `/data/<date>/`, the service stores inputs, model/OCR caches, selection
decisions, article previews, the final PDF, and `audit.json`. A failed crop has
a `quality_failure.json` report. The worker does not delete source posts.
Data is retained until you remove it; monitor disk usage. Do not delete the
SQLite database to clean up PDFs, and do not use `docker compose down -v`
unless you intend to remove all stored state.

## Limits and deployment notes

- This implementation uses Telegram's hosted Bot API: incoming downloadable
  PDFs must be at most 20 MB, and the outgoing PDF at most 50 MB. Oversized
  files stop with a clear notice. A local Bot API server is a separate future
  integration; it is not enabled by this project.
- Telegram retains unconsumed updates for no more than 24 hours. Keep the
  service online. If it was offline longer, re-upload missing editions after
  restart. A bot cannot retrieve arbitrary old channel history through this API.
- Each newspaper is limited to 80 unlocked, upright PDF pages. Protected or
  malformed PDFs fail explicitly. The code does not bypass content protection.
- Newspaper page images and extracted text are sent to the configured model
  endpoint for selection and crop checks. With the documented local Ollama
  setup, inference stays on your computer. The OpenAI option uses its configured
  external API. Telegram still receives the input and output PDFs.
- Runtime depends on page count, OCR, API latency and repair attempts. No fixed
  processing-time or article-selection accuracy guarantee has been measured.
- This is a single-worker personal-use service. Keep one instance per bot/data
  volume. It refuses to take over a bot with an existing webhook.
- Docker was not available in the authoring environment; the container build
  needs verification on your chosen host. Telegram delivery and real model
  judgments also need a live acceptance run with your credentials.
- Source packages include their own licenses. Review dependency licenses if
  adapting this personal project into a distributed commercial product.

## Local use without Telegram

On Python 3.12 with Tesseract installed:

```bash
python -m pip install -r requirements.txt
# In .env, use DATA_DIR=./data. Configure either local Ollama or OpenAI.
python bot.py process-local --date 2026-09-23 --th hindu.pdf --ie express.pdf
python -m unittest discover -s tests -v
```

`process-local` never posts to Telegram. The local `serve` command has native
file locking for Windows, Linux and macOS. Windows startup still needs an
acceptance run on your computer; it was not executed on Windows here.

## Official references checked during implementation

- [Telegram Bot API: updates, channel permissions, files and delivery](https://core.telegram.org/bots/api)
- [Telegram bot FAQ: channel posts](https://core.telegram.org/bots/faq)
- [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [PyMuPDF original-page clipping](https://pymupdf.readthedocs.io/en/latest/page.html#Page.show_pdf_page)
- [Ollama vision input](https://docs.ollama.com/capabilities/vision)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama local authentication](https://docs.ollama.com/api/authentication)

The package does not contain newspaper copies, user credentials or a running
deployment. Upload your newspaper copies to your own configured channel.

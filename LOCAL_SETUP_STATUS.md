# Local setup status — 27 September 2026

## Completed

- Created `.venv` using the existing Python 3.12.2 installation.
- Installed the pinned dependencies in `requirements.txt`.
- Created private `.env` with local Ollama and `qwen3-vl:2b`.
- Confirmed Ollama 0.34.4 and downloaded `qwen3-vl:2b`.
- Installed Tesseract 5.4 with `eng` and `osd` language data.
- Fixed UTF-8 model-cache reads on Windows.
- Enabled and passed the Windows worker-lock test.
- Added Unicode-cache and optional-thinking regression tests: **33 tests passed**.
- Disabled optional thinking when the model reports support for doing so.
- Limited `check-model` to 4096 context tokens, 128 output tokens and a maximum
  180-second request timeout. These are diagnostic settings, not newspaper settings.
- Added `run-bot.cmd` to resolve Tesseract and use UTF-8 console output.
- Verified both supplied PDFs are unlocked and upright. OCR confirms the printed
  date 2026-09-27: The Hindu has 18 pages and Indian Express has 22 pages.

## Live test results and current blockers

The original probe timed out after approximately 20 minutes. Ollama used CPU
inference, a 3584 MiB context cache, and generated thousands of thinking tokens.
The revised 4K-context probe also timed out during image processing. Its context
cache was 448 MiB. Neither probe passed; no newspaper selection or cuttings PDF
has been produced. The full newspaper pipeline has not been started.

Hardware: AMD Ryzen 3 3250U, about 5.9 GiB RAM visible to Windows, integrated
Radeon graphics. Windows reported only about 470 MiB free RAM with the model
unloaded. Close unused applications before retrying. More timeout alone does
not solve memory pressure. Do not lower the edition context blindly: the BPSC
evidence prompt alone is approximately 20 KB, before OCR and output.

Telegram token and channel ID were empty when checked. No Telegram calls or
posts have been made. Do not paste credentials into chat or this document.

## Resume in PowerShell

Run from `D:\All Projects\BPSC Minutes`:

```powershell
.\run-bot.cmd check-model
```

After the probe passes, run the real edition locally:

```powershell
.\run-bot.cmd process-local --date 2026-09-27 --th "Newspaper\THE HINDU HD Delhi Editable Full Edition 27~09~2026.pdf" --ie "Newspaper\INDIAN EXPRESS HD Delhi 27~09~2026.pdf"
```

Compare the output against both original papers for missed articles, relevance,
headlines, all columns, graphics and continuations. `check-model` does not prove
newspaper quality. Do not start unattended delivery before this review.

For Telegram, enter `TELEGRAM_BOT_TOKEN` directly in `.env`, add the bot to your
channel as an administrator with Post Messages permission, and post a new test
message. Then run:

```powershell
.\run-bot.cmd discover-channel
```

Match the returned channel title and put its numeric ID in
`TELEGRAM_CHANNEL_ID` in `.env`. Then:

```powershell
.\run-bot.cmd check
.\run-bot.cmd serve
```

Upload the original PDFs with `#TH 2026-09-27` and `#IE 2026-09-27` captions.
Keep one listener running, with the computer awake and Ollama available.

Regression tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Front-page OCR diagnostics are under `data/preflight/`.

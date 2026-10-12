# Gemini source-PDF workflow

This workflow is under live newspaper validation. A passing connectivity probe or
unit test is not a validated edition. Current output must be reviewed before delivery.

Keep the existing private key in `.env`. Use `.env.gemini.example` as a reference;
do not overwrite an existing `.env` containing credentials. Set `AI_PROVIDER=gemini`,
`GEMINI_MODEL=gemini-3.5-flash-lite`, and `GEMINI_MAX_OUTPUT_TOKENS=16384`.
Use a free-tier project without billing. Model access and quotas are determined by
Google; this program does not enable billing or bypass quotas.

The existing Python environment also needs `requirements-layout.txt` for image-based
newspapers. Tesseract must be installed. The optional layout detector runs on CPU;
Ollama and a GPU are not required for this workflow. Model downloads are kept under
the project's `.model-cache` folder.

```powershell
.\.venv\Scripts\python.exe bot.py check-model
.\.venv\Scripts\python.exe bot.py process-local --date 2026-09-27 --th "path/to/hindu.pdf" --ie "path/to/express.pdf"
```

Use the date printed in the actual PDFs. `process-local` does not post to Telegram.
It checks identity/date, extracts and audits each page, assesses BPSC evidence using
the existing selection policy, links continuations and duplicates through the existing
plan validator, then builds original-PDF cuttings. Any unresolved extraction,
selection, completeness or crop check stops the edition instead of publishing a partial result.

Source regions come from native PDF blocks or detected raster regions plus OCR.
Approximate model areas guide assignment; final cuts use original source geometry.
The model cannot replace final crop coordinates during edition QA. A failed final
QA requires ownership review rather than an unrestricted coordinate repair.

Responses and OCR/layout data are cached. `MAX_MODEL_CALLS_PER_EDITION` bounds all
uncached generation attempts across page subprocesses and metadata calls; its counter
persists in the edition folder. A quota response saves the server's cooldown. Restarting
reuses completed results but does not bypass a cooldown or reset the edition budget.
`GEMINI_CACHE_DIR` can point to a shared cache directory to reuse trials in edition runs.

The existing `serve` command supports the provider through the same processing entry
point. Telegram end-to-end delivery has not yet been validated for this workflow.

Article fragments retain their original relative page positions, including column wraps. Unrelated regions remain blank; the output does not stack fragments into a new reading order.

Selection responses are restricted to the policy catalog IDs. Invalid pattern/question relationships receive one correction attempt and otherwise stop processing. Intermediate candidate_progress.json is explicitly incomplete and is never a delivery artifact.

# Multi-page newspaper extraction

## Image-page layout benchmark

Install the optional detector with `python -m pip install -r requirements-layout.txt`.
Run `python layout_benchmark.py "path/to/express.pdf" --page 1` to generate a
detector JSON report and annotated PDF under `review/layout-detector`. This CPU
benchmark uses PP-DocLayout_plus-L and does not call Gemini. Downloads are routed
to the project's `.model-cache` directory. Detector output is experimental until
visually reviewed; region labels alone do not establish article membership.

Run from the project directory with the existing virtual environment. Set
`GEMINI_API_KEY` privately in `.env`; credentials are inherited by child processes,
never passed as command-line arguments or included in reports.

```powershell
.\.venv\Scripts\python.exe newspaper_batch.py --th "path/to/hindu.pdf" --ie "path/to/express.pdf" --pages 1,3
```

`--pages all` requests every PDF page and can consume substantial API quota.
PDF page numbers are physical file indexes, not printed newspaper page labels.

Each run creates a timestamped directory under `review/batches`. Each page has
its own log, extracted block ledger, model responses, and (when checks pass)
original-PDF crop preview. `summary.json` records every attempted page. Completed
API replies are cached by model and full request, including image and schema;
semantic checks are rerun on cached replies. Authentication or quota errors stop
the batch. Other page failures are recorded while remaining pages are attempted.

Set `GEMINI_MODEL` and optionally `GEMINI_OWNERSHIP_MODEL` in the environment to
choose an explicitly supported model. Each stage records its actual model.
`GEMINI_AUDIT_MODEL` selects the visual reviewer. Flash-Lite uses high reasoning
for these trials; this increases latency and token use and does not guarantee accuracy.
Newer Flash models may be listed in the catalog while generation is temporarily
unavailable. Only HTTP 502/503/504 receive two delayed retries; quota/auth errors
are not retried. Billing is never enabled by this code.
Server-provided quota cooldowns are saved per key/model without storing the key.
Restarting cannot bypass a live cooldown; cached responses can still be reused.

`GEMINI_LAYOUT_MODE=regions` tests a smaller article-area request, guided by source
headline locations. Python assigns whole source blocks to those approximate areas;
the model's approximate edges are never used as final crop boundaries. Uncovered
or conflicting blocks require an explicit ownership response. This mode remains
experimental until the resulting cuts pass review on multiple editions.

Overlapping source regions are assigned jointly as connected components. The
renderer partitions remaining same-article overlaps without increasing the
covered area. After rendering, a separate model audit compares the cuttings with
the source page and enlarged source contexts; a failed audit leaves a **rejected
draft**, not an accepted PDF. Reports explicitly distinguish awaiting audit,
rejected draft, and automated checks passed. Automated acceptance is not a human
accuracy certification.
Failed multi-cut audits receive an isolated comparison for each affected cutting.
Up to two bounded ownership repairs are allowed after confirmed failures; the rejected
PDF and findings are saved as `attempt-N-*`, and all checks run again. Persistent
failures stop the page. The default page timeout is 1,800 seconds and is configurable
with `--page-timeout`.
`replay_grouping.py` can render saved ownership responses without API calls.

The extractor detects broken embedded font mappings and recovers text through
Tesseract while retaining native block coordinates. Explicit, geometrically
unambiguous continuation labels inherit their preceding column's owner; changes
are recorded in `geometry_assignments.json`. Ownership schemas are partitioned
into at most 50 blocks per request, with the complete page ledger as context.

The optional detector is automatically used for full-page raster PDFs after
installing `requirements-layout.txt`. OCR words outside detected regions are
retained as separate blocks. Detector overlap and article ownership still require
validation; successful detection alone is not a successful article extraction.

This is an extraction benchmark, **not a complete BPSC edition generator**.
Passing structural checks does not prove semantic accuracy.
Cross-page continuation linking, BPSC assessment, deduplication, and Telegram
delivery are not wired into this command. The previous single-page Kaggle trial
can still be rebuilt with `build_gemini_trial.py`.

# Validation record

Updated on 24 September 2026. This is a runnable starter implementation,
not an activated Telegram service or a measured article-selection benchmark.

## Passed in the authoring environment

`python3 -m unittest discover -s tests -v`: **31 tests passed**.

Ollama update checks:

- A local HTTP test server exercised the real HTTP client against the native
  `/api/show` and `/api/chat` request shapes, including labelled images and
  JSON Schema. This was a stub, not Ollama inference.
- Local configuration needs no AI key and never sends a residual OpenAI key.
- Text-only models and reported cloud aliases fail before generation.
- Invalid/truncated model replies are rejected and are not cached.
- Cached retries, changed model names, call budgets and estimated context
  overflow behave as expected.
- Existing OpenAI request/configuration behavior remains covered.
- A second native Linux worker cannot acquire the same data-directory lock.

The selector policy/evidence snapshot is unchanged. The grouping input now
keeps every candidate ID, its decision, facts, mains angles and continuation
references while leaving out repetitive crop coordinates and PYQ metadata.

- Either upload order; both newspapers must have the same date.
- Duplicate update/upload handling and prevention of output feedback loops.
- Rejection of wrong channels, invalid/conflicting dates and oversized files.
- Date identification from real-style filenames and edited captions.
- Recovery after restart during processing; no blind retry after uncertain delivery.
- Processing-to-delivery orchestration using a simulated Telegram client.
- Native-text and scanned-image crop rendering: output pixels exactly matched
  the corresponding original source regions in the test fixtures.
- Complete local processing orchestration with explicit mocked vision decisions.
- Rejection of an unresolved continuation.

New selection-skill checks:

- The page-inspection prompt actually loads the evidence ledger and skill fingerprint.
- Award and sports briefs remain eligible without mains analysis; mains explainers
  remain eligible without one-line facts.
- Bihar keywords do not rescue ordinary crime, party chatter or other noise.
- New issues can qualify as labelled syllabus extensions without fabricated PYQs.
- No blanket cutoff for older data in new reports or confirmed future events.
- Invented question references and mismatched pattern/reference pairs fail validation.
- Unreadable relevant content stops the pipeline before grouping or publication.
- Qualifying articles cannot be dropped without a specifically retained duplicate.
- A claimed-complete story fails if its referenced continuation page is absent.
- Policy changes alter the fingerprint and the prompt used for model caching.

The tests use synthetic evidence and mocked model extraction. They establish
runtime rule enforcement, not measured AI relevance accuracy. The evidence
bundle contains 198 source-located examples from 30 linked documents; all
references resolve to declared patterns/sources and valid PDF page ranges.
The personal skill passed the skill-creator validation check.

Additional checks:

- All Python modules compiled, and the command-line help loaded.
- Tesseract successfully processed a real Indian Express front page, returning
  271 positioned OCR lines, including its 22 September 2026 masthead date.
- The clipping function was run on two previously selected real articles:
  one from The Hindu PDF page 12 and one from Indian Express PDF page 13.
  The resulting PDF was rendered with Poppler and visually inspected. Headlines,
  columns, photos, chart, article endings and surrounding margins were intact.
  These known coordinates tested clipping only, not fresh model selection.
- Credentials, source newspapers, runtime databases, model caches and temporary
  review PDFs are excluded from the deliverable archive.

## Not yet verified

- Ollama is not installed in the authoring environment. No real local model
  inference, full newspaper selection, GPU/RAM sizing or latency was measured.
  Run `check-model` and then `process-local` on the user's computer.
- Native Windows startup and its file-lock branch were added but could not be
  executed on Windows here. Run the first listener in a visible terminal.
- No Telegram token was supplied; no live Telegram calls or posts were made.
- No model API key/model was selected; no paid model requests were made.
  Automated article relevance, bounding boxes, deduplication, continuation
  matching and model-based crop checks still require a live acceptance run.
- Docker was unavailable here, so the image build and hosted startup have not
  been executed. Build and check the container on your chosen host.
- Long-term uptime, model cost, full-edition latency and performance across
  different editions have not been measured.

## First live acceptance run

1. Verify bot/channel identity and permissions with `python bot.py check`.
2. Upload one dated paper; confirm that the bot waits.
3. Upload the other paper for that date; confirm one combined PDF is posted.
4. Inspect selected articles and all their continuations against both originals.
5. Upload the same papers again; confirm that no duplicate output is posted.
6. Restart the service and inspect `status` to confirm retained state.

The active CCE policy is `selection_skill/selection_policy.json`. Keep the
personal skill and deployed snapshot in sync when changing it. Human review of
the first outputs is necessary to assess real model selection and crop quality.

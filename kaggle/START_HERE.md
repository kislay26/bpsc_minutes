# Clean Kaggle notebook: staged newspaper trial

This replaces the old notebook and its repair/diagnostic cells. Page inventory,
inventory coverage checking, single-article reading/crop regions and text-only
BPSC assessment now use separate requests. Original PDF clipping, selection
rules, continuation checks and final crop QA remain in place.

## Replace the old setup

1. Download any old outputs you want to keep, then stop the old notebook session.
2. Upload the new BPSC_Kaggle_Input.zip as a PRIVATE dataset version or dataset.
   Attach only that new input; detach the old bundle to avoid duplicate inputs.
3. Import BPSC_Kaggle_Trial.ipynb into a fresh PRIVATE notebook. Select GPU and
   enable Internet. Do not add any old repair or diagnostic cells.
4. Run cells 1-5: configuration, input, installation, Ollama and basic probe.
5. Run cell 6 for the real first Hindu page. Review page_trial_crops.pdf and
   page_trial.json against the original page: every article, column, caption,
   picture and ending. The preview includes nonqualifying stories too.
6. If satisfactory, set PAGE_REVIEWED = True in cell 7 and run it. Cell 8 processes
   both newspapers; cell 9 provides the finished PDF.

The bundled edition is 2026-09-27, regardless of today's date. No Telegram token
or AI API key is needed. The notebook does not post to Telegram.

## Progress and failures

Outputs and caches use /kaggle/working/data-staged/2026-09-27, separate from old
pipeline results. Each stage is cached; full processing reuses the page trial.
Installation adds wrapt to the isolated environment to address the missing module.
Other startup errors, if any, still require their own diagnosis.

The full run reports progress every 30 seconds. Incomplete model answers are
saved in last_incomplete_response.json with their stage and partial content;
no extra diagnostic cell is required. Keep outputs private: they contain source
newspaper text. Do not bypass failed checks.

Requests use 32,768 context tokens and at most 4,096 output tokens. The model-call
ceiling is 2,000 because there are multiple calls per article. This is a safety
ceiling, not a runtime estimate. Processing may take substantial GPU time.
Long articles or final grouping may still hit a bound and will fail explicitly.

## Verification limits

Automated tests use simulated AI responses. They test code and validation, not
real newspaper accuracy. Notebook syntax and ZIP contents are checked locally.
A successful live Kaggle newspaper run has NOT yet been established. The first
page preview is the next acceptance step, not a guarantee for all later pages.

Old repair and diagnostic files remain locally for reference. None is required
by this notebook. Download results before stopping the Kaggle session.

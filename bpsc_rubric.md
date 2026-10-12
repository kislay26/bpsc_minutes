# BPSC CCE selection policy

The active policy is `selection_skill/selection_policy.json`, executed by
`news_selection.py` and used automatically by `pdf_flow.py`.

Read `BPSC_PYQ_Research.md` and `selection_skill/methodology.md` for the
198 selected past-question examples, source links, scope and limitations.
This policy covers CCE General Studies; it is not a TRE syllabus filter.

Both high and standard priority items are retained. Short awards, books and
major sporting milestones can qualify alongside Bihar development, schemes,
reports, law, economy, environment, international affairs, science and culture.
Use current hooks and concrete facts or mains analysis, not keyword matching.
Keep generated analysis in audit files; output original cuttings only.

Edit the JSON policy and bump its version when changing selection rules.
Sync the personal skill and deployment snapshot together, then run the tests.
Editing this guide alone does not change runtime behaviour.

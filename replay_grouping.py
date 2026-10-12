"""Replay saved model assignments locally; never sends an API request."""
import argparse
import json
import time
import hashlib
from pathlib import Path
import fitz
from native_layout import overlap_components, parse_ownership, build_regions, reconcile_continuations
from region_assignment import assign_components
from native_layout import EXCLUSIONS


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('pdf', type=Path)
    ap.add_argument('--page', type=int, default=1)
    ap.add_argument('--output', type=Path, default=Path('review/grouped-replay'))
    args = ap.parse_args()
    blocks = json.loads((args.run/'blocks.json').read_text(encoding='utf-8'))
    inventory = json.loads(json.loads((args.run/'inventory-review.json').read_text(encoding='utf-8'))['content'])
    articles = {f'A{i}': title for i, title in enumerate(inventory['titles'], 1)}
    raw = {}
    for path in args.run.glob('ownership-*.json'):
        if path.stem.startswith('ownership-quality-repair') or path.stem in ('ownership-repair', 'ownership-regions', 'ownership-regions-refine'):
            continue
        content = json.loads(json.loads(path.read_text(encoding='utf-8'))['content'])
        if 'assignments' in content:
            rows = content['assignments']
            content = {str(row['component_id']): row['owner'] for row in rows}
            if len(content) != len(rows):
                raise ValueError('Duplicate component assignment in saved response.')
        if set(raw) & set(content):
            raise ValueError('Duplicate components across saved batches.')
        raw.update(content)
    owners = {}
    coarse_path = args.run/'ownership-regions.json'
    if (args.run/'ownership-regions-refine.json').exists():
        coarse_path = args.run/'ownership-regions-refine.json'
    if coarse_path.exists():
        zones = json.loads(json.loads(coarse_path.read_text(encoding='utf-8'))['content'])['zones']
        with fitz.open(args.pdf) as source:
            owners, _ = assign_components(blocks, overlap_components(blocks), zones,
                                           source[args.page-1].rect, list(articles)+EXCLUSIONS)
    for group in overlap_components(blocks):
        if str(group[0]) in raw:
            owners.update({str(ident): raw[str(group[0])] for ident in group})
    saved_report = args.run/'response.json'
    if saved_report.exists():
        saved = json.loads(saved_report.read_text(encoding='utf-8'))
        if saved.get('source_sha256') != hashlib.sha256(args.pdf.read_bytes()).hexdigest() or saved.get('source_page', 1) != args.page:
            raise ValueError('Source PDF/page does not match the saved trial.')
        owners = saved['owners']
    owners = parse_ownership(json.dumps(owners), blocks, list(articles))
    owners, changes = reconcile_continuations(blocks, owners, list(articles))
    started = time.monotonic()
    regions = build_regions(blocks, owners, list(articles))
    print('Geometry seconds:', round(time.monotonic()-started, 2), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'source_run': str(args.run), 'articles': articles, 'owners': owners,
              'regions': {k: [list(r) for r in rs] for k, rs in regions.items()},
              'accuracy_verified': False, 'replay': True}
    (args.output/'response.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with fitz.open(args.pdf) as source, fitz.open() as preview:
        for ident in articles:
            rects = regions[ident]
            from native_layout import render_article
            render_article(preview, source, args.page-1, rects)
        preview.set_toc([[1, title, i] for i, title in enumerate(articles.values(), 1)])
        preview.save(args.output/'crop_preview.pdf')
    print('Saved draft crop replay:', args.output, flush=True)


if __name__ == '__main__':
    main()

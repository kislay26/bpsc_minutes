"""Run independently audited page trials across PDFs; never claim edition success."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import fitz
from core import load_env


def page_passed(folder, code, source_sha256, page):
    if code != 0:
        return False
    try:
        report = json.loads((folder / 'response.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    review_path = folder/'independent_review.json'
    if review_path.is_file():
        review = json.loads(review_path.read_text(encoding='utf-8'))
        if review.get('accepted') is False or review.get('accepted_for_page_trial') is False:
            return False
    artifact = (folder/'crop_preview.pdf').is_file() or (report.get('no_editorial_content') is True and report.get('articles') == {})
    return (artifact and report.get('source_sha256') == source_sha256 and report.get('source_page') == page
            and report.get('native_geometry_checks_passed') is True
            and report.get('visual_audit_passed') is True)


def parse_pages(value, count):
    if value == 'all':
        return list(range(1, count + 1))
    pages = set()
    for part in value.split(','):
        ends = part.split('-')
        if len(ends) == 1:
            pages.add(int(ends[0]))
        elif len(ends) == 2:
            first, last = map(int, ends)
            if first > last:
                raise ValueError('Page range is reversed.')
            pages.update(range(first, last + 1))
        else:
            raise ValueError('Invalid page range.')
    if not pages or min(pages) < 1 or max(pages) > count:
        raise ValueError('Requested pages are outside the PDF.')
    return sorted(pages)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--th', type=Path)
    parser.add_argument('--ie', type=Path)
    parser.add_argument('--pages', default='1', help='PDF pages: 1,3,7-9 or all')
    parser.add_argument('--output', type=Path, default=Path('review/batches'))
    parser.add_argument('--page-timeout', type=int, default=1800,
                        help='Maximum seconds per page including one bounded quality repair')
    args = parser.parse_args()
    if args.page_timeout <= 0:
        parser.error('--page-timeout must be positive.')
    load_env()
    if not os.environ.get('GEMINI_API_KEY'):
        parser.error('Set GEMINI_API_KEY privately in .env.')
    jobs = []
    for paper, source in [('TH', args.th), ('IE', args.ie)]:
        if source is None:
            continue
        source = source.resolve()
        with fitz.open(source) as doc:
            if doc.needs_pass:
                parser.error('Unlock the source PDF first.')
            pages = parse_pages(args.pages, len(doc))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        jobs.extend((paper, source, digest, page) for page in pages)
    if not jobs:
        parser.error('Supply --th and/or --ie.')
    run = args.output.resolve() / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    run.mkdir(parents=True)
    summary = {'status': 'running', 'accuracy_verified': False,
               'bpsc_selection_tested': False, 'pages': []}
    for paper, source, digest, page in jobs:
        folder = run / f'{paper}-{page:03d}'
        folder.mkdir()
        print(f'{paper} PDF page {page}: starting', flush=True)
        with (folder / 'run.log').open('w', encoding='utf-8') as log:
            try:
                result = subprocess.run(
                    [sys.executable, '-u', str(Path(__file__).with_name('gemini_layout_trial.py')),
                     str(source), str(folder), str(page)],
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                         'GEMINI_CACHE_DIR': str(args.output.resolve() / 'http-cache')},
                    stdout=log, stderr=subprocess.STDOUT, timeout=args.page_timeout)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = -1
        output = (folder / 'run.log').read_text(encoding='utf-8')
        print(output[-4000:], flush=True)
        passed = page_passed(folder, code, digest, page)
        summary['pages'].append({'paper': paper, 'pdf_page': page,
                                 'source_sha256': digest, 'folder': folder.name,
                                 'status': 'automated_checks_passed' if passed else 'needs_review'})
        (run / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        if any(f'HTTP {status}' in output for status in (401, 403, 429)):
            print('Stopping batch after authentication/quota failure.', flush=True)
            break
    summary['status'] = 'review_required'
    summary['requested_pages'] = len(jobs)
    (run / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print('Batch report:', run / 'summary.json', flush=True)
    return 0 if len(summary['pages']) == len(jobs) and all(
        p['status'] == 'automated_checks_passed' for p in summary['pages']) else 1


if __name__ == '__main__':
    raise SystemExit(main())

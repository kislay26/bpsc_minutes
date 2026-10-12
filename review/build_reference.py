"""Manual reference for TH page 1, 2026-09-27. Not an automatic extractor."""
import hashlib
import json
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Newspaper/THE HINDU HD Delhi Editable Full Edition 27~09~2026.pdf'
OUT = Path(__file__).resolve().parent

# Assignments reviewed against this specific source page. Never reuse by ID on
# another PDF: IDs describe native blocks in this file, not stable article IDs.
ARTICLES = [
    ('Maharashtra govt. declares drought in 265 taluks', [[47, 48, 50, 49]]),
    ('Jharkhand govt. against mines Act to aid coal theft', [[51, 52]]),
    ('EC switches to damage control mode after facing flak over SIR',
     [[21, 23], [24, 14, 15], [22], [16, 17, 18, 19, 20, 78]]),
    ('Congress urges top court to hold CEC accountable', [[76, 77]]),
    ('Jaishankar lashes out at Sharif in UN speech', [[41, 44, 39, 40, 42, 43, 84]]),
    ('Golden double', [[65, 66, 68, 67]]),
    ('UPSC candidates challenge ambiguous CSE questions', [[72, 73, 69, 70, 71, 74, 75, 83]]),
    ('2 Naga civilians killed in Manipur Senapati; cowardly act, says CM', [[12, 13, 8, 11, 9, 10]]),
    ('Out of sync: Bengaluru AI system mistakes guitar case for pillion rider, issues challan',
     [[59, 63, 60, 53, 54, 55, 61, 62, 56, 57, 58, 64]]),
    ('China, U.S. agree to cut tariff, launch AI dialogue', [[80, 81, 79, 82]]),
]
EXCLUDED = [0, 1, 2, 3, 4, 5, 6, 7, *range(25, 39), 45, 46, 85, 86]


def main():
    with fitz.open(SOURCE) as source, fitz.open() as preview, fitz.open() as annotated:
        page = source[0]
        blocks = page.get_text('dict')['blocks']
        used = EXCLUDED + [i for _, groups in ARTICLES for group in groups for i in group]
        assert len(blocks) == 87 and len(used) == len(set(used)) and set(used) == set(range(87))
        annotated.insert_pdf(source, from_page=0, to_page=0)
        audit = []
        for number, (title, groups) in enumerate(ARTICLES, 1):
            rects = []
            owned = {i for group in groups for i in group}
            for group in groups:
                rect = fitz.Rect(blocks[group[0]]['bbox'])
                for ident in group[1:]:
                    rect |= fitz.Rect(blocks[ident]['bbox'])
                if number == 3 and group == [22]:
                    # The infographic's vector lettering is not represented in
                    # native text blocks. Preserve the entire visually reviewed panel.
                    rect = fitz.Rect(265, 558, 608, 724)
                rect = (rect + (-0.7, -0.7, 0.7, 0.7)) & page.rect
                for ident, block in enumerate(blocks):
                    if ident in owned or block['type'] != 0:
                        continue
                    other = fitz.Rect(block['bbox'])
                    assert (rect & other).get_area() <= other.get_area() * 0.01, (title, ident)
                rects.append(rect)
            for ident in owned:
                block = fitz.Rect(blocks[ident]['bbox'])
                assert any((rect & block).get_area() >= block.get_area() * .999 for rect in rects), ident
            width = max(r.width for r in rects) + 24
            height = sum(r.height for r in rects) + 12 * (len(rects) + 1) + 24
            dest = preview.new_page(width=width, height=height)
            dest.insert_text((12, 15), f'MANUAL REFERENCE | {number}', fontsize=6)
            y = 36
            for rect in rects:
                dest.show_pdf_page(fitz.Rect(12, y, 12+rect.width, y+rect.height), source, 0, clip=rect)
                y += rect.height + 12
                mark = annotated[0].add_rect_annot(rect)
                mark.set_info(title=str(number), content=title)
                mark.set_colors(stroke=(1, 0, 0))
                mark.update()
            audit.append({'title': title, 'groups': groups, 'rectangles_pdf_points': [list(r) for r in rects]})
        preview.set_toc([[1, title, i] for i, (title, _) in enumerate(ARTICLES, 1)])
        preview.save(OUT / 'TH_page1_manual_reference.pdf')
        annotated.save(OUT / 'TH_page1_reference_boundaries.pdf')
        (OUT / 'TH_page1_reference_audit.json').write_text(json.dumps({
            'manual_reference': True, 'automatic_pipeline_validated': False,
            'bpsc_selection_tested': False, 'continuations_assembled': False,
            'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'source_page': 1, 'articles': audit, 'excluded_block_ids': EXCLUDED,
            'note': 'EC infographic includes a manually located vector panel absent from native text blocks.'
        }, indent=2), encoding='utf-8')
    print('Created 10-page manual reference; all 87 native blocks accounted for.')
    print('Checked owned block coverage and absence of foreign text-block intersections.')


if __name__ == '__main__':
    main()

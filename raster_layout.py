"""Learned page regions with OCR, expressed in original PDF coordinates."""
import os
from pathlib import Path
import json
import hashlib

import fitz


def refine_overlapping_headline_bounds(page, blocks):
    from native_layout import matching_ocr_text_bounds, ocr_region_words
    headlines = [b for b in blocks if b.get('kind') == 'text'
                 and b.get('layout_label') == 'doc_title' and b.get('text', '').strip()]
    overlapping = set()
    for index, first in enumerate(headlines):
        for second in headlines[index+1:]:
            if (fitz.Rect(first['bbox']) & fitz.Rect(second['bbox'])).get_area() > .01:
                overlapping.update((first['id'], second['id']))
    for block in headlines:
        if block['id'] not in overlapping:
            continue
        words = ocr_region_words(page, fitz.Rect(block['bbox']))
        bounds = matching_ocr_text_bounds(block['text'], words)
        if bounds is not None:
            bounds &= fitz.Rect(block['bbox'])
            if not bounds.is_empty:
                block['bbox'] = list(bounds)


def refine_overlapping_source_headline_anchors(page, anchors, crop_anchors, articles, blocks):
    from native_layout import (matching_ocr_text_bounds, matching_ocr_title_bounds,
                               ocr_region_words)
    overlapping = set()
    owners = list(anchors)
    for index, first_owner in enumerate(owners):
        for second_owner in owners[index+1:]:
            for first in anchors[first_owner]:
                for second in anchors[second_owner]:
                    if (fitz.Rect(first['bbox']) & fitz.Rect(second['bbox'])).get_area() > .01:
                        overlapping.update(((first_owner, id(first)), (second_owner, id(second))))
    if not overlapping:
        return

    refined = {}
    for owner, anchor in ((owner, anchor) for owner in owners for anchor in anchors[owner]):
        if (owner, id(anchor)) not in overlapping:
            continue
        rect = fitz.Rect(anchor['bbox'])
        words = ocr_region_words(page, rect)
        bounds = (matching_ocr_text_bounds(articles[owner], words)
                  or matching_ocr_title_bounds(articles[owner], words))
        if bounds is None:
            continue
        bounds &= rect
        if not bounds.is_empty and bounds.get_area() > .01:
            refined[(owner, id(anchor))] = list(bounds)

    if not refined:
        return
    proposed = {
        (owner, id(anchor)): refined.get((owner, id(anchor)), anchor['bbox'])
        for owner in owners for anchor in anchors[owner]
    }
    for index, first_owner in enumerate(owners):
        for second_owner in owners[index+1:]:
            for first in anchors[first_owner]:
                for second in anchors[second_owner]:
                    first_rect = fitz.Rect(proposed[(first_owner, id(first))])
                    second_rect = fitz.Rect(proposed[(second_owner, id(second))])
                    if (first_rect & second_rect).get_area() > .01:
                        return

    for owner in owners:
        for anchor in anchors[owner]:
            bbox = refined.get((owner, id(anchor)))
            if bbox is None:
                continue
            anchor['bbox'] = bbox
            source_block = next((block for block in blocks if block['id'] == anchor['id']), None)
            if source_block is not None:
                source_block['bbox'] = bbox
            for crop_anchor in crop_anchors.get(owner, []):
                if crop_anchor['id'] == anchor['id'] and not crop_anchor.get('fragment'):
                    crop_anchor['bbox'] = bbox


def extract_raster_blocks(page):
    from native_layout import ocr_words
    cache = Path(__file__).resolve().parent / '.model-cache'
    for name, folder in [('PADDLE_PDX_CACHE_HOME', 'paddlex'), ('HF_HOME', 'huggingface'),
                         ('PADDLE_HOME', 'paddle')]:
        os.environ.setdefault(name, str(cache / folder))
    os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'BOS')
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    from paddleocr import LayoutDetection
    import numpy as np
    scale = 2000 / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    model_name = 'PP-DocLayout_plus-L'
    digest = hashlib.sha256(pix.samples + model_name.encode()).hexdigest()
    folder = cache / 'layout-results'
    folder.mkdir(parents=True, exist_ok=True)
    saved = folder / (digest + '.json')
    if not saved.exists():
        model = LayoutDetection(model_name=model_name, device='cpu', cpu_threads=2,
                                enable_mkldnn=False)
        result = next(iter(model.predict(image[:, :, ::-1].copy(), batch_size=1, layout_nms=True)))
        result.save_to_json(str(saved))
    data = json.loads(saved.read_text(encoding='utf-8'))
    detections = data.get('res', data)['boxes']
    blocks = []
    for detection in detections:
        rect = fitz.Rect([float(v)/scale for v in detection['coordinate']]) & page.rect
        if rect.is_empty or rect.is_infinite:
            raise ValueError('Layout detector returned invalid geometry.')
        blocks.append({'id': len(blocks), 'kind': 'image' if detection['label'] in
                       ('image', 'chart', 'table', 'figure') else 'text',
                       'bbox': list(rect), 'text': '', 'font_min': 0, 'font_max': 0,
                       'layout_label': detection['label'], 'layout_score': float(detection['score']),
                       'geometry_source': model_name, 'text_source': 'tesseract_ocr'})
    words = ocr_words(page)
    if not words or not blocks:
        raise ValueError('Raster extraction returned no text or layout regions.')
    for word in words:
        point = fitz.Point(word['cx'], word['cy'])
        candidates = [b for b in blocks if fitz.Rect(b['bbox']).contains(point)]
        if candidates:
            # Assign a word once, preferring the smallest text region over image panels.
            chosen = min(candidates, key=lambda b: (b['kind'] != 'text', fitz.Rect(b['bbox']).get_area()))
            chosen['text'] += (' ' if chosen['text'] else '') + word['text']
        else:
            # Never silently drop OCR words that the detector missed.
            blocks.append({'id': len(blocks), 'kind': 'text', 'bbox': word['bbox'],
                           'text': word['text'], 'font_min': 0, 'font_max': 0,
                           'geometry_source': 'unmatched_ocr_word', 'text_source': 'tesseract_ocr'})
    refine_overlapping_headline_bounds(page, blocks)
    return blocks

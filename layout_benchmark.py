"""Inspect learned layout detections on a PDF page without calling Gemini."""
import argparse
import json
import os
from pathlib import Path
import time

import fitz


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--page', type=int, default=1)
    parser.add_argument('--model', default='PP-DocLayout_plus-L')
    parser.add_argument('--output', type=Path, default=Path('review/layout-detector'))
    args = parser.parse_args()
    cache = Path('.model-cache').resolve()
    for name, folder in [('PADDLE_PDX_CACHE_HOME', 'paddlex'), ('HF_HOME', 'huggingface'),
                         ('PADDLE_HOME', 'paddle')]:
        os.environ.setdefault(name, str(cache / folder))
    os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'BOS')
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    from paddleocr import LayoutDetection
    args.output.mkdir(parents=True, exist_ok=True)
    with fitz.open(args.pdf) as doc:
        page = doc[args.page-1]
        scale = 2000 / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image_path = args.output / 'input.png'
        pix.save(image_path)
        started = time.monotonic()
        model = LayoutDetection(model_name=args.model, device='cpu', cpu_threads=2,
                                enable_mkldnn=False)
        result = next(iter(model.predict(str(image_path), batch_size=1, layout_nms=True)))
        result.save_to_json(str(args.output / 'detections.json'))
        payload = json.loads((args.output / 'detections.json').read_text(encoding='utf-8'))
        boxes = payload.get('res', payload)['boxes']
        with fitz.open() as annotated:
            annotated.insert_pdf(doc, from_page=args.page-1, to_page=args.page-1)
            for i, box in enumerate(boxes):
                rect = fitz.Rect([float(v)/scale for v in box['coordinate']]) & page.rect
                mark = annotated[0].add_rect_annot(rect)
                mark.set_info(title=f"{i}: {box['label']}", content=str(box['score']))
                mark.set_colors(stroke=(1, 0, 0))
                mark.update()
            annotated.save(args.output / 'layout_preview.pdf')
            annotated[0].get_pixmap(matrix=fitz.Matrix(.7, .7)).save(args.output / 'layout_preview.png')
        print(json.dumps({'model': args.model, 'regions': len(boxes),
                          'seconds': round(time.monotonic()-started, 1),
                          'labels': {label: sum(b['label']==label for b in boxes)
                                     for label in sorted({b['label'] for b in boxes})}}, indent=2))


if __name__ == '__main__':
    main()

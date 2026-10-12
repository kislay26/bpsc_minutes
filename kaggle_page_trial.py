"""Run the first real page through staged extraction and export review crops."""
import argparse
import json

import fitz

from core import Config, FlowError
from pdf_flow import Vision, PageScan, process_edition, crop_rect, atomic_json
from news_selection import NewsSelector
from pathlib import Path


class TrialComplete(Exception):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--th', required=True)
    args = parser.parse_args()
    cfg = Config.from_env()
    folder = cfg.root / args.date
    folder.mkdir(parents=True, exist_ok=True)
    status = folder / 'page_trial.json'
    atomic_json(status, {'passed': False})
    selector = NewsSelector(Path(__file__).parent / 'selection_skill')

    class TrialVision(Vision):
        def ask(self, schema, prompt, images=()):
            result = super().ask(schema, prompt, images)
            if schema is not PageScan:
                return result
            decisions = [selector.decide(a.evidence.model_dump()) for a in result.articles]
            if not result.articles or any(d['action'] == 'review' for d in decisions):
                raise FlowError('First-page extraction is empty or needs evidence review.')
            preview = folder / 'page_trial_crops.pdf'
            with fitz.open(args.th) as original, fitz.open() as output:
                for article in result.articles:
                    for box in article.boxes:
                        rect = crop_rect(original[0], box)
                        page = output.new_page(width=rect.width, height=rect.height)
                        page.show_pdf_page(page.rect, original, 0, clip=rect)
                output.save(preview)
            atomic_json(status, {'passed': True, 'visual_review_required': True,
                                  'scan': result.model_dump(), 'decisions': decisions})
            print('First-page extraction completed. Review page_trial_crops.pdf against TH page 1.', flush=True)
            print('This is a crop preview, not a validated final edition.', flush=True)
            raise TrialComplete()

    try:
        process_edition(cfg, args.date, {'TH': args.th}, vision=TrialVision(cfg, folder))
    except TrialComplete:
        return
    raise FlowError('The first-page trial did not run.')


if __name__ == '__main__':
    main()

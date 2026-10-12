import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from bot import perform_job
from core import Config, FlowError, Store
from pdf_flow import (Box, Candidate, Check, Group, Identity, PageScan, Plan,
                      Region, SelectionEvidence, build_original_pdf, process_edition, validate_plan)
from transport import DeliveryUnknown

CHANNEL = -1001234567890


def fixture_evidence(**updates):
    data = dict(kind='development', status='reported', pattern_ids=['BIHAR_SCHEMES'],
        pyq_ids=['BPSC-71-prelims-Q26'], syllabus_links=['Bihar development'],
        event_hook='A newly reported state education programme.',
        prelim_facts=['The programme supports schoolchildren.'], mains_angles=[],
        bihar_link='Bihar programme', match_explanation='Programme objective and beneficiary pattern.',
        noise_reason='none')
    return SelectionEvidence(**(data | updates))


def update(n, paper='TH', edition='2026-09-23', unique=None, channel=CHANNEL):
    return {'update_id': n, 'channel_post': {'message_id': n, 'chat': {'id': channel},
        'caption': f'#{paper} {edition}', 'document': {'file_id': f'file-{n}',
        'file_unique_id': unique or f'unique-{n}', 'file_name': f'{paper}.pdf', 'file_size': 900}}}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def test_either_order_waits_for_matching_date(self):
        self.store.ingest(update(1, 'IE'), CHANNEL)
        self.assertIsNone(self.store.claim())
        self.store.ingest(update(2, 'TH', '2026-09-22'), CHANNEL)
        self.assertIsNone(self.store.claim())
        self.store.ingest(update(3, 'TH'), CHANNEL)
        date, uploads = self.store.claim()
        self.assertEqual(date, '2026-09-23')
        self.assertEqual({u['paper'] for u in uploads}, {'TH', 'IE'})
        self.assertIsNone(self.store.claim())

    def test_run_without_date_notifies_when_multiple_editions_are_waiting(self):
        self.store.ingest(update(1, 'TH', '2026-09-22'), CHANNEL)
        self.store.ingest(update(2, 'TH', '2026-09-23'), CHANNEL)
        run = {'update_id': 3, 'channel_post': {'message_id': 3,
               'chat': {'id': CHANNEL}, 'text': 'run'}}

        self.store.ingest(run, CHANNEL)

        self.assertEqual(self.store.pop_notice(),
                         '2026-09-22: The Hindu saved. You can upload the other newspaper for this date, or post run to process this PDF by itself.')
        self.assertEqual(self.store.pop_notice(),
                         '2026-09-23: The Hindu saved. You can upload the other newspaper for this date, or post run to process this PDF by itself.')
        self.assertEqual(self.store.pop_notice(),
                         'More than one edition is waiting: 2026-09-22, 2026-09-23. Post run followed by the date you want.')
        self.assertIsNone(self.store.claim())

    def test_run_without_date_notifies_when_no_editions_are_waiting(self):
        run = {'update_id': 1, 'channel_post': {'message_id': 1,
               'chat': {'id': CHANNEL}, 'text': 'run'}}

        self.store.ingest(run, CHANNEL)

        self.assertEqual(self.store.pop_notice(),
                         'Nothing is waiting. Upload a newspaper PDF first.')
        self.assertEqual(self.store.offset(), 2)

    def test_run_for_an_edition_already_processing_notifies_without_crashing(self):
        self.store.ingest(update(1), CHANNEL)
        edition = '2026-09-23'
        self.store.ingest({'update_id': 2, 'channel_post': {
            'message_id': 2, 'chat': {'id': CHANNEL}, 'text': f'run {edition}'}}, CHANNEL)
        edition, _ = self.store.claim()
        run = {'update_id': 3, 'channel_post': {'message_id': 3,
               'chat': {'id': CHANNEL}, 'text': f'run {edition}'}}

        self.store.ingest(run, CHANNEL)

        self.assertEqual(self.store.status()[0]['status'], 'processing')
        self.assertEqual(self.store.pop_notice(),
                         f'{edition}: The Hindu saved. You can upload the other newspaper for this date, or post run to process this PDF by itself.')
        self.assertEqual(self.store.pop_notice(),
                         f'{edition}: processing started for The Hindu.')
        self.assertEqual(self.store.pop_notice(),
                         f'{edition}: cannot start because its status is processing. Use status or retry if it failed.')

    def test_duplicate_uploads_and_anonymous_output_do_not_rerun(self):
        first = update(1)
        self.store.ingest(first, CHANNEL)
        self.store.ingest(first, CHANNEL)
        self.store.ingest(update(2, 'IE'), CHANNEL)
        edition, _ = self.store.claim()
        self.store.set_status(edition, 'done', message=50)
        self.store.ingest(update(3, unique='unique-1'), CHANNEL)
        outgoing = update(4)
        outgoing['channel_post']['caption'] = '#BPSC_OUTPUT The Hindu and Indian Express 2026-09-23'
        outgoing['channel_post']['document']['file_name'] = 'BPSC_Cuttings_2026-09-23.pdf'
        self.store.ingest(outgoing, CHANNEL)
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.status()[0]['status'], 'done')
        self.assertEqual(self.store.offset(), 5)

    def test_wrong_channel_bad_dates_and_oversize_are_not_queued(self):
        self.store.ingest(update(1, channel=-100999), CHANNEL)
        self.store.ingest(update(2, edition='2026-02-30'), CHANNEL)
        oversize = update(3)
        oversize['channel_post']['document']['file_size'] = 20_000_001
        self.store.ingest(oversize, CHANNEL)
        conflict = update(4)
        conflict['channel_post']['document']['file_name'] = 'The Hindu 22~09~2026.pdf'
        self.store.ingest(conflict, CHANNEL)
        self.assertEqual(self.store.status(), [])
        self.assertIsNotNone(self.store.pop_notice())

    def test_filename_detection_and_caption_edit(self):
        first = update(1)
        first['channel_post']['caption'] = ''
        first['channel_post']['document']['file_name'] = 'THE HINDU Delhi 22~09~2026.pdf'
        self.store.ingest(first, CHANNEL)
        second = update(2, 'IE', '2026-09-22')
        second['edited_channel_post'] = second.pop('channel_post')
        self.store.ingest(second, CHANNEL)
        self.assertEqual(self.store.claim()[0], '2026-09-22')

    def test_restart_recovers_processing_but_not_uncertain_delivery(self):
        for i, day in enumerate(['2026-09-22', '2026-09-23']):
            self.store.ingest(update(i*2+1, 'TH', day), CHANNEL)
            self.store.ingest(update(i*2+2, 'IE', day), CHANNEL)
        first, _ = self.store.claim()
        second, _ = self.store.claim()
        self.store.set_status(second, 'sending')
        restarted = Store(self.root)
        restarted.recover()
        self.assertEqual(restarted.claim()[0], first)
        self.assertIsNone(restarted.claim())
        with self.assertRaises(FlowError):
            restarted.retry(second)
        restarted.retry(second, delivery_checked=True)
        self.assertEqual(restarted.claim()[0], second)

    def test_worker_posts_to_configured_channel_and_records_delivery(self):
        self.store.ingest(update(1), CHANNEL)
        self.store.ingest(update(2, 'IE'), CHANNEL)
        fake = FakeTelegram()
        cfg = Config(self.root, channel=CHANNEL)
        perform_job(cfg, self.store, fake, *self.store.claim(), processor=fixture_processor)
        self.assertEqual(fake.sent[0][0], CHANNEL)
        self.assertIn('#BPSC_OUTPUT', fake.sent[0][2])
        self.assertEqual(self.store.status()[0]['output_message'], 500)
        self.assertEqual(self.store.status()[0]['status'], 'done')

    def test_ambiguous_delivery_requires_manual_check(self):
        self.store.ingest(update(1), CHANNEL)
        self.store.ingest(update(2, 'IE'), CHANNEL)
        fake = FakeTelegram(uncertain=True)
        perform_job(Config(self.root, channel=CHANNEL), self.store, fake,
                    *self.store.claim(), processor=fixture_processor)
        self.assertEqual(self.store.status()[0]['status'], 'delivery_unknown')
        self.assertIsNone(self.store.claim())


class FakeTelegram:
    def __init__(self, uncertain=False):
        self.sent = []
        self.uncertain = uncertain

    def download(self, ident, path):
        make_pdf(path)

    def document(self, channel, path, caption):
        if self.uncertain:
            raise DeliveryUnknown('Simulated missing delivery confirmation.')
        self.sent.append((channel, path, caption))
        return {'message_id': 500}


def fixture_processor(cfg, edition, paths):
    out = cfg.root / edition / f'BPSC_Cuttings_{edition}.pdf'
    make_pdf(out)
    return out, 2


def make_pdf(path, scanned=False):
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((35, 65), 'Original headline', fontsize=16)
    page.insert_text((35, 105), 'Complete original article body.', fontsize=12)
    page.insert_text((35, 125), 'End of this article.', fontsize=12)
    page.draw_rect(fitz.Rect(40, 145, 160, 200), color=(0.2, 0.4, 0.8), fill=(0.8, 0.9, 1))
    page.insert_text((35, 310), 'Unrelated advertisement', fontsize=14)
    if scanned:
        image = page.get_pixmap().tobytes('png')
        doc.close()
        doc = fitz.open()
        page = doc.new_page(width=400, height=500)
        page.insert_image(page.rect, stream=image)
    doc.save(path)
    doc.close()


class PDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_separated_regions_share_source_layout_in_final_pdf(self):
        with fitz.open() as source:
            page = source.new_page(width=300, height=300)
            page.insert_text((20, 30), 'LEFT')
            page.insert_text((170, 160), 'RIGHT')
            page.insert_text((20, 160), 'NEIGHBOR')
            regions = [Region(paper='TH', page=1, box=Box(
                x0=x0/300*1000, y0=y0/300*1000, x1=x1/300*1000, y1=y1/300*1000))
                for x0,y0,x1,y1 in [(10,10,100,50),(160,140,250,180)]]
            out = self.root/'layout.pdf'
            audit = build_original_pdf({'TH': source}, [{'title': 'Columns',
                'subject': 'Science', 'regions': regions, 'source_geometry': True}], out, '2026-09-27')
            with fitz.open(out) as result:
                self.assertEqual(len(result), 1)
                words = {w[4]: w for w in result[0].get_text('words')}
                self.assertEqual(set(words), {'LEFT', 'RIGHT'})
                self.assertAlmostEqual(words['RIGHT'][0]-words['LEFT'][0], 150, places=3)
                self.assertEqual([r['output_page'] for r in audit], [1, 1])
                self.assertAlmostEqual(audit[0]['rect'][0], 10, places=3)
                self.assertAlmostEqual(audit[1]['rect'][0], 160, places=3)

    def test_native_and_scanned_crops_are_visually_identical(self):
        for scanned in [False, True]:
            src = self.root / f'source_{scanned}.pdf'
            make_pdf(src, scanned)
            with fitz.open(src) as source:
                region = Region(paper='TH', page=1, box=Box(x0=50, y0=60, x1=750, y1=460))
                out = self.root / f'cut_{scanned}.pdf'
                audit = build_original_pdf({'TH': source}, [{'title': 'Original headline',
                    'subject': 'Science', 'regions': [region]}], out, '2026-09-23')
                with fitz.open(out) as target:
                    actual = target[0].get_pixmap(clip=fitz.Rect(12, 12, target[0].rect.width-12, target[0].rect.height-12), alpha=False)
                    expected = source[0].get_pixmap(clip=fitz.Rect(audit[0]['rect']), alpha=False)
                    self.assertEqual((actual.width, actual.height), (expected.width, expected.height))
                    self.assertEqual(actual.samples, expected.samples)
                    self.assertTrue(target.get_toc())
                    if not scanned:
                        text = target[0].get_text()
                        self.assertIn('Original headline', text)
                        self.assertNotIn('advertisement', text)

    def test_full_local_pipeline_with_mocked_model_decisions(self):
        paths = {p: self.root / f'{p}.pdf' for p in ['TH', 'IE']}
        for p in paths.values():
            make_pdf(p)
        model = FakeVision()
        # OCR is exercised separately on a real newspaper during package QA.
        with patch('pdf_flow.ocr_layout', return_value='Original headline and full article.'):
            result, count = process_edition(Config(self.root, model='offline-test-double'),
                                            '2026-09-23', paths, vision=model)
        self.assertEqual(count, 2)
        with fitz.open(result) as doc:
            self.assertEqual(len(doc), 2)
            self.assertTrue(all('Original headline' in p.get_text() for p in doc))
        audit = json.loads((result.parent / 'audit.json').read_text())
        self.assertEqual(len(audit['visual_checks']), 2)
        self.assertEqual(audit['selection_skill_version'], '1.0.0')
        self.assertTrue(all(x['action'] == 'include' for x in audit['relevance_decisions'].values()))
        decisions = json.loads((result.parent / 'relevance_decisions.json').read_text())
        self.assertEqual(decisions['skill_sha256'], audit['selection_skill_sha256'])

    def test_missing_continuation_blocks_output(self):
        c = Candidate(title='Story', subject='Bihar', relevance=3, reason='Bihar policy',
                      text_hint='', boxes=[Box(x0=0,y0=0,x1=100,y1=100)], continued_from='',
                      continues_to=['8'], evidence=fixture_evidence())
        plan = Plan(groups=[Group(title='Story', subject='Bihar', candidate_ids=['TH-1-1'],
                                 complete=False, reason='Missing page 8')], excluded=[])
        with self.assertRaises(FlowError):
            validate_plan(plan, {'TH-1-1': {'article': c}})


class FakeVision:
    def __init__(self):
        self.meta = 0

    def ask(self, schema, prompt, images=()):
        if schema is Identity:
            self.meta += 1
            return Identity(paper='TH' if self.meta == 1 else 'IE', edition_date='2026-09-23')
        if schema is PageScan:
            if 'BPSC-71-prelims-Q26' not in prompt or 'Skill fingerprint:' not in prompt:
                raise AssertionError('The selection skill was not loaded into the page prompt.')
            return PageScan(printed_page='1', articles=[Candidate(title='Original headline',
                subject='Bihar', relevance=3, reason='State development', text_hint='Full article',
                boxes=[Box(x0=50,y0=60,x1=750,y1=460)], continued_from='', continues_to=[],
                evidence=fixture_evidence())])
        if schema is Plan:
            return Plan(groups=[Group(title='Original headline', subject='Bihar',
                candidate_ids=[f'{p}-1-1'], complete=True, reason='Distinct topic') for p in ['TH','IE']], excluded=[])
        if schema is Check:
            return Check(ok=True, issues=[])
        raise AssertionError(f'Unexpected request: {schema}')


if __name__ == '__main__':
    unittest.main()

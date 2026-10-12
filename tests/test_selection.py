import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Config, FlowError
from news_selection import NewsSelector, SelectionError
from gemini_native import prune_unreferenced_patterns
from pdf_flow import (Box, Candidate, Excluded, Group, PageScan, Plan,
                      process_edition, validate_plan)
from test_workflow import FakeVision, fixture_evidence, make_pdf

BUNDLE = Path(__file__).resolve().parents[1] / 'selection_skill'


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.skill = NewsSelector(BUNDLE)

    def decide(self, **updates):
        return self.skill.decide(fixture_evidence(**updates).model_dump())

    def test_short_award_and_sports_briefs_survive_without_mains_analysis(self):
        for pattern, ref, fact in [
            ('PEOPLE_AWARDS_BOOKS', 'BPSC-71-prelims-Q9', 'Named author receives a major literary prize.'),
            ('SPORTS_EVENTS', 'BPSC-70-prelims-Q89', 'An athlete qualifies for a major international event.')]:
            with self.subTest(pattern=pattern):
                d = self.decide(pattern_ids=[pattern], pyq_ids=[ref], bihar_link='',
                    syllabus_links=[], prelim_facts=[fact], mains_angles=[],
                    event_hook='A confirmed milestone in this edition.', match_explanation='Same fact relationship as the referenced question.')
                self.assertEqual((d['action'], d['priority']), ('include', 'standard'))

    def test_mains_analysis_without_one_line_facts_is_kept(self):
        d = self.decide(kind='explainer', pattern_ids=['POLICY_LAW'],
            pyq_ids=['BPSC-68-mains_gs1-Q5b'], bihar_link='', prelim_facts=[],
            mains_angles=['Explains the institutional effects of a current constitutional dispute.'])
        self.assertEqual(d['action'], 'include')

    def test_bihar_is_not_a_keyword_pass_for_crime_or_party_quotes(self):
        for reason in ['routine_local_crime', 'routine_party_exchange', 'celebrity_gossip', 'market_tip', 'routine_match']:
            self.assertEqual(self.decide(kind='noise', noise_reason=reason)['action'], 'exclude')

    def test_novel_syllabus_issue_does_not_require_fabricated_history(self):
        d = self.decide(pattern_ids=[], pyq_ids=[], syllabus_links=['Science and health'], bihar_link='',
            event_hook='Newly reported public-health technology.', prelim_facts=['A reported mechanism.'])
        self.assertEqual((d['action'], d['basis']), ('include', 'syllabus_extension'))

    def test_old_data_and_future_confirmed_event_are_not_cut_off(self):
        for hook in ['New report revises 2018 employment data.', 'Confirmed venue for the 2030 major event.']:
            self.assertEqual(self.decide(event_hook=hook)['action'], 'include')

    def test_fake_reference_and_mismatched_pattern_are_rejected(self):
        with self.assertRaises(SelectionError):
            self.decide(pyq_ids=['BPSC-71-prelims-Q999'])
        with self.assertRaises(SelectionError):
            self.decide(pattern_ids=['SPORTS_EVENTS'])

    def test_unreferenced_pattern_claims_are_pruned_without_changing_question_refs(self):
        evidence = fixture_evidence(pattern_ids=['BIHAR_SCHEMES', 'POLICY_LAW'])

        normalized, removed = prune_unreferenced_patterns(evidence, self.skill)

        self.assertEqual(normalized.pattern_ids, ['BIHAR_SCHEMES'])
        self.assertEqual(normalized.pyq_ids, evidence.pyq_ids)
        self.assertEqual(removed, ['POLICY_LAW'])
        self.assertEqual(self.skill.decide(normalized.model_dump())['action'], 'include')

    def test_topic_only_and_unreadable_material_have_different_outcomes(self):
        self.assertEqual(self.decide(prelim_facts=[], mains_angles=[])['action'], 'exclude')
        self.assertEqual(self.decide(status='unreadable')['action'], 'review')
        self.assertEqual(self.decide(kind='continuation')['action'], 'attach_only')

    def test_changed_policy_changes_prompt_cache_key_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'bundle'
            shutil.copytree(BUNDLE, target)
            policy = json.loads((target / 'selection_policy.json').read_text())
            policy['version'] = '1.0.1-test'
            (target / 'selection_policy.json').write_text(json.dumps(policy))
            changed = NewsSelector(target)
            self.assertNotEqual(changed.fingerprint, self.skill.fingerprint)
            self.assertNotEqual(changed.prompt(), self.skill.prompt())

    def candidate(self, action='include'):
        evidence = fixture_evidence(kind='continuation' if action=='attach_only' else 'development')
        return {'article': Candidate(title='Story', subject='Bihar', relevance=3, reason='State programme',
            text_hint='Story', boxes=[Box(x0=0,y0=0,x1=100,y1=100)], continued_from='',
            continues_to=[], evidence=evidence), 'decision': {'action': action}}

    def test_plan_cannot_drop_qualifying_article_without_retained_duplicate(self):
        candidates = {'a': self.candidate(), 'b': self.candidate()}
        group = Group(title='Story', subject='Bihar', candidate_ids=['a'], complete=True, reason='Complete')
        for target in ['', 'missing', 'b']:
            with self.subTest(target=target), self.assertRaises(FlowError):
                validate_plan(Plan(groups=[group], excluded=[Excluded(candidate_id='b',
                    reason='duplicate' if target else 'Too short', duplicate_of=target)]), candidates)
        validate_plan(Plan(groups=[group], excluded=[Excluded(candidate_id='b',
            reason='duplicate facts covered by a', duplicate_of='a')]), candidates)

    def test_fragment_needs_qualifying_parent_and_excluded_cannot_be_selected(self):
        for action in ['attach_only', 'exclude', 'review']:
            with self.subTest(action=action), self.assertRaises(FlowError):
                validate_plan(Plan(groups=[Group(title='Story', subject='Bihar', candidate_ids=['a'],
                    complete=True, reason='Complete')], excluded=[]), {'a': self.candidate(action)})
        validate_plan(Plan(groups=[Group(title='Story', subject='Bihar', candidate_ids=['a','b'],
            complete=True, reason='Complete')], excluded=[]), {'a': self.candidate(), 'b': self.candidate('attach_only')})

    def test_pipeline_stops_before_grouping_unreadable_relevant_news(self):
        class UnreadableVision(FakeVision):
            def ask(self, schema, prompt, images=()):
                result = super().ask(schema, prompt, images)
                if schema is PageScan:
                    result.articles[0].evidence.status = 'unreadable'
                if schema is Plan:
                    raise AssertionError('Unreviewed content reached grouping.')
                return result
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {p: root / (p+'.pdf') for p in ['TH','IE']}
            for p in paths.values(): make_pdf(p)
            with patch('pdf_flow.ocr_layout', return_value='fixture'), self.assertRaisesRegex(FlowError, 'source review'):
                process_edition(Config(root), '2026-09-23', paths, vision=UnreadableVision())
            self.assertTrue((root/'2026-09-23/relevance_decisions.json').exists())
            self.assertFalse((root/'2026-09-23/BPSC_Cuttings_2026-09-23.pdf').exists())

    def test_claim_of_completeness_cannot_hide_a_missing_referenced_page(self):
        main = self.candidate()
        main.update(paper='TH', printed_page='1')
        main['article'].continues_to = ['II']
        part = self.candidate('attach_only')
        part.update(paper='TH', printed_page='II')
        plan = Plan(groups=[Group(title='Story', subject='Bihar', candidate_ids=['a'],
            complete=True, reason='Claimed complete')], excluded=[])
        with self.assertRaisesRegex(FlowError, 'continuation page'):
            validate_plan(plan, {'a': main})
        plan.groups[0].candidate_ids.append('b')
        validate_plan(plan, {'a': main, 'b': part})


if __name__ == '__main__':
    unittest.main()

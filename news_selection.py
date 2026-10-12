"""Execute the selection policy on extracted newspaper evidence (standard library)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


class SelectionError(ValueError):
    pass


class NewsSelector:
    def __init__(self, bundle: Path):
        self.bundle = Path(bundle)
        raw = {name: (self.bundle / name).read_bytes() for name in
               ('selection_policy.json', 'question_evidence.json', 'sources.json')}
        self.policy = json.loads(raw['selection_policy.json'])
        records = json.loads(raw['question_evidence.json'])
        self.sources = json.loads(raw['sources.json'])
        self.patterns = {p['id']: p for p in self.policy['patterns']}
        self.evidence = {r['id']: r for r in records}
        sources = {s['id']: s for s in self.sources['sources']}
        if len(self.evidence) != len(records) or not records:
            raise SelectionError('The evidence ledger is empty or has duplicate IDs.')
        for row in records:
            if row['pattern_id'] not in self.patterns or row['source_id'] not in sources:
                raise SelectionError('The evidence ledger has an unknown pattern or source.')
            if not 1 <= row['pdf_page'] <= sources[row['source_id']]['pages']:
                raise SelectionError('An evidence reference has an invalid PDF page.')
        if set(r['cycle'] for r in records) != set(self.sources['cycles']):
            raise SelectionError('The declared cycle coverage does not match the ledger.')
        digest = hashlib.sha256(Path(__file__).read_bytes())
        for name, data in sorted(raw.items()):
            digest.update(name.encode() + b'\0' + data)
        self.fingerprint = digest.hexdigest()

    def prompt(self):
        lines = ['BPSC CCE news-selection skill ' + self.policy['version'],
                 'Skill fingerprint: ' + self.fingerprint,
                 self.policy['evidence_type'], *self.policy['rules']]
        for pattern in self.patterns.values():
            lines.append('\n' + pattern['id'] + ': ' + pattern['select'])
            for row in self.evidence.values():
                if row['pattern_id'] == pattern['id']:
                    lines.append(f"{row['id']} [{row['classification']}]: {row['cue']}")
        lines.append('\nAllowed syllabus_links: ' + ', '.join(self.policy['syllabus_links']))
        return '\n'.join(lines)

    def decide(self, item: dict):
        """Validate provenance and apply the policy; extraction remains a model judgment."""
        required = {'kind', 'status', 'pattern_ids', 'pyq_ids', 'syllabus_links',
                    'event_hook', 'prelim_facts', 'mains_angles', 'bihar_link',
                    'match_explanation', 'noise_reason'}
        if set(item) != required:
            raise SelectionError('Selection evidence has missing or unknown fields.')
        list_fields = ('pattern_ids', 'pyq_ids', 'syllabus_links', 'prelim_facts', 'mains_angles')
        for key in list_fields:
            if not isinstance(item[key], list) or any(not isinstance(x, str) or not x.strip() for x in item[key]):
                raise SelectionError(f'Invalid evidence list: {key}.')
        for key in required - set(list_fields):
            if not isinstance(item[key], str):
                raise SelectionError(f'Invalid evidence text: {key}.')
        if item['kind'] not in ('development', 'explainer', 'continuation', 'noise'):
            raise SelectionError('Unknown article kind.')
        if item['status'] not in ('reported', 'proposal', 'contested', 'unreadable'):
            raise SelectionError('Unknown reporting status.')
        noises = ('none', 'advertisement', 'routine_local_crime', 'routine_party_exchange',
                  'celebrity_gossip', 'market_tip', 'routine_match', 'no_exam_substance')
        if item['noise_reason'] not in noises:
            raise SelectionError('Unknown exclusion category.')
        patterns, refs = set(item['pattern_ids']), set(item['pyq_ids'])
        if patterns - self.patterns.keys() or refs - self.evidence.keys():
            raise SelectionError('Unknown past-question ID or selection pattern; do not invent evidence.')
        if set(item['syllabus_links']) - set(self.policy['syllabus_links']):
            raise SelectionError('Unknown syllabus link.')
        referenced_patterns = {self.evidence[i]['pattern_id'] for i in refs}
        if patterns != referenced_patterns:
            raise SelectionError('Each claimed pattern needs a matching question reference.')
        basis = 'pyq_pattern' if refs else 'syllabus_extension' if item['syllabus_links'] else 'none'
        result = {'action': 'exclude', 'priority': 'none', 'basis': basis,
                  'pattern_ids': sorted(patterns), 'pyq_ids': sorted(refs),
                  'skill_version': self.policy['version'], 'skill_sha256': self.fingerprint}

        def answer(action, reason, priority='none'):
            return result | {'action': action, 'reason': reason, 'priority': priority}

        if item['kind'] == 'noise' or item['noise_reason'] != 'none':
            return answer('exclude', 'No substantive exam material: ' + item['noise_reason'])
        if item['kind'] == 'continuation':
            return answer('attach_only', 'Use only to complete a qualifying story.')
        if basis == 'none':
            return answer('exclude', 'No documented question pattern or specific syllabus link.')
        if item['status'] == 'unreadable':
            return answer('review', 'Potentially relevant material is unreadable; inspect the source.')
        if not item['prelim_facts'] and not item['mains_angles']:
            return answer('exclude', 'A topic mention alone supplies no usable exam material.')
        if not item['event_hook'].strip() or not item['match_explanation'].strip():
            return answer('review', 'Explain the current hook and the concrete exam connection.')
        priority = 'high' if item['bihar_link'].strip() or any(
            self.patterns[p]['priority'] == 'high' for p in patterns) else 'standard'
        return answer('include', item['match_explanation'], priority)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parent.parent / 'references')
    parser.add_argument('--input', type=Path, help='JSON object mapping candidate IDs to extracted evidence')
    parser.add_argument('--output', type=Path, help='Write decisions as JSON; otherwise print')
    parser.add_argument('--prompt', action='store_true', help='Print the evidence-backed extraction prompt')
    args = parser.parse_args()
    selector = NewsSelector(args.bundle)
    if args.prompt:
        print(selector.prompt())
        return
    if not args.input:
        parser.error('--input is required unless --prompt is used')
    result = {key: selector.decide(value) for key, value in json.loads(args.input.read_text()).items()}
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()

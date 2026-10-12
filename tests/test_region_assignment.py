import unittest
import fitz
from region_assignment import (assign_components, anchor_issues, footer_assignments,
                               include_source_headlines, trim_regions_at_foreign_headlines,
                               embedded_callout_merges)


class RegionTests(unittest.TestCase):
    def test_headline_completion_does_not_expand_body_zone(self):
        zones = [{'owner': 'a', 'boxes': [[0, 100, 600, 500]]}]
        anchors = {'a': [[0, 100, 700, 200]]}
        resolved = include_source_headlines(zones, anchors)
        self.assertEqual(resolved[0], zones[0])
        self.assertEqual(resolved[1]['boxes'], [[0, 100, 700, 200]])
        self.assertEqual(anchor_issues(resolved, anchors), [])
    def test_region_cannot_cut_through_known_headline(self):
        anchors = {'a': [[0, 100, 700, 200]], 'b': [[750, 100, 1000, 200]]}
        bad = [{'owner': 'a', 'boxes': [[0, 100, 600, 500]]},
               {'owner': 'b', 'boxes': [[600, 100, 1000, 500]]}]
        self.assertEqual(len(anchor_issues(bad, anchors)), 2)
        good = [{'owner': 'a', 'boxes': [[0, 100, 740, 500]]},
                {'owner': 'b', 'boxes': [[740, 100, 1000, 500]]}]
        self.assertEqual(anchor_issues(good, anchors), [])

    def test_foreign_headline_is_removed_from_overlapping_regions(self):
        anchors = {'A1': [], 'A3': [[758, 350, 996, 401]]}
        zones = [{'owner': 'A1', 'boxes': [[242, 142, 873, 442]]}]
        trimmed = trim_regions_at_foreign_headlines(zones, anchors)
        self.assertEqual(anchor_issues(
            include_source_headlines(trimmed, anchors), anchors), [])
        self.assertFalse(any(
            (fitz.Rect(zone['boxes'][0]) & fitz.Rect(anchors['A3'][0])).get_area() > .01
            for zone in trimmed))
        self.assertAlmostEqual(sum(fitz.Rect(zone['boxes'][0]).get_area()
                                   for zone in trimmed), 631*300-115*51)

    def test_source_headline_is_reincluded_after_foreign_region_trimming(self):
        anchors = {
            'A1': [[0, 37.9, 608.8, 87.1]],
            'A6': [[879.2, 243.8, 992.5, 305.6]],
        }
        zones = [
            {'owner': 'A1', 'boxes': [[0, 35, 666, 266]]},
            {'owner': 'A4', 'boxes': [[333, 90, 666, 505]]},
            {'owner': 'A6', 'boxes': [[833, 240, 1000, 505]]},
        ]
        trimmed = trim_regions_at_foreign_headlines(zones, anchors)
        restored = include_source_headlines(trimmed, anchors)
        final = trim_regions_at_foreign_headlines(restored, anchors)
        self.assertEqual(anchor_issues(final, anchors), [])
        for owner, box in (('A1', anchors['A1'][0]), ('A6', anchors['A6'][0])):
            self.assertTrue(any(
                zone['owner'] == owner
                and (fitz.Rect(zone['boxes'][0]) & fitz.Rect(box)).get_area()
                    >= fitz.Rect(box).get_area() * .98
                for zone in final))

    def test_footer_does_not_exclude_article_above_it(self):
        blocks = [{'id': 0, 'bbox': [0, 95, 60, 97], 'layout_label': 'footer', 'text': 'example.com'},
                  {'id': 1, 'bbox': [0, 91, 60, 94], 'text': 'story ends'},
                  {'id': 2, 'bbox': [80, 95, 90, 98], 'text': 'w'}]
        self.assertEqual(footer_assignments(blocks, [[0], [1], [2]], fitz.Rect(0, 0, 100, 100)),
                         {'0': 'exclude:print_mark', '2': 'exclude:print_mark'})

    def test_centered_footer_domain_despite_detector_text_label(self):
        blocks = [{'id': 0, 'bbox': [43, 98, 57, 99], 'layout_label': 'text', 'text': 'epaper.example.:com'},
                  {'id': 1, 'bbox': [60, 98, 64, 99], 'text': 'EE'}]
        self.assertEqual(footer_assignments(blocks, [[0], [1]], fitz.Rect(0, 0, 100, 100)),
                         {'0': 'exclude:print_mark', '1': 'exclude:print_mark'})

    def test_inset_sidebar_and_uncovered_block(self):
        blocks = [{'id': 0, 'bbox': [10, 10, 20, 20]},
                  {'id': 1, 'bbox': [70, 10, 80, 20]},
                  {'id': 2, 'bbox': [10, 90, 20, 100]}]
        zones = [{'owner': 'main', 'boxes': [[0, 0, 1000, 500]]},
                 {'owner': 'sidebar', 'boxes': [[600, 0, 900, 300]]}]
        owners, missing = assign_components(blocks, [[0], [1], [2]], zones,
                                             fitz.Rect(0, 0, 100, 100), ['main', 'sidebar'])
        self.assertEqual(owners, {'0': 'main', '1': 'sidebar'})
        self.assertEqual(missing, [2])

    def test_compact_paragraph_title_nested_in_story_is_detected_as_callout(self):
        blocks = [
            {'id': 1, 'kind': 'text', 'layout_label': 'doc_title'},
            {'id': 2, 'kind': 'text', 'layout_label': 'paragraph_title'},
        ]
        articles = {'A1': 'Main story', 'A2': 'Inset callout'}
        anchors = {
            'A1': [{'id': 1, 'bbox': [10, 10, 80, 20]}],
            'A2': [{'id': 2, 'bbox': [40, 40, 50, 45]}],
        }
        roles = {'1': 'headline', '2': 'headline'}
        zones = [
            {'owner': 'A1', 'boxes': [[0, 0, 800, 800]]},
            {'owner': 'A2', 'boxes': [[300, 300, 400, 400]]},
        ]
        self.assertEqual(
            embedded_callout_merges(articles, blocks, anchors, roles, zones),
            {'A2': 'A1'})

    def test_standalone_headline_is_not_merged_as_callout(self):
        blocks = [
            {'id': 1, 'kind': 'text', 'layout_label': 'doc_title'},
            {'id': 2, 'kind': 'text', 'layout_label': 'doc_title'},
        ]
        articles = {'A1': 'Main story', 'A2': 'Independent story'}
        anchors = {
            'A1': [{'id': 1, 'bbox': [10, 10, 80, 20]}],
            'A2': [{'id': 2, 'bbox': [600, 10, 700, 20]}],
        }
        roles = {'1': 'headline', '2': 'headline'}
        zones = [
            {'owner': 'A1', 'boxes': [[0, 0, 500, 800]]},
            {'owner': 'A2', 'boxes': [[550, 0, 800, 200]]},
        ]
        self.assertEqual(
            embedded_callout_merges(articles, blocks, anchors, roles, zones),
            {})

    def test_conflicting_overlap_component_is_not_split(self):
        blocks = [{'id': 0, 'bbox': [10, 10, 20, 20]}, {'id': 1, 'bbox': [19, 10, 30, 20]}]
        zones = [{'owner': 'a', 'boxes': [[0, 0, 210, 300]]},
                 {'owner': 'b', 'boxes': [[190, 0, 400, 300]]}]
        owners, missing = assign_components(blocks, [[0, 1]], zones, fitz.Rect(0, 0, 100, 100), ['a', 'b'])
        self.assertEqual(owners, {})
        self.assertEqual(missing, [0])

    def test_invalid_coordinates_rejected(self):
        for box in ([0, 0, float('nan'), 50], [50, 0, 10, 50], [0, 0, 1001, 50]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                assign_components([], [], [{'owner': 'a', 'boxes': [box]}], fitz.Rect(0, 0, 100, 100), ['a'])

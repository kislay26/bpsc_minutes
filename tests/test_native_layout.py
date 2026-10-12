import hashlib
import json
import unittest
from unittest.mock import patch
from pathlib import Path

import fitz
from native_layout import (extract_blocks, parse_ownership, build_regions, ownership_issues,
                           reconcile_continuations, reconcile_headline_column_owners, damaged_text,
                           split_mixed_ad_image_blocks, headline_fragment_matches,
                           reconcile_full_width_headline_owners, reconcile_nearby_lead_images,
                           overlap_components)


class NativeLayoutTests(unittest.TestCase):
    def test_render_preserves_column_positions_and_excludes_neighbor(self):
        from native_layout import render_article
        with fitz.open() as source, fitz.open() as output:
            page = source.new_page(width=300, height=300)
            page.insert_text((20, 30), 'LEFT')
            page.insert_text((170, 160), 'RIGHT')
            page.insert_text((20, 160), 'NEIGHBOR')
            render_article(output, source, 0, [(10, 10, 100, 50), (160, 140, 250, 180)])
            words = {w[4]: w for w in output[0].get_text('words')}
            self.assertEqual(set(words), {'LEFT', 'RIGHT'})
            self.assertAlmostEqual(words['RIGHT'][0]-words['LEFT'][0], 150, places=3)
            self.assertAlmostEqual(words['RIGHT'][1]-words['LEFT'][1], 130, places=3)

    def test_mixed_font_headline_is_not_hidden_by_small_byline(self):
        from native_layout import headline_evidence, inventory_issues
        blocks = [{'id': 0, 'kind': 'text', 'bbox': [0,0,200,50],
                   'text': 'Author NEW DELHI Police step up park audits', 'font_min': 7, 'font_max': 27}]
        self.assertTrue(headline_evidence(blocks)[0]['headline_candidate'])
        self.assertTrue(inventory_issues(blocks, {'A1': blocks[0]['text']}, {'0': 'subheadline'}))

    def test_empty_detector_regions_are_not_headline_evidence(self):
        from native_layout import headline_evidence
        blocks = [{'id': 0, 'kind': 'text', 'text': '', 'layout_label': 'paragraph_title', 'bbox': [0, 0, 100, 20]},
                  {'id': 1, 'kind': 'text', 'text': '---', 'layout_label': 'doc_title', 'bbox': [0, 30, 100, 50]}]
        self.assertEqual(headline_evidence(blocks), [])

    def test_headline_matching_rejects_short_ocr_fragments(self):
        from native_layout import headline_matches
        title = 'Disquiet within all three Election Commissioners meet take first steps'
        for fragment in ('S', 'in', 'ON', 'Election', 'first steps'):
            self.assertFalse(headline_matches(fragment, title), fragment)
        self.assertTrue(headline_matches(title, title))
        self.assertTrue(headline_matches('all three Election Commissioners meet take first steps', title))

    def test_headline_matching_recovers_compacted_ocr_words(self):
        from native_layout import headline_matches
        title = '25 FIRs in 8 Days'
        self.assertTrue(headline_matches('e 25FIRSIN8 DAYS', title))
        self.assertFalse(headline_matches('25 FIRs about 8 Days', title))

    def test_long_contiguous_headline_fragment_matches_inventory_title(self):
        title = ('Hotels asked to turn away guests, CP to shut, schools and courts go online')
        self.assertTrue(headline_fragment_matches(
            'to shut, schools and courts go online', title))
        self.assertFalse(headline_fragment_matches('schools and courts', title))

    def test_ocr_title_bounds_ignore_interleaved_words_and_single_character_errors(self):
        from native_layout import matching_ocr_title_bounds
        words = [
            {'text': text, 'bbox': [x0, 360, x1, 380]}
            for text, x0, x1 in [
                ('Hotels', 270, 320), ('asked', 325, 365), ('to', 370, 385),
                ('turn', 390, 425), ('away', 430, 465), ('guests', 470, 515),
                ('CP', 520, 540), ('45MetroStations', 550, 650), ('_', 655, 660),
                ('to', 665, 680), ('shut', 685, 715), ('schools', 720, 770),
                ('and', 775, 800), ('courts', 805, 850), ('go', 855, 870),
                ('online', 875, 920), ('A5', 1100, 1120), ('Metro', 1125, 1165),
                ('stations', 1170, 1220), ('shut', 1225, 1255), ('until', 1260, 1295),
                ('6', 1300, 1310), ('pm', 1315, 1330), ('traffic', 1335, 1380),
                ('curbs', 1385, 1420), ('in', 1425, 1440), ('30', 1445, 1460),
                ('locations', 1465, 1495),
            ]
        ]
        first = matching_ocr_title_bounds(
            'Hotels asked to turn away guests, CP to shut, schools and courts go online',
            words)
        second = matching_ocr_title_bounds(
            '45 Metro stations shut until 6 pm, traffic curbs in 30 locations', words)
        self.assertEqual(list(first), [270, 360, 920, 380])
        self.assertEqual(list(second), [1100, 360, 1495, 380])

    def test_full_width_merged_headline_assigns_body_until_next_headline(self):
        title_a4 = 'Car checks, eye on bulk food orders & hotels: Noida, Faridabad on alert'
        title_a3 = '45 Metro stations shut until 6 pm, traffic curbs in 30 locations'
        blocks = [
            {'id': 70, 'kind': 'text', 'bbox': [0, 1990, 1466, 2056],
             'text': 'POLICE IN BOTH CITIES HAVE STEPPED UP DEPLOYMENT. ' + title_a4},
            {'id': 16, 'kind': 'text', 'bbox': [100, 2060, 450, 2110], 'text': 'A4 body'},
            {'id': 32, 'kind': 'text', 'bbox': [700, 2070, 1050, 2120], 'text': 'A4 second column'},
            {'id': 86, 'kind': 'text', 'bbox': [1100, 2140, 1498, 2180], 'text': title_a3},
            {'id': 90, 'kind': 'text', 'bbox': [1100, 2200, 1498, 2240], 'text': 'A3 body'},
        ]
        owners, changes = reconcile_full_width_headline_owners(
            blocks, {'70': 'A4', '16': 'A3', '32': 'A1', '86': 'A3', '90': 'A3'},
            {'A1': 'Fortress Delhi', 'A3': title_a3, 'A4': title_a4}, 1498)
        self.assertEqual(owners, {'70': 'A4', '16': 'A4', '32': 'A4', '86': 'A3', '90': 'A3'})
        self.assertEqual([change['block'] for change in changes], [16, 32])

    def test_nearby_lead_photo_and_caption_follow_matching_headline(self):
        blocks = [
            {'id': 91, 'kind': 'text', 'bbox': [382, 821, 1109, 935],
             'text': 'to shut, schools and courts go online'},
            {'id': 0, 'kind': 'image', 'bbox': [379, 941, 1117, 1254], 'text': ''},
            {'id': 72, 'kind': 'text', 'bbox': [377, 1265, 1110, 1280],
             'text': 'Security personnel deploy a drone (top); commuters stopped at barricades.'},
            {'id': 1, 'kind': 'image', 'bbox': [379, 335, 1496, 807], 'text': ''},
        ]
        owners, changes = reconcile_nearby_lead_images(
            blocks, {'91': 'A2', '0': 'A1', '72': 'A1', '1': 'A1'},
            {'A2': [{'id': 91, 'bbox': [382, 821, 1109, 935], 'fragment': True}]}, 1500)
        self.assertEqual(owners, {'91': 'A2', '0': 'A2', '72': 'A2', '1': 'A1'})
        self.assertEqual([change['block'] for change in changes], [0, 72])

    def test_text_after_lead_image_follows_matching_fragment_headline(self):
        blocks = [
            {'id': 91, 'kind': 'text', 'bbox': [382, 821, 1109, 935],
             'text': 'to shut, schools and courts go online'},
            {'id': 0, 'kind': 'image', 'bbox': [379, 941, 1117, 1254]},
            {'id': 72, 'kind': 'text', 'bbox': [377, 1265, 1110, 1280],
             'text': 'Security personnel deploy a drone.'},
            {'id': 87, 'kind': 'text', 'bbox': [378, 1293, 505, 1355],
             'text': 'Reporter Name New Delhi, October 9'},
            {'id': 4, 'kind': 'text', 'bbox': [377, 1369, 552, 1553],
             'text': 'Hotels have been asked to turn away students.'},
            {'id': 17, 'kind': 'text', 'bbox': [1132, 1350, 1308, 1627],
             'text': 'Metro story in the neighboring column.'},
        ]
        owners, changes = reconcile_nearby_lead_images(
            blocks, {'91': 'A2', '0': 'A1', '72': 'A1', '87': 'A1', '4': 'A1', '17': 'A3'},
            {'A2': [{'id': 91, 'bbox': blocks[0]['bbox'], 'fragment': True}]}, 1500)
        self.assertEqual(owners, {'91': 'A2', '0': 'A2', '72': 'A2',
                                  '87': 'A2', '4': 'A2', '17': 'A3'})
        self.assertEqual([change['block'] for change in changes], [0, 72, 87, 4])

    def test_inventory_accepts_kicker_and_known_headline_merged_in_one_ocr_block(self):
        from native_layout import inventory_issues
        title = 'Car checks, eye on bulk food orders & hotels: Noida, Faridabad on alert'
        block = {'id': 70, 'kind': 'text', 'bbox': [0, 1990, 1466, 2056],
                 'text': 'POLICE IN BOTH CITIES HAVE STEPPED UP DEPLOYMENT AND SET UP CHECKPOSTS '
                         'ALONG THE BORDER TO DELHI ' + title,
                 'layout_label': 'doc_title'}
        self.assertEqual(inventory_issues([block], {'A1': title}), [])
        self.assertTrue(inventory_issues([block], {'A1': 'A different article headline'}))

    def test_ownership_accepts_known_headline_merged_with_kicker(self):
        from native_layout import ownership_issues
        title = 'Car checks, eye on bulk food orders & hotels: Noida, Faridabad on alert'
        block = {'id': 70, 'kind': 'text', 'bbox': [0, 1990, 1466, 2056],
                 'text': 'POLICE IN BOTH CITIES HAVE STEPPED UP DEPLOYMENT AND SET UP CHECKPOSTS '
                         'ALONG THE BORDER TO DELHI ' + title,
                 'layout_label': 'doc_title'}
        self.assertEqual(ownership_issues([block], {'70': 'A4'}, {'A4': title}), [])
        self.assertTrue(ownership_issues([block], {'70': 'A1'},
                                         {'A1': 'A different article headline', 'A4': title}))

    def test_explicit_page_link_teaser_excludes_only_marker_and_headline(self):
        from native_layout import (explicit_page_teaser_ids, headline_evidence, inventory_issues,
                                   remove_explicit_page_teaser_headlines)
        blocks = [
            {'id': 0, 'kind': 'text', 'bbox': [1325, 1800, 1376, 1813], 'text': 'INSIDE'},
            {'id': 1, 'kind': 'text', 'bbox': [1446, 1803, 1482, 1813], 'text': 'PAGE'},
            {'id': 2, 'kind': 'text', 'bbox': [1322, 1814, 1490, 1848],
             'text': 'BLOW TO PARTY CHIEF, BJP WINS NAGAON SEAT'},
            {'id': 3, 'kind': 'text', 'bbox': [1322, 1850, 1498, 1901],
             'text': 'The party won the seat by a record margin.'},
        ]

        self.assertEqual(explicit_page_teaser_ids(blocks), {0, 1, 2})
        hint = next(item for item in headline_evidence(blocks) if item['block_id'] == 2)
        self.assertTrue(hint['teaser_hint'])
        self.assertEqual(inventory_issues(blocks, {'A1': 'A different article headline'}), [])
        retained, removed = remove_explicit_page_teaser_headlines(
            ['BLOW TO PARTY CHIEF, BJP WINS NAGAON SEAT', 'The real article headline'], blocks)
        self.assertEqual(retained, ['The real article headline'])
        self.assertEqual(removed, ['BLOW TO PARTY CHIEF, BJP WINS NAGAON SEAT'])

    def test_mixed_story_and_ad_image_is_split_at_framed_panel_border(self):
        with fitz.open() as doc:
            page = doc.new_page(width=100, height=200)
            page.draw_rect(fitz.Rect(10, 10, 90, 80), color=(0, 0, 0), width=1)
            page.draw_line(fitz.Point(10, 80), fitz.Point(90, 80), color=(0, 0, 0), width=1)
            page.draw_line(fitz.Point(10, 100), fitz.Point(90, 100), color=(0, 0, 0), width=1)
            blocks = [
                {'id': 0, 'kind': 'image', 'bbox': [10, 10, 90, 190],
                 'layout_label': 'image',
                 'text': 'CRPF pays tribute. Contact for Advt, Booking. UPSC course.'},
                {'id': 1, 'kind': 'text', 'bbox': [15, 15, 85, 25],
                 'text': 'Salute the Soldier'},
                {'id': 2, 'kind': 'image', 'bbox': [20, 30, 80, 55],
                 'text': 'soldier portrait'},
            ]
            revised, excluded = split_mixed_ad_image_blocks(
                page, blocks, {'A1': 'Salute the Soldier'})

        self.assertEqual(len(revised), 4)
        self.assertEqual(excluded, {3})
        story, ad = revised[0], revised[-1]
        self.assertEqual(story['bbox'][:3], [10, 10, 90])
        self.assertGreaterEqual(story['bbox'][3], 80)
        self.assertLess(story['bbox'][3], 100)
        self.assertTrue(story['text'].endswith('tribute.'))
        self.assertEqual(ad['bbox'][:3], [10, story['bbox'][3], 90])
        self.assertEqual(ad['text'], 'Contact for Advt, Booking. UPSC course.')

    def test_misassigned_text_follows_nearest_headline_in_same_column(self):
        blocks = [
            {'id': 1, 'kind': 'text', 'bbox': [100, 10, 180, 30], 'text': 'Article A'},
            {'id': 2, 'kind': 'text', 'bbox': [100, 40, 200, 80], 'text': 'First article body'},
            {'id': 3, 'kind': 'text', 'bbox': [210, 10, 280, 30], 'text': 'Article B'},
            {'id': 4, 'kind': 'text', 'bbox': [210, 100, 300, 140],
             'text': 'Misassigned body ' + ' '.join(['story'] * 55)},
            {'id': 5, 'kind': 'text', 'bbox': [210, 200, 300, 240], 'text': 'Unrelated text'},
        ]
        owners, changes = reconcile_headline_column_owners(
            blocks, {'1': 'A1', '2': 'A1', '3': 'A2', '4': 'A1', '5': 'A1'},
            ['A1', 'A2'],
            {'A1': [{'id': 1, 'bbox': blocks[0]['bbox']}],
             'A2': [{'id': 3, 'bbox': blocks[2]['bbox']}]})
        self.assertEqual(owners['4'], 'A2')
        self.assertEqual(owners['5'], 'A1')
        self.assertEqual(changes, [{
            'block': 4, 'previous_owner': 'A1', 'owner': 'A2', 'headline': 3,
            'basis': 'long text block in the same headline column'}])

    def test_long_text_keeps_owner_when_overlapping_its_ad_title(self):
        headline = {'id': 84, 'kind': 'text', 'bbox': [565, 217, 908, 394],
                    'text': 'HC refuses urgent hearings for Jantar Mantar protest'}
        body = {'id': 64, 'kind': 'text', 'bbox': [509, 1493, 985, 1629],
                'text': 'I.T.S Dental College celebrated an event. ' + ' '.join(['details'] * 60)}
        ad_title = {'id': 96, 'kind': 'text', 'bbox': [516, 1481, 542, 1494],
                    'text': '1.1.S', 'geometry_source': 'unmatched_ocr_word'}
        owners, changes = reconcile_headline_column_owners(
            [headline, body, ad_title], {'84': 'A4', '64': 'A7', '96': 'A7'},
            ['A4', 'A7'], {'A4': [{'id': 84, 'bbox': headline['bbox']}]})
        self.assertEqual(owners['64'], 'A7')
        self.assertEqual(changes, [])

    def test_long_text_does_not_reassign_to_distant_headline(self):
        headline = {'id': 1, 'kind': 'text', 'bbox': [210, 10, 300, 30],
                    'text': 'Nearby-column headline'}
        body = {'id': 2, 'kind': 'text', 'bbox': [210, 400, 300, 500],
                'text': 'Long unrelated body ' + ' '.join(['details'] * 60)}
        owners, changes = reconcile_headline_column_owners(
            [headline, body], {'1': 'A2', '2': 'A1'}, ['A1', 'A2'],
            {'A2': [{'id': 1, 'bbox': headline['bbox']}]})
        self.assertEqual(owners['2'], 'A1')
        self.assertEqual(changes, [])

    def test_misassigned_headline_follows_source_title_match(self):
        block = {'id': 86, 'kind': 'text', 'bbox': [1131, 833, 1498, 958],
                 'text': '45 Metro stations shut until 6 pm, traffic curbs in 30 locations'}
        owners, changes = reconcile_headline_column_owners(
            [block], {'86': 'A1'}, ['A1', 'A3'],
            {'A3': [{'id': 86, 'bbox': block['bbox']}]})
        self.assertEqual(owners['86'], 'A3')
        self.assertEqual(changes, [{
            'block': 86, 'previous_owner': 'A1', 'owner': 'A3', 'headline': 86,
            'basis': 'source headline match'}])

    def test_overlapping_raster_headlines_use_their_ocr_word_bounds(self):
        from raster_layout import refine_overlapping_headline_bounds
        first = {'id': 91, 'kind': 'text', 'layout_label': 'doc_title',
                 'bbox': [378, 830, 1498, 954],
                 'text': 'to shut, schools and courts go online'}
        second = {'id': 86, 'kind': 'text', 'layout_label': 'doc_title',
                  'bbox': [1131, 833, 1498, 958],
                  'text': '45 Metro stations shut until 6 pm, traffic curbs in 30 locations'}
        blocks = [first, second]
        first_words = [
            {'text': text, 'bbox': [x, 840, x+width, 875]}
            for text, x, width in [('to', 400, 24), ('shut,', 430, 45), ('schools', 480, 70),
                                   ('and', 555, 35), ('courts', 595, 60), ('go', 660, 25),
                                   ('online', 690, 65), ('45', 1137, 39)]]
        second_words = [
            {'text': text, 'bbox': [x, 840, x+width, 875]}
            for text, x, width in [('45', 1137, 39), ('Metro', 1183, 99), ('stations', 1290, 128),
                                   ('shut', 1138, 72), ('until', 1215, 78), ('6', 1300, 19),
                                   ('pm', 1326, 63), ('traffic', 1395, 99), ('curbs', 1137, 89),
                                   ('in', 1234, 32), ('30', 1272, 41), ('locations', 1320, 148)]]
        with patch('native_layout.ocr_region_words', side_effect=[first_words, second_words]):
            refine_overlapping_headline_bounds(None, blocks)
        self.assertFalse((fitz.Rect(first['bbox']) & fitz.Rect(second['bbox'])).get_area())
        self.assertEqual(
            build_regions(blocks, {'91': 'A1', '86': 'A3'}, ['A1', 'A3'])['A1'],
            [first['bbox']])

    def test_overlapping_source_headlines_are_refined_to_their_own_ocr_words(self):
        from raster_layout import refine_overlapping_source_headline_anchors
        first_block = {'id': 91, 'bbox': [250, 350, 1000, 400]}
        second_block = {'id': 86, 'bbox': [750, 350, 995, 400]}
        first = {'id': 91, 'bbox': list(first_block['bbox'])}
        second = {'id': 86, 'bbox': list(second_block['bbox'])}
        anchors = {'A2': [first], 'A3': [second]}
        crop_anchors = {'A2': [dict(first)], 'A3': [dict(second)]}
        blocks = [first_block, second_block]
        words = [
            {'text': text, 'bbox': [x0, 360, x1, 380]}
            for text, x0, x1 in [
                ('Hotels', 270, 320), ('asked', 325, 365), ('to', 370, 385),
                ('turn', 390, 425), ('away', 430, 465), ('guests', 470, 515),
                ('45', 770, 790), ('Metro', 795, 830), ('stations', 835, 885),
            ]
        ]
        with patch('native_layout.ocr_region_words', return_value=words):
            refine_overlapping_source_headline_anchors(
                None, anchors, crop_anchors,
                {'A2': 'Hotels asked to turn away guests', 'A3': '45 Metro stations'},
                blocks)
        self.assertEqual(first['bbox'], [270, 360, 515, 380])
        self.assertEqual(second['bbox'], [770, 360, 885, 380])
        self.assertEqual(first_block['bbox'], first['bbox'])
        self.assertEqual(second_block['bbox'], second['bbox'])
        self.assertEqual(crop_anchors['A2'][0]['bbox'], first['bbox'])
        self.assertEqual(overlap_components(blocks), [[91], [86]])
        self.assertFalse((fitz.Rect(first['bbox']) & fitz.Rect(second['bbox'])).get_area())

    def test_empty_block_above_headline_stays_with_that_article(self):
        blocks = [
            {'id': 1, 'kind': 'text', 'bbox': [100, 10, 180, 30], 'text': 'Article A'},
            {'id': 2, 'kind': 'text', 'bbox': [210, 10, 280, 30], 'text': 'Article B'},
            {'id': 3, 'kind': 'text', 'bbox': [212, 0, 278, 8], 'text': ''},
        ]
        owners, changes = reconcile_headline_column_owners(
            blocks, {'1': 'A1', '2': 'A2', '3': 'exclude:teaser'}, ['A1', 'A2'],
            {'A1': [{'id': 1, 'bbox': blocks[0]['bbox']}],
             'A2': [{'id': 2, 'bbox': blocks[1]['bbox']}]})
        self.assertEqual(owners['3'], 'A2')
        self.assertEqual(changes[0]['basis'], 'adjacent headline in the same text column')
        self.assertEqual(changes[0]['previous_owner'], 'exclude:teaser')

    def test_irregular_overlap_partition_preserves_area_without_enlargement(self):
        from native_layout import disjoint_rectangles
        rects = disjoint_rectangles([fitz.Rect(0, 0, 10, 10), fitz.Rect(5, 5, 15, 15)])
        self.assertEqual(sum(r.get_area() for r in rects), 175)
        for i, a in enumerate(rects):
            for b in rects[i+1:]:
                self.assertEqual((a & b).get_area(), 0)

    def test_overlapping_components_preserve_transitive_membership(self):
        from native_layout import overlap_components
        blocks = [{'id': 10, 'bbox': [0, 0, 10, 10]},
                  {'id': 20, 'bbox': [9, 0, 20, 10]},
                  {'id': 30, 'bbox': [19, 0, 30, 10]},
                  {'id': 40, 'bbox': [40, 0, 50, 10]}]
        self.assertEqual(overlap_components(blocks), [[10, 20, 30], [40]])

    def test_conflict_audit_ignores_excluded_pairs_but_not_article_overlap(self):
        from native_layout import conflicting_pairs
        blocks = [{'id': 0, 'bbox': [0, 0, 10, 10]},
                  {'id': 1, 'bbox': [5, 5, 15, 15]}]
        self.assertEqual(conflicting_pairs(blocks, {'0': 'exclude:teaser',
                         '1': 'exclude:masthead'}, ['A1']), [])
        self.assertEqual(conflicting_pairs(blocks, {'0': 'A1',
                         '1': 'exclude:masthead'}, ['A1']), [[0, 1]])

    def test_ocr_body_without_font_metrics_is_not_a_headline(self):
        from native_layout import headline_evidence
        blocks = [{'id': 0, 'kind': 'text', 'bbox': [0, 0, 100, 20],
                   'font_min': 0, 'text': 'ordinary paragraph with several words',
                   'layout_label': 'text'},
                  {'id': 1, 'kind': 'text', 'bbox': [0, 30, 100, 50],
                   'font_min': 0, 'text': 'Actual headline', 'layout_label': 'doc_title'}]
        self.assertEqual([h['block_id'] for h in headline_evidence(blocks)], [1])

    def test_full_page_raster_is_not_treated_as_an_article_photo(self):
        with fitz.open() as doc:
            page = doc.new_page(width=100, height=100)
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
            pix.clear_with(255)
            page.insert_image(page.rect, pixmap=pix)
            page.insert_text((10, 30), 'Text overlay')
            with patch('raster_layout.extract_raster_blocks', return_value=[{'id': 0}]) as detector:
                self.assertEqual(extract_blocks(page), [{'id': 0}])
                detector.assert_called_once_with(page)

    def test_broken_font_mapping_requires_ocr(self):
        self.assertTrue(damaged_text('\x01\x02\x03a\x04'))
        self.assertFalse(damaged_text('Election ﬂak — report\ncontinued'))
        self.assertFalse(damaged_text(''))

    def test_full_page_ocr_uses_150_dpi_and_maps_word_bounds_to_pdf_points(self):
        from native_layout import ocr_words
        header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        row = '5\t1\t1\t1\t1\t1\t150\t75\t30\t15\t90\tHeadline\n'
        pixmap = type('Pixmap', (), {'tobytes': lambda self, kind: b'png'})()
        result = type('Result', (), {'returncode': 0, 'stdout': (header + row).encode()})()
        with fitz.open() as doc:
            page = doc.new_page(width=100, height=100)
            with patch('fitz.Page.get_pixmap', return_value=pixmap) as render, \
                    patch('native_layout.subprocess.run', return_value=result):
                words = ocr_words(page)
        matrix = render.call_args.kwargs['matrix']
        self.assertAlmostEqual(matrix.a, 150/72)
        self.assertAlmostEqual(words[0]['bbox'][0], 72)
        self.assertAlmostEqual(words[0]['bbox'][1], 36)
        self.assertEqual(words[0]['text'], 'Headline')

    def test_continuation_constraints_do_not_guess_ambiguous_columns(self):
        body = {'id': 0, 'kind': 'text', 'bbox': [0, 0, 100, 100],
                'text': 'one two three four five six seven eight nine'}
        label = {'id': 1, 'kind': 'text', 'bbox': [0, 110, 50, 120],
                 'text': 'CONTINUED ON PAGE 7'}
        owners = {'0': 'A1', '1': 'A2'}
        fixed, changes = reconcile_continuations([body, label], owners, ['A1', 'A2'])
        self.assertEqual(fixed['1'], 'A1')
        self.assertEqual(owners['1'], 'A2')
        self.assertEqual(len(changes), 1)
        rival = {**body, 'id': 2}
        fixed, changes = reconcile_continuations([body, label, rival],
                                                {**owners, '2': 'A2'}, ['A1', 'A2'])
        self.assertEqual(fixed['1'], 'A2')
        self.assertEqual(changes, [])

    def test_ownership_rejects_duplicate_missing_unknown_keys(self):
        blocks = [{'id': 0, 'kind': 'text'}, {'id': 1, 'kind': 'text'}]
        for content in ['{"0":"A1","0":"A1","1":"A1"}',
                        '{"0":"A1"}', '{"0":"A1","1":"A1","2":"A1"}']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_ownership(content, blocks, ['A1'])

    def test_sidebar_prevents_rectangle_merge(self):
        blocks = [{'id': 0, 'kind': 'text', 'bbox': [0, 0, 100, 20]},
                  {'id': 1, 'kind': 'text', 'bbox': [0, 30, 40, 100]},
                  {'id': 2, 'kind': 'text', 'bbox': [60, 30, 100, 100]}]
        regions = build_regions(blocks, {'0': 'A1', '1': 'A1', '2': 'A2'}, ['A1', 'A2'])
        self.assertEqual(len(regions['A1']), 2)

    def test_conflicting_overlapping_panel_fails(self):
        blocks = [{'id': 0, 'kind': 'vector_artwork', 'bbox': [0, 0, 100, 100]},
                  {'id': 1, 'kind': 'image', 'bbox': [20, 20, 40, 40]}]
        with self.assertRaisesRegex(ValueError, 'different owners'):
            build_regions(blocks, {'0': 'A1', '1': 'A2'}, ['A1', 'A2'])

    def test_merges_do_not_create_overlapping_output_regions(self):
        blocks = [{'id': 0, 'kind': 'text', 'bbox': [0, 0, 100, 20]},
                  {'id': 1, 'kind': 'text', 'bbox': [0, 20, 40, 100]},
                  {'id': 2, 'kind': 'text', 'bbox': [60, 20, 100, 80]},
                  {'id': 3, 'kind': 'text', 'bbox': [60, 90, 100, 100]}]
        regions = build_regions(blocks, {'0': 'A1', '1': 'A1', '2': 'A1', '3': 'A2'}, ['A1', 'A2'])
        for rs in regions.values():
            for i, a in enumerate(rs):
                for b in rs[i+1:]:
                    self.assertLessEqual((a & b).get_area(), .01)

    def test_saved_bad_ownership_is_rejected_semantically(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / 'review/failed_gemini_ownership.json'
        source = root / 'Newspaper/THE HINDU HD Delhi Editable Full Edition 27~09~2026.pdf'
        if not fixture.exists() or not source.exists():
            self.skipTest('Private local regression fixture not available.')
        report = json.loads(fixture.read_text(encoding='utf-8'))
        with fitz.open(source) as doc:
            blocks = extract_blocks(doc[0])
        issues = ownership_issues(blocks, report['owners'], report['articles'])
        for expected in ['teaser block 27', 'teaser block 31', 'teaser block 34', 'teaser block 37',
                         'block 76', 'Continuation block 83', 'Continuation block 84']:
            self.assertTrue(any(expected in issue for issue in issues), expected)

    def test_reviewed_newspaper_geometry(self):
        root = Path(__file__).resolve().parents[1]
        reference = root / 'review/TH_page1_reference_audit.json'
        source = root / 'Newspaper/THE HINDU HD Delhi Editable Full Edition 27~09~2026.pdf'
        if not reference.exists() or not source.exists():
            self.skipTest('Local newspaper reference not bundled.')
        audit = json.loads(reference.read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), audit['source_sha256'])
        with fitz.open(source) as doc:
            blocks = extract_blocks(doc[0])
        owners = {str(i): 'exclude:print_mark' for i in audit['excluded_block_ids']}
        article_ids = []
        for i, article in enumerate(audit['articles'], 1):
            ident = f'A{i}'
            article_ids.append(ident)
            for group in article['groups']:
                for b in group:
                    owners[str(b)] = ident
        # Test-only reference labels for newly discovered vector artwork.
        # Production never reads this audit or any per-page manual assignment.
        for block in blocks:
            if str(block['id']) in owners:
                continue
            rect = fitz.Rect(block['bbox'])
            matches = [f'A{i}' for i, a in enumerate(audit['articles'], 1)
                       if any((rect & fitz.Rect(r)).get_area() >= rect.get_area()*.999
                              for r in a['rectangles_pdf_points'])]
            owners[str(block['id'])] = matches[0] if matches else 'exclude:print_mark'
        owners = parse_ownership(json.dumps(owners), blocks, article_ids)
        titles = {f'A{i}': article['title'] for i, article in enumerate(audit['articles'], 1)}
        self.assertEqual(ownership_issues(blocks, owners, titles), [])
        result = build_regions(blocks, owners, article_ids)
        panel = [b for b in blocks if b['kind'] == 'vector_artwork' and owners[str(b['id'])] == 'A3']
        self.assertTrue(panel, 'The EC infographic must be discovered without manual coordinates.')
        for block in blocks:
            ident = owners[str(block['id'])]
            if ident.startswith('exclude:'):
                continue
            rect = fitz.Rect(block['bbox'])
            self.assertTrue(any((r & rect).get_area() >= rect.get_area()*.999 for r in result[ident]))
        self.assertGreater(len(result['A3']), 1, 'EC sidebar must prevent a single giant crop.')

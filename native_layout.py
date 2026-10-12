"""Native geometry for trial crops; AI assigns ownership, never coordinates."""
import fitz
import re
import unicodedata
import csv
import io
import os
import shutil
import subprocess
from statistics import median
from difflib import SequenceMatcher


def extract_blocks(page):
    blocks = []
    for block in page.get_text('dict')['blocks']:
        spans = [s for line in block.get('lines', []) for s in line['spans'] if s['text'].strip()]
        blocks.append({'id': len(blocks), 'kind': 'text' if block['type'] == 0 else 'image',
                       'bbox': list(block['bbox']),
                       'font_min': min((s['size'] for s in spans), default=0),
                       'font_max': max((s['size'] for s in spans), default=0),
                       'text': ' '.join(s['text'] for line in block.get('lines', []) for s in line['spans'])})
    if any(b['kind'] == 'image' and
           (fitz.Rect(b['bbox']) & page.rect).get_area() >= page.rect.get_area() * .9
           for b in blocks):
        from raster_layout import extract_raster_blocks
        return extract_raster_blocks(page)
    # Long page rules connect otherwise separate drawing clusters. Ignore those
    # spanning shapes when discovering local vector artwork, not when rendering.
    drawings = [d for d in page.get_drawings()
                if d['rect'].width < page.rect.width * .65
                and d['rect'].height < page.rect.height * .65]
    for rect in page.cluster_drawings(drawings=drawings):
        if rect.width <= 30 or rect.height <= 12:
            continue
        if any(b['kind'] == 'image' and (rect & fitz.Rect(b['bbox'])).get_area() >= rect.get_area() * .99
               for b in blocks):
            continue
        blocks.append({'id': len(blocks), 'kind': 'vector_artwork', 'bbox': list(rect), 'text': ''})
    damaged = [b for b in blocks if b['kind'] == 'text' and damaged_text(b['text'])]
    if damaged or not any(b['kind'] == 'text' for b in blocks):
        words = ocr_words(page)
        if not words:
            raise ValueError('OCR returned no words for a page requiring text recovery.')
        if damaged:
            for block in damaged:
                rect = fitz.Rect(block['bbox'])
                recovered = [w['text'] for w in words
                             if rect.contains(fitz.Point(w['cx'], w['cy']))]
                if not recovered:
                    recovered = [ocr_region(page, rect)]
                if not recovered[0].strip():
                    raise ValueError(f"OCR could not recover native block {block['id']}.")
                block['text'] = ' '.join(recovered)
                block['text_source'] = 'tesseract_ocr'
        else:
            # A full-page scan image is a rendering surface, not an article region.
            blocks = []
            groups = {}
            for word in words:
                groups.setdefault(word['group'], []).append(word)
            for group in groups.values():
                rect = fitz.Rect(group[0]['bbox'])
                for word in group[1:]:
                    rect |= fitz.Rect(word['bbox'])
                blocks.append({'id': len(blocks), 'kind': 'text', 'bbox': list(rect),
                               'font_min': 0, 'font_max': 0, 'text_source': 'tesseract_ocr',
                               'text': ' '.join(w['text'] for w in group)})
            # Image-only regions require a layout detector; do not silently omit them.
            raise ValueError('Scanned page requires image-region layout detection; OCR text recovered but crops withheld.')
    return blocks


def damaged_text(text):
    compact = ''.join(c for c in text if not c.isspace())
    bad = sum(unicodedata.category(c) == 'Cc' or c == '\ufffd' for c in compact)
    # Isolated dingbats are common in otherwise usable newspaper text.
    return bool(compact) and bad >= 3 and bad / len(compact) > .05


def ocr_words(page):
    executable = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    if not executable and os.path.isfile(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
        executable = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if not executable:
        raise ValueError('Text recovery requires Tesseract OCR; set TESSERACT_CMD.')
    scale = 150 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    env = {**os.environ, 'OMP_THREAD_LIMIT': '2'}
    timeout = int(os.environ.get('TESSERACT_TIMEOUT_SECONDS', '1200'))
    result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '3', 'tsv'],
                            input=pix.tobytes('png'), capture_output=True, env=env, timeout=timeout)
    if result.returncode:
        raise ValueError('Tesseract OCR failed during text recovery.')
    words = []
    for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8')), delimiter='\t'):
        if row['level'] != '5' or not row.get('text', '').strip():
            continue
        x, y, w, h = [float(row[k]) / scale for k in ('left', 'top', 'width', 'height')]
        words.append({'text': row['text'], 'bbox': [x, y, x+w, y+h],
                      'cx': x+w/2, 'cy': y+h/2,
                      'group': (row['block_num'], row['par_num'])})
    return words


def ocr_region(page, rect):
    executable = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    if not executable:
        executable = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect, alpha=False)
    result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '6'],
                            input=pix.tobytes('png'), capture_output=True, timeout=30)
    return result.stdout.decode('utf-8').strip() if result.returncode == 0 else ''


def ocr_region_words(page, rect):
    executable = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    if not executable and os.path.isfile(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
        executable = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if not executable:
        raise ValueError('Text geometry recovery requires Tesseract OCR; set TESSERACT_CMD.')
    scale = 3
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '6', 'tsv'],
                            input=pix.tobytes('png'), capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Tesseract OCR failed during text geometry recovery.')
    words = []
    for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8')), delimiter='\t'):
        if row['level'] != '5' or not row.get('text', '').strip():
            continue
        x, y, w, h = [float(row[k]) / scale for k in ('left', 'top', 'width', 'height')]
        words.append({'text': row['text'],
                      'bbox': [rect.x0+x, rect.y0+y, rect.x0+x+w, rect.y0+y+h]})
    return words


EXCLUSIONS = ['exclude:masthead', 'exclude:teaser', 'exclude:advertisement', 'exclude:print_mark']


def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def matching_ocr_text_bounds(text, words):
    target = normalized(text).replace(' ', '')
    if not target:
        return None
    stream = ''
    spans = []
    for word in words:
        token = normalized(word['text']).replace(' ', '')
        if token:
            spans.append((len(stream), len(stream)+len(token), fitz.Rect(word['bbox'])))
            stream += token
    start = stream.find(target)
    if start < 0:
        return None
    end = start + len(target)
    matched = [rect for first, last, rect in spans if first < end and last > start]
    if not matched:
        return None
    bounds = matched[0]
    for rect in matched[1:]:
        bounds |= rect
    return bounds


def matching_ocr_title_bounds(text, words):
    target = normalized(text).split()
    if not target:
        return None
    observed = [(token, fitz.Rect(word['bbox']))
                for word in words for token in normalized(word['text']).split()]
    matched = []
    cursor = 0
    for token in target:
        best = None
        for index in range(cursor, len(observed)):
            candidate = observed[index][0]
            if candidate == token:
                best = index
                break
            if len(token) >= 2 and len(candidate) == len(token):
                differences = sum(a != b for a, b in zip(token, candidate))
                if differences <= 1:
                    best = index
                    break
        if best is not None:
            matched.append(observed[best][1])
            cursor = best + 1
    if len(matched) < max(4, len(target) * .85):
        return None
    bounds = matched[0]
    for rect in matched[1:]:
        bounds |= rect
    return bounds


def headline_matches(headline, title):
    a, b = normalized(headline), normalized(title)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    substantial = len(short.split()) >= 2 and len(short) >= 8 and len(short) >= len(long)*.55
    compact_match = (min(len(a), len(b)) >= 8
                     and SequenceMatcher(None, a.replace(' ', ''),
                                         b.replace(' ', '')).ratio() >= .92)
    return ((substantial and short in long)
            or SequenceMatcher(None, a, b).ratio() >= .92
            or compact_match)


def headline_fragment_matches(fragment, title):
    short, long = normalized(fragment), normalized(title)
    return (len(short.split()) >= 4 and len(short) >= 24
            and len(short) >= len(long)*.35
            and f' {short} ' in f' {long} ')


def headline_embedded(text, title):
    block, headline = normalized(text), normalized(title)
    if len(headline.split()) < 4 or len(headline) < 24:
        return False
    return f' {headline} ' in f' {block} '


def reconcile_full_width_headline_owners(blocks, owners, articles, page_width):
    """Attach following body columns to a known headline spanning the page."""
    resolved = dict(owners)
    changes = []
    headings = []
    for block in blocks:
        if block.get('kind') != 'text' or not block.get('text', '').strip():
            continue
        rect = fitz.Rect(block['bbox'])
        if rect.width < page_width * .65:
            continue
        matches = [owner for owner, title in articles.items()
                   if headline_embedded(block['text'], title)]
        if len(matches) == 1:
            headings.append((block, matches[0]))
    heading_bounds = [(fitz.Rect(block['bbox']), owner) for block in blocks
                      if block.get('kind') == 'text' and block.get('text', '').strip()
                      for owner, title in articles.items()
                      if (headline_matches(block['text'], title)
                          or headline_fragment_matches(block['text'], title)
                          or headline_embedded(block['text'], title))]
    for heading, owner in headings:
        title_rect = fitz.Rect(heading['bbox'])
        following_headlines = [rect.y0 for rect, other in heading_bounds
                               if other != owner and rect.y0 >= title_rect.y1 - 8]
        stop_y = min(following_headlines, default=float('inf'))
        for block in blocks:
            if block['id'] == heading['id'] or block.get('kind') not in ('text', 'image', 'vector_artwork'):
                continue
            rect = fitz.Rect(block['bbox'])
            if rect.y0 < title_rect.y1 - 8 or rect.y0 >= stop_y:
                continue
            if rect.width and (rect & title_rect).width < min(rect.width, title_rect.width) * .2:
                continue
            key = str(block['id'])
            current = resolved[key]
            if current == owner or current in ('exclude:masthead', 'exclude:print_mark'):
                continue
            changes.append({'block': block['id'], 'previous_owner': current,
                            'owner': owner, 'headline': heading['id'],
                            'basis': 'body below full-width embedded headline'})
            resolved[key] = owner
    return resolved, changes


def reconcile_nearby_lead_images(blocks, owners, anchors, page_width):
    resolved = dict(owners)
    changes = []
    assigned_images = []
    for block in blocks:
        if block.get('kind') != 'image':
            continue
        rect = fitz.Rect(block['bbox'])
        if rect.width > page_width * .6:
            continue
        matches = []
        for owner, owner_anchors in anchors.items():
            for anchor in owner_anchors:
                if not anchor.get('fragment'):
                    continue
                anchor_rect = fitz.Rect(anchor['bbox'])
                horizontal_overlap = (rect & anchor_rect).width / min(rect.width, anchor_rect.width)
                gap = max(anchor_rect.y0 - rect.y1, rect.y0 - anchor_rect.y1, 0)
                if horizontal_overlap >= .8 and gap <= 24:
                    matches.append((gap, owner, anchor['id']))
        if not matches:
            continue
        matches.sort()
        if len(matches) > 1 and matches[0][0] == matches[1][0] and matches[0][1] != matches[1][1]:
            continue
        _, owner, headline_id = matches[0]
        previous = resolved[str(block['id'])]
        assigned_images.append((rect, owner, block['id']))
        if previous != owner:
            changes.append({'block': block['id'], 'previous_owner': previous,
                            'owner': owner, 'headline': headline_id,
                            'basis': 'nearby article headline and matching photo width'})
            resolved[str(block['id'])] = owner
    for block in blocks:
        if block.get('kind') != 'text' or not block.get('text', '').strip():
            continue
        rect = fitz.Rect(block['bbox'])
        if rect.height > 36:
            continue
        matches = []
        for image_rect, owner, image_id in assigned_images:
            horizontal_overlap = (rect & image_rect).width / min(rect.width, image_rect.width)
            gap = max(image_rect.y0 - rect.y1, rect.y0 - image_rect.y1, 0)
            if horizontal_overlap >= .8 and gap <= 24:
                matches.append((gap, owner, image_id))
        if not matches:
            continue
        matches.sort()
        if len(matches) > 1 and matches[0][0] == matches[1][0] and matches[0][1] != matches[1][1]:
            continue
        _, owner, image_id = matches[0]
        previous = resolved[str(block['id'])]
        if previous != owner:
            changes.append({'block': block['id'], 'previous_owner': previous,
                            'owner': owner, 'image': image_id,
                            'basis': 'caption directly adjoining lead image'})
            resolved[str(block['id'])] = owner
    fragment_ids = {str(anchor['id']) for owner_anchors in anchors.values()
                    for anchor in owner_anchors if anchor.get('fragment')}
    for block in blocks:
        if (block.get('kind') != 'text' or not block.get('text', '').strip()
                or str(block['id']) in fragment_ids):
            continue
        rect = fitz.Rect(block['bbox'])
        matches = []
        for image_rect, owner, image_id in assigned_images:
            if rect.y0 < image_rect.y1:
                continue
            horizontal_overlap = (rect & image_rect).width / min(rect.width, image_rect.width)
            gap = rect.y0 - image_rect.y1
            if horizontal_overlap >= .8 and gap <= 180:
                matches.append((gap, owner, image_id))
        if not matches:
            continue
        matches.sort()
        if len(matches) > 1 and matches[0][0] == matches[1][0] and matches[0][1] != matches[1][1]:
            continue
        _, owner, image_id = matches[0]
        previous = resolved[str(block['id'])]
        if previous != owner:
            changes.append({'block': block['id'], 'previous_owner': previous,
                            'owner': owner, 'image': image_id,
                            'basis': 'text directly following matching lead image'})
            resolved[str(block['id'])] = owner
    return resolved, changes


def split_mixed_ad_image_blocks(page, blocks, articles):
    """Split an OCR-detected image panel where a framed story sits above ads."""
    candidates = []
    for block in blocks:
        text = block.get('text', '')
        if (block.get('kind') != 'image'
                or not re.search(r'\bcontact\s+for\s+advt\b|\badvertising\s+booking\b', text, re.I)):
            continue
        rect = fitz.Rect(block['bbox'])
        headlines = [other for other in blocks if other['id'] != block['id']
                     and other.get('kind') == 'text'
                     and rect.contains(fitz.Rect(other['bbox']))
                     and any(headline_matches(other.get('text', ''), title)
                             for title in articles.values())]
        nested_images = [other for other in blocks if other['id'] != block['id']
                         and other.get('kind') == 'image'
                         and rect.contains(fitz.Rect(other['bbox']))]
        if headlines and nested_images:
            candidates.append((block, rect, max(fitz.Rect(image['bbox']).y1
                                                for image in nested_images)))

    auto_excluded = set()
    additions = []
    for block, rect, nested_bottom in candidates:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
        samples, width, height, channels = pix.samples, pix.width, pix.height, pix.n
        scan_start = max(rect.y0 + 20, nested_bottom + rect.height * .05)
        scan_end = min(rect.y1 - 20, rect.y0 + rect.height * .45)
        first_border = None
        min_run = width * .06
        for row in range(max(0, int((scan_start - rect.y0) * 2)),
                         min(height, int((scan_end - rect.y0) * 2))):
            longest = run = 0
            for column in range(width):
                offset = (row * width + column) * channels
                if max(samples[offset:offset + 3]) < 100:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            if longest >= min_run:
                first_border = rect.y0 + row / 2
                break
        if first_border is None:
            continue

        marker = re.search(r'\bcontact\s+for\s+advt\b|\badvertising\s+booking\b',
                           block['text'], re.I)
        story_text = block['text'][:marker.start()].rstrip()
        ad_text = block['text'][marker.start():].lstrip()
        if not story_text or not ad_text:
            continue
        split_y = min(first_border + .5, rect.y1)
        block['bbox'] = [rect.x0, rect.y0, rect.x1, split_y]
        block['text'] = story_text
        block['layout_label'] = 'article_image_panel'
        ad_id = max(item['id'] for item in blocks + additions) + 1
        additions.append({**block, 'id': ad_id,
                          'bbox': [rect.x0, split_y, rect.x1, rect.y1],
                          'text': ad_text, 'layout_label': 'advertisement_panel'})
        auto_excluded.add(ad_id)

    return blocks + additions, auto_excluded


def explicit_page_teaser_ids(blocks):
    text = [b for b in blocks if b['kind'] == 'text' and normalized(b.get('text', ''))]
    markers = []
    inside = [b for b in text if normalized(b.get('text', '')) == 'inside']
    pages = [b for b in text if re.fullmatch(r'page(?: \d+)?', normalized(b.get('text', '')))]
    for block in text:
        if re.search(r'\binside\s+page(?:\s+\d+)?\b', block.get('text', ''), re.I):
            markers.append((fitz.Rect(block['bbox']), {block['id']}))
    for label in inside:
        label_rect = fitz.Rect(label['bbox'])
        for page_label in pages:
            page_rect = fitz.Rect(page_label['bbox'])
            row_overlap = min(label_rect.y1, page_rect.y1) - max(label_rect.y0, page_rect.y0)
            horizontal_gap = page_rect.x0 - label_rect.x1
            if (row_overlap >= min(label_rect.height, page_rect.height) * .35
                    and -2 <= horizontal_gap <= max(48, label_rect.width * 2)):
                markers.append((label_rect | page_rect, {label['id'], page_label['id']}))

    result = set()
    for marker, marker_ids in markers:
        for headline in text:
            if headline['id'] in marker_ids:
                continue
            headline_rect = fitz.Rect(headline['bbox'])
            gap = headline_rect.y0 - marker.y1
            horizontal_overlap = max(0, min(marker.x1, headline_rect.x1)
                                     - max(marker.x0, headline_rect.x0))
            overlap_ratio = horizontal_overlap / max(headline_rect.width, 1)
            letters = [char for char in headline.get('text', '') if char.isalpha()]
            uppercase_ratio = sum(char.isupper() for char in letters) / max(len(letters), 1)
            words = headline.get('text', '').split()
            if (-2 <= gap <= max(8, marker.height * .75)
                    and overlap_ratio >= .65 and 4 <= len(words) <= 18
                    and uppercase_ratio >= .8):
                result.update(marker_ids)
                result.add(headline['id'])
    return result


def remove_explicit_page_teaser_headlines(titles, blocks):
    teaser_ids = explicit_page_teaser_ids(blocks)
    teaser_text = [b.get('text', '') for b in blocks if b['id'] in teaser_ids]
    article_text = [b.get('text', '') for b in blocks if b['id'] not in teaser_ids]
    retained, removed = [], []
    for title in titles:
        is_teaser = any(headline_matches(text, title) for text in teaser_text)
        is_article = any(headline_matches(text, title) for text in article_text)
        (retained if not is_teaser or is_article else removed).append(title)
    return retained, removed


def headline_evidence(blocks):
    """Conservative typography/teaser hints, not a universal article detector."""
    text = [b for b in blocks if b['kind'] == 'text' and normalized(b.get('text', ''))]
    explicit_teasers = explicit_page_teaser_ids(blocks)
    body_sizes = [b.get('font_min', 0) for b in text
                  if len(b.get('text', '').split()) >= 30 and b.get('font_min', 0) > 0]
    body_size = median(body_sizes) if body_sizes else 9
    extent = fitz.Rect(blocks[0]['bbox']) if blocks else fitz.Rect()
    for block in blocks[1:]:
        extent |= fitz.Rect(block['bbox'])
    result = []
    for b in text:
        words = b.get('text', '').split()
        rect = fitz.Rect(b['bbox'])
        # Teaser headline is inside a promotional image with a page-link label.
        containers = [fitz.Rect(i['bbox']) for i in blocks if i['kind'] == 'image'
                      and fitz.Rect(i['bbox']).get_area() < extent.get_area() * .4
                      and (rect & fitz.Rect(i['bbox'])).get_area() >= rect.get_area()*.98]
        teaser = any(any(re.search(r'\bPAGE\s+(?:\d+|[IVX]+)\b', t.get('text', ''), re.I)
                         and (fitz.Rect(t['bbox']) & image).get_area() >= fitz.Rect(t['bbox']).get_area()*.98
                         for t in text) for image in containers) or b['id'] in explicit_teasers
        # Long standfirsts can use headline-sized fonts too. Keep this detector
        # conservative; it is a review guard, not proof of complete inventory.
        candidate = (2 <= len(words) <= 26 and (b.get('font_min', 0) >= body_size * 1.3
                     or b.get('font_max', 0) >= body_size * 1.8)
                     or b.get('layout_label') in ('doc_title', 'paragraph_title'))
        if candidate or teaser:
            result.append({'block_id': b['id'], 'text': b['text'],
                           'headline_candidate': candidate, 'teaser_hint': teaser})
    return result


def inventory_issues(blocks, articles, roles=None):
    issues = []
    for hint in headline_evidence(blocks):
        role = (roles or {}).get(str(hint['block_id']))
        if role in ('subheadline', 'kicker', 'masthead', 'teaser'):
            if any(headline_matches(hint['text'], title) or headline_embedded(hint['text'], title)
                   for title in articles.values()):
                issues.append(f"Non-article {role} block {hint['block_id']} appears as a standalone story.")
            continue
        if role == 'other':
            continue
        matched = [ident for ident, title in articles.items()
                   if headline_matches(hint['text'], title) or headline_embedded(hint['text'], title)]
        if hint['teaser_hint'] and matched:
            issues.append(f"Promotional teaser block {hint['block_id']} appears as an article: {matched}")
        elif hint['headline_candidate'] and not hint['teaser_hint'] and not matched:
            issues.append(f"Headline candidate block {hint['block_id']} is absent from inventory: {hint['text']}")
    return issues


def ownership_issues(blocks, owners, articles, roles=None):
    issues = inventory_issues(blocks, articles, roles)
    for hint in headline_evidence(blocks):
        if roles and roles.get(str(hint['block_id'])) in ('subheadline', 'kicker', 'masthead', 'teaser', 'other'):
            continue
        owner = owners[str(hint['block_id'])]
        if hint['headline_candidate'] and not hint['teaser_hint'] and (
                owner not in articles or not (
                    headline_matches(hint['text'], articles[owner])
                    or headline_embedded(hint['text'], articles[owner]))):
            issues.append(f"Headline block {hint['block_id']} has mismatched owner {owner}")
    for link in continuation_links(blocks):
        label, column = str(link['label']), str(link['column'])
        if owners[label] != owners[column]:
            issues.append(f'Continuation block {label} owner {owners[label]} differs from nearby column {column} owner {owners[column]}')
    return issues


def continuation_links(blocks):
    """Unambiguous explicit continuation labels and their nearest preceding column."""
    links = []
    for block in blocks:
        if not re.match(r'^\s*CONTINUED\s+ON\b', block.get('text', ''), re.I):
            continue
        rect = fitz.Rect(block['bbox'])
        above = []
        for other in blocks:
            if other['kind'] != 'text' or len(other.get('text', '').split()) < 8:
                continue
            r = fitz.Rect(other['bbox'])
            gap = rect.y0 - r.y1
            horizontal = min(rect.x1, r.x1) - max(rect.x0, r.x0)
            if 0 <= gap <= 40 and horizontal >= rect.width*.8:
                above.append((gap, other))
        if above:
            above.sort(key=lambda entry: entry[0])
            if len(above) > 1 and abs(above[0][0] - above[1][0]) < 1:
                continue
            nearest = above[0][1]
            links.append({'label': block['id'], 'column': nearest['id']})
    return links


def reconcile_continuations(blocks, owners, article_ids):
    """Apply only unambiguous native column links, retaining an audit of changes."""
    resolved = dict(owners)
    changes = []
    for link in continuation_links(blocks):
        label, column = str(link['label']), str(link['column'])
        owner = owners[column]
        if owner in article_ids and owners[label] != owner:
            changes.append({**link, 'previous_owner': owners[label], 'owner': owner,
                            'basis': 'explicit continuation beneath unambiguous native column'})
            resolved[label] = owner
    return resolved, changes


def reconcile_headline_column_owners(blocks, owners, article_ids, anchors):
    """Repair strong same-column headline links without crossing story boundaries."""
    resolved = dict(owners)
    changes = []
    headlines = [(owner, fitz.Rect(anchor['bbox']), anchor['id'])
                 for owner in article_ids for anchor in anchors.get(owner, [])]
    headline_ids = {headline_id for _, _, headline_id in headlines}
    headline_owners = {}
    for owner, _, headline_id in headlines:
        headline_owners.setdefault(headline_id, set()).add(owner)
    for block in blocks:
        if block.get('kind') != 'text':
            continue
        if block['id'] in headline_ids:
            expected_owners = headline_owners[block['id']]
            current = owners[str(block['id'])]
            if len(expected_owners) == 1:
                expected = next(iter(expected_owners))
                if current != expected:
                    changes.append({'block': block['id'], 'previous_owner': current,
                                    'owner': expected, 'headline': block['id'],
                                    'basis': 'source headline match'})
                    resolved[str(block['id'])] = expected
            continue
        block_rect = fitz.Rect(block['bbox'])
        text = block.get('text', '').strip()
        current = owners[str(block['id'])]
        if current not in article_ids and not (not text and current == 'exclude:teaser'):
            continue
        overlaps_current_owner = any(
            str(other['id']) != str(block['id'])
            and owners[str(other['id'])] == current
            and (block_rect & fitz.Rect(other['bbox'])).get_area() > .01
            for other in blocks)
        candidates = []
        for owner, headline_rect, headline_id in headlines:
            if headline_id == block['id']:
                continue
            overlap = min(block_rect.x1, headline_rect.x1) - max(block_rect.x0, headline_rect.x0)
            if overlap < min(block_rect.width, headline_rect.width) * .5:
                continue
            if text:
                if block_rect.y0 < headline_rect.y1:
                    continue
                gap = block_rect.y0 - headline_rect.y1
                if gap > 24:
                    if gap > 300 or len(text.split()) < 50 or overlaps_current_owner:
                        continue
                basis = ('adjacent headline in the same text column' if gap <= 24
                         else 'long text block in the same headline column')
            else:
                if headline_rect.y0 < block_rect.y1:
                    continue
                gap = headline_rect.y0 - block_rect.y1
                if gap > 24:
                    continue
                basis = 'adjacent headline in the same text column'
                gap = -gap
            candidates.append((abs(gap), owner, headline_id, basis))
        if not candidates:
            continue
        _, expected, headline_id, basis = min(candidates)
        if current != expected:
            changes.append({'block': block['id'], 'previous_owner': current,
                            'owner': expected, 'headline': headline_id,
                            'basis': basis})
            resolved[str(block['id'])] = expected
    return resolved, changes


def ownership_schema(blocks, article_ids):
    return {'type': 'object', 'properties': {
        str(b['id']): {'type': 'string', 'enum': article_ids + EXCLUSIONS} for b in blocks},
        'required': [str(b['id']) for b in blocks], 'additionalProperties': False}


def parse_ownership(text, blocks, article_ids):
    import json
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate ownership key: ' + key)
            result[key] = value
        return result
    owners = json.loads(text, object_pairs_hook=unique_pairs)
    expected = {str(b['id']) for b in blocks}
    if not isinstance(owners, dict) or set(owners) != expected:
        actual = set(owners) if isinstance(owners, dict) else set()
        raise ValueError(f'Ownership coverage: missing={sorted(expected-actual)}, unknown={sorted(actual-expected)}')
    allowed = set(article_ids + EXCLUSIONS)
    if any(not isinstance(v, str) or v not in allowed for v in owners.values()):
        raise ValueError('Unknown article/exclusion owner.')
    for ident in article_ids:
        if not any(owners[str(b['id'])] == ident and b['kind'] == 'text' for b in blocks):
            raise ValueError('Article has no text blocks: ' + ident)
    return owners


def build_regions(blocks, owners, article_ids):
    """Greedily combine rectangles only when no foreign block is intersected."""
    foreign = {owner: [(b['id'], b['bbox']) for b in blocks
                       if owners[str(b['id'])] != owner] for owner in article_ids}
    conflict_cache = {}
    def conflicts(rect, owner):
        key = (owner, *rect)
        if key not in conflict_cache:
            conflict_cache[key] = [ident for ident, box in foreign[owner]
                if max(0, min(rect.x1, box[2])-max(rect.x0, box[0]))
                * max(0, min(rect.y1, box[3])-max(rect.y0, box[1])) > .01]
        return conflict_cache[key]

    result = {}
    for owner in article_ids:
        regions = [fitz.Rect(b['bbox']) for b in blocks if owners[str(b['id'])] == owner]
        for rect in regions:
            bad = conflicts(rect, owner)
            if bad:
                raise ValueError(f'{owner}: overlapping native blocks have different owners: {bad}')
        while True:
            choices = []
            for i in range(len(regions)):
                # Only nearby candidates are useful for compact article columns.
                # This bounds search work, not retained content or article count.
                a = regions[i]
                neighbors = sorted(range(i + 1, len(regions)), key=lambda j:
                    max(0, regions[j].x0-a.x1, a.x0-regions[j].x1)
                    + max(0, regions[j].y0-a.y1, a.y0-regions[j].y1))[:8]
                for j in neighbors:
                    union = regions[i] | regions[j]
                    absorbed = {i, j}
                    # A merged crop must also absorb every same-owner region it
                    # intersects. Otherwise two output crops repeat source text.
                    while True:
                        extra = {k for k, r in enumerate(regions) if k not in absorbed
                                 and (r & union).get_area() > .01}
                        if not extra:
                            break
                        for k in extra:
                            union |= regions[k]
                        absorbed |= extra
                    if not conflicts(union, owner):
                        cost = union.get_area() - sum(regions[k].get_area() for k in absorbed)
                        choices.append((cost, i, j, union, absorbed))
                        break
                if choices:
                    break
            if not choices:
                break
            _, i, j, union, absorbed = min(choices, key=lambda x: x[:3])
            regions = [r for k, r in enumerate(regions) if k not in absorbed] + [union]
        regions = disjoint_rectangles(regions)
        result[owner] = sorted(regions, key=lambda r: (r.y0, r.x0))
    return result


def disjoint_rectangles(rectangles):
    """Partition a union exactly; never enlarge crops to resolve an overlap."""
    accepted = []
    for rectangle in rectangles:
        pending = [fitz.Rect(rectangle)]
        for prior in accepted:
            next_parts = []
            for part in pending:
                hit = part & prior
                if hit.is_empty:
                    next_parts.append(part)
                    continue
                pieces = [(part.x0, part.y0, part.x1, hit.y0),
                          (part.x0, hit.y1, part.x1, part.y1),
                          (part.x0, hit.y0, hit.x0, hit.y1),
                          (hit.x1, hit.y0, part.x1, hit.y1)]
                next_parts.extend(fitz.Rect(p) for p in pieces if p[2] > p[0] and p[3] > p[1])
            pending = next_parts
        accepted.extend(pending)
    return accepted


def conflicting_pairs(blocks, owners, article_ids):
    """Report cross-owner crop overlaps, excluding pairs that are both excluded."""
    pairs = []
    for i, a in enumerate(blocks):
        for b in blocks[i+1:]:
            first, second = owners[str(a['id'])], owners[str(b['id'])]
            if first == second or not ({first, second} & set(article_ids)):
                continue
            if (fitz.Rect(a['bbox']) & fitz.Rect(b['bbox'])).get_area() > .01:
                pairs.append([a['id'], b['id']])
    return pairs


def overlap_components(blocks):
    """Connected overlapping source regions cannot be cropped as separate owners."""
    parent = list(range(len(blocks)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(blocks):
        for j in range(i + 1, len(blocks)):
            if (fitz.Rect(a['bbox']) & fitz.Rect(blocks[j]['bbox'])).get_area() > .01:
                parent[root(j)] = root(i)
    groups = {}
    for i, block in enumerate(blocks):
        groups.setdefault(root(i), []).append(block['id'])
    return list(groups.values())


def render_article(preview, source, page_index, rectangles, label=None):
    """Keep source-relative column positions while leaving unrelated areas blank."""
    rects = [fitz.Rect(r) for r in rectangles]
    if not rects or any(r.is_empty or r.is_infinite for r in rects):
        raise ValueError('Article needs finite nonempty source regions.')
    bounds = fitz.Rect(rects[0])
    for rect in rects[1:]:
        bounds |= rect
    top = 36 if label else 12
    dest = preview.new_page(width=bounds.width+24, height=bounds.height+top+12)
    if label:
        dest.insert_text((12, 15), label, fontsize=6)
    for rect in rects:
        target = fitz.Rect(rect.x0-bounds.x0+12, rect.y0-bounds.y0+top,
                           rect.x1-bounds.x0+12, rect.y1-bounds.y0+top)
        dest.show_pdf_page(target, source, page_index, clip=rect)
    return dest

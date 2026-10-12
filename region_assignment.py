"""Snap approximate model regions to complete source blocks; never crop to model edges."""
import math
import re
import fitz


def footer_assignments(blocks, components, page_rect):
    def footer(b):
        rect = fitz.Rect(b['bbox'])
        if rect.y0 < page_rect.y0+page_rect.height*.9:
            return False
        if b.get('layout_label') == 'footer':
            return True
        text = re.sub(r'[^a-z0-9.-]', '', b.get('text', '').lower())
        return (rect.y0 >= page_rect.y0+page_rect.height*.95
                and rect.width < page_rect.width*.3 and rect.height < page_rect.height*.02
                and abs((rect.x0+rect.x1)/2-(page_rect.x0+page_rect.x1)/2) < page_rect.width*.15
                and re.fullmatch(r'(?:[a-z0-9-]+\.)+(?:com|org|net|in|co|uk)', text))
    footers = [b for b in blocks if footer(b)]
    if not footers:
        return {}
    top = min(b['bbox'][1] for b in footers)
    max_height = max(b['bbox'][3]-b['bbox'][1] for b in footers)*2
    by_id = {b['id']: b for b in blocks}
    result = {}
    for group in components:
        members = [by_id[i] for i in group]
        if all(b['bbox'][1] >= top and b['bbox'][3]-b['bbox'][1] <= max_height
               and len(b.get('text', '').split()) <= 4 for b in members):
            result.update({str(i): 'exclude:print_mark' for i in group})
    return result


def anchor_issues(zones, anchors):
    """Check normalized regions against source-derived headline bounds."""
    issues = []
    for owner, boxes in anchors.items():
        own = [fitz.Rect(box) for z in zones if z['owner'] == owner for box in z['boxes']]
        for box in boxes:
            headline = fitz.Rect(box)
            area = headline.get_area()
            if area <= 0:
                continue
            if not any((rect & headline).get_area() >= area*.98 for rect in own):
                issues.append(f'{owner}: no region covers its complete headline {box}')
            for zone in zones:
                if zone['owner'] == owner:
                    continue
                for candidate in zone['boxes']:
                    fraction = (fitz.Rect(candidate) & headline).get_area()/area
                    if .05 < fraction < .95:
                        issues.append(f"{zone['owner']}: region {candidate} cuts across part of {owner}'s headline {box}")
    return issues


def include_source_headlines(zones, anchors):
    result = [{'owner': z['owner'], 'boxes': [list(b) for b in z['boxes']]} for z in zones]
    for owner, boxes in anchors.items():
        for box in boxes:
            headline = fitz.Rect(box)
            if not any(z['owner'] == owner and any(
                    (fitz.Rect(b) & headline).get_area() >= headline.get_area()*.98 for b in z['boxes'])
                       for z in result):
                # This is source-derived headline geometry, never an invented
                # expansion of body regions into neighbouring columns.
                result.append({'owner': owner, 'boxes': [list(box)]})
    return result


def trim_regions_at_foreign_headlines(zones, anchors):
    """Keep another article's known headline out of each region without dropping nearby content."""
    result = []
    for zone in zones:
        pieces = [fitz.Rect(box) for box in zone['boxes']]
        for owner, boxes in anchors.items():
            if owner == zone['owner']:
                continue
            for box in boxes:
                headline = fitz.Rect(box)
                next_pieces = []
                for piece in pieces:
                    hit = piece & headline
                    if hit.is_empty or hit.get_area() <= .01:
                        next_pieces.append(piece)
                        continue
                    candidates = [
                        (piece.x0, piece.y0, piece.x1, hit.y0),
                        (piece.x0, hit.y1, piece.x1, piece.y1),
                        (piece.x0, hit.y0, hit.x0, hit.y1),
                        (hit.x1, hit.y0, piece.x1, hit.y1)]
                    next_pieces.extend(fitz.Rect(box) for box in candidates
                                       if box[2] > box[0] and box[3] > box[1])
                pieces = next_pieces
        result.extend({'owner': zone['owner'], 'boxes': [list(piece)]} for piece in pieces)
    return result


def embedded_callout_merges(articles, blocks, anchors, roles, zones):
    """Find tiny paragraph-title regions embedded in a larger headed article."""
    by_id = {block['id']: block for block in blocks}
    zone_rects = {}
    for zone in zones:
        zone_rects.setdefault(zone['owner'], []).extend(
            fitz.Rect(box) for box in zone.get('boxes', []))

    merges = {}
    for child in articles:
        child_anchors = anchors.get(child, [])
        if not child_anchors:
            continue
        anchor_blocks = [by_id.get(anchor['id']) for anchor in child_anchors]
        if any(block is None or block.get('layout_label') != 'paragraph_title'
               or roles.get(str(block['id'])) != 'headline' for block in anchor_blocks):
            continue
        child_rects = zone_rects.get(child, [])
        child_area = sum(rect.get_area() for rect in child_rects)
        if not child_area or child_area > 50_000:
            continue

        parents = []
        for parent in articles:
            if parent == child or not any(
                    (anchor_block := by_id.get(anchor['id'])) is not None
                    and anchor_block.get('layout_label') == 'doc_title'
                    for anchor in anchors.get(parent, [])):
                continue
            parent_rects = zone_rects.get(parent, [])
            parent_area = sum(rect.get_area() for rect in parent_rects)
            if parent_area < child_area * 3:
                continue
            covered = sum((child_rect & parent_rect).get_area()
                          for child_rect in child_rects for parent_rect in parent_rects)
            if min(covered, child_area) / child_area >= .85:
                parents.append(parent)
        if len(parents) == 1:
            merges[child] = parents[0]
    return merges


def assign_components(blocks, components, zones, page_rect, allowed):
    regions = []
    for zone in zones:
        if zone.get('owner') not in allowed:
            raise ValueError('Unknown region owner.')
        for box in zone.get('boxes', []):
            if len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                   or not math.isfinite(v) or not 0 <= v <= 1000 for v in box):
                raise ValueError('Invalid approximate region coordinates.')
            x0, y0, x1, y1 = box
            if x1 <= x0 or y1 <= y0:
                raise ValueError('Reversed approximate region.')
            rect = fitz.Rect(page_rect.x0+x0*page_rect.width/1000,
                             page_rect.y0+y0*page_rect.height/1000,
                             page_rect.x0+x1*page_rect.width/1000,
                             page_rect.y0+y1*page_rect.height/1000)
            regions.append((zone['owner'], rect))
    by_id = {b['id']: b for b in blocks}
    assigned, unresolved = {}, []
    for component in components:
        owners = set()
        for ident in component:
            rect = fitz.Rect(by_id[ident]['bbox'])
            area = rect.get_area()
            choices = []
            if area > 0:
                for owner, region in regions:
                    coverage = (rect & region).get_area()/area
                    if coverage >= .7:
                        choices.append((coverage, region.get_area(), owner))
            if not choices:
                owners.add(None)
                continue
            best = max(c[0] for c in choices)
            # A smaller sidebar takes precedence over an enclosing story area
            # only when both cover effectively the same amount of this block.
            candidates = sorted((size, owner) for coverage, size, owner in choices if coverage >= best-.02)
            size, owner = candidates[0]
            if any(other != owner and other_size <= size*1.05 for other_size, other in candidates[1:]):
                owners.add(None)
            else:
                owners.add(owner)
        if len(owners) == 1 and None not in owners:
            owner = owners.pop()
            assigned.update({str(i): owner for i in component})
        else:
            unresolved.append(component[0])
    return assigned, unresolved

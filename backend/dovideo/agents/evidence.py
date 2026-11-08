"""Extractive evidence selection. Text and its provenance travel together."""
import re
from dovideo.agents.recall import relevance, terms

MATH = re.compile(r'\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\$)\$(?!\$)[^\n$]+\$|```[\s\S]*?```')


def units(text):
    """Sentence/line ranges; display math and its adjacent conditions stay atomic."""
    protected = [(m.start(), m.end()) for m in MATH.finditer(text)]
    boundaries = [0]
    for m in re.finditer(r'\n+|[。！？；]', text):
        if not any(a < m.end() < b for a, b in protected):
            boundaries.append(m.end())
    boundaries.append(len(text))
    ranges = [(a, b) for a, b in zip(boundaries, boundaries[1:]) if text[a:b].strip()]
    # Retain surrounding statements when selecting a formula, rather than sending
    # an isolated equality with its domain/exception removed.
    groups = []
    for i, (a, b) in enumerate(ranges):
        if any(a < y and x < b for x, y in protected):
            left = ranges[max(0, i-1)][0]
            right = ranges[min(len(ranges)-1, i+1)][1]
            if groups and left <= groups[-1][1]:
                groups[-1] = (groups[-1][0], max(right, groups[-1][1]))
            else:
                groups.append((left, right))
    result = list(groups)
    result.extend((a,b) for a,b in ranges if not any(a < y and x < b for x,y in groups))
    return sorted(result)


def segments(item):
    """Accept precise element provenance only if it reconstructs the actual text."""
    text = str(item.get('content') or '')
    spans = item.get('source_segments') or []
    if spans and all(isinstance(s,dict) and isinstance(s.get('text'),str) for s in spans):
        if '\n\n'.join(s['text'].strip() for s in spans) == text:
            return [(s['text'].strip(), s.get('locators',[])) for s in spans], True
    return [(text,item.get('locators',[]))], False


def select(item, query='', limit=None):
    """Return original text excerpts with conservative, never guessed locators."""
    source, precise = segments(item)
    text = str(item.get('content') or '')
    if limit is None or len(text) <= limit:
        return text, item.get('locators',[]), False, precise
    candidates = []
    for section, (part, locators) in enumerate(source):
        for start,end in units(part):
            piece = part[start:end]
            if len(piece) > limit:
                if MATH.search(piece):
                    continue  # Never cut a formula/condition group in half.
                matches = [m.start() for t in terms(query) for m in re.finditer(re.escape(t),piece.lower())]
                left = max(0,(min(matches) if matches else 0)-limit//3)
                piece = piece[left:left+limit]
            candidates.append((relevance(query,piece),section,start,piece,locators))
    if any(c[0]>0 for c in candidates):
        candidates=[c for c in candidates if c[0]>0]
    selected = []; used = 0
    for candidate in sorted(candidates,key=lambda c:(-c[0],c[1],c[2])):
        cost = len(candidate[3]) + (5 if selected else 0)
        if used + cost <= limit:
            selected.append(candidate); used += cost
    selected.sort(key=lambda c:(c[1],c[2]))
    locators = []
    for candidate in selected:
        for locator in candidate[4]:
            if locator not in locators:locators.append(locator)
    return ' […] '.join(c[3] for c in selected), locators, True, precise

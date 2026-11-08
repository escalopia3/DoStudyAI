"""Deterministic citation integrity. This does not judge semantic support."""
import hashlib
import re
TRUSTED_REFUSAL='本轮已返回的课程证据不足以生成可验证答案，尚不能核实所问内容；这不代表资料全文不存在相关信息。请补充相关页面或缩小范围。'


def identity(item):
    return {k: item.get(k) for k in ('resource_id', 'index_version_id', 'chunk_id')}


def snapshot(item, reference=None):
    reference=reference or item
    text=item.get('content','')
    original=reference.get('content','')
    return {**identity(reference), 'content_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'document_name':item.get('document_name') or reference.get('document_name'),
            'boundary_definition_visible':all(term in text for term in ('边界点','任意邻域','不属于')),
            'reference_sha256':hashlib.sha256(original.encode()).hexdigest(),
            'excerpt_matches_source':bool(text) and all(piece in original for piece in text.split(' […] ')),
            'pages': item.get('pages', []), 'locators': item.get('locators', []),
            'video_ranges': item.get('video_ranges', [])}


def validate(answer, references, visible):
    markers=re.findall(r'[\[［]\s*S[^\]］\n]*[\]］]',answer)
    malformed=[m for m in markers if re.search(r'\bS(?:\?|#|[A-Za-z])',m) or not re.search(r'\bS[0-9]+\b',m)]
    cited = sorted(set(re.findall(r'\bS[0-9]+\b', answer)))
    rows = []
    for sid in cited:
        ref, view = references.get(sid), visible.get(sid)
        row = {'source_id': sid, 'existence': 'pass' if ref else 'fail',
               'visibility': 'fail', 'provenance': 'unverifiable', 'reasons': []}
        if not ref:
            row['reasons'].append('UNKNOWN_SOURCE')
        elif not view:
            row['reasons'].append('NOT_IN_MODEL_INPUT')
        elif (any(view.get(k) and ref.get(k) != view[k] for k in identity(ref))
              or (view.get('reference_sha256') and view['reference_sha256']!=hashlib.sha256(ref.get('content','').encode()).hexdigest())
              or view.get('excerpt_matches_source') is False):
            row['reasons'].append('SOURCE_VERSION_MISMATCH')
        else:
            row['visibility'] = 'pass'
            # Actual excerpt may be shorter than the original reference; its digest
            # identifies the delivered text, not a claim that both texts are equal.
            pages = view.get('pages', [])
            locators = ref.get('locators', [])
            known = {p['pageIndex']+1 for p in locators if type(p.get('pageIndex')) is int}
            if pages and known and not set(pages).issubset(known):
                row['provenance'] = 'fail'
                row['reasons'].append('PAGE_OUTSIDE_SOURCE')
            elif (all(identity(ref).values()) and view.get('content_sha256')
                  and ((pages and known) or view.get('video_ranges'))):
                row['provenance'] = 'pass'
            else:
                row['reasons'].append('LEGACY_OR_MISSING_LOCATOR')
        rows.append(row)
    # Only evaluate explicit [Sx]第N页 / [Sx] p.N claims; unsupported
    # prose layouts remain unverifiable rather than guessed associations.
    explicit = list(re.finditer(r'\[(S\d+)\]\s*(?:第\s*(\d+)\s*页|[pP]\.\s*(\d+))', answer))
    for match in explicit:
        sid, page = match[1], int(match[2] or match[3])
        row = next(r for r in rows if r['source_id'] == sid)
        if page not in visible.get(sid, {}).get('pages', []):
            row['provenance'] = 'fail'
            row['reasons'].append('CLAIMED_PAGE_NOT_VISIBLE')
    has_page_claim = bool(re.search(r'第\s*\d+\s*页|[pP]\.\s*\d+', answer))
    return {'cited_count': len(cited), 'missing_citations': bool(references) and not cited,
            'malformed_markers':malformed,
            'failed': bool(malformed) or any('fail' in (r['existence'], r['visibility'], r['provenance']) for r in rows),
            'unverifiable': sum(r['provenance'] == 'unverifiable' for r in rows),
            'page_claims_unverified': has_page_claim and not explicit, 'sources': rows}


def unsupported_scope_claims(answer):
    """Conservative lexical guard for absolute absence claims, not semantic judging."""
    pattern=r'(?:三份[^。\n]{0,8}(?:课件|材料|资料)|整份(?:课件|文件)|整套课件|全部(?:课件|资料)|这些材料|课件(?:本身|全文|中|里)|资料(?:中|里))[^。\n]{0,45}?(?:没有(?!找到|查到|检索)|不包含|不含|不存在|未提供|均未出现|均无)'
    found=[]
    for match in re.finditer(pattern,answer):
        before=answer[max(0,match.start()-18):match.start()]
        span=match[0]
        if re.search(r'(?:不能|无法|不应)[^。:：，,]{0,8}(?:断言|判断|认定|声称|证明|推断|认为|说|确定)|不代表|未必|是否|如果|假如|不意味着|不作(?:断言|判断)',before):continue
        if re.search(r'本轮|本次|已返回|可见|检索到|当前证据',before+span):continue
        found.append(span)
    return found


def definition_conflicts(answer,visible):
    # A narrow source-driven invariant, not a general semantic-support score.
    # Removing the centre changes the boundary test for isolated set points.
    if any(v.get('boundary_definition_visible') for v in visible.values()) and '边界' in answer:
        return re.findall(r'去心或含心(?:的)?邻域|含心或去心(?:的)?邻域',answer)
    return []


def inventory_conflicts(answer,visible):
    names={v.get('document_name') for v in visible.values() if v.get('document_name')}
    if len(names)<3:
        return re.findall(r'(?:另(?:外)?两份|其余两份)课件(?:的)?(?:已)?返回(?:的)?(?:内容|证据)',answer)
    return []

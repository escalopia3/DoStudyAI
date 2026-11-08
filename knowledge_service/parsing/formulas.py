"""Offline PPT equation audit and explicitly reviewed source transcriptions.

No network, OCR guesses, question-bank answers, or silent formula substitution.
Reviews are deployment-owned JSON files named by the immutable source SHA256.
"""
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from knowledge_service.models import DocumentElement

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
FLAG = 'PPTX_OLE_EQUATIONS_REQUIRE_REVIEW'


def audit(path):
    pages = []
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            match = re.fullmatch(r'ppt/slides/slide(\d+)\.xml',name)
            if not match:continue
            root = ET.fromstring(archive.read(name))
            # Choice/Fallback XML represents the same object twice.
            objects = {o.get('{'+R+'}id') for o in root.iter('{'+P+'}oleObj')
                if any(t in o.get('progId','').lower() for t in ('equation','mathtype','dsmt'))}
            pages.append({'page':int(match[1]),'equation_objects':len(objects)})
    return {'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'pages':sorted(pages,key=lambda p:p['page'])}


def enrich(doc, source, reviews_dir=''):
    if Path(source).suffix.lower()!='.pptx':return doc
    result = audit(source)
    risky = {p['page']-1 for p in result['pages'] if p['equation_objects']}
    if risky:
        doc.qualityFlags=list(dict.fromkeys([*doc.qualityFlags,FLAG]))
        for element in doc.elements:
            if any(l.get('pageIndex') in risky for l in element.locators):
                element.qualityFlags=list(dict.fromkeys([*element.qualityFlags,FLAG]))
    doc.parser=dict(doc.parser,equationAuditVersion='ole-v1',
        sourceSha256=result['source_sha256'],equationObjectCount=str(sum(p['equation_objects'] for p in result['pages'])))
    review_path=Path(reviews_dir)/(result['source_sha256']+'.json') if reviews_dir else None
    if not review_path or not review_path.is_file():return doc
    review=json.loads(review_path.read_text(encoding='utf-8'))
    doc.parser['formulaReviewSha256']=hashlib.sha256(review_path.read_bytes()).hexdigest()
    if review.get('schema_version')!=1 or review.get('source_sha256')!=result['source_sha256']:
        raise ValueError('FORMULA_REVIEW_SOURCE_MISMATCH')
    valid_pages={p['page'] for p in result['pages']}
    added=[];ids=set()
    for record in review.get('records',[]):
        if record.get('status')!='verified' or not record.get('reviewer'):
            raise ValueError('FORMULA_REVIEW_NOT_VERIFIED')
        page=record.get('page');identifier=record.get('id');text=record.get('markdown')
        if type(page) is not int or page not in valid_pages or not isinstance(identifier,str) or not identifier or identifier in ids:
            raise ValueError('FORMULA_REVIEW_INVALID_LOCATION_OR_ID')
        if not isinstance(text,str) or not text.strip() or len(text)>8000:
            raise ValueError('FORMULA_REVIEW_INVALID_TEXT')
        ids.add(identifier)
        added.append(DocumentElement(id='formula-review:'+identifier,type='FORMULA',markdown=text.strip(),
            titlePath=record.get('title_path',[]),sourceRefs=[f'pptx:slide:{page}'],locators=[{'pageIndex':page-1}],
            extractionMethod='REVIEWED_SOURCE_TRANSCRIPTION',
            qualityFlags=['PARTIAL_FORMULA_REVIEW'],data={'sourceSha256':result['source_sha256'],
                'reviewer':record['reviewer'],'reviewId':identifier}))
    # Put additions next to their source page, preserving all original elements.
    doc.elements=sorted([*doc.elements,*added],key=lambda e:min((l.get('pageIndex',10**9) for l in e.locators),default=10**9))
    if added:doc.qualityFlags=list(dict.fromkeys([*doc.qualityFlags,'PARTIAL_FORMULA_REVIEW']))
    # A few reviewed formulas do not certify every OLE object. Keep the risk flag.
    return doc

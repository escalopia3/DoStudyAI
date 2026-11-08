"""Offline labelled retrieval evaluation against the same authorized service.

Usage: python -m dovideo.evaluate --user-id UUID --course-id UUID --dataset FILE
Dataset: [{"question":"...", "expectedResourceIds":["uuid"],
           "expectedChunkIds":["optional precise chunk id"]}]
"""
import argparse
import json
import uuid
from pathlib import Path
from sqlalchemy.orm import Session
from dovideo.config import Settings
from dovideo.storage import Storage
from dovideo.models import User
from dovideo.knowledge import search

def metrics(evidence, expected_resources, expected_chunks=()):
    expected = set(expected_chunks or expected_resources)
    key = 'chunkId' if expected_chunks else 'resourceId'
    ranked = list(dict.fromkeys(item[key] for item in evidence))
    found = expected.intersection(ranked)
    return {'recall':len(found)/len(expected) if expected else 0,
            'reciprocalRank':next((1/(i+1) for i,v in enumerate(ranked) if v in expected),0)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=uuid.UUID, required=True)
    parser.add_argument('--course-id', type=uuid.UUID, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=8, choices=range(1,31))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding='utf-8'))
    if not isinstance(dataset,list) or not dataset or len(dataset)>500:
        parser.error('Dataset must contain 1..500 questions')
    storage = Storage(Settings.from_env())
    try:
        reports = []
        with Session(storage.engine) as session:
            user = session.get(User,args.user_id)
            if user is None:
                parser.error('User does not exist')
            for case in dataset:
                question = case['question']
                if not isinstance(question,str) or not 1<=len(question.strip())<=2000 or not (case.get('expectedChunkIds') or case.get('expectedResourceIds')):
                    parser.error('Every question needs non-empty relevance labels')
                if 'intent' in case:
                    from dovideo.course_knowledge import query_course_knowledge
                    from time import perf_counter
                    started=perf_counter()
                    pages=[]; cursor=None
                    for _ in range(1000):
                        page=query_course_knowledge(session,storage,user,args.course_id,question,
                            intent=case['intent'],resource_ids=case.get('resource_ids',[]),
                            section_ids=case.get('section_ids',[]),cursor=cursor,limit=args.limit)
                        pages.append(page)
                        cursor=page['next_cursor']
                        if not cursor: break
                    result={'evidence':[dict(e,resourceId=e['resource_id'],chunkId=e['chunk_id']) for p in pages for e in p['evidence']],
                        'coverage':pages[-1]['coverage'],'elapsedMs':(perf_counter()-started)*1000,
                        'paginationComplete':not bool(cursor)}
                else:
                    result = search(session,storage,user,args.course_id,question,args.limit)
                reports.append({'question':question, **metrics(result['evidence'],case.get('expectedResourceIds',[]),case.get('expectedChunkIds',[])), **result})
        report = {'k':args.limit, 'count':len(reports),
            'recallAtK':sum(r['recall'] for r in reports)/len(reports),
            'mrrAtK':sum(r['reciprocalRank'] for r in reports)/len(reports),
            'meanElapsedMs':sum(r['elapsedMs'] for r in reports)/len(reports), 'cases':reports}
        text = json.dumps(report,ensure_ascii=False,indent=2)
        if args.output:
            args.output.write_text(text,encoding='utf-8')
        else:
            print(text)
    finally:
        storage.close()

if __name__ == '__main__':
    main()

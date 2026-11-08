"""Apply explicit, input-bound independent AI adjudications without changing raw grades.

An AI review is not human gold. Every decision needs exact answer and evidence anchors.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(report,run_dir,reviews,arm,truth):
    result=copy.deepcopy(report)
    items=reviews.get('arms',{}).get(arm,{})
    if reviews.get('method')!='codex-independent-ai-v1' or reviews.get('human_gold') is not False:
        raise ValueError('INVALID_REVIEW_PROVENANCE')
    if reviews.get('dataset_sha256')!=report['manifest']['dataset_sha256']:
        raise ValueError('REVIEW_DATASET_MISMATCH')
    seen=set();raw_errors=report['judge_error']
    for row in result['per_case']:
        item=items.get(row['id'])
        if item is None:continue
        directory=run_dir/row['id'];answer_file=directory/'result.json';state_file=directory/'checkpoint.json'
        if item.get('result_sha256')!=sha(answer_file) or item.get('checkpoint_sha256')!=sha(state_file):
            raise ValueError('STALE_REVIEW_INPUT')
        answer=json.loads(answer_file.read_text(encoding='utf-8'))['answer']
        state=json.loads(state_file.read_text(encoding='utf-8'))
        actual=state.get('retrieval_debug',{}).get('model_inputs',[])
        if not actual:raise ValueError('REVIEW_EVIDENCE_MISSING')
        sources={e['source_id']:e for e in actual[-1].get('evidence',[]) if e.get('source_id')}
        if type(item.get('task_success')) is not bool or not item.get('reason') or not item.get('all_unresolved_items_reviewed'):
            raise ValueError('INCOMPLETE_REVIEW')
        if not item.get('answer_quotes') or any(not q or q not in answer for q in item['answer_quotes']):
            raise ValueError('REVIEW_ANSWER_QUOTE_MISMATCH')
        if not item.get('evidence'):raise ValueError('UNSUPPORTED_REVIEW')
        for proof in item['evidence']:
            source=sources.get(proof.get('source_id'),{})
            if not proof.get('quote') or proof['quote'] not in source.get('content',''):
                raise ValueError('REVIEW_EVIDENCE_QUOTE_MISMATCH')
            if proof.get('file')!=source.get('document_name'):
                raise ValueError('REVIEW_SOURCE_MISMATCH')
        for proof in item.get('source_page_quotes',[]):
            if not any(t['file']==proof.get('file') and t['page']==proof.get('page')
                       and proof.get('quote') and proof['quote'] in t['text'] for t in truth):
                raise ValueError('REVIEW_PAGE_QUOTE_MISMATCH')
        score=item.get('answer_score',row.get('answer_score'))
        if type(score) is not int or score not in (0,1,2):raise ValueError('INVALID_REVIEW_PRIMARY')
        if item['task_success'] and (score!=2 or row.get('integrity',{}).get('failed')):
            raise ValueError('REVIEW_CANNOT_BYPASS_DETERMINISTIC_FAILURE')
        row['automated_assessment']={k:row.get(k) for k in ('status','answer_score','task_success','judge_error','judge_error_code')}
        row.update(status='completed',answer_score=score,task_success=item['task_success'],
                   independent_ai_review=item)
        row.pop('judge_error',None);row.pop('judge_error_code',None)
        seen.add(row['id'])
    if seen!=set(items):raise ValueError('REVIEW_CASE_SET_MISMATCH')
    rows=result['per_case'];known=[r for r in rows if r.get('task_success') is not None]
    result.update(judge_error=sum(r['status']=='judge_error' for r in rows),raw_judge_error=raw_errors,
        independent_ai_review_count=len(seen),automated_task_assessment_coverage=report['task_assessment_coverage'],
        task_assessment_coverage=len(known)/len(rows),task_success_count=sum(r.get('task_success') is True for r in rows),
        verified_task_success_rate=sum(r.get('task_success') is True for r in rows)/len(rows),
        answer_complete_count=sum(r.get('answer_score')==2 for r in rows),
        review_protocol=reviews['method'],human_gold=False)
    result['manifest']['independent_review_sha256']=hashlib.sha256(json.dumps(reviews,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--reviews',type=Path,required=True);p.add_argument('--arm',required=True)
    p.add_argument('--truth',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'));reviews=json.loads(args.reviews.read_text(encoding='utf-8'))
    truth=json.loads(args.truth.read_text(encoding='utf-8'))
    if reviews.get('truth_sha256')!=sha(args.truth):raise ValueError('REVIEW_TRUTH_MISMATCH')
    value=apply(report,args.run_dir,reviews,args.arm,truth)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:value[k] for k in ('answer_complete_count','judge_error','raw_judge_error','task_assessment_coverage','task_success_count','independent_ai_review_count')},ensure_ascii=False))


if __name__=='__main__':main()

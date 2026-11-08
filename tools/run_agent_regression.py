"""Reproducible real-agent regression; no production writes or implicit deployment.

Run with the backend environment and PYTHONPATH=backend, from the repository root.
Exit: 0 passed, 1 regression, 2 configuration/execution, 3 incomplete assessment.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(dataset, course_id):
    from dovideo.agents.checkpoints import fingerprint
    from dovideo.agents.prompt import VERSION
    files = sorted((ROOT/'backend/dovideo').rglob('*.py')) + sorted((ROOT/'backend/app').rglob('*.py'))
    files += [ROOT/'tools/evaluate_course_rag.py', Path(__file__)]
    return {'dataset_sha256': digest(dataset), 'course_id': course_id,
            'code': {p.relative_to(ROOT).as_posix(): digest(p) for p in files},
            'config_fingerprint': fingerprint(), 'prompt_version': VERSION,
            'model': os.getenv('DOVIDEO_CHAT_MODEL'), 'protocol': 'agent-regression-v1',
            'options': {k: os.getenv(k, '') for k in (
                'DOVIDEO_DETAIL_EVIDENCE_MODE', 'DOVIDEO_MODEL_ATTEMPTS',
                'DOVIDEO_MODEL_DEADLINE_SECONDS', 'DOVIDEO_CHAT_OUTPUT_TOKENS')}}


def preflight(course_id, cases):
    import uuid
    from types import SimpleNamespace
    from sqlalchemy.orm import Session
    from dovideo.config import Settings
    from dovideo.storage import Storage
    from dovideo.models import Course
    from dovideo.knowledge import authorized_indexes
    storage = Storage(Settings.from_env())
    try:
        from sqlalchemy import text
        from dovideo.storage import EXPECTED_ALEMBIC_REVISION
        with storage.engine.connect() as connection:
            revisions=connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
        if revisions!=[EXPECTED_ALEMBIC_REVISION]:
            from dovideo.agents.reliability import AgentFailure
            raise AgentFailure('SCHEMA_MIGRATION_REQUIRED')
        storage.ready()
        with Session(storage.engine) as session:
            course = session.get(Course, uuid.UUID(course_id))
            if course is None:
                raise ValueError('COURSE_NOT_FOUND')
            rows = authorized_indexes(session, SimpleNamespace(id=course.created_by), course.id)
            names = {r.display_name for r, i in rows}
            if {s['file'] for c in cases for s in c.get('sources', [])} - names:
                raise ValueError('SOURCE_MATERIAL_NOT_INDEXED')
            return [{'resource_id': str(r.id), 'index_id': str(i.id),
                     'config': i.config, 'manifest_sha256': hashlib.sha256(
                         json.dumps(i.manifest, sort_keys=True).encode()).hexdigest()} for r, i in rows]
    finally:
        storage.close()


def judge_model():
    from judge_protocol import JsonJudge as ChatModel
    # Separate instance, never swap process-global generator credentials.
    model = object.__new__(ChatModel)
    model.model = os.getenv('DOVIDEO_JUDGE_MODEL', '')
    model.url = os.getenv('DOVIDEO_JUDGE_BASE_URL', '').rstrip('/')
    model.key = os.getenv('DOVIDEO_JUDGE_API_KEY', '')
    model.output_tokens=int(os.getenv('DOVIDEO_JUDGE_OUTPUT_TOKENS','8192'))
    if not all((model.model, model.url, model.key)):
        raise ValueError('JUDGE_NOT_CONFIGURED')
    return model.final_answer_model()


def answer_span(quote, answer):
    """Formatting-only alignment; never use this to invent source support."""
    import re
    from grade_rag_round2_separated import norm
    def canonical(value):
        value=value.replace('**','').replace('`','')
        value=re.sub(r'\\(?:operatorname|mathrm|mathbb)\{([^{}]+)\}',r'\1',value)
        value=re.sub(r'\\mathbb\s+([A-Za-z])',r'\1',value)
        replacements={'pi':'π','theta':'θ','alpha':'α','beta':'β','delta':'δ','epsilon':'ε',
                      'ne':'≠','neq':'≠','le':'≤','leq':'≤','ge':'≥','geq':'≥',
                      'in':'∈','arg':'arg','pm':'±','ldots':'…','cdots':'…','left':'','right':''}
        value=re.sub(r'\\([A-Za-z]+)',lambda m:replacements.get(m[1],m[0]),value)
        value=re.sub(r'_\{([0-9]+)\}',r'\1',value)
        value=re.sub(r'_([0-9]+)',r'\1',value)
        return norm(value)
    q=canonical(quote).strip('.;:!?')
    return bool(q) and q in canonical(answer)


def assess(case, result, state, model, destination, truth):
    from grade_rag_round2_separated import PRIMARY, FAITH, CITATIONS, request as raw_request, grounded
    from dovideo.agents.citations import validate, snapshot,TRUSTED_REFUSAL
    from dovideo.agents.context import visible_evidence
    destination.mkdir(parents=True, exist_ok=True)
    def request(model,path,system,payload):
        from judge_protocol import JsonJudge,structured_request
        if isinstance(model,JsonJudge):
            kind='primary' if system==PRIMARY else ('faithfulness' if system==FAITH else 'citations')
            return structured_request(model,path,system,payload,kind)
        # The old cache hashes inputs only; include judge identity in that hash.
        system+='\n评审配置标识（仅元数据）：'+json.dumps({'model':model.model,'endpoint':model.url},sort_keys=True)
        for attempt in range(2):
            target=path if not attempt else path.with_name(path.stem+'-schema-retry.json')
            data=raw_request(model,target,system,payload)
            if not isinstance(data,dict):continue
            if system.startswith(PRIMARY):
                valid=type(data.get('answer_score')) is int and data['answer_score'] in (0,1,2)
            elif system.startswith(FAITH):
                valid=isinstance(data.get('claims'),list) and all(
                    isinstance(c,dict) and c.get('status') in ('supported','unsupported','contradicted')
                    and isinstance(c.get('claim'),str) and type(c.get('cited')) is bool
                    and type(c.get('requires_course_citation')) is bool
                    and c.get('basis') in ('direct','derivation','question','limitation')
                    for c in data['claims'])
            else:
                valid=isinstance(data.get('citations'),list) and all(
                    isinstance(c,dict) and c.get('verdict') in ('valid','invalid','unverifiable')
                    and isinstance(c.get('claim'),str) and isinstance(c.get('source_ids'),list)
                    for c in data['citations'])
            if valid:return data
        if hasattr(model,'output_tokens'):
            from judge_protocol import repair_cached
            kind='primary' if system.startswith(PRIMARY) else ('faithfulness' if system.startswith(FAITH) else 'citations')
            return repair_cached(model,path,kind)
        raise ValueError('INVALID_JUDGE_SCHEMA')
    inputs = state.get('retrieval_debug', {}).get('model_inputs', [])
    actual = inputs[-1].get('evidence', []) if inputs else []
    if not inputs:
        raise ValueError('ACTUAL_MODEL_INPUT_MISSING')
    refs = state.get('references', {})
    visible = {e['source_id']: snapshot(e,refs.get(e['source_id'])) for e in actual if e.get('source_id')}
    integrity = validate(result['answer'], refs, visible)
    trusted_abstention=state.get('answer_status')=='abstained' and result['answer']==TRUSTED_REFUSAL
    if trusted_abstention:integrity=validate(result['answer'],{}, {})
    registry = [{'source_id': sid, 'file': r.get('document_name'),
                 'pages': visible.get(sid, {}).get('pages', [])} for sid, r in refs.items()]
    primary = request(model, destination/'primary.json', PRIMARY,
        {k: case[k] for k in ('id','question', 'reference_answer', 'key_points', 'answerable')} | {'answer': result['answer']})
    faith = request(model, destination/'faithfulness.json', FAITH,
        {'question': case['question'], 'answer': result['answer'], 'actual_model_evidence': actual})
    citation = request(model, destination/'citations.json', CITATIONS,
        {'question': case['question'], 'answer': result['answer'], 'source_registry': registry,
         'source_pages_truth': truth}) if truth else None
    score = primary.get('answer_score')
    if type(score) is not int or score not in (0, 1, 2):
        raise ValueError('INVALID_PRIMARY_SCORE')
    if not isinstance(faith.get('claims'), list):
        raise ValueError('INVALID_CLAIMS')
    texts = {e['source_id']: e.get('content', '') for e in actual if e.get('source_id')}
    claims = faith['claims']
    extraction_errors=[]
    for claim in claims:
        if (claim.get('status') not in ('supported', 'unsupported', 'contradicted')
                or not isinstance(claim.get('claim'), str)
                or type(claim.get('requires_course_citation')) is not bool
                or type(claim.get('cited')) is not bool
                or claim.get('basis') not in ('direct', 'derivation', 'question', 'limitation')):
            raise ValueError('INVALID_CLAIM_SCHEMA')
        if not answer_span(claim['claim'],result['answer']):
            claim['status']='unverifiable'
            claim['validation_reason']='CLAIM_NOT_ALIGNED_TO_ANSWER'
            extraction_errors.append(claim['claim'])
            continue
        if claim['status'] == 'supported' and claim['basis'] in ('direct', 'derivation'):
            proofs = claim.get('source_quotes', [])
            if not proofs or any(not grounded(p.get('quote', ''), texts.get(p.get('source_id'), '')) for p in proofs):
                claim['status'] = 'unsupported'
                claim['validation_reason'] = 'Ungrounded quote'
    citations = citation.get('citations') if citation else None
    if citation and not isinstance(citations, list):
        raise ValueError('INVALID_CITATIONS')
    uncited_extractions=[c.get('claim','') for c in citations or [] if not c.get('source_ids')]
    # Some judges include explicitly uncited claims in their response. Preserve
    # those audit findings, but do not turn them into malformed citations.
    citations=[c for c in citations if c.get('source_ids')] if citations is not None else None
    for item in citations or []:
        if (item.get('verdict') not in ('valid', 'invalid', 'unverifiable')
                or not item.get('source_ids')):
            raise ValueError('INVALID_CITATION_SCHEMA')
        if not answer_span(item.get('claim',''),result['answer']):
            item['verdict']='unverifiable'
            item['validation_reason']='CLAIM_NOT_ALIGNED_TO_ANSWER'
        if any(s not in refs for s in item['source_ids']):
            item['verdict']='invalid'
        if item['verdict'] == 'valid':
            proofs = item.get('source_quotes', [])
            valid = proofs and all(
                any(t['file'] == p.get('file') and t['page'] == p.get('page')
                    and grounded(p.get('quote', ''), t.get('text', '')) for t in truth)
                and any(r['source_id'] in item['source_ids'] and r['file'] == p.get('file')
                        and p.get('page') in r['pages'] for r in registry) for p in proofs)
            if not valid:
                item['verdict'] = 'unverifiable'
    required = [c for c in claims if c['requires_course_citation']]
    has_citations = integrity['cited_count'] > 0
    # A judge omitting a requested citation list is missing coverage, not success.
    listed={sid for c in citations or [] for sid in c['source_ids']}
    cited={r['source_id'] for r in integrity['sources']}
    semantic_complete = not has_citations or (bool(citations) and cited.issubset(listed))
    verified = (not integrity['failed'] and not integrity['missing_citations']
                and not integrity['unverifiable'] and not integrity['page_claims_unverified'])
    known = (semantic_complete and (not has_citations or citations is not None)
             and not integrity['unverifiable'] and not integrity['page_claims_unverified']
             and not any(c['verdict']=='unverifiable' for c in citations or [])
             and not extraction_errors)
    success = (score == 2 and verified and all(c['status'] == 'supported' for c in claims)
               and all(c['cited'] for c in required)
               and all(c['verdict'] == 'valid' for c in citations or [])) if known else None
    if score<2 or integrity['failed'] or any(c['status'] in ('unsupported','contradicted') for c in claims):
        success=False
    # An answerable answer without any assessed substantive claims cannot pass.
    if case['answerable'] and score==2 and not claims:
        success = None
    return {'answer_score': score, 'answer_reason': primary.get('answer_reason'),
            'claims': claims, 'citations': citations, 'integrity': integrity,
            'task_success': success, 'judge_model': model.model,'claim_extraction_unverifiable':len(extraction_errors),
            'uncited_claims_reported_by_citation_judge':uncited_extractions,'trusted_abstention':trusted_abstention}


def build_report(cases, run_dir, output, manifest_value, model=None, truth=None, workers=3):
    def one(case):
        qid = case['id']; base = run_dir/qid
        row = {'id': qid, 'status': 'not_run', 'answer_score': None, 'task_success': None}
        if (base/'failure.json').exists() and not (base/'result.json').exists():
            row['status'] = 'run_failed'
        if (base/'result.json').exists():
            result = json.loads((base/'result.json').read_text(encoding='utf-8'))
            row.update(status='completed', elapsed_seconds=result.get('elapsed_seconds'), usage=result.get('usage', {}),
                       retrieval_call_count=result.get('retrieval_call_count'),
                       locator_hit_at_5=result.get('locator_hit_at_5'),locator_hit_at_8=result.get('locator_hit_at_8'))
            if result.get('status') != 'SUCCEEDED' or not result.get('answer', '').strip():
                row['status'] = 'run_failed'
            elif model is None:
                row['status']='ungraded'
            else:
                try:
                    if result.get('question') is not None and result['question']!=case.get('question'):
                        raise ValueError('HISTORICAL_QUESTION_MISMATCH')
                    for key in ('reference_answer','key_points'):
                        if key in result and result[key]!=case.get(key):
                            raise ValueError('HISTORICAL_RUBRIC_MISMATCH')
                    if model is not None:
                        state = json.loads((base/'checkpoint.json').read_text(encoding='utf-8'))
                        grade = assess(case, result, state, model, output/'judges'/qid, truth or [])
                        dump(output/'judges'/qid/'grade.json', grade)
                    else:
                        # Generation-only is not a scored evaluation. Never pick up
                        # a grade produced by an unrelated earlier judge phase.
                        raise ValueError('JUDGE_NOT_RUN')
                    row.update(grade)
                except Exception as exc:
                    import re
                    row.update(status='judge_error', judge_error=type(exc).__name__,
                        judge_error_code=str(exc) if re.fullmatch(r'[A-Z_]+',str(exc)) else None)
                    # A later grounding/citation schema failure must not erase a
                    # valid primary assessment. Keep the failure and unknown task
                    # outcome, but retain this independent dimension's evidence.
                    primary_path=output/'judges'/qid/'primary.json'
                    structured_primary=output/'judges'/qid/'primary-latest-structured.json'
                    if structured_primary.exists():primary_path=structured_primary
                    if primary_path.exists():
                        cached=json.loads(primary_path.read_text(encoding='utf-8'))
                        expected={k:case[k] for k in ('id','question','reference_answer','key_points','answerable')}
                        expected['answer']=result['answer']
                        value=cached.get('result',{});score=value.get('answer_score')
                        if (cached.get('payload')==expected and cached.get('judge_model')==model.model
                                and type(score) is int and score in (0,1,2)):
                            row.update(answer_score=score,answer_reason=value.get('answer_reason'),
                                       primary_preserved_after_partial_judge_failure=True)
        print('EVAL_CASE '+qid+' '+row['status'],flush=True)
        return row
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1,min(4,workers))) as pool:
        rows=list(pool.map(one,cases))
    counts = {k: sum(r['status'] == k for r in rows) for k in ('completed', 'run_failed', 'not_run', 'judge_error','ungraded')}
    assessed = [r for r in rows if r.get('answer_score') is not None]
    known = [r for r in rows if r['task_success'] is not None]
    success = sum(r['task_success'] is True for r in rows)
    claims=[c for r in rows for c in r.get('claims',[])]
    citations=[c for r in rows for c in r.get('citations') or []]
    ratio=lambda a,b:a/b if b else None
    integrity=[r['integrity'] for r in rows if r.get('integrity')]
    report = {'manifest': manifest_value, 'generated_at': datetime.now(timezone.utc).isoformat(),
              'expected': len(cases), **counts, 'assessed': len(assessed),
              'completed_runs':sum(r['status'] in ('completed','judge_error','ungraded') for r in rows),
              'task_success_count': success, 'verified_task_success_rate': success/len(cases),
              'task_assessment_coverage': len(known)/len(cases),
              'task_success_among_assessed': success/len(known) if known else None,
              'answer_complete_count': sum(r.get('answer_score') == 2 for r in rows),
              'claim_support_rate':ratio(sum(c['status']=='supported' for c in claims),len(claims)),
              'citation_validated_rate':ratio(sum(c['verdict']=='valid' for c in citations),len(citations)),
              'citation_unverifiable':sum(c['verdict']=='unverifiable' for c in citations),
              'integrity_failed_cases':sum(v['failed'] for v in integrity),
              'integrity_unverifiable_sources':sum(v['unverifiable'] for v in integrity),
              'prompt_tokens_known':sum(r.get('usage',{}).get('prompt_tokens',0) for r in rows),
              'completion_tokens_known':sum(r.get('usage',{}).get('completion_tokens',0) for r in rows),
              'generation_usage_missing_cases':sum(not r.get('usage') for r in rows if r['status'] in ('completed','judge_error')),
              'boundary_count':sum(not c.get('answerable',True) for c in cases),
              'per_case': rows}
    dump(output/'report.json', report)
    return report


def compare(current, baseline):
    a, b = current['manifest'], baseline['manifest']
    if (a['dataset_sha256'] != b['dataset_sha256'] or a['protocol'] != b['protocol']
            or a.get('judge_fingerprint') != b.get('judge_fingerprint')
            or a.get('truth_sha256') != b.get('truth_sha256')):
        raise ValueError('INCOMPATIBLE_BASELINE')
    old = {r['id']: r for r in baseline['per_case']}
    changes = []
    for row in current['per_case']:
        previous = old[row['id']]
        changes.append({'id': row['id'], 'before_status': previous['status'], 'after_status': row['status'],
                        'before_score': previous.get('answer_score'), 'after_score': row.get('answer_score'),
                        'before_success': previous.get('task_success'), 'after_success': row.get('task_success')})
    regressed = any((r['before_score'] is not None and r['after_score'] is not None and r['after_score'] < r['before_score'])
                    or (r['before_success'] is True and r['after_success'] is False) for r in changes)
    return {'regressed': regressed, 'per_case': changes}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--course-id')
    p.add_argument('--dataset', type=Path, default=ROOT/'rag_eval_materials/RAG评测集_40题.jsonl')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--run-dir', type=Path, help='Historical result/checkpoint directory; no new generation')
    p.add_argument('--source-truth', type=Path, help='JSON array: file, page (1-based), text; reviewed source only')
    p.add_argument('--phase', choices=('full', 'preflight', 'run', 'judge', 'compare'), default='full')
    p.add_argument('--workers',type=int,choices=range(1,5),default=3,help='Bounded judge concurrency; generation stays sequential')
    args = p.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase=='compare' and not args.baseline:
            raise ValueError('BASELINE_REQUIRED')
        from dovideo.config import load_local_environment
        load_local_environment()
        cases = [json.loads(line) for line in args.dataset.read_text(encoding='utf-8').splitlines() if line.strip()]
        ids = [c['id'] for c in cases]
        if not cases or len(ids) != len(set(ids)) or any(not __import__('re').fullmatch(r'Q\d+', i) for i in ids):
            raise ValueError('INVALID_DATASET_IDS')
        for case in cases:
            if type(case['answerable']) is not bool or not case['question'] or not isinstance(case['key_points'], list):
                raise ValueError('INVALID_DATASET_CASE')
        if args.phase in ('full','judge'):
            # Validate paid-phase dependencies before any generation requests.
            prepared_model=judge_model()
            if not args.source_truth:
                raise ValueError('SOURCE_TRUTH_REQUIRED')
            prepared_truth=json.loads(args.source_truth.read_text(encoding='utf-8'))
            if not isinstance(prepared_truth,list) or any(
                not isinstance(t.get('file'),str) or type(t.get('page')) is not int
                or t['page']<1 or not isinstance(t.get('text'),str) for t in prepared_truth):
                raise ValueError('INVALID_SOURCE_TRUTH')
        if args.phase == 'compare':
            report = json.loads((args.output/'report.json').read_text(encoding='utf-8'))
        else:
            m = manifest(args.dataset, args.course_id)
            if args.phase=='judge' and not args.run_dir:
                original=json.loads((args.output/'generation-manifest.json').read_text(encoding='utf-8'))
                if original['dataset_sha256']!=m['dataset_sha256']:
                    raise ValueError('DATASET_FINGERPRINT_MISMATCH')
                m={**original,'evaluation_code':m['code']}
            if args.phase in ('full', 'run', 'preflight'):
                if not args.course_id or args.run_dir:
                    raise ValueError('LIVE_RUN_REQUIRES_COURSE_AND_NO_RUN_DIR')
                dump(args.output/'attempt-manifest.json',m)
                m['indexes'] = preflight(args.course_id, cases)
            run_dir = args.run_dir or args.output/'runs'
            if args.run_dir:
                # Preserve historical metadata and its hash; never label the current
                # judge code as the code that generated archived answers.
                m['historical_generation'] = True
                meta = args.run_dir/'metadata.json'
                m['historical_metadata_sha256'] = digest(meta) if meta.exists() else None
            if args.phase in ('full', 'run'):
                target = args.output/'generation-manifest.json'
                if target.exists() and json.loads(target.read_text(encoding='utf-8')) != m:
                    raise ValueError('CACHE_FINGERPRINT_MISMATCH')
                dump(target, m)
                from evaluate_course_rag import main as run
                run(['--course-id', args.course_id, '--dataset', str(args.dataset), '--output', str(run_dir)])
            if args.phase == 'preflight':
                dump(args.output/'preflight.json', {'status': 'ready', 'manifest': m})
                return 0
            model = prepared_model if args.phase in ('full', 'judge') else None
            truth = json.loads(args.source_truth.read_text(encoding='utf-8')) if args.source_truth else []
            m['truth_sha256'] = digest(args.source_truth) if args.source_truth else None
            from grade_rag_round2_separated import PRIMARY,FAITH,CITATIONS
            m['judge_fingerprint'] = hashlib.sha256(json.dumps({
                'model': model.model if model else None, 'url': model.url if model else None,
                'prompts':[PRIMARY,FAITH,CITATIONS],
                'output_tokens':getattr(model,'output_tokens',os.getenv('DOVIDEO_CHAT_OUTPUT_TOKENS','2048')),
                'thinking':os.getenv('DOVIDEO_CHAT_FINAL_THINKING','disabled'),
                'scoring_code':digest(Path(__file__)),
                'judge_adapter_code':digest(ROOT/'tools/grade_rag_round2_separated.py'),
                'structured_judge_code':digest(ROOT/'tools/judge_protocol.py'),
                'protocol': 'structured-separated-grounded-v3'}, sort_keys=True).encode()).hexdigest()
            m['same_model_self_judgment'] = bool(model and model.model == os.getenv('DOVIDEO_CHAT_MODEL'))
            report = build_report(cases, run_dir, args.output, m, model, truth,args.workers)
        incomplete = report['not_run'] or report['judge_error'] or report['task_assessment_coverage'] < 1
        status=2 if report['run_failed'] else (1 if report.get('integrity_failed_cases') else (3 if incomplete else 0))
        if args.baseline:
            old = json.loads((args.baseline/'report.json').read_text(encoding='utf-8'))
            delta = compare(report, old)
            dump(args.output/'comparison.json', delta)
            text = ['# Agent regression', '', f"Expected: {report['expected']}; run failures: {report['run_failed']}; judge failures: {report['judge_error']}; not run: {report['not_run']}", '',
                    '| Case | Before score | After score | Before success | After success |', '|---|---|---|---|---|']
            text += [f"| {r['id']} | {r['before_score']} | {r['after_score']} | {r['before_success']} | {r['after_success']} |" for r in delta['per_case']]
            (args.output/'comparison.md').write_text('\n'.join(text), encoding='utf-8')
            if status:return status
            if old.get('task_assessment_coverage', 0) < 1:return 3
            return 1 if delta['regressed'] else 0
        return status
    except Exception as exc:
        # Deliberately omit raw exception messages: provider/DB errors may contain credentials.
        import re
        safe_code=getattr(exc,'code',None) or (str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',str(exc)) else None)
        dump(args.output/'execution-error.json', {'status': 'preflight_failed' if args.phase == 'preflight' else 'execution_failed',
             'saved_result_count':len(list((args.output/'runs').glob('Q*/result.json'))), 'error_type': type(exc).__name__,
             'error_code': safe_code})
        print('EVALUATION_FAILED '+type(exc).__name__, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

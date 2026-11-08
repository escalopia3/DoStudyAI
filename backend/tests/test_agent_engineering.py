import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from dovideo.agents.checkpoints import restore
from dovideo.agents.citations import snapshot, validate
from dovideo.agents.loop import make_loop
from dovideo.agents.provider import ChatModel
from dovideo.agents.reliability import AgentFailure, execution_scope, invoke

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from run_agent_regression import build_report, compare, assess,answer_span


def model():
    value=object.__new__(ChatModel)
    value.model,value.url,value.key='fixture','https://example.invalid','secret'
    return value


def evidence():
    return {'source_id':'S1','content':'原始定义','resource_id':'r','index_version_id':'i',
            'chunk_id':'c','locators':[{'pageIndex':4}],'pages':[5]}


def error(status, **headers):
    request=httpx.Request('POST','https://example.invalid')
    return httpx.HTTPStatusError('private provider body',request=request,
        response=httpx.Response(status,headers=headers,request=request))


@pytest.mark.parametrize('status,code,retries',[(401,'MODEL_AUTH_ERROR',1),
    (404,'MODEL_NOT_FOUND',1),(422,'MODEL_REQUEST_REJECTED',1),(503,'MODEL_UNAVAILABLE',3)])
def test_provider_classification_and_bounded_attempts(status,code,retries):
    # A fake monotonic clock makes backoff deterministic without sleeping.
    clock=[0.]
    def sleep(seconds):clock[0]+=seconds
    with patch('dovideo.agents.reliability.time.monotonic',side_effect=lambda:clock[0]), \
         patch('dovideo.agents.reliability.time.sleep',side_effect=sleep), \
         patch.object(ChatModel,'_request',side_effect=error(status)) as call:
        with pytest.raises(AgentFailure,match=code):model()([],[])
    assert call.call_count==retries


def test_rate_limit_recovers_and_honors_retry_after():
    clock=[0.]
    def sleep(seconds):clock[0]+=seconds
    with patch('dovideo.agents.reliability.time.monotonic',side_effect=lambda:clock[0]), \
         patch('dovideo.agents.reliability.time.sleep',side_effect=sleep), \
         patch.object(ChatModel,'_request',side_effect=[error(429,**{'Retry-After':'2'}),({'content':'ok'},{})]) as call:
        assert model()([],[])[0]['content']=='ok'
    assert clock[0]>=2 and call.call_count==2


def test_retry_after_exceeding_deadline_does_not_retry_early():
    with patch.object(ChatModel,'_request',side_effect=error(429,**{'Retry-After':'1000'})) as call:
        with pytest.raises(AgentFailure,match='MODEL_DEADLINE_EXCEEDED'):model()([],[])
    assert call.call_count==1


def test_cancellation_is_not_wrapped_as_provider_failure():
    def cancelled():raise RuntimeError('RUN_CANCELLED_OR_LEASE_LOST')
    with execution_scope(check=cancelled):
        with pytest.raises(RuntimeError,match='RUN_CANCELLED_OR_LEASE_LOST'):
            invoke(lambda _:None)


def test_partial_stream_is_not_retried_or_duplicated():
    def request(messages,tools,output,check,remaining):
        output('部分回答')
        raise httpx.ReadTimeout('private')
    seen=[]
    with patch.object(ChatModel,'_stream_request',side_effect=request) as call:
        with pytest.raises(AgentFailure,match='PARTIAL_STREAM'):
            model().stream([],[],seen.append,lambda:None)
    assert call.call_count==1 and seen==['部分回答']


def test_missing_done_is_failure_not_success():
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,
        text='data: '+json.dumps({'choices':[{'delta':{'content':'片段'}}]})+'\n\n')))
    with patch('dovideo.agents.provider.httpx.Client',return_value=client):
        with pytest.raises(AgentFailure,match='PARTIAL_STREAM'):
            model().stream([],[],lambda _:None,lambda:None)


def test_mixed_good_and_orphan_citation_is_rejected():
    ref=evidence()
    validation=validate('解释 [S1] [S99]',{'S1':ref},{'S1':snapshot(ref)})
    assert validation['failed']
    assert validation['sources'][1]['reasons']==['UNKNOWN_SOURCE']


def test_visibility_version_and_page_checks():
    ref=evidence(); visible=snapshot(ref)
    assert validate('[S1]',{'S1':ref},{})['failed']
    assert validate('[S1]',{'S1':ref},{'S1':{**visible,'index_version_id':'other'}})['failed']
    assert validate('[S1]第6页',{'S1':ref},{'S1':visible})['failed']
    assert not validate('[S1]第5页',{'S1':ref},{'S1':visible})['failed']
    assert validate('课件第5页 [S1]',{'S1':ref},{'S1':visible})['page_claims_unverified']


def test_legacy_metadata_is_unverifiable_not_success():
    ref={'content':'原文','pages':[1]}
    value=validate('[S1]',{'S1':ref},{'S1':snapshot(ref)})
    assert not value['failed'] and value['unverifiable']==1


def test_citation_retry_shared_and_bounded():
    calls=[]
    def bad(messages,tools):
        calls.append(1)
        return {'role':'assistant','content':'原文 [S1] [S99]'},{}
    with pytest.raises(AgentFailure,match='CITATION_VALIDATION_FAILED'):
        make_loop(bad,{}).invoke({'messages':[{'role':'user','content':'问题'}],
            'references':{'S1':evidence()},'detail_rounds':3})
    assert len(calls)==2


def test_checkpoint_future_corrupt_and_changed_config_rejected():
    assert restore({},'fingerprint')=={}
    base={'schema_version':1,'config_fingerprint':'a','messages':[],'calls':2,'phase':'model'}
    assert restore(base,'a')['calls']==2
    for state in ({**base,'schema_version':2},{**base,'messages':'broken'},
                  {**base,'calls':-1}, {**base,'config_fingerprint':'b'}):
        with pytest.raises(AgentFailure,match='CHECKPOINT_INCOMPATIBLE'):restore(state,'a')


def test_unversioned_checkpoint_requires_explicit_opt_in(monkeypatch):
    state={'messages':[],'phase':'model'}
    monkeypatch.delenv('DOVIDEO_ALLOW_LEGACY_CHECKPOINT',raising=False)
    with pytest.raises(AgentFailure):restore(state,'a')
    monkeypatch.setenv('DOVIDEO_ALLOW_LEGACY_CHECKPOINT','1')
    assert restore(state,'a')['schema_version']==1


def test_report_keeps_run_and_judge_failures_and_not_run_in_denominator(tmp_path):
    cases=[{'id':'Q01'},{'id':'Q02'},{'id':'Q03'}]
    run=tmp_path/'runs';(run/'Q01').mkdir(parents=True);(run/'Q02').mkdir()
    (run/'Q01/failure.json').write_text('{}')
    (run/'Q02/result.json').write_text(json.dumps({'status':'SUCCEEDED','answer':'answer'}))
    result=build_report(cases,run,tmp_path,{'protocol':'fixture'})
    assert result['run_failed']==1 and result['ungraded']==1 and result['judge_error']==0 and result['not_run']==1
    assert result['expected']==3 and result['verified_task_success_rate']==0


def test_comparison_catches_per_case_regression_and_refuses_rubric_drift():
    m={'dataset_sha256':'a','protocol':'p','judge_fingerprint':'j','truth_sha256':'s'}
    base={'manifest':m,'per_case':[{'id':'Q01','status':'completed','answer_score':2,'task_success':True}]}
    current={'manifest':m,'per_case':[{'id':'Q01','status':'completed','answer_score':1,'task_success':False}]}
    assert compare(current,base)['regressed']
    with pytest.raises(ValueError,match='INCOMPATIBLE_BASELINE'):
        compare({**current,'manifest':{**m,'judge_fingerprint':'different'}},base)


def test_tool_batch_and_round_budget_are_bounded():
    state={'messages':[{'role':'assistant','tool_calls':[{}]*9}],'phase':'tools'}
    with pytest.raises(ValueError,match='TOOL_BATCH_LIMIT'):make_loop(lambda *_:None,{}).invoke(state)
    result=make_loop(lambda *_:pytest.fail('model must not be called'),{}).invoke({'calls':12,'messages':[]})
    assert '预算' in result['answer']


def test_judge_separation_and_fabricated_proof_cannot_pass(tmp_path):
    ref=evidence();ref['document_name']='course.pptx'
    case={'id':'Q01','question':'定义是什么','reference_answer':'原始定义','key_points':['原始定义'],'answerable':True}
    result={'answer':'原始定义 [S1]'}
    state={'references':{'S1':ref},'retrieval_debug':{'model_inputs':[{'evidence':[ref]}]}}
    def judge(m,path,system,payload):
        if path.name.startswith('primary'):
            return {'answer_score':2,'answer_reason':'complete'}
        if path.name.startswith('faithfulness'):
            assert 'reference_answer' not in payload and 'source_pages_truth' not in payload
            return {'claims':[{'claim':'原始定义','status':'supported','basis':'direct',
                'source_quotes':[{'source_id':'S1','quote':'不存在的证明'}],
                'requires_course_citation':True,'cited':True}]}
        return {'citations':[{'claim':'原始定义','source_ids':['S1'],'verdict':'valid',
            'source_quotes':[{'file':'course.pptx','page':5,'quote':'原始定义'}]}]}
    with patch('grade_rag_round2_separated.request',side_effect=judge):
        grade=assess(case,result,state,model(),tmp_path,[{'file':'course.pptx','page':5,'text':'原始定义'}])
    assert grade['answer_score']==2
    assert grade['claims'][0]['status']=='unsupported' and grade['task_success'] is False


def test_judge_invalid_schema_retried_once_then_recordable_failure(tmp_path):
    case={'id':'Q01','question':'定义是什么','reference_answer':'定义','key_points':['定义'],'answerable':True}
    state={'references':{},'retrieval_debug':{'model_inputs':[{'evidence':[]}]}}
    with patch('grade_rag_round2_separated.request',return_value={'answer_score':True}) as call:
        with pytest.raises(ValueError,match='INVALID_JUDGE_SCHEMA'):
            assess(case,{'answer':'定义'},state,model(),tmp_path,[])
    assert call.call_count==2


def test_private_attempts_keep_call_and_request_correlation():
    observed=[]
    with execution_scope(run_id='r',request_id='request',call_id=4,
                         observe=lambda kind,data:observed.append((kind,data))):
        assert invoke(lambda _:({'content':'ok'},{'total_tokens':3}),model_id='fixture')[0]['content']=='ok'
    assert observed[0][1]['call_id']==4 and observed[0][1]['request_id']=='request'
    assert observed[0][1]['model']=='fixture' and observed[0][1]['usage']['total_tokens']==3


def test_answer_alignment_normalizes_formatting_without_changing_math_relations():
    assert answer_span('D 是开集，即 D 内每一点都是内点','**D 是开集**，即 D 内每一点都是内点。')
    assert answer_span('z≠0，-π<θ0≤π',r'$z\ne0$，$-\pi<\theta_0\le\pi$')
    assert not answer_span('z=0，-π≤θ0<π',r'$z\ne0$，$-\pi<\theta_0\le\pi$')


def test_uncited_judge_findings_do_not_erase_valid_primary_score(tmp_path):
    ref=evidence();ref['document_name']='course.pptx'
    case={'id':'Q01','question':'定义是什么','reference_answer':'原始定义','key_points':['原始定义'],'answerable':True}
    def judge(m,path,system,payload):
        if path.name.startswith('primary'):return {'answer_score':2,'answer_reason':'complete'}
        if path.name.startswith('faithfulness'):
            return {'claims':[{'claim':'原始定义','status':'supported','basis':'direct',
                'source_quotes':[{'source_id':'S1','quote':'原始定义'}],
                'requires_course_citation':True,'cited':True}]}
        return {'citations':[{'claim':'原始定义','source_ids':['S1'],'verdict':'valid',
            'source_quotes':[{'file':'course.pptx','page':5,'quote':'原始定义'}]},
            {'claim':'额外未引用主张','source_ids':[],'verdict':'unverifiable'}]}
    state={'references':{'S1':ref},'retrieval_debug':{'model_inputs':[{'evidence':[ref]}]}}
    with patch('grade_rag_round2_separated.request',side_effect=judge):
        result=assess(case,{'answer':'原始定义 [S1]'},state,model(),tmp_path,[{'file':'course.pptx','page':5,'text':'原始定义'}])
    assert result['answer_score']==2 and len(result['citations'])==1
    assert result['uncited_claims_reported_by_citation_judge']==['额外未引用主张']


def test_partial_judge_error_preserves_primary_and_unknown_task(tmp_path):
    case={'id':'Q01','question':'问题','reference_answer':'答案','key_points':['答案'],'answerable':True}
    base=tmp_path/'runs/Q01';base.mkdir(parents=True)
    result={'status':'SUCCEEDED','answer':'答案','question':'问题','reference_answer':'答案','key_points':['答案']}
    (base/'result.json').write_text(json.dumps(result),encoding='utf-8')
    (base/'checkpoint.json').write_text('{}',encoding='utf-8')
    target=tmp_path/'judges/Q01';target.mkdir(parents=True)
    (target/'primary.json').write_text(json.dumps({'payload':{**case,'answer':'答案'},
        'judge_model':'fixture','result':{'answer_score':2,'answer_reason':'complete'}}),encoding='utf-8')
    with patch('run_agent_regression.assess',side_effect=ValueError('INVALID_JUDGE_SCHEMA')):
        report=build_report([case],tmp_path/'runs',tmp_path,{},model=model())
    assert report['answer_complete_count']==1 and report['judge_error']==1
    assert report['per_case'][0]['task_success'] is None

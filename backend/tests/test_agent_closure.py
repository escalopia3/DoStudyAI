import json
import logging
import sys
from pathlib import Path
from unittest.mock import Mock,patch
import httpx
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from judge_protocol import JsonJudge,repair_cached,valid
from dovideo.agents.observability import persist_health
from adjudicate_agent_report import apply,sha
from judge_protocol import structured_request
from dovideo.agents.citations import validate,unsupported_scope_claims


def test_explicit_repair_gives_feedback_and_is_bounded(tmp_path):
    path=tmp_path/'faithfulness.json'
    path.write_text(json.dumps({'system':'JSON only','payload':{'question':'q'},'result':{'claims':[{'status':'question'}]}}))
    result={'claims':[{'claim':'q','status':'supported','basis':'question','cited':False,'requires_course_citation':False}]}
    model=Mock(return_value=({'content':json.dumps(result)},{'total_tokens':5}));model.model='fixture'
    assert repair_cached(model,path,'faithfulness')==result
    assert model.call_count==1
    messages=model.call_args.args[0]
    assert 'question和derivation不是status' in messages[0]['content']
    repair_cached(model,path,'faithfulness')
    assert model.call_count==1
    assert json.loads(path.read_text())['result']['claims'][0]['status']=='question'


def test_invalid_explicit_repair_is_not_normalized_to_pass(tmp_path):
    path=tmp_path/'citations.json'
    path.write_text(json.dumps({'system':'JSON','payload':{},'result':{'citations':[{'verdict':'maybe'}]}}))
    model=Mock(return_value=({'content':'{"citations":[{"verdict":"still_maybe"}]}'},{}));model.model='fixture'
    with pytest.raises(ValueError,match='INVALID_JUDGE_SCHEMA'):repair_cached(model,path,'citations')
    with pytest.raises(ValueError,match='INVALID_JUDGE_SCHEMA'):repair_cached(model,path,'citations')
    assert model.call_count==1


def test_json_transport_sends_explicit_json_mode_without_tools():
    captured=[]
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"answer_score":2}'}}],'usage':{}})
    client=httpx.Client(transport=httpx.MockTransport(handle))
    model=object.__new__(JsonJudge);model.model='fixture';model.url='https://example.invalid';model.key='secret';model.output_tokens=8192
    with patch('judge_protocol.httpx.Client',return_value=client):model._request([{'role':'user','content':'JSON'}],[],10)
    assert captured[0]['response_format']=={'type':'json_object'}
    assert captured[0]['temperature']==0 and 'tools' not in captured[0]


def test_health_persists_metrics_and_only_alert_transitions(tmp_path,monkeypatch):
    monkeypatch.setenv('DOVIDEO_OBSERVABILITY_DIR',str(tmp_path))
    base={'kind':'agent.health','states':{'FAILED':3},'oldest_queued_seconds':150,'alerts':['QUEUE_AGE_EXCEEDED']}
    persist_health(base);persist_health(base)
    assert len((tmp_path/'alerts.jsonl').read_text().splitlines())==1
    persist_health({**base,'alerts':[]})
    assert len((tmp_path/'alerts.jsonl').read_text().splitlines())==2
    assert 'dovideo_agent_runs_failed 3' in (tmp_path/'metrics.prom').read_text()
    assert json.loads((tmp_path/'health.json').read_text())['alerts']==[]


def test_supplementary_negative_coverage_is_versioned():
    root=Path(__file__).resolve().parents[2]/'datasets/agent'
    cases=[json.loads(l) for l in (root/'golden-46.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(cases)==46 and sum(not c['answerable'] for c in cases)==10
    assert len({c['id'] for c in cases})==46


def test_ai_review_is_input_bound_and_cannot_bypass_integrity(tmp_path):
    folder=tmp_path/'Q01';folder.mkdir()
    (folder/'result.json').write_text(json.dumps({'answer':'actual answer'}))
    (folder/'checkpoint.json').write_text(json.dumps({'retrieval_debug':{'model_inputs':[{'evidence':[
        {'source_id':'S1','document_name':'file','content':'actual evidence'}]}]}}))
    report={'manifest':{'dataset_sha256':'dataset'},'judge_error':0,'task_assessment_coverage':0,
        'per_case':[{'id':'Q01','status':'completed','answer_score':2,'task_success':None,'integrity':{'failed':False}}]}
    item={'task_success':True,'reason':'independent evidence review','all_unresolved_items_reviewed':True,
        'result_sha256':sha(folder/'result.json'),'checkpoint_sha256':sha(folder/'checkpoint.json'),
        'answer_quotes':['actual answer'],'evidence':[{'source_id':'S1','file':'file','quote':'actual evidence'}]}
    reviews={'method':'codex-independent-ai-v1','human_gold':False,'dataset_sha256':'dataset','arms':{'arm':{'Q01':item}}}
    assert apply(report,tmp_path,reviews,'arm',[])['task_assessment_coverage']==1
    report['per_case'][0]['integrity']['failed']=True
    with pytest.raises(ValueError,match='BYPASS_DETERMINISTIC'):apply(report,tmp_path,reviews,'arm',[])
    report['per_case'][0]['integrity']['failed']=False
    (folder/'result.json').write_text(json.dumps({'answer':'different answer'}))
    with pytest.raises(ValueError,match='STALE_REVIEW_INPUT'):apply(report,tmp_path,reviews,'arm',[])


def test_placeholder_sources_and_absolute_absence_are_not_silent_passes():
    assert validate('内容 [S?，见目录]',{}, {})['failed']
    assert validate('内容 [Sx]',{}, {})['malformed_markers']
    assert unsupported_scope_claims('课件本身是数学课件，并不包含考试安排。')
    assert unsupported_scope_claims('三份已解析课件的内容都是数学知识，没有课程安排。')
    assert not unsupported_scope_claims('不能据此断言三份课件全文中一定没有该信息。')
    assert not unsupported_scope_claims('本轮已返回的证据未找到考试信息。')
    assert not unsupported_scope_claims('三份课件的本轮已返回内容中没有考试信息。')
    assert unsupported_scope_claims('课件中没有固定上课教室信息。')
    assert unsupported_scope_claims('课件中未提供补考日期。')
    assert not unsupported_scope_claims('本轮已返回的课件中没有找到考试信息。')
    assert unsupported_scope_claims('结论：无法给出准确日期：三份课件中未提供补考安排。')


def test_fresh_structured_protocol_repairs_once_and_pins_parameters(tmp_path):
    good={'citations':[{'claim':'text','source_ids':['S1'],'verdict':'unverifiable'}]}
    model=Mock(side_effect=[({'content':'{"citations":[{"verdict":"made_up"}]}'},{}),({'content':json.dumps(good)},{})])
    model.model='fixture';model.url='https://example.invalid';model.output_tokens=8192
    assert structured_request(model,tmp_path/'citations.json','JSON',{},'citations')==good
    assert model.call_count==2 and '自造标签' in model.call_args.args[0][-1]['content']
    structured_request(model,tmp_path/'citations.json','JSON',{},'citations')
    assert model.call_count==2


def test_repeated_scope_overclaim_becomes_explicit_safe_abstention():
    from dovideo.agents.loop import make_loop
    from dovideo.agents.citations import TRUSTED_REFUSAL
    model=Mock(return_value=({'role':'assistant','content':'课件中没有考试安排。'},{}))
    state=make_loop(model,{}).invoke({'messages':[{'role':'user','content':'考试安排？'}]})
    assert model.call_count==2 and state['answer']==TRUSTED_REFUSAL
    assert state['answer_status']=='abstained' and state['rejected_answer']=='课件中没有考试安排。'
    assert state['scope_validation']['fallback']


def test_boundary_guard_requires_visible_source_definition():
    from dovideo.agents.citations import definition_conflicts,snapshot
    text='边界点可以用去心或含心邻域判断。'
    assert not definition_conflicts(text,{})
    evidence=snapshot({'content':'边界点的任意邻域既含属于集合的点又含不属于集合的点。'})
    assert definition_conflicts(text,{'S1':evidence})
    assert not definition_conflicts('边界点需要考察任意邻域。',{'S1':evidence})


def test_source_inventory_does_not_confuse_chunks_with_documents():
    from dovideo.agents.citations import inventory_conflicts
    view={'S1':{'document_name':'one.pptx'},'S2':{'document_name':'one.pptx'}}
    assert inventory_conflicts('另两份课件返回的内容为其他知识。',view)
    assert not inventory_conflicts('另两份课件是否包含该知识，本轮尚不能核实。',view)

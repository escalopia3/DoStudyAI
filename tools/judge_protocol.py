"""Evaluation-only JSON judge transport and bounded, explicit schema repair."""
import hashlib
import json
from pathlib import Path
import httpx
from dovideo.agents.provider import ChatModel


class JsonJudge(ChatModel):
    def _request(self,messages,tools,remaining):
        if tools:raise ValueError('JUDGE_TOOLS_FORBIDDEN')
        payload={'model':self.model,'messages':messages,'max_tokens':int(getattr(self,'output_tokens',8192)),
                 'temperature':0,'response_format':{'type':'json_object'}}
        payload.update(self.thinking_options())
        with httpx.Client(timeout=httpx.Timeout(min(90,remaining),connect=min(10,remaining)),trust_env=False) as client:
            response=client.post(self.url+'/chat/completions',headers={'Authorization':'Bearer '+self.key},json=payload)
            response.raise_for_status();data=response.json()
        return data['choices'][0]['message'],data.get('usage',{})


def structured_request(model,path,system,payload,kind):
    """Two total semantic attempts, including JSON/schema failures, with pinned cache."""
    config={'protocol':'structured-judge-v3','model':model.model,'endpoint':model.url,
            'temperature':0,'response_format':'json_object','max_tokens':model.output_tokens}
    key=hashlib.sha256(json.dumps({'system':system,'payload':payload,'config':config},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    target=path.with_name(path.stem+'-structured-v3-'+key[:12]+'.json')
    legacy=path.with_name(path.stem+'-structured-v3.json')
    existing=target if target.exists() else legacy
    if existing.exists():
        cached=json.loads(existing.read_text(encoding='utf-8'))
        if cached.get('input_sha256')==key:
            if not target.exists():target.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding='utf-8')
            path.with_name(path.stem+'-latest-structured.json').write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding='utf-8')
            if not valid(kind,cached.get('result')):raise ValueError('INVALID_JUDGE_SCHEMA')
            return cached['result']
    messages=[{'role':'system','content':system+'\n只输出JSON，严格使用示例字段及允许枚举。'},
              {'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    attempts=[];result=None
    rules={'primary':'answer_score须为整数0、1或2，不是布尔值。',
           'faithfulness':'status只能为supported/unsupported/contradicted；basis只能为direct/derivation/question/limitation。question和derivation不是status。cited和requires_course_citation必须为布尔值。',
           'citations':'verdict只能为valid/invalid/unverifiable，不能输出任何自造标签；source_ids必须为列表。'}[kind]
    for attempt in range(2):
        reply,usage=model(messages,[])
        raw=reply.get('content') or ''
        try:result=json.loads(raw)
        except (ValueError,TypeError):result=None
        attempts.append({'reply':raw,'usage':usage,'valid':valid(kind,result)})
        if valid(kind,result):break
        messages.append({'role':'assistant','content':raw or '{}'})
        messages.append({'role':'user','content':'上次输出未通过结构校验：'+rules+'\n请重新依据原始输入完整评审。保持同一量表，不以提高分数为目标，只修正结构与非法标签。'})
    value={'input_sha256':key,'system':system,'payload':payload,'config':config,
           'result':result,'judge_model':model.model,'attempts':attempts,'valid':valid(kind,result)}
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    path.with_name(path.stem+'-latest-structured.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    if not value['valid']:raise ValueError('INVALID_JUDGE_SCHEMA')
    return result


def valid(kind,data):
    if not isinstance(data,dict):return False
    if kind=='primary':return type(data.get('answer_score')) is int and data['answer_score'] in (0,1,2)
    if kind=='faithfulness':
        return isinstance(data.get('claims'),list) and all(isinstance(c,dict)
            and c.get('status') in ('supported','unsupported','contradicted')
            and c.get('basis') in ('direct','derivation','question','limitation')
            and isinstance(c.get('claim'),str) and type(c.get('cited')) is bool
            and type(c.get('requires_course_citation')) is bool for c in data['claims'])
    if kind=='citations':
        return isinstance(data.get('citations'),list) and all(isinstance(c,dict)
            and c.get('verdict') in ('valid','invalid','unverifiable')
            and isinstance(c.get('claim'),str) and isinstance(c.get('source_ids'),list) for c in data['citations'])
    raise ValueError('UNKNOWN_JUDGE_KIND')


def repair_cached(model,path,kind):
    """Repair a failed stage once under a new explicit protocol; never silently map labels."""
    original=json.loads(path.read_text(encoding='utf-8'))
    if valid(kind,original.get('result')):return original['result']
    rules={'faithfulness':'status只能是supported/unsupported/contradicted；basis只能是direct/derivation/question/limitation。question和derivation不是status。',
           'citations':'verdict只能是valid/invalid/unverifiable。任何混合标签都非法；有问题的引用判invalid，证据不足判unverifiable。',
           'primary':'answer_score只能是0/1/2整数，不能用布尔值。'}[kind]
    payload={'original_task':original['payload'],'invalid_response':original.get('result'),
             'schema_error':rules,'instruction':'重新依据原始材料完整评审，保持原量表，不以提高分数为目标。只返回合法JSON。'}
    system=original['system']+'\n结构修复协议v2：'+rules
    key=hashlib.sha256(json.dumps({'system':system,'payload':payload,'model':model.model},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    target=path.with_name(path.stem+'-explicit-repair-v2.json')
    if target.exists():
        cached=json.loads(target.read_text(encoding='utf-8'))
        if cached.get('input_sha256')==key:
            if not valid(kind,cached.get('result')):raise ValueError('INVALID_JUDGE_SCHEMA')
            return cached['result']
    reply,usage=model([{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],[])
    try:result=json.loads(reply.get('content') or '')
    except (TypeError,ValueError):result=None
    value={'input_sha256':key,'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
           'system':system,'payload':payload,'result':result,'usage':usage,'judge_model':model.model,
           'protocol':'explicit-schema-repair-v2','valid':valid(kind,result)}
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    if not value['valid']:raise ValueError('INVALID_JUDGE_SCHEMA')
    return result

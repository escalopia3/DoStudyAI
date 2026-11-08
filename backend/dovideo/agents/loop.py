import json
import re
import time
from dovideo.agents.citations import validate as validate_citations,unsupported_scope_claims,TRUSTED_REFUSAL,definition_conflicts,inventory_conflicts
from dovideo.agents.reliability import AgentFailure, notify, runtime
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from dovideo.agents.prompt import SYSTEM
from dovideo.tools.registry import SPECS,BASE,execute
from dovideo.agents.context import build, visible_evidence
from dovideo.agents.retrieval_debug import record_model_input, tracing_enabled
class State(TypedDict,total=False):
    messages:list
    history:list
    context_budget:dict
    loaded:list
    calls:int
    phase:str
    answer:str
    usage:dict
    references:dict
    citation_evidence:dict
    retrieval_debug:dict
    detail_rounds:int
    tool_intent_retry:bool
    finalize_reason:str
    citation_retry:bool
    answer_retry:bool
    task_context:dict
    memory_debug:dict
    memory_actions:list
    schema_version:int
    config_fingerprint:str
    citation_snapshot:dict
    citation_validation:dict
    scope_validation:dict
    definition_validation:dict
    answer_status:str
    rejected_answer:str


def evidence_identity(item):
    """Only deduplicate scoped, identical evidence; retain distinct revisions/content."""
    if not item.get('resource_id') or not item.get('index_version_id'):return None
    unit=item.get('parent_id') if item.get('expanded') else item.get('chunk_id')
    if not unit:return None
    return (item['resource_id'],item['index_version_id'],unit,item.get('content'))


def make_loop(model,context,save=lambda s:None,emit=lambda k,d:None,check=lambda:None):
    def model_node(state):
        check()
        if state.get('calls',0)>=12:
            state.update(answer='本轮预算已达到上限，请缩小范围后继续。',phase='done');save(state);return state
        loaded=state.setdefault('loaded',list(BASE))
        finalizing=bool(state.get('references')) and (state.get('detail_rounds',0)>=3 or state.get('calls',0)>=11
            or state.get('citation_retry') or state.get('answer_retry'))
        if finalizing and not state.get('finalize_reason'):state['finalize_reason']='RETRIEVAL_ROUND_LIMIT'
        try:
            messages,tools,budget=build(state,SPECS,context.get('memories',()),context.get('teaching_policy'),finalize=finalizing)
        except ValueError as exc:
            if str(exc)!='CONTEXT_BUDGET_EXCEEDED':raise
            if state.get('references'):
                finalizing=True;state['finalize_reason']='CONTEXT_BUDGET'
                try:
                    messages,tools,budget=build(state,SPECS,context.get('memories',()),context.get('teaching_policy'),finalize=True)
                except ValueError as final_error:
                    if str(final_error)!='CONTEXT_BUDGET_EXCEEDED':raise
                    state.update(answer='本轮问题和证据仍超过可处理范围，尚未完成回答。请缩小问题范围。',phase='done')
                    save(state);return state
            else:
                state.update(answer='这轮资料超出了模型可处理的范围。请缩小章节范围，或把问题拆成几步。',phase='done')
                save(state);return state
        state['context_budget']=budget
        state['citation_evidence']=visible_evidence(messages)
        state['citation_snapshot']=visible_evidence(messages,detailed=True,references=state.get('references',{}))
        if tracing_enabled(context):
            record_model_input(state,messages,budget)
            save(state)
        request_model=model.final_answer_model() if finalizing and hasattr(model,'final_answer_model') else model
        started=time.monotonic()
        if runtime.get():runtime.get()['call_id']=state.get('calls',0)+1
        notify('model.started',call_id=state.get('calls',0)+1)
        if hasattr(request_model,'stream') and context.get('stream',False):
            emit('model.started',{})
            reply,usage=request_model.stream(messages,tools,lambda text:emit('model.delta',{'text':text}),check)
        else:
            reply,usage=request_model(messages,tools)
        notify('model.completed',call_id=state.get('calls',0)+1,
               elapsed_ms=round((time.monotonic()-started)*1000),usage=usage)
        if isinstance(usage.get('prompt_tokens'),int):
            state['context_budget']={**budget,'actual_prompt_tokens':usage['prompt_tokens'],
                'actual_to_estimated_ratio':round(usage['prompt_tokens']/max(1,budget['estimated_input_tokens']),4)}
            if tracing_enabled(context):
                state['retrieval_debug']['model_inputs'][-1]['actual_prompt_tokens']=usage['prompt_tokens']
        state['messages']=state.get('messages',[])+[reply];state['calls']=state.get('calls',0)+1
        state['usage']={key:state.get('usage',{}).get(key,0)+value for key,value in usage.items() if isinstance(value,int)}
        state['phase']='tools' if reply.get('tool_calls') else 'done'
        if finalizing and reply.get('tool_calls'):
            state['phase']='done'
            reply={'role':'assistant','content':'现有证据不足以生成可靠回答，本轮检索已结束。请补充资料或缩小问题范围。'}
            state['messages'][-1]=reply
        if not finalizing and state['phase']=='done' and not state.get('references') and not state.get('tool_intent_retry') and any(
            phrase in (reply.get('content') or '') for phrase in ('我先查','先检索','先查一下','我将查询','我会先查')):
            state['tool_intent_retry']=True
            state['messages'].append({'role':'user','content':'请实际执行所需工具并给出结果，不要只宣布准备查询。'})
            state['phase']='model'
        if state['phase']=='done' and not (reply.get('content') or '').strip():
            if state.get('answer_retry'):raise RuntimeError('EMPTY_MODEL_ANSWER')
            state['answer_retry']=True;state['finalize_reason']='EMPTY_ANSWER_RETRY'
            state['messages'].append({'role':'user','content':'上一轮没有输出可见答案。请立即用简洁中文回答，500字以内。独立解题根据题面推导，用户只要提示时只给提示；涉及课程资料的结论仅依据已返回证据，不能核实时直接说明。'})
            state['phase']='model'
        if state['phase']=='done':
            validation=validate_citations(reply.get('content') or '',state.get('references',{}),state['citation_snapshot'])
            state['citation_validation']=validation
            scope_claims=unsupported_scope_claims(reply.get('content') or '')
            state['scope_validation']={'failed':bool(scope_claims),'claims':scope_claims}
            conflicts=definition_conflicts(reply.get('content') or '',state['citation_snapshot'])
            inventory=inventory_conflicts(reply.get('content') or '',state['citation_snapshot'])
            conflicts+=inventory
            state['definition_validation']={'failed':bool(conflicts),'conflicts':conflicts}
            invalid=validation['failed'] or validation['missing_citations'] or bool(scope_claims) or bool(conflicts)
            error_code='EVIDENCE_INVENTORY_MISMATCH' if inventory else ('DEFINITION_CONFLICT' if conflicts else ('EVIDENCE_SCOPE_UNSUPPORTED' if scope_claims else 'CITATION_VALIDATION_FAILED'))
            if invalid and context.get('stream',False):
                save(state)
                raise AgentFailure(error_code)
            if invalid and not state.get('citation_retry'):
                state['citation_retry']=True;state['finalize_reason']='CITATION_FORMAT_RETRY'
                repair='上一回答未通过引用或资料范围校验。仅使用本次输入中存在的编号，不得使用S?等占位符或猜测页码。不能把检索未命中或目录变成全文不存在的证明；资料不足时只说明本轮已返回证据中未找到或尚不能核实。给出简洁结论与必要依据。'
                if inventory:repair+=' 本轮实际输入只有返回证据列出的文件，不能把同一文件的不同块说成另外两份课件。删除不必要的其他资料比较，只回答问题与可见依据。'
                elif conflicts:repair+=' 本轮可见证据中的边界点定义使用包含中心点的任意邻域，不能改成“去心或含心邻域”；去掉中心点会改变孤立点的判断。请保持已给定义的条件。'
                state['messages'].append({'role':'user','content':repair})
                state['phase']='model'
            elif invalid:
                # A known-invalid answer must not be published as a successful answer.
                if (scope_claims or conflicts) and not context.get('stream',False):
                    state['rejected_answer']=reply.get('content') or ''
                    state['answer_status']='abstained'
                    state['finalize_reason']='ANSWER_VALIDATION_REFUSAL'
                    state['scope_validation']={'failed':False,'fallback':True,'rejected_claims':scope_claims}
                    state['definition_validation']={'failed':False,'fallback':True,'rejected_conflicts':conflicts}
                    state['citation_validation']=validate_citations(TRUSTED_REFUSAL,{},{})
                    reply={'role':'assistant','content':TRUSTED_REFUSAL};state['messages'][-1]=reply
                else:
                    save(state)
                    raise AgentFailure(error_code)
        if state['phase']=='done':
            state['answer']=reply.get('content') or ''
            if not context.get('stream',False):emit('model.delta',{'text':state['answer']})
        save(state);return state
    def tools_node(state):
        calls=state['messages'][-1]['tool_calls']
        if len(calls)>8:raise ValueError('TOOL_BATCH_LIMIT')
        results=[]
        detail_used=False
        for call in calls:
            check();name=call['function']['name'];emit('tool.started',{'id':call['id'],'name':name})
            started=time.monotonic()
            notify('tool.started',call_id=call['id'],tool=name)
            trace=None
            if name=='query_course_knowledge' and tracing_enabled(context):
                trace={'tool_call_id':call['id'],'call_number':len(state.setdefault('retrieval_debug',
                    {'schema_version':1,'calls':[],'model_inputs':[]})['calls'])+1}
                state['retrieval_debug']['calls'].append(trace)
            try:
                result=execute(name,json.loads(call['function']['arguments']),state['loaded'],
                    {**context,'references':state.get('references',{}),'tool_call_id':call['id'],
                     **({'retrieval_trace':trace} if trace is not None else {})})
                data=result.get('data')
                if isinstance(data,dict) and data.get('coverage',{}).get('mode')=='detail':detail_used=True
                for item in data.get('evidence',[]) if isinstance(data,dict) else ():
                    refs=state.setdefault('references',{})
                    identity=evidence_identity(item)
                    reference=next((key for key,value in refs.items() if identity is not None and evidence_identity(value)==identity),None)
                    if reference is None:reference='S'+str(len(refs)+1)
                    item['source_id']=reference;refs.setdefault(reference,item)
            except Exception as exc:result={'status':'error','code':getattr(exc,'code',type(exc).__name__)}
            if trace is not None:
                trace.update(status=result['status'],error_code=result.get('code'))
            text=json.dumps(result,ensure_ascii=False)
            if len(text)>40000 and not (isinstance(result.get('data'),dict) and 'coverage' in result['data']):
                text=json.dumps({'status':'error','code':'RESULT_TOO_LARGE','hint':'缩小范围'})
            results.append({'role':'tool','tool_call_id':call['id'],'content':text})
            emit('tool.completed',{'id':call['id'],'name':name,'status':result['status']})
            notify('tool.completed',call_id=call['id'],tool=name,status=result['status'],
                   error_code=result.get('code'),elapsed_ms=round((time.monotonic()-started)*1000))
        if detail_used:state['detail_rounds']=state.get('detail_rounds',0)+1
        state['messages']+=results;state['phase']='model';save(state);return state
    graph=StateGraph(State);graph.add_node('model',model_node);graph.add_node('tools',tools_node)
    graph.add_conditional_edges(START,lambda s:'tools' if s.get('phase')=='tools' else 'model')
    graph.add_conditional_edges('model',lambda s:s['phase'],{'tools':'tools','model':'model','done':END})
    graph.add_edge('tools','model');return graph.compile()

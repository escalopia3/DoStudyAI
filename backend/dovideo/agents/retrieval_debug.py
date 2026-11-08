"""Private checkpoint instrumentation. Never put these records in API/SSE/model data."""
import copy
import json
from dovideo.agents.context import FINAL_EVIDENCE_PREFIX


def tracing_enabled(context):
    return context.get('retrieval_debug') is True


def record_model_input(state, messages, budget):
    """Record evidence after context projection/truncation, as actually sent to the model."""
    debug=state.setdefault('retrieval_debug',{'schema_version':1,'calls':[],'model_inputs':[]})
    evidence=[]
    for message in messages:
        final_data=budget.get('finalizing') and message.get('role')=='user' and message.get('content','').startswith(FINAL_EVIDENCE_PREFIX)
        if message.get('role')!='tool' and not final_data:continue
        try:
            data=json.loads(message['content'][len(FINAL_EVIDENCE_PREFIX):]) if final_data else json.loads(message['content']).get('data',{})
        except (ValueError,TypeError,AttributeError):continue
        if not isinstance(data,dict) or 'coverage' not in data:continue
        for item in data.get('evidence',[]):
            if not isinstance(item,dict):continue
            evidence.append({**copy.deepcopy(item),'tool_call_id':message.get('tool_call_id')})
    debug['model_inputs'].append({'model_call':state.get('calls',0)+1,
        'context_budget':dict(budget),'evidence':evidence})

"""Graph entry for local model-loop inspection; durable runs use agent_worker."""
from dovideo.agents.loop import make_loop
from dovideo.agents.provider import ChatModel

def _model(messages,tools):
    return ChatModel()(messages,tools)

def _no_context(*_):
    raise RuntimeError('Use app.agent_worker for authorized tool execution')

agent=make_loop(_model,None,check=_no_context)

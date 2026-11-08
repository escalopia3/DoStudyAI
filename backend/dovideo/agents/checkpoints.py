"""Explicit, conservative recovery of persisted graph state."""
import hashlib
import json
import os
from pathlib import Path
from dovideo.agents.reliability import AgentFailure


def fingerprint():
    from dovideo.agents.prompt import SYSTEM, VERSION
    from dovideo.tools.registry import SPECS
    payload = {'prompt_version': VERSION, 'prompt': SYSTEM,
               'tools': [SPECS[k].schema() for k in sorted(SPECS)],
               'model': os.getenv('DOVIDEO_CHAT_MODEL', ''),
               'endpoint': os.getenv('DOVIDEO_CHAT_BASE_URL', ''),
               'options': {k: os.getenv(k, '') for k in (
                   'DOVIDEO_CHAT_THINKING', 'DOVIDEO_CHAT_FINAL_THINKING',
                   'DOVIDEO_CHAT_OUTPUT_TOKENS', 'DOVIDEO_DETAIL_EVIDENCE_MODE',
                   'DOVIDEO_CHAT_STREAM','DOVIDEO_CHAT_CONTEXT_TOKENS',
                   'DOVIDEO_CHAT_MEMORY_TOKENS','DOVIDEO_CHAT_HISTORY_TOKENS')}}
    root=Path(__file__).resolve().parent
    payload['implementation']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob('*.py'))}
    registry=root.parent/'tools/registry.py'
    payload['tool_implementation']=hashlib.sha256(registry.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def restore(value, config_fingerprint):
    if not isinstance(value, dict):
        raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    if not value:
        return {}
    state = dict(value)
    if (state.get('schema_version', 0) not in (0, 1)
            or not isinstance(state.get('messages'), list)
            or state.get('phase', 'model') not in ('model', 'tools', 'done')
            or type(state.get('calls', 0)) is not int
            or not 0 <= state.get('calls', 0) <= 12
            or not isinstance(state.get('references', {}), dict)):
        raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    if any(not isinstance(m,dict) or m.get('role') not in ('user','assistant','tool','system')
           for m in state['messages']):
        raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    if state.get('phase')=='tools':
        calls=state['messages'][-1].get('tool_calls') if state['messages'] else None
        if not isinstance(calls,list) or not 1<=len(calls)<=8 or any(
            not isinstance(c,dict) or not c.get('id') or not isinstance(c.get('function'),dict)
            or not isinstance(c['function'].get('name'),str)
            or not isinstance(c['function'].get('arguments'),str) for c in calls):
            raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    if state.get('config_fingerprint') not in (None, config_fingerprint):
        raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    # Legacy states with no fingerprint cannot prove cross-release compatibility.
    if not state.get('schema_version') and os.getenv('DOVIDEO_ALLOW_LEGACY_CHECKPOINT', '0') != '1':
        raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    if state.get('schema_version') == 1 and not state.get('config_fingerprint'):
        raise AgentFailure('CHECKPOINT_INCOMPATIBLE')
    state.update(schema_version=1, config_fingerprint=config_fingerprint)
    return state

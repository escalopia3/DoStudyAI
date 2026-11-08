"""Low-cardinality health signals from shared run state; no question/evidence text."""
import json
import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from dovideo.models import AgentRun


def directory():
    root=Path(__file__).resolve().parents[3]
    value=Path(os.getenv('DOVIDEO_OBSERVABILITY_DIR',str(root/'.learning-work/observability')))
    if not value.is_absolute():value=root/value
    value.mkdir(parents=True,exist_ok=True)
    (value/'.gitignore').write_text('*\n',encoding='utf-8')
    return value


def configure():
    logger=logging.getLogger('dovideo.agent')
    if not any(getattr(h,'agent_json_sink',False) for h in logger.handlers):
        handler=RotatingFileHandler(directory()/'agent-events.jsonl',maxBytes=10_000_000,backupCount=5,encoding='utf-8')
        handler.agent_json_sink=True;handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler);logger.setLevel(logging.INFO)


def persist_health(value):
    folder=directory();target=folder/'health.json'
    (folder/'alerts.jsonl').touch(exist_ok=True)
    previous=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    value={**value,'generated_at':datetime.now(timezone.utc).isoformat()}
    temporary=folder/'health.tmp';temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
    gauges={'queue_oldest_seconds':value['oldest_queued_seconds'],'alerts_active':len(value['alerts'])}
    gauges.update({'runs_'+state.lower():value['states'].get(state,0) for state in ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')})
    temporary=folder/'metrics.tmp';temporary.write_text('\n'.join(f'dovideo_agent_{k} {v}' for k,v in gauges.items())+'\n',encoding='utf-8');temporary.replace(folder/'metrics.prom')
    if previous.get('alerts',[])!=value['alerts']:
        with (folder/'alerts.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'generated_at':value['generated_at'],'kind':'alerts.changed','alerts':value['alerts'],'previous_alerts':previous.get('alerts',[])})+'\n')
    return value


def health(engine):
    now=datetime.now(timezone.utc)
    with Session(engine) as session:
        states=dict(session.execute(select(AgentRun.state,func.count()).where(
            AgentRun.created_at>=now-timedelta(minutes=10)).group_by(AgentRun.state)).all())
        oldest=session.scalar(select(func.min(AgentRun.created_at)).where(AgentRun.state=='QUEUED'))
        recovery=session.scalar(select(func.count()).where(AgentRun.created_at>=now-timedelta(minutes=10),
            AgentRun.error_code.in_(['LEASE_EXHAUSTED','CHECKPOINT_INCOMPATIBLE'])))
    terminal=sum(states.get(s,0) for s in ('FAILED','SUCCEEDED','CANCELLED'))
    age=(now-oldest).total_seconds() if oldest else 0
    alerts=[]
    if age>120:alerts.append('QUEUE_AGE_EXCEEDED')
    if recovery:alerts.append('RECOVERY_FAILURE')
    if terminal>=20 and states.get('FAILED',0)/terminal>.1:alerts.append('RUN_FAILURE_RATE_EXCEEDED')
    value={'kind':'agent.health','window_minutes':10,'states':states,'oldest_queued_seconds':age,'alerts':alerts}
    logger=logging.getLogger('dovideo.agent')
    logger.log(logging.WARNING if alerts else logging.INFO,json.dumps(value))
    return persist_health(value)

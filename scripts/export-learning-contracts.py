"""Export checked-in request/event schemas and FastAPI OpenAPI without a database."""
import json
from pathlib import Path
from agent_service.contracts import ParseRequest, JobEvent
from agent_service.config import Settings
from agent_service.api import create_app

destination=Path(__file__).resolve().parents[1]/'contracts'/'learning-agent'
destination.mkdir(parents=True,exist_ok=True)
for name,model in [('parse-request',ParseRequest),('job-event',JobEvent)]:
    (destination/f'{name}.schema.json').write_text(json.dumps(model.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(destination/'python-openapi.json').write_text(json.dumps(create_app(Settings('sqlite://','contract-export-only'),object()).openapi(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

import secrets
from fastapi import FastAPI, Header, HTTPException, Depends
from sqlalchemy import select
from agent_service.config import Settings
from agent_service.contracts import ParseRequest
from agent_service.store import Store, Conflict, jobs
from agent_service.learning_agent.persistence import AgentRunConflict, AgentRunStore
from agent_service.learning_agent.schemas import AgentRunRequest


def create_app(settings=None, store=None):
    settings = settings or Settings.from_env()
    store = store or Store(settings.database_url)
    agent_runs = AgentRunStore(store.engine)
    app = FastAPI(title="Learning document parsing", version="0.1.0")

    def authenticate(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + settings.token):
            raise HTTPException(401, "Service authentication required")

    @app.get("/health/live")
    def live(): return {"status": "UP"}

    @app.get("/health/ready", dependencies=[Depends(authenticate)])
    def ready():
        try:
            with store.engine.connect() as db: db.execute(select(jobs.c.id).limit(1))
        except Exception:
            raise HTTPException(503, "Database or migration unavailable")
        return {"status": "UP"}

    def public(row):
        return {"jobId": row["id"], "state": row["state"], "sequence": row["sequence"],
                "attempt": row["attempt"], "artifactPrefix": row.get("artifact_prefix"),
                "errorCode": row.get("error_code")}

    @app.post("/internal/knowledge/jobs", status_code=202, dependencies=[Depends(authenticate)])
    def submit(request: ParseRequest):
        try: return public(store.submit(request))
        except Conflict as error: raise HTTPException(409, str(error))

    @app.get("/internal/knowledge/jobs/{job_id}", dependencies=[Depends(authenticate)])
    def get(job_id: str):
        row = store.get(job_id)
        if not row: raise HTTPException(404, "Job not found")
        return public(row)

    @app.post("/internal/knowledge/jobs/{job_id}/cancel", dependencies=[Depends(authenticate)])
    def cancel(job_id: str):
        try: row = store.cancel(job_id)
        except Conflict as error: raise HTTPException(409, str(error))
        if not row: raise HTTPException(404, "Job not found")
        return public(row)

    def public_run(row):
        return {"runId": row["run_id"], "state": row["state"], "sequence": row["sequence"],
                "attempt": row["attempt"], "result": row.get("result_json"),
                "errorCode": row.get("error_code")}

    @app.post("/internal/learning-agent/runs", status_code=202, dependencies=[Depends(authenticate)])
    def submit_agent_run(request: AgentRunRequest):
        try: return public_run(agent_runs.submit(request))
        except AgentRunConflict as error: raise HTTPException(409, str(error))

    @app.get("/internal/learning-agent/runs/{run_id}", dependencies=[Depends(authenticate)])
    def get_agent_run(run_id: str):
        row = agent_runs.get(run_id)
        if not row: raise HTTPException(404, "Run not found")
        return public_run(row)

    @app.post("/internal/learning-agent/runs/{run_id}/cancel", dependencies=[Depends(authenticate)])
    def cancel_agent_run(run_id: str):
        row = agent_runs.cancel(run_id)
        if not row: raise HTTPException(404, "Run not found")
        return public_run(row)

    return app

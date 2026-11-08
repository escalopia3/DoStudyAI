from contextlib import asynccontextmanager
import logging
import uuid
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from dovideo.config import Settings
from dovideo.storage import Storage
from dovideo.errors import ApiError
from dovideo.routers import ALL_ROUTERS

logger = logging.getLogger("dovideo.gateway")

def create_app(settings=None, storage_factory=Storage):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings.from_env()
        app.state.storage = storage_factory(app.state.settings)
        try:
            await run_in_threadpool(app.state.storage.ensure_bucket)
            yield
        finally:
            app.state.storage.close()

    app = FastAPI(title="DoVideo v2 Gateway", version="0.1.0", lifespan=lifespan)
    for router in ALL_ROUTERS:
        app.include_router(router)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info("request id=%s method=%s status=%s", request.state.request_id, request.method, response.status_code)
        return response

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.error("request_failed id=%s type=%s", request.state.request_id, type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "code": "INTERNAL_ERROR",
            "message": "Unexpected server error",
            "request_id": request.state.request_id,
        })

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={
            "code": exc.code, "message": exc.message, "request_id": request.state.request_id,
        })

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={
            "code": "VALIDATION_ERROR", "message": "请求参数无效",
            "request_id": request.state.request_id,
        })

    @app.get("/health/live")
    async def live():
        return {"status": "UP"}

    @app.get("/health/ready")
    async def ready():
        try:
            await run_in_threadpool(app.state.storage.ready)
        except Exception:
            return JSONResponse(status_code=503, content={"status": "NOT_READY"})
        return {"status": "UP"}
    return app

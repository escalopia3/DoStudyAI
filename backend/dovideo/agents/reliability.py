"""Bounded provider retries, independent of graph rounds and worker claims."""
import email.utils
import logging
import random
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from contextlib import contextmanager

import httpx

log = logging.getLogger('dovideo.agent')
runtime = ContextVar('agent_runtime', default={})


class AgentFailure(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@contextmanager
def execution_scope(**values):
    token = runtime.set(values)
    try:
        yield
    finally:
        runtime.reset(token)


def classify(exc):
    if isinstance(exc, AgentFailure):
        return exc.code, False
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return 'MODEL_RATE_LIMITED', True
        if status in (500, 502, 503, 504):
            return 'MODEL_UNAVAILABLE', True
        return {401: 'MODEL_AUTH_ERROR', 403: 'MODEL_AUTH_ERROR',
                404: 'MODEL_NOT_FOUND'}.get(status, 'MODEL_REQUEST_REJECTED'), False
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return 'MODEL_TRANSPORT_ERROR', True
    if isinstance(exc,ValueError) and str(exc)=='MODEL_STREAM_INTERRUPTED':
        return 'MODEL_STREAM_INTERRUPTED',True
    return 'MODEL_PROTOCOL_ERROR', False


def retry_after(exc):
    if not isinstance(exc, httpx.HTTPStatusError):
        return 0
    value = exc.response.headers.get('Retry-After', '')
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (email.utils.parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


def notify(kind, **data):
    scope = runtime.get()
    event = {'kind': kind, 'run_id': scope.get('run_id'), 'request_id':scope.get('request_id'),
             'call_id':scope.get('call_id'),**data}
    import json
    log.info(json.dumps(event, ensure_ascii=False))
    if scope.get('observe'):
        scope['observe'](kind, {k:v for k,v in event.items() if k!='kind'})


def invoke(operation, *, check=lambda: None, emitted=lambda: False, attempts=3, budget=120, model_id=None):
    scope = runtime.get()
    deadline = min(time.monotonic() + budget, scope.get('deadline', float('inf')))
    for attempt in range(1, attempts + 1):
        check()
        if scope.get('check'):
            scope['check']()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AgentFailure('MODEL_DEADLINE_EXCEEDED')
        started = time.monotonic()
        try:
            result = operation(remaining)
        except Exception as exc:
            # Cancellation and lease loss must never be reclassified/retried.
            check()
            if scope.get('check'):
                scope['check']()
            code, retryable = classify(exc)
            if emitted():
                code, retryable = 'PARTIAL_STREAM', False
            notify('model.attempt', model=model_id,attempt=attempt, elapsed_ms=round((time.monotonic()-started)*1000),
                   error_code=code, usage_known=False)
            if not retryable or attempt == attempts:
                raise AgentFailure(code) from exc
            delay = max(retry_after(exc), 2 ** (attempt - 1) + random.uniform(0, .25))
            if delay >= deadline - time.monotonic():
                raise AgentFailure('MODEL_DEADLINE_EXCEEDED') from exc
            until = time.monotonic() + delay
            while time.monotonic() < until:
                check()
                if scope.get('check'):
                    scope['check']()
                time.sleep(min(.1, max(0, until - time.monotonic())))
        else:
            if time.monotonic() > deadline:
                raise AgentFailure('PARTIAL_STREAM' if emitted() else 'MODEL_DEADLINE_EXCEEDED')
            notify('model.attempt', model=model_id,attempt=attempt, elapsed_ms=round((time.monotonic()-started)*1000),
                   error_code=None, usage_known=bool(result[1]), usage=result[1])
            return result

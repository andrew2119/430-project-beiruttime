import asyncio
import json
import inspect
import logging
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4
import asyncpg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from bt_contracts_core.errors import AccessDenied, PublicError, error_body
from bt_runtime.modules import discover
from bt_runtime.request_budget import RequestBudget
from bt_runtime.supervisor import LoopSupervisor
from . import db
from .settings import Settings

logger = logging.getLogger('beirut_time')
REQUEST_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'timestamp': self.formatTime(record), 'level': record.levelname,
            'event': record.getMessage(), **getattr(record, 'fields', {})})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(settings.log_level)

    @asynccontextmanager
    async def lifespan(app):
        # The migration container alone gets owner credentials. Runtime only reads ledger.
        app.state.pool = await db.create_pool(settings.database_url, settings.database_pool_size)
        supervisor = LoopSupervisor(app, workers)
        app.state.supervisor = supervisor
        supervisor.start()
        logger.info('service.started', extra={'fields': {'service': settings.service_name}})
        try:
            yield
        finally:
            await supervisor.close()
            await asyncio.wait_for(app.state.pool.close(), timeout=5)

    app = FastAPI(title=f'Beirut Time · {settings.service_name}', version='0.1.0', lifespan=lifespan)
    app.state.settings = settings

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        candidate = request.headers.get('X-Request-ID', '')
        rid = candidate if REQUEST_ID.fullmatch(candidate) else uuid4().hex
        request.state.request_id = rid
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.error('request.failed', extra={'fields': {'service': settings.service_name, 'request_id': rid}})
            response = JSONResponse(error_body('internal_error', 'An unexpected error occurred.', rid), status_code=500)
        response.headers['X-Request-ID'] = rid
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        route = request.scope.get('route')
        logger.info('request.completed', extra={'fields': {'service': settings.service_name, 'request_id': rid,
            'method': request.method, 'route': getattr(route, 'path', 'unmatched'), 'status': response.status_code,
            'duration_ms': round((time.monotonic() - started) * 1000, 2)}})
        return response

    @app.exception_handler(PublicError)
    async def public_error(request, exc):
        return JSONResponse(error_body(exc.code, exc.message, request.state.request_id, details=exc.details), status_code=exc.status)

    @app.exception_handler(AccessDenied)
    async def policy_denied(request, exc):
        return JSONResponse(error_body('forbidden', 'Access denied.', request.state.request_id), status_code=403)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        messages = {401: ('unauthorized', 'Sign in to continue.'), 403: ('forbidden', 'Access denied.'),
            404: ('not_found', 'Resource not found.'), 503: ('unavailable', 'Service is temporarily unavailable.')}
        code, message = messages.get(exc.status_code, ('http_error', 'The request could not be completed.'))
        return JSONResponse(error_body(code, message, request.state.request_id),
            status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo PII, tokens or rejected values in errors or logs.
        return JSONResponse(error_body('validation_error', 'Check the supplied fields.', request.state.request_id,
            fields=[{'path': '.'.join(map(str, e['loc'])), 'type': e['type']} for e in exc.errors()]), status_code=422)

    @app.get('/health/live', tags=['health'])
    async def live():
        return {'status': 'ok', 'service': settings.service_name}

    @app.get('/health/ready', tags=['health'])
    async def readiness():
        if getattr(app.state, 'pool', None) is None:
            raise HTTPException(503)
        try:
            async with asyncio.timeout(1.5):
                if not await db.ready(app.state.pool, settings.modules_path):
                    raise HTTPException(503)
        except (asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError, OSError):
            raise HTTPException(503) from None
        return {'status': 'ready', 'service': settings.service_name}

    # Every lane contributes only its module.json and owned subtree.
    modules = discover(settings.modules_path)
    hooks, workers = {}, {}
    for module in modules:
        for reference in module.workers:
            worker = module.load(reference)
            if not inspect.iscoroutinefunction(worker):
                raise ValueError(f'Worker must be asynchronous: {module.id}')
            workers[module.id + ':' + reference] = worker
        for name, reference in module.hooks.items():
            callback = module.load(reference)
            if not re.fullmatch(r'[a-z][a-z0-9.-]+\.v[1-9][0-9]*', name) or name in hooks or not callable(callback) or inspect.iscoroutinefunction(callback):
                raise ValueError(f'Invalid, duplicate or asynchronous pure hook: {name}')
            hooks[name] = callback
        dependencies = [Depends(module.load(module.authorization))] if module.authorization else []
        for reference in module.routes:
            router = module.load(reference)
            if not isinstance(router, APIRouter):
                raise ValueError(f'{module.id} must export an APIRouter')
            existing = {(method, route.path) for route in app.routes for method in getattr(route, 'methods', [])}
            for route in router.routes:
                for method in getattr(route, 'methods', []):
                    if (method, route.path) in existing:
                        raise ValueError(f'Duplicate route in {module.id}: {route.path}')
                    existing.add((method, route.path))
            app.include_router(router, dependencies=dependencies)
    app.state.modules = modules
    app.state.hooks = hooks
    app.add_middleware(RequestBudget, max_bytes=settings.request_body_limit)
    return app

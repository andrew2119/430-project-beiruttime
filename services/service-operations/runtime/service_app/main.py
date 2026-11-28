"""Service-local composition of the shared runtime."""
import os
from uuid import UUID

from asyncpg import RaiseError
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from bt_contracts_core.errors import error_body
from bt_runtime.app import db, main
from bt_runtime.request_budget import RequestBudget
from .modules import discover


class ServiceRequestBudget(RequestBudget):
    async def __call__(self, scope, receive, send):
        if (scope['type'] == 'http' and scope['method'] == 'POST'
                and scope['path'] in {'/internal/v1/quality/records',
                                      '/internal/v1/authorized-work/commands'}):
            # These routes authenticate before streaming their bounded bodies.
            return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


def create_app(settings=None):
    # Startup and readiness must calculate the same complete migration plan.
    main.discover = discover
    db.discover = discover
    app = main.create_app(settings)

    @app.exception_handler(RaiseError)
    async def frozen_job(request, error):
        if error.message != 'd24_job_work_frozen':
            raise error
        return JSONResponse(error_body('d24_job_work_frozen', 'Work is frozen for cancellation.',
                                       request.state.request_id), status_code=409)

    operator = os.getenv('BT_MAINTENANCE_DELIVERY_OPERATOR_ID')
    app.state.maintenance_delivery_operator_id = UUID(operator) if operator else None
    app.user_middleware = [
        Middleware(ServiceRequestBudget, *entry.args, **entry.kwargs)
        if entry.cls is RequestBudget else entry
        for entry in app.user_middleware
    ]
    return app

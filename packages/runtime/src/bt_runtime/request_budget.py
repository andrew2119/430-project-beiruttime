"""Bound request bytes and receive time before JSON/model allocation."""
import asyncio
import re
from uuid import uuid4
from starlette.responses import JSONResponse
from bt_contracts_core.errors import error_body


class RequestBudget:
    def __init__(self, app, max_bytes: int = 1024 * 1024):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        chunks, size, complete = [], 0, False
        status, code = 413, 'body_too_large'
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    body = message.get('body', b'')
                    size += len(body)
                    if size > self.max_bytes:
                        break
                    chunks.append(body)
                    if not message.get('more_body', False):
                        complete = True
                        break
        except TimeoutError:
            status, code = 408, 'request_timeout'
        if complete:
            first = True
            async def replay():
                nonlocal first
                if first:
                    first = False
                    return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
                return await receive()
            return await self.app(scope, replay, send)
        headers = dict(scope.get('headers', []))
        candidate = headers.get(b'x-request-id', b'').decode('ascii', errors='ignore')
        rid = candidate if re.fullmatch(r'[A-Za-z0-9_-]{1,64}', candidate) else uuid4().hex
        response = JSONResponse(error_body(code, 'The request could not be completed.', rid), status_code=status,
            headers={'X-Request-ID': rid, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        await response(scope, receive, send)

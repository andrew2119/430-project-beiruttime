"""Bound private JSON bodies before parsing, including direct service requests."""
import asyncio
from fastapi import Request
from fastapi.routing import APIRoute
from .service import fail


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == 'POST':
                chunks, size = [], 0
                try:
                    async with asyncio.timeout(1):
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > 8192:
                                fail('request_too_large', 413)
                            chunks.append(chunk)
                except TimeoutError:
                    fail('unavailable', 503)
                body = b''.join(chunks)
                sent = False

                async def receive():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {'type': 'http.request', 'body': body, 'more_body': False}
                    return {'type': 'http.disconnect'}

                request = Request(request.scope, receive)
            return await original(request)
        return bounded

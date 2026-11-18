"""One bounded response barrier in front of a real local dependency."""
import asyncio
import json
from urllib.parse import urlsplit

import httpx


class ResponseBarrier:
    """Forward unchanged requests; retain one committed response until released."""
    def __init__(self, upstream, matches, on_commit=None):
        parsed = urlsplit(upstream)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1':
            raise ValueError('A local dependency is required')
        self.upstream, self.matches = upstream.rstrip('/'), matches
        self.on_commit = on_commit
        self.committed = asyncio.Event()
        self.release = asyncio.Event()
        self.captured = None
        self.server = self.client = None
        self.tasks = set()

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=5, trust_env=False)
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=65536)
        self.url = 'http://127.0.0.1:' + str(self.server.sockets[0].getsockname()[1])
        return self

    async def __aexit__(self, *exc):
        self.release.set()
        self.server.close()
        await self.server.wait_closed()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.aclose()

    async def forward(self, method, path, headers, content):
        response = await self.client.request(method, self.upstream + path,
                                             headers=headers, content=content)
        if (self.captured is None and 200 <= response.status_code < 300
                and self.matches(method, path, json.loads(content or b'{}'))):
            self.captured = (method, path, headers, content)
            if self.on_commit is not None:
                self.on_commit()
            self.committed.set()
            await self.release.wait()
        return response

    async def replay(self):
        """Re-deliver the identical authenticated event, never manufacture one."""
        if self.captured is None:
            raise AssertionError('No committed request was captured')
        method, path, headers, content = self.captured
        return await self.client.request(method, self.upstream + path,
                                         headers=headers, content=content)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with asyncio.timeout(45):
                head = await reader.readuntil(b'\r\n\r\n')
                lines = head.decode('latin1').split('\r\n')
                method, path, _ = lines[0].split(' ')
                if not path.startswith('/') or path.startswith('//'):
                    raise ValueError('Relative dependency path required')
                headers = dict(line.split(':', 1) for line in lines[1:] if line)
                headers = {key.lower(): value.strip() for key, value in headers.items()}
                if 'transfer-encoding' in headers:
                    raise ValueError('A bounded body is required')
                size = int(headers.get('content-length', '0'))
                if not 0 <= size <= 2_000_000:
                    raise ValueError('Body exceeds bound')
                content = await reader.readexactly(size)
                for key in ('host', 'connection', 'content-length'):
                    headers.pop(key, None)
                response = await self.forward(method, path, headers, content)
                payload = response.content
                if len(payload) > 2_000_000:
                    raise ValueError('Response exceeds bound')
                writer.write((f'HTTP/1.1 {response.status_code} Response\r\n'
                              f'Content-Length: {len(payload)}\r\n'
                              'Content-Type: application/json\r\nConnection: close\r\n\r\n').encode() + payload)
                await writer.drain()
        except (OSError, ValueError, httpx.HTTPError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.tasks.discard(task)

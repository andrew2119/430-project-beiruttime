import { expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

it('never intercepts APIs, RSC, external resources or commands; activation waits for consent', async () => {
  const handlers = new Map<string, (event: Record<string, unknown>) => void>();
  const skipWaiting = vi.fn();
  const cache = { match: vi.fn(), put: vi.fn().mockResolvedValue(undefined), keys: vi.fn().mockResolvedValue([]), delete: vi.fn() };
  const fetcher = vi.fn().mockResolvedValue(new Response('asset', {status:200}));
  runInNewContext(readFileSync('public/sw.js','utf8'), {
    self: { addEventListener: (name: string, handler: (event: Record<string, unknown>) => void) => handlers.set(name,handler), location: { origin: 'https://beirut.test' }, skipWaiting, clients: { claim: vi.fn() } },
    caches: { open: vi.fn().mockResolvedValue(cache), keys: vi.fn().mockResolvedValue([]), delete: vi.fn() },
    URL, Response, fetch: fetcher,
  });
  expect(skipWaiting).not.toHaveBeenCalled();
  for (const [url,method] of [['https://beirut.test/api/web/v1/status','GET'],['https://beirut.test/en?_rsc=1','GET'],['https://other.test/_next/static/x.js','GET'],['https://beirut.test/api/bid','POST']]) {
    const respondWith = vi.fn();
    handlers.get('fetch')!({ request: { url, method, mode:'cors' }, respondWith });
    expect(respondWith).not.toHaveBeenCalled();
  }
  let answer: Promise<Response> | undefined;
  handlers.get('fetch')!({ request: {url:'https://beirut.test/_next/static/chunk.js', method:'GET',mode:'cors'}, respondWith: (r: Promise<Response>) => { answer=r; } });
  expect((await answer!).status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(1);
  handlers.get('message')!({ data:'SKIP_WAITING' });
  expect(skipWaiting).toHaveBeenCalledTimes(1);
});

it('retires only older public caches after activation so updated icons can load', async () => {
  const handlers = new Map<string, (event: Record<string, unknown>) => void>();
  const deleted = vi.fn().mockResolvedValue(true);
  const claim = vi.fn().mockResolvedValue(undefined);
  runInNewContext(readFileSync('public/sw.js', 'utf8'), {
    self: { addEventListener: (name: string, handler: (event: Record<string, unknown>) => void) => handlers.set(name, handler), clients: { claim } },
    caches: { keys: vi.fn().mockResolvedValue(['bt-public-v1', 'bt-public-v2', 'unrelated-cache']), delete: deleted },
  });
  let activation: Promise<void> | undefined;
  handlers.get('activate')!({ waitUntil: (task: Promise<void>) => { activation = task; } });
  await activation;
  expect(deleted).toHaveBeenCalledTimes(1);
  expect(deleted).toHaveBeenCalledWith('bt-public-v1');
  expect(claim).toHaveBeenCalledTimes(1);
});

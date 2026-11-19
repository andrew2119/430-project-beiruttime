import { afterEach, expect, it, vi } from 'vitest';
import { Dependency } from './dependency';
const { dependencies } = vi.hoisted(() => ({ dependencies: new Map() }));
vi.mock('@/registry-loader', () => ({
  gatewayRegistrations: [
    { service: 'catalog', path: '/v1/seller/listings/:id/publish', methods: ['POST'], roles: ['seller'] },
    { service: 'catalog', path: '/v1/seller/listings/:id', methods: ['GET'], roles: ['seller'] },
  ],
}));
vi.mock('@/lib/bff/status', () => ({
  dependencies, serviceNames: ['catalog', 'identity'], requestId: () => 'test-request',
  privateHeaders: () => ({ 'Cache-Control': 'no-store' }),
}));
import { forward } from './forward';
const listingId = '00000000-0000-4000-8000-000000000001';
const listingPath = `/v1/seller/listings/${listingId}`;
const path = `${listingPath}/publish`;
const envelope = { error: { code: 'publication_review_pending', message: 'Possession review is pending.', request_id: 'test-domain-request', details: { operation_id: 'test-operation', next_actor: 'reviewer', pending_reason: 'possession_review' } } };
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  dependencies.clear();
});

it.each([
  ['publication succeeds within its budget', 'POST', path, 1500, 200, 'published'],
  ['publication exceeds its budget', 'POST', path, 18701, 503, 'unavailable'],
  ['listing read keeps its original budget', 'GET', listingPath, 1201, 503, 'unavailable'],
  ['early publication review remains pending', 'POST', path, 100, 503, 'publication_review_pending'],
] as const)('%s', async (_label, method, route, responseMs, expectedStatus, outcome) => {
  vi.useFakeTimers();
  // Route native abort deadlines through the same clock as the delayed response.
  const deadline = vi.spyOn(AbortSignal, 'timeout').mockImplementation(ms => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), ms);
    return controller.signal;
  });
  const pending = outcome === 'publication_review_pending';
  const body = JSON.stringify(pending ? envelope : { id: listingId, status: 'published' }, null, 2);
  const fetch = vi.fn((_url: URL, { signal }: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(new Response(body, {
      status: pending ? 503 : 200,
      headers: { 'Content-Type': 'application/json' },
    })), responseMs);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(signal.reason);
    }, { once: true });
  }));
  vi.stubGlobal('fetch', fetch);
  dependencies.set('catalog', new Dependency('catalog', 'https://catalog.test'));
  dependencies.set('identity', { request: async () => Response.json({ actor: { subject_id: 'test-seller' }, roles: ['seller'] }) });

  const headers = new Headers({ Origin: 'http://localhost:3000', Authorization: 'Bearer test-session' });
  let publication: string | undefined;
  if (method === 'POST') {
    headers.set('Content-Type', 'application/json');
    headers.set('Idempotency-Key', 'test-publication');
    headers.set('If-Match', '"1"');
    publication = JSON.stringify({ fee_quote_id: '00000000-0000-4000-8000-000000000002', rules_version: 'test-rules' });
  }
  const result = forward(
    new Request('http://localhost:3000/api/web/v1/catalog' + route, {
      method, headers, body: publication,
    }),
    { params: Promise.resolve({ service: 'catalog', path: route.slice(1).split('/') }) },
  );
  await vi.advanceTimersByTimeAsync(responseMs);
  const response = await result;
  expect(response.status).toBe(expectedStatus);
  if (outcome === 'unavailable') expect((await response.json()).error.code).toBe(outcome);
  else expect(await response.text()).toBe(body);
  expect(deadline).toHaveBeenCalledWith(method === 'POST' ? 18700 : 1200);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each([false, true])('preserves the pending bytes and keeps the circuit closed through forward: %s', async throughForward => {
  const body = JSON.stringify(envelope, null, 2);
  const fetch = vi.fn(async () => new Response(body, { status: 503, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetch);
  const dependency = new Dependency('catalog', 'https://catalog.test');
  dependencies.set('catalog', dependency);
  dependencies.set('identity', { request: async () => Response.json({ actor: { subject_id: 'test-seller' }, roles: ['seller'] }) });
  for (let count = 0; count < 4; count++) {
    const response = throughForward
      ? await forward(new Request('http://localhost:3000/api/web/v1/catalog' + path, { method: 'POST', headers: { Origin: 'http://localhost:3000', Authorization: 'Bearer test-session' } }), { params: Promise.resolve({ service: 'catalog', path: path.slice(1).split('/') }) })
      : await dependency.request('POST', path, 'test-request');
    expect(response).toBeInstanceOf(Response);
    expect((response as Response).status).toBe(503);
    expect(await (response as Response).text()).toBe(body);
    expect(dependency.failures).toBe(0);
    expect(dependency.openedAt).toBe(0);
  }
  expect(fetch).toHaveBeenCalledTimes(4);
});

it.each([
  ['invalid JSON', '{', 503, 'catalog', 'POST', path, 'application/json'],
  ['unknown code', JSON.stringify({ error: { ...envelope.error, code: 'unknown' } }), 503, 'catalog', 'POST', path, 'application/json'],
  ['missing field', JSON.stringify({ error: { code: 'publication_review_pending' } }), 503, 'catalog', 'POST', path, 'application/json'],
  ['extra field', JSON.stringify({ error: { ...envelope.error, private: 'test-private' } }), 503, 'catalog', 'POST', path, 'application/json'],
  ['oversized', JSON.stringify({ error: { ...envelope.error, details: { value: 'x'.repeat(16384) } } }), 503, 'catalog', 'POST', path, 'application/json'],
  ['wrong service', JSON.stringify(envelope), 503, 'identity', 'POST', path, 'application/json'],
  ['wrong method', JSON.stringify(envelope), 503, 'catalog', 'GET', path, 'application/json'],
  ['wrong route', JSON.stringify(envelope), 503, 'catalog', 'POST', '/v1/other', 'application/json'],
  ['wrong status', JSON.stringify(envelope), 500, 'catalog', 'POST', path, 'application/json'],
  ['rate limited', JSON.stringify(envelope), 429, 'catalog', 'POST', path, 'application/json'],
  ['wrong content type', JSON.stringify(envelope), 503, 'catalog', 'POST', path, 'text/html'],
])('counts an untrusted answer: %s', async (_label, body, status, service, method, route, contentType) => {
  const fetch = vi.fn(async () => new Response(body, { status: Number(status), headers: { 'Content-Type': String(contentType) } }));
  vi.stubGlobal('fetch', fetch);
  const dependency = new Dependency(String(service), 'https://service.test');
  for (let count = 0; count < 4; count++) expect(await dependency.request(String(method), String(route), 'test-request')).toEqual({ kind: 'unavailable', dependency: service });
  expect(dependency.failures).toBe(3);
  expect(dependency.openedAt).toBeGreaterThan(0);
  expect(fetch).toHaveBeenCalledTimes(3);
});

it('replaces a malformed publish answer through forward and counts the failure', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: { code: 'publication_review_pending' } }, { status: 503 })));
  const dependency = new Dependency('catalog', 'https://catalog.test');
  dependencies.set('catalog', dependency);
  dependencies.set('identity', { request: async () => Response.json({ actor: { subject_id: 'test-seller' }, roles: ['seller'] }) });
  const response = await forward(new Request('http://localhost:3000/api/web/v1/catalog' + path, { method: 'POST', headers: { Origin: 'http://localhost:3000', Authorization: 'Bearer test-session' } }), { params: Promise.resolve({ service: 'catalog', path: path.slice(1).split('/') }) });
  expect(response.status).toBe(503);
  expect((await response.json()).error.code).toBe('unavailable');
  expect(dependency.failures).toBe(1);
});

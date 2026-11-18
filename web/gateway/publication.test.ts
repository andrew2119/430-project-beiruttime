import { afterEach, expect, it, vi } from 'vitest';
import { Dependency } from './dependency';
const { dependencies } = vi.hoisted(() => ({ dependencies: new Map() }));
vi.mock('@/registry-loader', () => ({ gatewayRegistrations: [{ service: 'catalog', path: '/v1/seller/listings/:id/publish', methods: ['POST'], roles: ['seller'] }] }));
vi.mock('@/lib/bff/status', () => ({
  dependencies, serviceNames: ['catalog', 'identity'], requestId: () => 'test-request',
  privateHeaders: () => ({ 'Cache-Control': 'no-store' }),
}));
import { forward } from './forward';
const path = '/v1/seller/listings/test-listing/publish';
const envelope = { error: { code: 'publication_review_pending', message: 'Possession review is pending.', request_id: 'test-domain-request', details: { operation_id: 'test-operation', next_actor: 'reviewer', pending_reason: 'possession_review' } } };
afterEach(() => { vi.unstubAllGlobals(); dependencies.clear(); });

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

import { beforeEach, afterEach, expect, it, vi } from 'vitest';
const { identity, resource } = vi.hoisted(() => ({ identity: vi.fn(), resource: vi.fn() }));
vi.mock('@/registry-loader', () => ({
  gatewayRegistrations: [{ service: 'catalog', path: '/v1/protected-proof', methods: ['GET'], roles: ['buyer'] }],
}));
vi.mock('@/lib/bff/status', () => ({
  dependencies: new Map([['identity', { request: identity }], ['catalog', { request: resource }]]),
  serviceNames: ['identity', 'catalog'], requestId: () => 'auth-status-proof',
  privateHeaders: (id: string) => ({ 'Cache-Control': 'no-store', 'X-Request-ID': id }),
}));
import { forward } from '../gateway/forward';
import { request, ApiError } from '../lib/api/client';
const path = '/api/web/v1/catalog/v1/protected-proof';
const context = { params: Promise.resolve({ service: 'catalog', path: ['v1', 'protected-proof'] }) };
beforeEach(() => {
  identity.mockReset(); resource.mockReset();
  identity.mockResolvedValue(Response.json({ actor: { subject_id: 'synthetic-subject' }, roles: ['buyer'] }));
  resource.mockResolvedValue(Response.json({ accepted: true }));
  vi.stubGlobal('fetch', vi.fn((path: string, init: RequestInit) => forward(new Request('https://beirut.test' + path, init), context)));
});
afterEach(() => vi.unstubAllGlobals());

it.each([[401, 'unauthorized'], [403, 'forbidden']] as const)('preserves Identity %s through the gateway into ApiError', async (status, code) => {
  identity.mockResolvedValue(Response.json({ private: 'not-forwarded' }, { status }));
  try {
    await request(path, { headers: { Authorization: 'Bearer synthetic-proof' } });
    throw new Error('Expected denial');
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status, code, requestId: 'auth-status-proof' });
  }
  expect(resource).not.toHaveBeenCalled();
});
it.each([[401, 'unauthorized'], [403, 'forbidden']] as const)('preserves domain %s into ApiError after successful principal verification', async (status, code) => {
  resource.mockResolvedValue(Response.json({ error: { code, request_id: 'domain-proof', details: {} } }, { status }));
  await expect(request(path, { headers: { Authorization: 'Bearer synthetic-proof' } })).rejects.toMatchObject({ status, code, requestId: 'domain-proof' });
});
it('returns 401 for missing authentication without contacting either service', async () => {
  await expect(request(path)).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
  expect(identity).not.toHaveBeenCalled(); expect(resource).not.toHaveBeenCalled();
});
it('returns 403 for an authenticated principal without the required role', async () => {
  identity.mockResolvedValue(Response.json({ actor: { subject_id: 'synthetic-subject' }, roles: [] }));
  await expect(request(path, { headers: { Authorization: 'Bearer synthetic-proof' } })).rejects.toMatchObject({ status: 403, code: 'forbidden' });
  expect(resource).not.toHaveBeenCalled();
});
it.each([400, 503])('does not turn unexpected Identity %s into a refreshable authentication failure', async status => {
  identity.mockResolvedValue(new Response(null, { status }));
  await expect(request(path, { headers: { Authorization: 'Bearer synthetic-proof' } })).rejects.toMatchObject({ status: 503, code: 'unavailable' });
  expect(resource).not.toHaveBeenCalled();
});

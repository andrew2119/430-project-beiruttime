import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const { upstream } = vi.hoisted(() => ({ upstream: vi.fn() }));
vi.mock('@/registry-loader', () => ({
  gatewayRegistrations: [
    ...['login', 'register', 'refresh'].map(operation => ({
      service: 'identity', path: `/v1/auth/${operation}`, methods: ['POST'],
      roles: ['public'], forwardCookies: ['bt-refresh'],
    })),
    { service: 'identity', path: '/v1/auth/session', methods: ['GET'], roles: ['public'] },
  ],
}));
vi.mock('@/lib/bff/status', () => ({
  dependencies: new Map([['identity', { request: upstream }]]),
  serviceNames: ['identity'],
  requestId: () => 'origin-proof',
  privateHeaders: (id: string) => ({ 'Cache-Control': 'no-store', 'X-Request-ID': id }),
}));
import { forward } from '@/gateway/forward';

const origin = 'https://beirut.test';
const context = (operation: string) => ({ params: Promise.resolve({ service: 'identity', path: ['v1', 'auth', operation] }) });
function mutation(operation: string, suppliedOrigin?: string, bindOrigin = origin) {
  const headers = new Headers({
    'Content-Type': 'application/json', Authorization: 'Bearer synthetic-proof',
    'Idempotency-Key': 'proof-key', 'If-Match': '"1"',
    Cookie: 'bt-refresh=synthetic-cookie; other=not-forwarded', 'X-Actor-ID': 'not-trusted',
  });
  if (suppliedOrigin !== undefined) headers.set('Origin', suppliedOrigin);
  return new Request(`${bindOrigin}/api/web/v1/identity/v1/auth/${operation}`, { method: 'POST', headers, body: '{}' });
}
afterEach(() => vi.unstubAllEnvs());
beforeEach(() => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', origin);
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'false');
  upstream.mockReset();
  upstream.mockResolvedValue(Response.json({ accepted: true }));
});

it.each(['login', 'register', 'refresh'])('forwards the validated browser Origin for %s', async operation => {
  const response = await forward(mutation(operation, origin), context(operation));
  expect(response.status).toBe(200);
  expect(upstream).toHaveBeenCalledTimes(1);
  const [method, path, id, options] = upstream.mock.calls[0];
  expect([method, path, id]).toEqual(['POST', `/v1/auth/${operation}`, 'origin-proof']);
  expect(options.headers.get('Origin')).toBe(origin);
  expect(options.headers.get('Authorization')).toBe('Bearer synthetic-proof');
  expect(options.headers.get('Idempotency-Key')).toBe('proof-key');
  expect(options.headers.get('If-Match')).toBe('"1"');
  expect(options.headers.get('Cookie')).toBe('bt-refresh=synthetic-cookie');
  expect(options.headers.has('X-Actor-ID')).toBe(false);
});

it.each([undefined, 'https://foreign.test', 'null'])('rejects mutation Origin %s before any upstream call', async suppliedOrigin => {
  const response = await forward(mutation('login', suppliedOrigin), context('login'));
  expect(response.status).toBe(403);
  expect((await response.json()).error.code).toBe('invalid_origin');
  expect(upstream).not.toHaveBeenCalled();
});

it.each([undefined, 'https://foreign.test', 'null'])('never forwards an unvalidated read Origin %s', async suppliedOrigin => {
  const headers = new Headers();
  if (suppliedOrigin !== undefined) headers.set('Origin', suppliedOrigin);
  const response = await forward(new Request(`${origin}/api/web/v1/identity/v1/auth/session`, { headers }), context('session'));
  expect(response.status).toBe(200);
  expect(upstream.mock.calls[0][3].headers.has('Origin')).toBe(false);
});

it('accepts a configured Docker-published origin rather than the internal Next bind URL', async () => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', 'http://localhost:33101');
  const response = await forward(mutation('login', 'http://localhost:33101', 'http://0.0.0.0:3000'), context('login'));
  expect(response.status).toBe(200);
  expect(upstream.mock.calls[0][3].headers.get('Origin')).toBe('http://localhost:33101');
});

it('accepts a trusted edge origin only after explicit proxy opt-in', async () => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', '');
  const request = mutation('refresh', 'https://beirut.up.railway.app', 'http://web.internal:3000');
  request.headers.set('X-Forwarded-Host', 'beirut.up.railway.app');
  request.headers.set('X-Forwarded-Proto', 'https');
  expect((await forward(request, context('refresh'))).status).toBe(403);
  expect(upstream).not.toHaveBeenCalled();
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'true');
  expect((await forward(request, context('refresh'))).status).toBe(200);
  const headers = upstream.mock.calls[0][3].headers;
  expect(headers.get('Origin')).toBe('https://beirut.up.railway.app');
  expect(headers.has('X-Forwarded-Host')).toBe(false);
  expect(headers.has('X-Forwarded-Proto')).toBe(false);
});

it('may forward a read Origin only after the same validation', async () => {
  await forward(new Request(`${origin}/api/web/v1/identity/v1/auth/session`, { headers: { Origin: origin } }), context('session'));
  expect(upstream.mock.calls[0][3].headers.get('Origin')).toBe(origin);
});

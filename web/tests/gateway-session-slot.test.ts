import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const { identity, catalog, entry } = vi.hoisted(() => ({ identity: vi.fn(), catalog: vi.fn(), entry: vi.fn() }));
vi.mock('@/registry-loader', () => ({
  gatewayRegistrations: [
    ...['refresh', 'logout'].map(operation => ({
      service: 'identity', path: `/v1/accounts/${operation}`, methods: ['POST'], roles: ['public'], forwardCookies: ['bt_refresh'],
    })),
    { service: 'identity', path: '/v1/demo-entry/sessions', methods: ['POST'], roles: ['public'], forwardCookies: ['bt_refresh'] },
    { service: 'identity', path: '/v1/public-proof', methods: ['POST'], roles: ['public'] },
    { service: 'catalog', path: '/v1/public-proof', methods: ['POST'], roles: ['public'] },
  ],
}));
vi.mock('@/lib/bff/status', () => ({
  dependencies: new Map([['identity', { request: identity }], ['catalog', { request: catalog }]]),
  sampleEntry: { request: entry },
  serviceNames: ['identity', 'catalog'],
  requestId: () => 'slot-proof',
  privateHeaders: (id: string) => ({ 'Cache-Control': 'no-store', 'X-Request-ID': id }),
}));
import { forward } from '@/gateway/forward';

const origin = 'https://beirut.test';
const slot = 'A1b2C3d4E5f6G7h8I9j0_-';
const otherSlot = 'Zz9Yy8Xx7Ww6Vv5Uu4Tt3-';
const jar = `bt_refresh=ordinary-tab; bt_refresh_s_${slot}=this-tab; bt_refresh_s_${otherSlot}=other-tab; unrelated=not-forwarded`;

function post(service: string, path: string[], headers: Record<string, string>) {
  const request = new Request(`${origin}/api/web/v1/${service}/${path.join('/')}`, {
    method: 'POST', body: '{}', headers: { Origin: origin, 'Content-Type': 'application/json', Cookie: jar, ...headers },
  });
  return forward(request, { params: Promise.resolve({ service, path }) });
}
function sent(upstream: ReturnType<typeof vi.fn>) {
  expect(upstream).toHaveBeenCalledOnce();
  return upstream.mock.calls[0][3].headers as Headers;
}

beforeEach(() => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', origin);
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'false');
  identity.mockReset(); catalog.mockReset(); entry.mockReset();
  identity.mockResolvedValue(Response.json({ accepted: true }));
  catalog.mockResolvedValue(Response.json({ accepted: true }));
  entry.mockResolvedValue(Response.json({ accepted: true }));
});
afterEach(() => vi.unstubAllEnvs());

it.each(['refresh', 'logout'])('keeps an ordinary tab on bt_refresh alone for %s', async operation => {
  expect((await post('identity', ['v1', 'accounts', operation], {})).status).toBe(200);
  const headers = sent(identity);
  expect(headers.get('Cookie')).toBe('bt_refresh=ordinary-tab');
  expect(headers.has('X-BT-Session-Slot')).toBe(false);
});

it.each(['refresh', 'logout'])('forwards only the matching slot cookie for %s', async operation => {
  expect((await post('identity', ['v1', 'accounts', operation], { 'X-BT-Session-Slot': slot })).status).toBe(200);
  const headers = sent(identity);
  expect(headers.get('Cookie')).toBe(`bt_refresh_s_${slot}=this-tab`);
  expect(headers.get('X-BT-Session-Slot')).toBe(slot);
});

it('forwards no cookie when the named slot holds none', async () => {
  const fresh = 'Q'.repeat(22);
  await post('identity', ['v1', 'demo-entry', 'sessions'], { 'X-BT-Session-Slot': fresh });
  const headers = sent(entry);
  expect(headers.has('Cookie')).toBe(false);
  expect(headers.get('X-BT-Session-Slot')).toBe(fresh);
});

it('sends sample-account entry only through its own Identity dependency', async () => {
  await post('identity', ['v1', 'demo-entry', 'sessions'], { 'X-BT-Session-Slot': slot });
  expect(entry.mock.calls[0][1]).toBe('/v1/demo-entry/sessions');
  expect(identity).not.toHaveBeenCalled();
  await post('identity', ['v1', 'accounts', 'refresh'], { 'X-BT-Session-Slot': slot });
  expect(identity.mock.calls[0][1]).toBe('/v1/accounts/refresh');
  expect(entry).toHaveBeenCalledOnce();
});

it.each(['short', 'x'.repeat(23), `${'a'.repeat(21)};`, `${'a'.repeat(21)}=`, ''])('refuses the malformed slot %j before contacting Identity', async value => {
  const response = await post('identity', ['v1', 'accounts', 'refresh'], { 'X-BT-Session-Slot': value });
  expect(response.status).toBe(400);
  expect((await response.json()).error.code).toBe('invalid_session_slot');
  expect(identity).not.toHaveBeenCalled();
});

it('passes the slot cookie Identity sets back to the browser', async () => {
  const upstream = new Response('{}', { headers: { 'Content-Type': 'application/json' } });
  upstream.headers.append('Set-Cookie', `bt_refresh_s_${slot}=successor; HttpOnly; Path=/; SameSite=strict`);
  identity.mockResolvedValue(upstream);
  const response = await post('identity', ['v1', 'accounts', 'refresh'], { 'X-BT-Session-Slot': slot });
  expect(response.headers.getSetCookie()).toEqual([`bt_refresh_s_${slot}=successor; HttpOnly; Path=/; SameSite=strict`]);
});

it('never forwards the slot or any cookie to endpoints without refresh cookies', async () => {
  await post('identity', ['v1', 'public-proof'], { 'X-BT-Session-Slot': slot });
  await post('catalog', ['v1', 'public-proof'], { 'X-BT-Session-Slot': slot });
  for (const upstream of [identity, catalog]) {
    const headers = sent(upstream);
    expect(headers.has('Cookie')).toBe(false);
    expect(headers.has('X-BT-Session-Slot')).toBe(false);
  }
});

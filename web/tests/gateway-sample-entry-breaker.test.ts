import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

vi.mock('@/registry-loader', () => ({
  gatewayRegistrations: [
    { service: 'identity', path: '/v1/demo-entry/sessions', methods: ['POST'], roles: ['public'], forwardCookies: ['bt_refresh'] },
    { service: 'identity', path: '/v1/accounts/refresh', methods: ['POST'], roles: ['public'], forwardCookies: ['bt_refresh'] },
    { service: 'identity', path: '/v1/accounts/me', methods: ['GET'], roles: ['buyer'] },
  ],
}));
import { forward } from '@/gateway/forward';
import { dependencies, sampleEntry } from '@/lib/bff/status';

const origin = 'https://beirut.test';
const slot = 'A1b2C3d4E5f6G7h8I9j0_-';
const sampleList = JSON.parse(readFileSync(new URL('../../packages/contracts-identity/accounts/sample-accounts.v1.json', import.meta.url), 'utf8')) as { accounts: { set: string; role: string }[] };
// Every tab a kit set opens: its listed sample roles plus the Operator tab, which the list never names.
const kitTabs = [...new Set(sampleList.accounts.map(entry => entry.set))]
  .flatMap(set => [...sampleList.accounts.filter(entry => entry.set === set).map(entry => entry.role), 'operator'].map(role => ({ set, role })));
// Made at run time; nothing here can turn sample entry on anywhere.
const rightKey = crypto.randomUUID().replaceAll('-', '') + crypto.randomUUID().replaceAll('-', '');
// Identity's own shared wrong-key budget (services/identity/modules/accounts/demo_entry.py).
const refusedBudget = 30;
const calls: string[] = [];
let refused = 0;
let outage = false;

function call(method: string, path: string[], body?: unknown, headers: Record<string, string> = {}) {
  const request = new Request(`${origin}/api/web/identity/${path.join('/')}`, {
    method, body: method === 'POST' ? JSON.stringify(body ?? {}) : undefined,
    headers: { Origin: origin, 'Content-Type': 'application/json', 'X-BT-Session-Slot': slot, ...headers },
  });
  return forward(request, { params: Promise.resolve({ service: 'identity', path }) });
}
const enter = (set: string, role: string, key: string) => call('POST', ['v1', 'demo-entry', 'sessions'], { set, role, key });

beforeEach(() => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', origin);
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'false');
  calls.length = 0;
  refused = 0;
  outage = false;
  // Identity as it answers entry: a wrong key is refused until the shared wrong-key budget is
  // spent, then throttled; the right key enters, counted per set and role.
  vi.stubGlobal('fetch', vi.fn(async (url: URL, init: RequestInit) => {
    calls.push(url.pathname);
    if (outage) return Response.json({ error: { code: 'internal_error' } }, { status: 500 });
    if (url.pathname === '/v1/demo-entry/sessions') {
      const { set, role, key } = JSON.parse(new TextDecoder().decode(init.body as Uint8Array)) as { set: string; role: string; key: string };
      if (key === rightKey) return Response.json({ entered: `${set}:${role}` });
      return ++refused > refusedBudget
        ? Response.json({ error: { code: 'try_later' } }, { status: 429 })
        : Response.json({ error: { code: 'demo_entry_refused' } }, { status: 401 });
    }
    if (url.pathname === '/internal/v1/principal') return Response.json({ actor: { subject_id: 'buyer-proof' }, roles: ['buyer'] });
    return Response.json({ accepted: true });
  }));
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); sampleEntry.failures = sampleEntry.openedAt = 0; });

it('lets a correct key enter every role after a wrong-key flood spends the refused budget', async () => {
  const wrong = 'w'.repeat(43);
  const flood: [number, string][] = [];
  for (let attempt = 0; attempt < refusedBudget + 20; attempt++) {
    const answer = await enter('demo', 'buyer', wrong);
    flood.push([answer.status, (await answer.json()).error.code]);
  }
  // Every guess reached Identity, and its throttle comes back as itself, never as a 503.
  expect(flood.filter(([status]) => status === 401)).toHaveLength(refusedBudget);
  expect(flood.filter(([status]) => status === 429)).toHaveLength(20);
  expect(flood.every(([status, code]) => (status === 401 && code === 'demo_entry_refused') || (status === 429 && code === 'try_later'))).toBe(true);
  expect(calls.filter(path => path === '/v1/demo-entry/sessions')).toHaveLength(refusedBudget + 20);
  // The guesses are answers from a working Identity: entry's breaker stays closed.
  expect(sampleEntry.failures).toBe(0);
  expect(sampleEntry.openedAt).toBe(0);
  expect(kitTabs.filter(tab => tab.role === 'operator')).toHaveLength(2);
  for (const { set, role } of kitTabs) {
    const entered = await enter(set, role, rightKey);
    expect(entered.status).toBe(200);
    expect((await entered.json()).entered).toBe(`${set}:${role}`);
  }
  // The shared Identity dependency saw none of it, and ordinary sign-in and principal calls work.
  expect(dependencies.get('identity')!.failures).toBe(0);
  expect(dependencies.get('identity')!.openedAt).toBe(0);
  expect((await call('POST', ['v1', 'accounts', 'refresh'])).status).toBe(200);
  expect((await call('GET', ['v1', 'accounts', 'me'], undefined, { Authorization: 'Bearer proof' })).status).toBe(200);
  expect(calls.slice(-3)).toEqual(['/v1/accounts/refresh', '/internal/v1/principal', '/v1/accounts/me']);
});

it('still opens entry\'s own breaker when Identity really fails, and leaves ordinary calls alone', async () => {
  outage = true;
  for (let attempt = 0; attempt < 5; attempt++) expect((await enter('demo', 'buyer', rightKey)).status).toBe(503);
  // Three failures opened entry's breaker, which then stopped contacting Identity.
  expect(sampleEntry.openedAt).not.toBe(0);
  expect(calls.filter(path => path === '/v1/demo-entry/sessions')).toHaveLength(3);
  expect(dependencies.get('identity')!.failures).toBe(0);
  outage = false;
  expect((await call('POST', ['v1', 'accounts', 'refresh'])).status).toBe(200);
});

import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

vi.mock('@/registry-loader', () => ({
  gatewayRegistrations: [
    { service: 'identity', path: '/v1/demo-entry/sessions', methods: ['POST'], roles: ['public'], forwardCookies: ['bt_refresh'] },
  ],
}));
import { forward } from '@/gateway/forward';
import { dependencies, sampleEntry, sampleEntryConcurrency } from '@/lib/bff/status';

const origin = 'https://beirut.test';
const sampleList = JSON.parse(readFileSync(new URL('../../packages/contracts-identity/accounts/sample-accounts.v1.json', import.meta.url), 'utf8')) as { accounts: { set: string; role: string }[] };
const sets = [...new Set(sampleList.accounts.map(entry => entry.set))];
// A kit set opens its listed sample roles plus the Operator tab, which the list never names.
const rolesOf = (set: string) => [...sampleList.accounts.filter(entry => entry.set === set).map(entry => entry.role), 'operator'];
const slotOf = (index: number) => `tab${index}`.padEnd(22, '_');
// Identity's answers wait here until the test releases them, so every entry stays in flight together.
let held: (() => void)[];

function enter(set: string, role: string, slot: string) {
  const request = new Request(`${origin}/api/web/identity/v1/demo-entry/sessions`, {
    method: 'POST', body: JSON.stringify({ set, role, key: 'k'.repeat(43) }),
    headers: { Origin: origin, 'Content-Type': 'application/json', 'X-BT-Session-Slot': slot },
  });
  return forward(request, { params: Promise.resolve({ service: 'identity', path: ['v1', 'demo-entry', 'sessions'] }) });
}

beforeEach(() => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', origin);
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'false');
  held = [];
  vi.stubGlobal('fetch', vi.fn((url: URL, init: RequestInit) => new Promise<Response>(resolve => {
    const slot = new Headers(init.headers).get('X-BT-Session-Slot') ?? '';
    const { set, role } = JSON.parse(new TextDecoder().decode(init.body as Uint8Array)) as { set: string; role: string };
    held.push(() => resolve(Response.json({ entered: `${set}:${role}`, slot })));
  })));
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it('admits at least one whole sample set at once', () => {
  expect(sets.length).toBeGreaterThan(0);
  for (const set of sets) expect(sampleEntryConcurrency).toBeGreaterThanOrEqual(rolesOf(set).length);
  // The shared Identity limit for ordinary traffic is unchanged.
  expect(dependencies.get('identity')!.concurrency).toBe(4);
  expect(sampleEntry).not.toBe(dependencies.get('identity'));
});

it('lets every tab of one sample set enter in the same instant, each as its own account', async () => {
  for (const set of sets) {
    const roles = rolesOf(set);
    const answers = roles.map((role, index) => enter(set, role, slotOf(index)));
    // Every entry reaches Identity while the others are still waiting: none was refused as busy.
    await vi.waitFor(() => expect(held).toHaveLength(roles.length), { timeout: 1000 });
    expect(sampleEntry.active).toBe(roles.length);
    // Ordinary sign-in and principal calls keep their own limit free during the burst.
    expect(dependencies.get('identity')!.active).toBe(0);
    held.forEach(answer => answer());
    const results = await Promise.all(answers);
    expect(results.map(result => result.status)).toEqual(roles.map(() => 200));
    const bodies = await Promise.all(results.map(result => result.json() as Promise<{ entered: string; slot: string }>));
    expect(bodies).toEqual(roles.map((role, index) => ({ entered: `${set}:${role}`, slot: slotOf(index) })));
    expect(sampleEntry.failures).toBe(0);
    expect(sampleEntry.openedAt).toBe(0);
    expect(sampleEntry.active).toBe(0);
    held = [];
  }
});

it('still refuses an entry beyond the bound at once, without opening the breaker', async () => {
  const set = sets[0];
  const roles = rolesOf(set);
  const filling = Array.from({ length: sampleEntryConcurrency }, (_, index) => enter(set, roles[index % roles.length], slotOf(index)));
  await vi.waitFor(() => expect(held).toHaveLength(sampleEntryConcurrency), { timeout: 1000 });
  const extra = await enter(set, roles[0], slotOf(sampleEntryConcurrency));
  expect(extra.status).toBe(503);
  expect((await extra.json()).error.code).toBe('unavailable');
  // The extra call never reached Identity, and a busy refusal is not a failure.
  expect(held).toHaveLength(sampleEntryConcurrency);
  expect(sampleEntry.failures).toBe(0);
  expect(sampleEntry.openedAt).toBe(0);
  held.forEach(answer => answer());
  expect((await Promise.all(filling)).map(result => result.status)).toEqual(filling.map(() => 200));
});

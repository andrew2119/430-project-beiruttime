import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import sampleList from '@contracts/contracts-identity/accounts/sample-accounts.v1.json';
import { backupRoles, dropSampleKey, heldSampleTab, holdSampleTab, primaryRoles, sampleFragment, sampleSets, sampleTab, sampleTabHref, useHeldSampleTab, type SampleRole } from './sample-accounts';

const { invoke, access, ApiError } = vi.hoisted(() => ({
  invoke: vi.fn(), access: vi.fn(),
  ApiError: class ApiError extends Error { constructor(public status:number,public code:string,public requestId:string) { super(code); } },
}));
vi.mock('@/lib/api/client', () => ({ request: invoke, ApiError }));
vi.mock('@/shell/private-state', () => ({ setAccessContext: access }));
// The session hooks run here outside React: an effect runs at once and a store reads its snapshot.
vi.mock('react', () => ({
  useEffect: (effect: () => void) => { effect(); },
  useSyncExternalStore: (_subscribe: unknown, snapshot: () => unknown) => snapshot(),
}));
const sample = { access_token:'memory-only',token_type:'Bearer' as const,expires_in:300,account:{id:'subject',email:'buyer.click-test@example.test',display_name:'Sample'},principal:{actor:{subject_id:'subject',session_id:'lineage',organization_id:null},roles:['buyer'],permissions:[],organizations:[],organization_grants:[]},access_fingerprint:'sample-fingerprint' };
const slotFormat = /^[A-Za-z0-9_-]{22}$/;
const key = 'K'.repeat(20) + '_-' + 'k'.repeat(20);
let storage: Map<string, string>;
let channels: { name: string; closed: boolean }[];
let locks: string[];
beforeEach(() => {
  vi.resetModules(); invoke.mockReset(); access.mockReset();
  storage = new Map(); channels = []; locks = [];
  vi.stubGlobal('sessionStorage', {
    getItem: (name: string) => storage.get(name) ?? null,
    setItem: (name: string, value: string) => { storage.set(name, String(value)); },
    removeItem: (name: string) => { storage.delete(name); },
  });
  vi.stubGlobal('BroadcastChannel', class {
    record: { name: string; closed: boolean };
    onmessage: ((event: { data: unknown }) => void) | null = null;
    constructor(public name: string) { this.record = { name, closed: false }; channels.push(this.record); }
    postMessage() { /* Other tabs are out of scope here. */ }
    close() { this.record.closed = true; }
  });
  vi.stubGlobal('navigator', { locks: { request: (name: string, callback: () => unknown) => { locks.push(name); return Promise.resolve(callback()); } } });
});
function sentSlot(call: number) { return new Headers(invoke.mock.calls[call][1]?.headers).get('X-BT-Session-Slot'); }

describe('sample accounts', () => {
  it('names the sets and roles Identity knows and only the seed accounts on the one sample list', () => {
    const source = readFileSync(fileURLToPath(new URL('../../../services/identity/runtime/service_app/session_slots.py', import.meta.url)), 'utf8');
    const named = (constant: string) => [...new RegExp(`^${constant} = \\(([^)]*)\\)$`, 'm').exec(source)?.[1].matchAll(/'([a-z-]+)'/g) ?? []].map(match => match[1]);
    const roles = named('ROLES');
    const listedRoles = named('LISTED_ROLES');
    expect(roles.length).toBeGreaterThan(0);
    expect([...sampleSets].sort()).toEqual(named('SETS').sort());
    expect([...primaryRoles, ...backupRoles].sort()).toEqual([...roles].sort());
    // The list names every role but the operator: the Operator tab is the site's own account.
    expect([...listedRoles].sort()).toEqual(roles.filter(role => role !== 'operator').sort());
    const entries = sampleList.accounts as { set: string; role: string; email: string; account_id: string }[];
    const listed = new Map(entries.map(entry => [`${entry.set}:${entry.role}`, entry.email]));
    for (const set of sampleSets) for (const role of roles as SampleRole[]) {
      expect(sampleTab(set, role).email).toBe(role === 'operator' ? null : listed.get(`${set}:${role}`) ?? null);
      expect(sampleTab(set, role).site).toBe(role === 'operator');
    }
    for (const entry of entries) {
      expect(sampleSets).toContain(entry.set);
      expect(listedRoles).toContain(entry.role);
      expect(entry.email).toBe(`${entry.role}.${entry.set}@example.test`);
      expect(entry.account_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    }
  });
  it('gives each set its own account for a role', () => {
    expect(sampleTab('demo', 'buyer')).toEqual({ email: 'buyer.demo@example.test', site: false, start: '/watches' });
    expect(sampleTab('click-test', 'staff')).toEqual({ email: 'staff.click-test@example.test', site: false, start: '/business' });
  });
  it('gives the Operator tab of both sets the site\'s own operator account, with no address in the page', () => {
    for (const set of sampleSets) expect(sampleTab(set, 'operator')).toEqual({ email: null, site: true, start: '/operations/dashboard' });
    const entries = sampleList.accounts as { role: string; email: string }[];
    expect(entries.filter(entry => entry.role === 'operator' || entry.email.startsWith('operator.'))).toEqual([]);
  });
  it('reads only a known set, a known role and a well-formed key from the fragment', () => {
    expect(sampleFragment(`#set=demo&role=operator&k=${key}`)).toEqual({ set: 'demo', role: 'operator', key });
    expect(sampleFragment('#set=click-test&role=seller')).toEqual({ set: 'click-test', role: 'seller', key: null });
    expect(sampleFragment(`#set=click-test&k=${key}`)).toEqual({ set: 'click-test', role: null, key });
    expect(sampleFragment(`#role=buyer&k=${key}`)).toEqual({ set: null, role: 'buyer', key });
    for (const set of ['sunday', 'Demo', 'toString', '__proto__', '']) expect(sampleFragment(`#set=${set}&role=buyer`).set).toBeNull();
    for (const role of ['admin', 'toString', '__proto__', 'Buyer', '']) expect(sampleFragment(`#set=demo&role=${role}`).role).toBeNull();
    for (const bad of ['short', 'k'.repeat(31), 'k'.repeat(201), `${'k'.repeat(32)}.`, `${'k'.repeat(32)}+`]) expect(sampleFragment(`#set=demo&role=buyer&k=${encodeURIComponent(bad)}`).key).toBeNull();
    expect(sampleFragment('')).toEqual({ set: null, role: null, key: null });
  });
  it('keeps the key in the fragment of each tab link, never in the path or query', () => {
    expect(sampleTabHref('ar', 'demo', 'seller', null)).toBe('/ar/sample-tabs#set=demo&role=seller');
    const href = new URL(sampleTabHref('en', 'click-test', 'buyer', key), 'https://beirut.test');
    expect(href.pathname + href.search).toBe('/en/sample-tabs');
    expect(sampleFragment(href.hash)).toEqual({ set: 'click-test', role: 'buyer', key });
  });
});

describe('held sample tab', () => {
  it('holds its set and role for good, and its key only until the tab drops it', () => {
    holdSampleTab('demo', 'staff', key);
    expect(storage.get('bt-sample-tab')).toBe('demo:staff');
    expect(heldSampleTab()).toEqual({ set: 'demo', role: 'staff', key });
    expect(useHeldSampleTab()).toEqual({ set: 'demo', role: 'staff', key });
    dropSampleKey();
    expect(heldSampleTab()).toEqual({ set: 'demo', role: 'staff', key: null });
    expect([...storage.values()].some(value => value.includes(key))).toBe(false);
  });
  it('never holds a malformed key, and a tab opened without a key forgets an earlier one', () => {
    holdSampleTab('click-test', 'buyer', 'short');
    expect(heldSampleTab()).toEqual({ set: 'click-test', role: 'buyer', key: null });
    holdSampleTab('click-test', 'buyer', key);
    holdSampleTab('click-test', 'seller', null);
    expect(heldSampleTab()).toEqual({ set: 'click-test', role: 'seller', key: null });
    expect([...storage.values()].some(value => value.includes(key))).toBe(false);
  });
  it('ignores a tampered record or key, and a tab without storage holds nothing', () => {
    for (const raw of ['demo:admin', 'sunday:buyer', 'demo:buyer:extra', 'demo', '']) {
      storage.set('bt-sample-tab', raw);
      expect(heldSampleTab()).toBeNull();
    }
    storage.set('bt-sample-tab', 'demo:buyer');
    storage.set('bt-sample-entry-key', 'not a key');
    expect(heldSampleTab()).toEqual({ set: 'demo', role: 'buyer', key: null });
    vi.stubGlobal('sessionStorage', undefined);
    expect(() => { holdSampleTab('demo', 'buyer', key); dropSampleKey(); }).not.toThrow();
    expect(heldSampleTab()).toBeNull();
    expect(useHeldSampleTab()).toBeNull();
  });
});

describe('per-tab session slot', () => {
  it('leaves an ordinary tab on the shared sign-in, channel and lock', async () => {
    const api = await import('./session');
    invoke.mockResolvedValue(sample);
    await api.refreshSession();
    expect(sentSlot(0)).toBeNull();
    expect(channels.map(channel => channel.name)).toEqual(['bt-identity-v1']);
    expect(locks).toEqual(['bt-refresh-v1']);
    expect(api.hasSessionSlot()).toBe(false);
  });
  it('ignores a tampered slot value and stays an ordinary tab', async () => {
    storage.set('bt-session-slot', 'not;a-slot');
    const api = await import('./session');
    invoke.mockResolvedValue(sample);
    await api.refreshSession();
    expect(sentSlot(0)).toBeNull();
    expect(locks).toEqual(['bt-refresh-v1']);
  });
  it('gives a fresh tab its slot synchronously, then scopes header, channel and lock to it', async () => {
    const api = await import('./session');
    const opening = api.openSessionSlot();
    const slot = storage.get('bt-session-slot');
    expect(slot).toMatch(slotFormat);
    expect(await opening).toBe(slot);
    expect(invoke).not.toHaveBeenCalled();
    invoke.mockResolvedValue(sample);
    await api.refreshSession();
    expect(invoke.mock.calls[0][0]).toBe('/api/web/v1/identity/v1/accounts/refresh');
    expect(sentSlot(0)).toBe(slot);
    expect(channels.map(channel => channel.name)).toEqual([`bt-identity-v1:${slot}`]);
    expect(locks).toEqual([`bt-refresh-v1:${slot}`]);
  });
  it('moves an ordinary tab off the shared channel when it takes a slot', async () => {
    const api = await import('./session');
    invoke.mockResolvedValue(sample);
    await api.refreshSession();
    const slot = await api.openSessionSlot();
    expect(channels).toEqual([{ name: 'bt-identity-v1', closed: true }, { name: `bt-identity-v1:${slot}`, closed: false }]);
    expect(access).toHaveBeenLastCalledWith(null, undefined);
  });
  it('signs the previous slot out before a tab opens a new one', async () => {
    const api = await import('./session');
    const first = await api.openSessionSlot();
    invoke.mockResolvedValue({ signed_out: true });
    const second = await api.openSessionSlot();
    expect(second).toMatch(slotFormat);
    expect(second).not.toBe(first);
    expect(invoke.mock.calls.map(call => call[0])).toEqual(['/api/web/v1/identity/v1/accounts/logout']);
    expect(sentSlot(0)).toBe(first);
    expect(storage.get('bt-session-slot')).toBe(second);
  });
  it('signs a slotted tab out under its own slot only', async () => {
    const api = await import('./session');
    const slot = await api.openSessionSlot();
    invoke.mockResolvedValue({ signed_out: true });
    await api.signOut();
    expect(invoke.mock.calls.map(call => call[0])).toEqual(['/api/web/v1/identity/v1/accounts/logout']);
    expect(sentSlot(0)).toBe(slot);
    expect(locks).toEqual([`bt-refresh-v1:${slot}`]);
  });
  it('still restores an ordinary tab from its refresh cookie when the shell first renders', async () => {
    const api = await import('./session');
    invoke.mockResolvedValue(sample);
    api.useSession();
    await vi.waitFor(() => expect(api.useSessionState()).toBe('authenticated'));
    expect(invoke.mock.calls.map(call => call[0])).toEqual(['/api/web/v1/identity/v1/accounts/refresh']);
    expect(sentSlot(0)).toBeNull();
  });
  it('still restores a reloaded sample tab from its own slot cookie', async () => {
    const slot = 'A1b2C3d4E5f6G7h8I9j0_-';
    storage.set('bt-session-slot', slot);
    const api = await import('./session');
    invoke.mockResolvedValue(sample);
    api.useSession();
    await vi.waitFor(() => expect(api.useSessionState()).toBe('authenticated'));
    expect(invoke.mock.calls.map(call => call[0])).toEqual(['/api/web/v1/identity/v1/accounts/refresh']);
    expect(sentSlot(0)).toBe(slot);
  });
  it('sends no refresh for a fresh slot, which has no cookie to restore, so tabs opened together never crowd Identity', async () => {
    const api = await import('./session');
    await api.openSessionSlot();
    api.useSession();
    await Promise.resolve();
    expect(invoke).not.toHaveBeenCalled();
    expect(api.useSessionState()).toBe('signed-out');
  });
});

describe('password-free sample entry', () => {
  it('refuses to run in a tab without a slot', async () => {
    const api = await import('./session');
    await expect(api.enterSampleSession('demo', 'buyer', key)).rejects.toMatchObject({ status: 400, code: 'invalid_session_slot' });
    expect(invoke).not.toHaveBeenCalled();
  });
  it('posts the set, role and key under the tab slot and publishes the sample account', async () => {
    const api = await import('./session');
    const slot = await api.openSessionSlot();
    invoke.mockResolvedValue(sample);
    expect(await api.enterSampleSession('click-test', 'buyer', key)).toEqual(sample);
    const [path, init] = invoke.mock.calls[0];
    expect(path).toBe('/api/web/v1/identity/v1/demo-entry/sessions');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ set: 'click-test', role: 'buyer', key });
    expect(sentSlot(0)).toBe(slot);
    expect(new Headers(init.headers).has('Idempotency-Key')).toBe(false);
    expect(access).toHaveBeenLastCalledWith('sample-fingerprint', ['buyer']);
  });
  it('sends a typed sign-in in a sample tab under its slot, so Identity refuses it there', async () => {
    const api = await import('./session');
    const slot = await api.openSessionSlot();
    invoke.mockResolvedValue(sample);
    await api.beginSession('login', JSON.stringify({ email: 'buyer.click-test@example.test', password: 'typed-at-run-time' }), 'operation');
    expect(invoke.mock.calls[0][0]).toBe('/api/web/v1/identity/v1/accounts/login');
    expect(sentSlot(0)).toBe(slot);
    expect(new Headers(invoke.mock.calls[0][1].headers).get('Idempotency-Key')).toBe('operation');
  });
});

describe('busy sample entry', () => {
  const entryPath = '/api/web/v1/identity/v1/demo-entry/sessions';
  // The gateway answers 503 when entry is busy or its breaker is cooling down; the API
  // client reports its own four-second deadline or a lost connection as 503 with no reference.
  const busy = () => new ApiError(503, 'unavailable', 'support-reference');
  const timedOut = () => new ApiError(503, 'unavailable', '');
  async function settle<T>(work: Promise<T>) {
    const outcome = work.then(value => ({ value }), (error: unknown) => ({ error }));
    await vi.runAllTimersAsync();
    return outcome;
  }
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('retries a busy or timed-out entry quietly and signs the tab in once it is admitted', async () => {
    const api = await import('./session');
    const slot = await api.openSessionSlot();
    invoke.mockRejectedValueOnce(busy()).mockRejectedValueOnce(timedOut()).mockResolvedValue(sample);
    let settled = false;
    const entering = api.enterSampleSession('click-test', 'buyer', key);
    void entering.then(() => { settled = true; }, () => { settled = true; });
    await vi.advanceTimersByTimeAsync(0);
    // Waiting after the first refusal: nothing is reported to the tab, which keeps its loading state.
    expect(invoke).toHaveBeenCalledTimes(1);
    expect(settled).toBe(false);
    expect(await settle(entering)).toEqual({ value: sample });
    expect(invoke).toHaveBeenCalledTimes(3);
    for (const call of [0, 1, 2]) {
      expect(invoke.mock.calls[call][0]).toBe(entryPath);
      expect(JSON.parse(invoke.mock.calls[call][1].body)).toEqual({ set: 'click-test', role: 'buyer', key });
      expect(sentSlot(call)).toBe(slot);
    }
    expect(access).toHaveBeenLastCalledWith('sample-fingerprint', ['buyer']);
  });
  it('never retries an answer that is not a temporary refusal', async () => {
    // 429 is Identity's own throttle on a spent entry budget, which the gateway passes through.
    for (const [status, code] of [[400, 'invalid_session_slot'], [401, 'demo_entry_refused'], [403, 'forbidden'], [404, 'not_found'], [409, 'sample_account_unavailable'], [409, 'operator_link_unavailable'], [422, 'validation_error'], [429, 'try_later']] as const) {
      vi.resetModules(); invoke.mockReset(); storage.clear();
      const api = await import('./session');
      await api.openSessionSlot();
      invoke.mockRejectedValue(new ApiError(status, code, 'support-reference'));
      expect(await settle(api.enterSampleSession('demo', 'staff', key))).toEqual({ error: expect.objectContaining({ status, code }) });
      expect(invoke).toHaveBeenCalledTimes(1);
    }
  });
  it('never retries a failure that is not an API answer', async () => {
    const api = await import('./session');
    await api.openSessionSlot();
    invoke.mockRejectedValue(new TypeError('unexpected'));
    expect(await settle(api.enterSampleSession('demo', 'staff', key))).toEqual({ error: expect.any(TypeError) });
    expect(invoke).toHaveBeenCalledTimes(1);
  });
  it('stops after a bounded number of attempts and a bounded wait, then reports the refusal', async () => {
    const api = await import('./session');
    await api.openSessionSlot();
    invoke.mockRejectedValue(busy());
    const started = Date.now();
    expect(await settle(api.enterSampleSession('demo', 'buyer', key))).toEqual({ error: expect.objectContaining({ status: 503, code: 'unavailable' }) });
    expect(invoke).toHaveBeenCalledTimes(api.sampleEntryAttempts);
    expect(api.sampleEntryAttempts).toBe(8);
    // Longer than entry's ten-second breaker cooldown, and short enough to stay a quiet wait.
    expect(Date.now() - started).toBeGreaterThan(10_000);
    expect(Date.now() - started).toBeLessThanOrEqual(15_750);
  });
  it('keeps every pause short, growing and jittered', async () => {
    const api = await import('./session');
    const random = vi.spyOn(Math, 'random');
    random.mockReturnValue(0);
    const shortest = Array.from({ length: api.sampleEntryAttempts - 1 }, (_, retry) => api.sampleEntryPause(retry));
    random.mockReturnValue(0.999999);
    const longest = Array.from({ length: api.sampleEntryAttempts - 1 }, (_, retry) => api.sampleEntryPause(retry));
    random.mockRestore();
    expect(shortest.map(Math.round)).toEqual([188, 375, 750, 1500, 3000, 3000, 3000]);
    expect(longest.map(Math.round)).toEqual([250, 500, 1000, 2000, 4000, 4000, 4000]);
  });
  it('ends the attempts when the tab signs out while it waits', async () => {
    const api = await import('./session');
    await api.openSessionSlot();
    invoke.mockRejectedValueOnce(busy()).mockResolvedValue({ signed_out: true });
    const entering = api.enterSampleSession('demo', 'seller', key);
    const outcome = entering.then(value => ({ value }), (error: unknown) => ({ error }));
    await vi.advanceTimersByTimeAsync(0);
    await api.signOut();
    await vi.runAllTimersAsync();
    expect(await outcome).toEqual({ error: expect.objectContaining({ status: 401, code: 'session_changed' }) });
    expect(invoke.mock.calls.map(call => call[0])).toEqual([entryPath, '/api/web/v1/identity/v1/accounts/logout']);
  });
});

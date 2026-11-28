import { afterEach, expect, test, vi } from '../../../../web/node_modules/vitest/dist/index.js';
import registration, { createLaneBoundary, outcomeModules, registrationFromModules, readOutcome, type CompositionTransport, composeRegistrations, createCompositionBoundary, CompositionRuntime, DependencyGate, runtimePlan, type RuntimeModule } from '../../../../web/registrations/L25';
import type { Registration } from '../../../../web/registry-types';
import old03 from '../../../../web/registrations/L03';
import old04 from '../../../../web/registrations/L04';
import old05 from '../../../../web/registrations/L05';
import old07 from '../../../../web/registrations/L07';
import manifest from '../../../../contracts/registrations/L25.json';

const fragment = (lane = 'L25'): Registration => ({
  ...registration, lane: lane as Registration['lane'], namespace: `lane-${lane.toLowerCase()}`,
  routes: [{ path: '/care/:id', roles: ['buyer'], area: 'account' }],
  gateway: [{ service: 'service-operations', path: '/v1/care/:id', methods: ['GET'], roles: ['buyer'] }],
});
const entry = (id = 'L25.care'): RuntimeModule => ({ id, service: 'service-operations', migrations: ['L25_0001_care.sql'], requires: [], receives: [], destinations: [] });
afterEach(() => vi.useRealTimers());

test('manifest and empty fragment never advertise absent producer operations', () => {
  expect(manifest.lane).toBe(registration.lane);
  expect(manifest.contracts).toEqual([]);
  expect(manifest.composition.operations.map(item => item.operation_id)).toEqual(['lane-composition.migrate.v1', 'lane-composition.subscribe.v1', 'lane-composition.enable.v1']);
  expect(composeRegistrations([undefined, registration])).toEqual([registration]);
  expect(composeRegistrations([])).toEqual([]);
  for (const state of Object.values(manifest.composition.states)) { expect(state.en).toBeTruthy(); expect(state.ar).toBeTruthy(); }
});

test.each(Array.from({ length: 26 }, (_, index) => `L${String(index).padStart(2, '0')}`))('admits %s metadata', (lane: string) => {
  expect(composeRegistrations([fragment(lane)])[0].lane).toBe(lane);
});

test('preserves old metadata and rejects duplicate URLs including parameter aliases', () => {
  const old = fragment('L01');
  expect(composeRegistrations([registration, old])).toEqual([registration, old]);
  expect(() => composeRegistrations([old, { ...fragment(), routes: [{ path: '/care/:watch', roles: ['buyer'], area: 'account' }] }])).toThrow();
});

test.each(['/v1/../private', '/v1/%2e%2e/private', '/v1/care?token=x', '/internal/v3/quotes', '//v1/care', '/v1/care#x'])('rejects unsafe gateway %s', (path: string) => {
  const entry = fragment(); entry.gateway![0].path = path;
  expect(() => composeRegistrations([entry])).toThrow();
});

test('rejects invalid lanes, namespaces, permissions, budgets and repeated endpoints', () => {
  expect(() => composeRegistrations([fragment('L26')])).toThrow();
  expect(() => composeRegistrations([{ ...fragment(), namespace: '../care' }])).toThrow();
  const entry = fragment(); entry.gateway![0].roles = [];
  expect(() => composeRegistrations([entry])).toThrow();
  entry.gateway![0].roles = ['buyer']; entry.gateway![0].maxBodyBytes = 16777217;
  expect(() => composeRegistrations([entry])).toThrow();
  delete entry.gateway![0].maxBodyBytes; entry.gateway!.push({ ...entry.gateway![0], path: '/v1/care/:watch' });
  expect(() => composeRegistrations([entry])).toThrow();
});

test('independent concurrent discovery does not retain global registration state', async () => {
  const results = await Promise.all([Promise.resolve().then(() => composeRegistrations([fragment()])), Promise.resolve().then(() => composeRegistrations([fragment()]))]);
  expect(results[0]).toEqual(results[1]);
  expect(() => composeRegistrations([fragment(), fragment()])).toThrow();
});

test('plans the complete service-local migration graph before subscribing and enabling', () => {
  const first = entry('L25.base');
  const second = { ...entry(), migrations: ['L25_0002_care.sql'], requires: [first.id], receives: ['care.updated.v1'] };
  first.destinations = [{ event: 'care.updated.v1', receiver: second.id }];
  const plan = runtimePlan([second, first]);
  expect(plan.modules.map(item => item.id)).toEqual([first.id, second.id]);
  expect(plan.phases).toEqual(['migrate', 'subscribe', 'enable']);
  expect(plan.receivers).toEqual(['L25.care:care.updated.v1']);
  expect(runtimePlan([]).modules).toEqual([]);
});

test('missing, cyclic, cross-service and duplicate migrations fail closed', () => {
  expect(() => runtimePlan([{ ...entry(), requires: ['L25.absent'] }])).toThrow();
  expect(() => runtimePlan([{ ...entry(), requires: ['L25.care'] }])).toThrow();
  expect(() => runtimePlan([entry(), { ...entry('L25.other'), migrations: [] , service: 'orders', requires: ['L25.care'] }])).toThrow();
  expect(() => runtimePlan([entry(), entry('L25.other')])).toThrow();
  expect(() => runtimePlan([{ ...entry(), migrations: ['../L25_0001_care.sql'] }])).toThrow();
  expect(() => runtimePlan([{ ...entry(), destinations: [{ event: 'care.updated.v1', receiver: 'L25.absent' }] }])).toThrow();
});

test.each(['denied', 'stale', 'pending'] as const)('preserves %s without guessing success', async (state: 'denied' | 'stale' | 'pending') => {
  const gate = new DependencyGate(() => 0);
  expect(await gate.call(async () => ({ state }), 4000)).toEqual({ state });
});

test('timeout aborts, stays pending and retains the dependency concurrency slot', async () => {
  vi.useFakeTimers();
  const gate = new DependencyGate(); let signal: AbortSignal | undefined;
  const result = gate.call(async value => { signal = value; return new Promise(() => {}); }, Date.now() + 4000);
  await vi.advanceTimersByTimeAsync(1500);
  expect(await result).toEqual({ state: 'pending' }); expect(signal!.aborted).toBe(true);
  expect(await gate.call(async () => ({ state: 'current', value: true }), Date.now() + 4000)).toEqual({ state: 'unavailable' });
});

test('request budget bounds time and circuits isolate dependencies and recover', async () => {
  vi.useFakeTimers(); const gate = new DependencyGate();
  for (let count = 0; count < 3; count++) expect(await gate.call(async () => { throw new Error('lost response'); }, Date.now() + 4000)).toEqual({ state: 'pending' });
  const current = vi.fn(async () => ({ state: 'current' as const, value: 1 }));
  expect(await gate.call(current, Date.now() + 4000)).toEqual({ state: 'unavailable' }); expect(current).not.toHaveBeenCalled();
  expect(await new DependencyGate().call(current, Date.now() + 4000)).toEqual({ state: 'current', value: 1 });
  await vi.advanceTimersByTimeAsync(30000);
  expect(await gate.call(current, Date.now() + 4000)).toEqual({ state: 'current', value: 1 });
  expect(await gate.call(current, Date.now())).toEqual({ state: 'unavailable' });
  const pending = gate.call(async () => new Promise(() => {}), Date.now() + 50);
  await vi.advanceTimersByTimeAsync(50); expect(await pending).toEqual({ state: 'pending' });
});


test('preserves authoritative first-match access and budgets while removing old duplicate endpoints', () => {
  const existing: Registration[] = [old03, old04, old05, old07];
  const result = composeRegistrations([registration], existing);
  expect(result.flatMap(item => item.routes)).toEqual(existing.flatMap(item => item.routes));
  const endpoints = result.flatMap(item => item.gateway ?? []);
  expect(endpoints.filter(item => item.path === '/v1/quotes' && item.methods.includes('POST'))).toEqual([old03.gateway[0]]);
  expect(endpoints.find(item => item.path === '/v1/listings/:id/photos/:asset/:variant')).toEqual(old03.gateway[9]);
  expect(() => composeRegistrations([fragment()], [fragment('L01')])).toThrow();
});

test('activation settles every receiver before enabling and resumes the same reference', async () => {
  const first = entry('L25.base');
  const second = { ...entry(), migrations: [], receives: ['care.updated.v1'] };
  first.destinations = [{ event: 'care.updated.v1', receiver: second.id }];
  const calls: string[] = [];
  let pending = true;
  const runtime = new CompositionRuntime({
    migrate: async (item, reference) => { calls.push(`migrate:${item.id}:${reference}`); return { state: 'current', value: null }; },
    subscribe: async (_item, _event, reference) => { calls.push(`subscribe:${reference}`); return pending ? { state: 'pending' } : { state: 'current', value: null }; },
    enable: async (_item, _destination, reference) => { calls.push(`enable:${reference}`); return { state: 'current', value: null }; },
  });
  expect(await runtime.activate([registration], [second, first], 'test-activation')).toEqual({ state: 'pending' });
  expect(calls).toEqual(['migrate:L25.base:test-activation', 'migrate:L25.care:test-activation', 'subscribe:test-activation']);
  expect(await runtime.activate([registration], [second, first], 'test-replacement')).toEqual({ state: 'stale' });
  pending = false;
  expect((await runtime.activate([registration], [second, first], 'test-activation')).state).toBe('current');
  expect(calls.slice(3)).toEqual(['subscribe:test-activation', 'enable:test-activation']);
  const settled = calls.length;
  expect((await runtime.activate([registration], [second, first], 'test-activation')).state).toBe('current');
  expect(calls).toHaveLength(settled);
});

test('invalid metadata never reaches an activation adapter', async () => {
  const run = vi.fn(async () => ({ state: 'current' as const, value: null }));
  const runtime = new CompositionRuntime({ migrate: run, subscribe: run, enable: run });
  await expect(runtime.activate([registration], [{ ...entry(), requires: ['L25.absent'] }], 'test-invalid')).rejects.toThrow();
  expect(run).not.toHaveBeenCalled();
});


test('discovered boundary dispatches bounded commands and reconciles a lost receipt', async () => {
  const first = entry('L25.base');
  const second = { ...entry(), migrations: [], receives: ['care.updated.v1'] };
  first.destinations = [{ event: 'care.updated.v1', receiver: second.id }];
  const commands: string[] = [];
  let lost = true;
  const activate = createCompositionBoundary(async () => ({ fragments: [registration], modules: [second, first], existing: [] }), async (service, path, command, signal) => {
    expect(service).toBe('service-operations');
    expect(signal.aborted).toBe(false);
    expect(manifest.composition.operations.some(item => item.path === path)).toBe(true);
    commands.push(command.step_id);
    if (command.step_id.startsWith('subscribe') && lost) return { state: 'current', operation_id: 'test-wrong', step_id: command.step_id };
    return { state: 'current', operation_id: command.operation_id, step_id: command.step_id };
  });
  expect(await activate('test-boundary')).toEqual({ state: 'pending' });
  expect(commands.some(item => item.startsWith('enable'))).toBe(false);
  lost = false;
  expect((await activate('test-boundary')).state).toBe('current');
  expect(commands).toEqual(['migrate:L25.base', 'migrate:L25.care', 'subscribe:L25.care:care.updated.v1', 'subscribe:L25.care:care.updated.v1', 'enable:L25.base:L25.care:care.updated.v1']);
});


test('stalled discovery aborts with pending recovery and retains its reference', async () => {
  vi.useFakeTimers();
  let signal: AbortSignal | undefined;
  const deliver = vi.fn();
  const activate = createCompositionBoundary(async value => {
    signal = value;
    return new Promise(() => {});
  }, deliver);
  const result = activate('test-discovery');
  await vi.advanceTimersByTimeAsync(1500);
  expect(await result).toEqual({ state: 'pending' });
  expect(signal!.aborted).toBe(true);
  expect(await activate('test-replacement')).toEqual({ state: 'stale' });
  expect(await activate('test-discovery')).toEqual({ state: 'unavailable' });
  expect(deliver).not.toHaveBeenCalled();
});

test('rejected discovery stays pending, opens its own circuit and recovers on the same reference', async () => {
  vi.useFakeTimers();
  const discover = vi.fn<() => Promise<{ fragments: Registration[]; modules: RuntimeModule[]; existing: Registration[] }>>(async () => { throw new Error('test-discovery-failure'); });
  const deliver = vi.fn();
  const activate = createCompositionBoundary(discover, deliver);
  for (let count = 0; count < 3; count++) expect(await activate('test-discovery')).toEqual({ state: 'pending' });
  expect(await activate('test-discovery')).toEqual({ state: 'unavailable' });
  expect(discover).toHaveBeenCalledTimes(3);
  expect(deliver).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(30000);
  discover.mockImplementationOnce(async () => ({ fragments: [registration], modules: [], existing: [] }));
  expect((await activate('test-discovery')).state).toBe('current');
});

test('discovery and activation share one request budget', async () => {
  vi.useFakeTimers();
  const discover = async () => {
    await new Promise(resolve => setTimeout(resolve, 1000));
    return { fragments: [registration], modules: [entry('L25.base'), { ...entry(), migrations: [] }, { ...entry('L25.last'), migrations: [] }], existing: [] };
  };
  const deliver = vi.fn<CompositionTransport>(async (_service: Parameters<CompositionTransport>[0], _path: string, command: Parameters<CompositionTransport>[2]) => {
    await new Promise(resolve => setTimeout(resolve, 1200));
    return { state: 'current', operation_id: command.operation_id, step_id: command.step_id };
  });
  const result = createCompositionBoundary(discover, deliver)('test-budget');
  await vi.advanceTimersByTimeAsync(4000);
  expect(await result).toEqual({ state: 'pending' });
  expect(deliver).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(600);
});


test('default discovery export maps every owned outcome exactly once', () => {
  expect(outcomeModules.map(module => module.outcome)).toEqual(['S06', 'M11', 'E06', 'E08']);
  expect(registration).toEqual(registrationFromModules(outcomeModules));
  expect(registration.gateway).toHaveLength(4);
  expect(new Set(registration.gateway?.map(endpoint => endpoint.path)).size).toBe(4);
  for (const outcome of outcomeModules) {
    expect(outcome.connection).toBe('deferred');
    expect(outcome.operations[0].service).toBe(outcome.service);
  }
  expect(registrationFromModules([]).gateway).toEqual([]);
  expect(() => registrationFromModules([...outcomeModules, outcomeModules[0]])).toThrow();
});

test('missing outcome producers fail closed and fixtures cover recovery states', async () => {
  for (const outcome of manifest.modules) {
    expect(await readOutcome(outcome.operations[0].operation_id)).toEqual({ state: 'unavailable' });
    expect(outcome.fixtures.map(fixture => fixture.state)).toEqual(['current', 'denied', 'stale', 'pending']);
  }
  expect(await readOutcome('test-unknown')).toEqual({ state: 'denied' });
});

test('owned runtime entry uses the same module discovery and stable references', async () => {
  const deliver = vi.fn<CompositionTransport>(async (_service: Parameters<CompositionTransport>[0], _path: string, command: Parameters<CompositionTransport>[2]) => ({
    state: 'current', operation_id: command.operation_id, step_id: command.step_id,
  }));
  const activate = createLaneBoundary(deliver);
  expect(await activate('test-owned')).toEqual({ state: 'current', value: [registration] });
  expect(deliver.mock.calls.map((call: Parameters<CompositionTransport>) => call[2].module.id)).toEqual(outcomeModules.map(module => module.id).sort());
  expect((await activate('test-owned')).state).toBe('current');
  expect(deliver).toHaveBeenCalledTimes(4);
});


test('outcome reads share dependency circuits and concurrency while other services stay available', async () => {
  vi.useFakeTimers();
  const operation = outcomeModules[0].operations[0].operation_id;
  const other = outcomeModules[1].operations[0].operation_id;
  const failed = vi.fn(async () => { throw new Error('test-lost-response'); });
  for (let count = 0; count < 3; count++) expect(await readOutcome(operation, failed)).toEqual({ state: 'pending' });
  expect(await readOutcome(operation, failed)).toEqual({ state: 'unavailable' });
  expect(failed).toHaveBeenCalledTimes(3);
  const current = vi.fn(async () => ({ state: 'current' as const, value: null }));
  expect(await readOutcome(other, current)).toEqual({ state: 'current', value: null });
  await vi.advanceTimersByTimeAsync(30000);
  expect(await readOutcome(operation, current)).toEqual({ state: 'current', value: null });
  let finish!: (value: { state: 'current'; value: null }) => void;
  const held = readOutcome(operation, async () => new Promise(resolve => { finish = resolve; }));
  expect(await readOutcome(operation, current)).toEqual({ state: 'unavailable' });
  finish({ state: 'current', value: null });
  expect(await held).toEqual({ state: 'current', value: null });
  let signal: AbortSignal | undefined;
  let settle!: (value: { state: 'current'; value: null }) => void;
  const timed = readOutcome(operation, async (_outcome, _operationId, value) => {
    signal = value;
    return new Promise(resolve => { settle = resolve; });
  });
  await vi.advanceTimersByTimeAsync(1500);
  expect(await timed).toEqual({ state: 'pending' });
  expect(signal!.aborted).toBe(true);
  expect(await readOutcome(operation, current)).toEqual({ state: 'unavailable' });
  settle({ state: 'current', value: null });
  await vi.advanceTimersByTimeAsync(0);
  expect(await readOutcome(operation, current)).toEqual({ state: 'current', value: null });
});

import { expect, test } from '../../../../web/node_modules/vitest/dist/index.js';
import registration, { composeL24, type LaneModule } from '../../../../web/registrations/L24';
import type { Registration } from '../../../../web/registry-types';
import manifest from '../../../../contracts/registrations/L24.json';

function fixture(): LaneModule {
  return {
    id: 'L24.example',
    registration: {
      lane: 'L24', namespace: 'example',
      routes: [{ path: '/example', roles: ['buyer'], area: 'account' }],
      dictionaries: { en: {}, ar: {} },
      gateway: [{ service: 'orders', path: '/v1/example/:id', methods: ['GET'], roles: ['buyer'] }],
    },
  };
}

test('absent fragments expose no speculative routes, destinations or operations', () => {
  expect(registration.routes).toEqual([]);
  expect(registration.gateway).toEqual([]);
  expect(registration.slots).toEqual([]);
  expect(manifest.composition.operation_lookup).toEqual([]);
  expect(manifest.composition.missing_module_state).toBe('unavailable');
});

test('discovered metadata contributes each declaration once', () => {
  const item = fixture();
  const result = composeL24([item]);
  expect(result.routes).toEqual(item.registration.routes);
  expect(result.gateway).toEqual(item.registration.gateway);
  expect(() => composeL24([item, item])).toThrow('duplicate module');
});

test('existing public registrations remain unchanged and collisions fail closed', () => {
  const prior: Registration = { ...fixture().registration, lane: 'L00', namespace: 'prior' };
  const before = JSON.stringify(prior);
  expect(() => composeL24([fixture()], [prior])).toThrow('Duplicate registration');
  expect(JSON.stringify(prior)).toBe(before);
});

test('parameter aliases cannot duplicate an endpoint', () => {
  const prior: Registration = { ...fixture().registration, lane: 'L01', namespace: 'prior', routes: [],
    gateway: [{ service: 'orders', path: '/v1/example/:reference', methods: ['GET'], roles: ['buyer'] }] };
  expect(() => composeL24([fixture()], [prior])).toThrow('Duplicate registration');
});

test.each(['/v1/../secret', '/v1/example?all=true', '/internal/v3/example', '/v1/example#private', '/v1/%2fsecret'])(
  'rejects unsafe gateway path %s', (path: string) => {
    const item = fixture();
    item.registration.gateway![0].path = path;
    expect(() => composeL24([item])).toThrow('gateway boundary');
  },
);

test('cross-service cookies, empty access and unbounded bodies deny registration', () => {
  const item = fixture();
  item.registration.gateway![0].forwardCookies = ['session'];
  expect(() => composeL24([item])).toThrow('cookie boundary');
  delete item.registration.gateway![0].forwardCookies;
  item.registration.gateway![0].maxBodyBytes = 16777217;
  expect(() => composeL24([item])).toThrow('byte budget');
  delete item.registration.gateway![0].maxBodyBytes;
  item.registration.gateway![0].roles = [];
  expect(() => composeL24([item])).toThrow('gateway boundary');
});

test('unknown lanes and conflicting namespaces are rejected', () => {
  const item = fixture();
  item.id = 'L25.example';
  expect(() => composeL24([item])).toThrow('Invalid');
  item.id = 'L24.example';
  expect(() => composeL24([item], [{ ...item.registration, lane: 'L26', namespace: 'prior' }])).toThrow('Invalid lane');
  expect(() => composeL24([item], [{ ...item.registration, routes: [], gateway: [] }])).toThrow('Duplicate namespace');
});

test('all admitted lane boundaries preserve existing registrations', () => {
  for (let lane = 0; lane <= 25; lane++) {
    expect(composeL24([], [{ ...fixture().registration, lane: `L${String(lane).padStart(2, '0')}` }]).routes).toEqual([]);
  }
});

test('parallel composition has no shared mutable registration state', async () => {
  const item = fixture();
  const results = await Promise.all(Array.from({ length: 20 }, async () => composeL24([item])));
  results[0].routes.pop();
  expect(results.slice(1).every(result => result.routes.length === 1)).toBe(true);
  expect(item.registration.routes).toHaveLength(1);
});

test('runtime activation is receiver-first and uncertain mutations retain their reference', () => {
  expect(manifest.composition.activation_order).toEqual(['migrations', 'receivers', 'destinations', 'routes']);
  expect(manifest.composition.dependency_policy).toEqual({ timeout_ms: 2000, concurrency: 4,
    failure_threshold: 3, reset_ms: 30000, mutation_retry: 'same_operation_id', uncertain_state: 'pending' });
  expect(new Set(manifest.composition.services).size).toBe(9);
});

test('full-module plan orders all additive migrations and receiver subscriptions first', async () => {
  const { planL24 } = await import('../../../../web/registrations/L24');
  const first = { ...fixture(), service: 'orders' as const, requires: [],
    migrations: ['migrations/L24_0001_example.sql', 'migrations/L24_0002_example.sql'],
    receivers: ['example.changed.v1'], destinations: ['example.changed.v1'] };
  const second = { ...first, id: 'L24.second', requires: [first.id], migrations: ['migrations/L24_0003_example.sql'],
    registration: { ...first.registration, namespace: 'second', routes: [], gateway: [] } };
  const plan = planL24([second, first]);
  expect(plan.migrations.map(item => item.path)).toEqual([...first.migrations, ...second.migrations]);
  expect(Object.keys(plan)).toEqual(['migrations', 'receivers', 'destinations']);
  expect(() => planL24([{ ...first, requires: ['L23.missing'] }])).toThrow('unavailable');
  expect(() => planL24([{ ...first, requires: [second.id] }, second])).toThrow('Cyclic');
  expect(() => planL24([{ ...first, migrations: ['migrations/L01_0001_example.sql'] }])).toThrow('additive');
  expect(() => planL24([{ ...first, receivers: [] }])).toThrow('subscribed receiver');
});

test('dependency preserves denied, stale and lost-response fixture states', async () => {
  const { createL24Dependency } = await import('../../../../web/registrations/L24');
  const binding = { operation_id: 'example-1', actor_id: 'buyer-example', organization_id: null,
    subject_id: 'subject-example', watch_id: null, expected_revision: 1, quote_revision: 1, policy_revision: 1 };
  for (const name of ['denied', 'stale', 'lost_response'] as const) {
    const fixture = manifest.composition.fixtures[name];
    const call = createL24Dependency('orders', async () => ({ state: fixture.state as 'denied' | 'review_required' | 'pending', reason: fixture.pending_reason! }));
    expect((await call(binding)).state).toBe(fixture.state);
  }
  const lost = createL24Dependency('orders', async () => { throw new Error('response lost'); });
  expect(await lost(binding)).toEqual({ state: 'pending', reason: 'result_unknown' });
});

test('dependency timeout, saturation and circuit recovery stay isolated', async () => {
  const { vi } = await import('../../../../web/node_modules/vitest/dist/index.js');
  const { createL24Dependency } = await import('../../../../web/registrations/L24');
  const binding = { operation_id: 'example-1', actor_id: 'buyer-example', organization_id: null,
    subject_id: 'subject-example', watch_id: null, expected_revision: 1, quote_revision: 1, policy_revision: 1 };
  vi.useFakeTimers();
  try {
    const signals: AbortSignal[] = [];
    const slow = createL24Dependency('orders', async (_binding, signal) => {
      signals.push(signal);
      return new Promise<never>(() => {});
    });
    const calls = Array.from({ length: 4 }, (_, index) => slow({ ...binding, operation_id: `example-${index}` }));
    expect(await slow({ ...binding, operation_id: 'overflow' })).toEqual({ state: 'pending', reason: 'dependency_busy' });
    await vi.advanceTimersByTimeAsync(2000);
    expect((await Promise.all(calls)).every(result => result.state === 'pending')).toBe(true);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(await slow({ ...binding, operation_id: 'new' })).toEqual({ state: 'pending', reason: 'circuit_open' });
    const healthy = createL24Dependency('pricing', async () => ({ state: 'ready', value: 1 }));
    expect(await healthy(binding)).toEqual({ state: 'ready', value: 1 });
    await vi.advanceTimersByTimeAsync(30000);
    expect(await slow({ ...binding, operation_id: 'later' })).toEqual({ state: 'pending', reason: 'dependency_busy' });
    let recovered = false;
    const recovering = createL24Dependency('communications', async () => {
      if (!recovered) throw new Error('unavailable');
      return { state: 'ready', value: 1 };
    });
    for (let attempt = 0; attempt < 3; attempt++) expect((await recovering(binding)).state).toBe('pending');
    expect(await recovering(binding)).toEqual({ state: 'pending', reason: 'circuit_open' });
    recovered = true;
    await vi.advanceTimersByTimeAsync(30000);
    expect(await recovering(binding)).toEqual({ state: 'ready', value: 1 });
  } finally { vi.useRealTimers(); }
});

test('duplicate requests reuse one invocation and conflicting bindings deny', async () => {
  const { createL24Dependency } = await import('../../../../web/registrations/L24');
  const binding = { operation_id: 'example-1', actor_id: 'buyer-example', organization_id: null,
    subject_id: 'subject-example', watch_id: null, expected_revision: 1, quote_revision: 1, policy_revision: 1 };
  let count = 0;
  const call = createL24Dependency('orders', async () => { count++; return { state: 'ready', value: 1 }; });
  const first = call(binding);
  expect(call(binding)).toBe(first);
  expect(await call({ ...binding, expected_revision: 2 })).toEqual({ state: 'denied', reason: 'operation_conflict' });
  expect(await first).toEqual({ state: 'ready', value: 1 });
  expect(count).toBe(1);
  expect(await call({ ...binding, operation_id: '' })).toEqual({ state: 'denied', reason: 'invalid_binding' });
});

test('metadata connects registration, activation and bounded operation dispatch', async () => {
  const { createL24Runtime, runtimeL24, decodeL24Modules } = await import('../../../../web/registrations/L24');
  expect(runtimeL24.registration).toBe(registration);
  const item = { ...fixture(), service: 'orders' as const, requires: [],
    migrations: ['migrations/L24_0001_example.sql'], receivers: ['example.changed.v1'],
    destinations: ['example.changed.v1'], operations: [{ id: 'example.read.v1', path: '/v1/example/:id', method: 'GET' as const }] };
  const steps: string[] = [];
  const binding = { operation_id: 'example-operation', actor_id: 'buyer-example', organization_id: null,
    subject_id: 'subject-example', watch_id: null, expected_revision: 1, quote_revision: 1, policy_revision: 1 };
  const runtime = createL24Runtime({ modules: decodeL24Modules(JSON.parse(JSON.stringify([item]))) }, {
    migrate: async () => { steps.push('migration'); },
    subscribe: async () => { steps.push('receiver'); },
    enable: async () => { steps.push('destination'); },
    invoke: async (service, operation, received) => {
      expect(service).toBe('orders'); expect(operation).toBe('example.read.v1');
      expect(received).toEqual(binding); return { state: 'ready', value: 'example' };
    },
  });
  expect(runtime.registration.routes).toEqual([]);
  expect(await runtime.call('example.read.v1', binding)).toEqual({ state: 'unavailable', reason: 'runtime_inactive' });
  const activation = runtime.activate();
  expect(runtime.activate()).toBe(activation);
  expect(await activation).toBe(runtime.registration);
  expect(steps).toEqual(['migration', 'receiver', 'destination']);
  expect(runtime.registration.routes).toEqual(item.registration.routes);
  expect(await runtime.call('example.read.v1', binding)).toEqual({ state: 'ready', value: 'example' });
  expect(await runtime.call('missing', binding)).toEqual({ state: 'unavailable', reason: 'operation_unavailable' });
  expect(() => createL24Runtime({ modules: [{ ...item, operations: [...item.operations, ...item.operations] }] })).toThrow('operation lookup');
  await expect(createL24Runtime({ modules: [item] }).activate()).rejects.toThrow('unavailable');
});

test('failed receiver subscription prevents destination activation', async () => {
  const { createL24Runtime } = await import('../../../../web/registrations/L24');
  const item = { ...fixture(), service: 'orders' as const, requires: [], migrations: [],
    receivers: ['example.changed.v1'], destinations: ['example.changed.v1'], operations: [] };
  let enabled = false;
  const runtime = createL24Runtime({ modules: [item] }, {
    migrate: async () => {}, subscribe: async () => { throw new Error('subscription unavailable'); },
    enable: async () => { enabled = true; }, invoke: async () => ({ state: 'pending', reason: 'example' }),
  });
  await expect(runtime.activate()).rejects.toThrow('subscription unavailable');
  expect(enabled).toBe(false);
  expect(runtime.registration.routes).toEqual([]);
  expect(runtime.registration.gateway).toEqual([]);
});

test('operations share service saturation and circuit state while dispatch stays distinct', async () => {
  const { vi } = await import('../../../../web/node_modules/vitest/dist/index.js');
  const { createL24Runtime } = await import('../../../../web/registrations/L24');
  const item = { ...fixture(), service: 'orders' as const, requires: [], migrations: [], receivers: [], destinations: [],
    operations: ['first', 'second'].map(id => ({ id, path: '/v1/example/:id', method: 'GET' as const })) };
  const binding = { operation_id: 'test-operation', actor_id: 'buyer-example', organization_id: null,
    subject_id: 'subject-example', watch_id: null, expected_revision: 1, quote_revision: 1, policy_revision: 1 };
  const dispatched: string[] = [];
  const releases: (() => void)[] = [];
  vi.useFakeTimers();
  try {
    const runtime = createL24Runtime({ modules: [item] }, {
      migrate: async () => {}, subscribe: async () => {}, enable: async () => {},
      invoke: async (_service, operation) => {
        dispatched.push(operation);
        await new Promise<void>(resolve => releases.push(resolve));
        return { state: 'ready', value: operation };
      },
    });
    await runtime.activate();
    const calls = Array.from({ length: 4 }, (_, index) => runtime.call(index % 2 ? 'second' : 'first',
      { ...binding, operation_id: `test-${index}` }));
    expect(await runtime.call('second', binding)).toEqual({ state: 'pending', reason: 'dependency_busy' });
    await vi.advanceTimersByTimeAsync(2000);
    expect(await Promise.all(calls)).toEqual(Array(4).fill({ state: 'pending', reason: 'timeout' }));
    expect(dispatched).toEqual(['first', 'second', 'first', 'second']);
    expect(await runtime.call('second', binding)).toEqual({ state: 'pending', reason: 'circuit_open' });
    releases.forEach(resolve => resolve());
    await vi.advanceTimersByTimeAsync(30000);
    const retry = runtime.call('second', binding);
    await vi.advanceTimersByTimeAsync(0);
    releases.at(-1)!();
    expect(await retry).toEqual({ state: 'ready', value: 'second' });
  } finally { vi.useRealTimers(); }
});

test('activation resumes after subscription recovery without repeating completed steps', async () => {
  const { createL24Runtime } = await import('../../../../web/registrations/L24');
  const item = { ...fixture(), service: 'orders' as const, requires: [],
    migrations: ['migrations/L24_0001_example.sql'], receivers: ['first.v1', 'second.v1'],
    destinations: ['second.v1'], operations: [] };
  const steps: string[] = [];
  let recovered = false;
  const runtime = createL24Runtime({ modules: [item] }, {
    migrate: async () => { steps.push('migration'); },
    subscribe: async ({ event }) => {
      steps.push(event);
      if (event === 'second.v1' && !recovered) throw new Error('temporarily unavailable');
    },
    enable: async () => { steps.push('destination'); },
    invoke: async () => ({ state: 'pending', reason: 'test' }),
  });
  await expect(runtime.activate()).rejects.toThrow('temporarily unavailable');
  expect(runtime.registration.routes).toEqual([]);
  recovered = true;
  const retry = runtime.activate();
  expect(runtime.activate()).toBe(retry);
  await retry;
  expect(steps).toEqual(['migration', 'first.v1', 'second.v1', 'second.v1', 'destination']);
  expect(runtime.registration.routes).toEqual(item.registration.routes);
  expect(runtime.activate()).toBe(retry);
});

test('serialized slots resolve through the canonical loader and activate once', async () => {
  const { decodeL24Modules, createL24Runtime } = await import('../../../../web/registrations/L24');
  const component = () => null;
  const load = async () => ({ default: component });
  const components = new Map([['L24.example-panel', load]]);
  const item = { ...fixture(), service: 'orders', requires: [], migrations: [], receivers: [], destinations: [],
    operations: [], registration: { ...fixture().registration,
      slots: [{ id: 'L24.example-slot', target: 'buyer.dashboard', component: 'L24.example-panel' }] } };
  const serialized = JSON.stringify([item]);
  const modules = decodeL24Modules(JSON.parse(serialized), components);
  const runtime = createL24Runtime({ modules }, {
    migrate: async () => {}, subscribe: async () => {}, enable: async () => {},
    invoke: async () => ({ state: 'pending', reason: 'test' }),
  });
  expect(runtime.registration.slots).toEqual([]);
  await runtime.activate();
  await runtime.activate();
  expect(runtime.registration.slots).toHaveLength(1);
  const slot = runtime.registration.slots![0];
  expect(slot.id).toBe('L24.example-slot');
  expect(slot.target).toBe('buyer.dashboard');
  expect(slot.load).toBe(load);
  expect((await slot.load()).default).toBe(component);
  expect(JSON.stringify([item])).toBe(serialized);
  const second = { ...item, id: 'L24.second', registration: { ...item.registration,
    namespace: 'second', routes: [], gateway: [] } };
  expect(() => decodeL24Modules([item, second], components)).toThrow('Duplicate registration');
  expect(() => composeL24(modules, [{ ...modules[0].registration, lane: 'L01', namespace: 'prior',
    routes: [], gateway: [] }])).toThrow('Duplicate registration');
  expect(() => decodeL24Modules([item])).toThrow('Slot component unavailable');
  for (const change of [
    { target: 'private.files' }, { id: 'L23.example-slot' }, { component: '../private' },
    { component: 'L24.unknown' }, { load: 'untrusted' },
  ]) {
    const invalid = { ...item, registration: { ...item.registration,
      slots: [{ ...item.registration.slots[0], ...change }] } };
    expect(() => decodeL24Modules([invalid], components)).toThrow();
  }
});

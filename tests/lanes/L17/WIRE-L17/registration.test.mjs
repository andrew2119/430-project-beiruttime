import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import registration, { composeL17, planL17, discoverL17, applyL17, composeDiscoveredL17 } from '../../../../web/registrations/L17.ts';
import { Dependency } from '../../../../web/gateway/dependency.ts';

const manifest = JSON.parse(readFileSync(new URL('../../../../contracts/registrations/L17.json', import.meta.url)));
function leaf(id = 'record') {
  return {
    outcome: 'C08', id: `L17.${id}`, requires: [], migrations: ['migrations/L17_0001_records.sql'], receivers: [], destinations: [],
    registration: {
      lane: 'L17', namespace: `l17-${id}`, routes: [{ path: `/${id}`, roles: ['buyer'], area: 'account' }],
      dictionaries: { en: { pending: 'Result pending.' }, ar: { pending: 'النتيجة قيد الانتظار.' } },
      gateway: [{ service: 'catalog', path: `/v1/${id}/:id`, methods: ['GET'], roles: ['buyer'], maxBodyBytes: 1024, maxResponseBytes: 4096 }], slots: [],
    },
  };
}

test('absent fragments expose no route, command, slot or destination', () => {
  assert.deepEqual(registration, composeL17());
  for (const field of ['routes', 'gateway', 'slots', 'navigation']) assert.deepEqual(registration[field], []);
  assert.deepEqual(planL17([]), { modules: [], migrations: [], receivers: [], destinations: [] });
  assert.equal(readFileSync(new URL('../../../../infra/compose/L17.yaml', import.meta.url), 'utf8').trim().endsWith('services: {}'), true);
});

test('composition is deterministic, isolated and retains existing registrations', async () => {
  const a = leaf('alpha'), b = leaf('beta');
  const original = structuredClone([a, b]);
  const previous = structuredClone(a.registration);
  previous.lane = 'L01';
  previous.routes = [{ path: '/older', roles: ['public'], area: 'storefront' }];
  previous.gateway = [];
  const results = await Promise.all(Array.from({ length: 12 }, (_, i) => Promise.resolve(composeL17(i % 2 ? [a, b] : [b, a], [previous]))));
  for (const result of results) assert.deepEqual(result, results[0]);
  results[0].routes[0].roles.push('operator');
  assert.deepEqual([a, b], original);
  assert.deepEqual(previous.routes[0].roles, ['public']);
  assert.equal(results[1].routes.length, 2);
});

test('duplicate URLs, parameter aliases, methods, namespace and slots fail closed', () => {
  const a = leaf();
  assert.throws(() => composeL17([a, a]), /Duplicate/);
  assert.throws(() => composeL17([], [registration]), /Duplicate lane or namespace/);
  assert.throws(() => composeL17([], [{ ...registration, lane: 'L01' }]), /Duplicate lane or namespace/);
  const b = leaf('other');
  b.registration.gateway[0].path = '/v1/record/:reference';
  assert.throws(() => composeL17([a, b]), /Duplicate/);
  assert.throws(() => composeL17([a], [{ ...a.registration, lane: 'L01' }]), /Duplicate/);
  b.registration.gateway = [];
  b.registration.namespace = a.registration.namespace;
  assert.throws(() => composeL17([a, b]), /Duplicate/);
  const slot = { id: 'l17-details', target: 'watch.detail', load: async () => ({ default: () => null }) };
  a.registration.slots = [slot, slot];
  assert.throws(() => composeL17([a]), /Duplicate/);
});

test('concrete paths cannot shadow a differently authorized existing parameter route', () => {
  const prior = leaf().registration;
  prior.lane = 'L01';
  const current = leaf('current');
  current.registration.gateway[0].path = '/v1/record/current';
  current.registration.gateway[0].roles = ['brand'];
  assert.throws(() => composeL17([current], [prior]), /overlapping/);
  current.registration.gateway = [];
  prior.routes[0].path = '/record/:id';
  current.registration.routes[0].path = '/record/current';
  assert.throws(() => composeL17([current], [prior]), /overlapping/);
  current.registration.routes[0].path = '/different';
  current.registration.gateway = [{ ...prior.gateway[0], path: '/v1/record/current', methods: ['POST'] }];
  assert.doesNotThrow(() => composeL17([current], [prior]));
});

test('service, paths, security, translation and byte bounds are validated', () => {
  for (const mutate of [
    m => { m.registration.namespace = '../private'; },
    m => { m.registration.routes[0].path = '/record/../private'; },
    m => { m.registration.gateway[0].path = '/internal/v3/commit'; },
    m => { m.registration.gateway[0].path = '/v1/record?actor=other'; },
    m => { m.registration.gateway[0].service = 'other'; },
    m => { m.registration.gateway[0].roles = ['public']; },
    m => { m.registration.gateway[0].roles = []; },
    m => { m.registration.gateway[0].forwardCookies = ['private']; },
    m => { m.registration.gateway[0].methods = []; },
    m => { m.registration.gateway[0].maxBodyBytes = undefined; },
    m => { m.registration.gateway[0].maxResponseBytes = 16777217; },
    m => { m.registration.dictionaries.ar = {}; },
  ]) {
    const fragment = leaf(); mutate(fragment);
    assert.throws(() => composeL17([fragment]));
  }
});

test('complete additive migration plan precedes receivers and destinations', () => {
  const a = leaf('first'), b = leaf('second');
  b.requires = [a.id]; a.receivers = ['records.changed.v1']; b.destinations = ['records.changed.v1'];
  const plan = planL17([b, a]);
  assert.deepEqual(plan.modules, [a.id, b.id]);
  assert.equal(plan.migrations.length, 2);
  assert.deepEqual(plan.receivers, plan.destinations);
  b.destinations.push('records.missing.v1');
  assert.throws(() => planL17([a, b]), /receiver/);
  b.destinations = []; a.requires = [b.id];
  assert.throws(() => planL17([a, b]), /cyclic/);
  a.requires = ['L17.missing'];
  assert.throws(() => planL17([a, b]), /Missing/);
  a.requires = []; a.migrations = ['../prior.sql'];
  assert.throws(() => planL17([a, b]), /additive/);
});

test('fixture receipts cover denied, stale and lost response with stable duplicate reference', () => {
  const contract = manifest.composition;
  assert.deepEqual(contract.outcomes, ['C08', 'S01', 'S05', 'S11']);
  for (const fixture of contract.fixtures) {
    for (const key of contract.required_receipt_fields) assert.ok(Object.hasOwn(fixture, key), key);
    assert.ok(contract.states[fixture.state]);
  }
  assert.deepEqual(contract.fixtures[3], contract.fixtures[4]);
  assert.equal(contract.fixtures[3].pending_reason, 'lost_response');
  for (const state of Object.values(contract.states)) assert.ok(state.en && state.ar);
  assert.equal(contract.states.pending.retry, true);
  assert.equal(contract.states.stale.retry, false);
});

test('shared transport isolates circuits and budgets without retrying commands', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(null, { status: 503 }); };
  try {
    const policy = manifest.composition.dependency_policy;
    const unavailable = new Dependency('catalog', 'http://catalog', policy.timeout_ms, policy.concurrency, policy.cooldown_ms);
    for (let i = 0; i < 4; i++) assert.equal((await unavailable.request('POST', '/v1/record', 'same-reference')).kind, 'unavailable');
    assert.equal(calls, 3);
    globalThis.fetch = async () => new Response('current');
    assert.equal(await (await new Dependency('orders', 'http://orders').get('/v1/record', 'same-reference')).text(), 'current');
    const limited = new Dependency('catalog', 'http://catalog', 100, 1);
    let release;
    globalThis.fetch = () => new Promise(resolve => { release = resolve; });
    const pending = limited.get('/v1/record', 'same-reference');
    assert.equal((await limited.get('/v1/record', 'same-reference')).kind, 'unavailable');
    release(new Response('current')); await pending;
    assert.equal(limited.active, 0);
    globalThis.fetch = async () => new Response('too large');
    assert.equal((await limited.request('GET', '/v1/record', 'same-reference', { maxResponseBytes: 1 })).kind, 'unavailable');
    globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true }));
    const keepAlive = setTimeout(() => {}, 100);
    try { assert.equal((await new Dependency('catalog', 'http://catalog', 5).get('/v1/record', 'same-reference')).kind, 'unavailable'); }
    finally { clearTimeout(keepAlive); }
  } finally { globalThis.fetch = original; }
});


test('discovered metadata composes routes, endpoints and slots without a manual module list', () => {
  const fragment = leaf('discovered');
  fragment.registration.slots = [{ id: 'l17-discovered', target: 'watch.detail', load: async () => ({ default: () => null }) }];
  const source = path => {
    assert.equal(path, './records/L17.registration.ts');
    return { default: fragment };
  };
  source.keys = () => ['./records/L17.registration.ts'];
  const result = composeL17(discoverL17(source));
  assert.equal(result.routes[0].path, '/discovered');
  assert.equal(result.gateway[0].path, '/v1/discovered/:id');
  assert.equal(typeof result.slots[0].load, 'function');
  source.keys = () => ['../outside/L17.registration.ts'];
  assert.throws(() => discoverL17(source), /metadata path/);
});

test('runtime awaits every migration and subscription before enabling destinations', async () => {
  const fragment = leaf();
  fragment.receivers = fragment.destinations = ['records.changed.v1'];
  const calls = [];
  const runtime = {
    migrate: async (module, path) => { calls.push(['migrate', module, path]); },
    subscribe: async receiver => { calls.push(['subscribe', receiver]); },
    enable: async destination => { calls.push(['enable', destination]); },
  };
  const result = await applyL17(runtime, [fragment], []);
  assert.deepEqual(calls.map(call => call[0]), ['migrate', 'subscribe', 'enable']);
  assert.equal(result.routes.length, 1);
  for (const stage of ['migrate', 'subscribe']) {
    calls.length = 0;
    await assert.rejects(applyL17({ ...runtime, [stage]: async () => { throw new Error('unavailable'); } }, [fragment], []), /unavailable/);
    assert.equal(calls.some(call => call[0] === 'enable'), false);
  }
});


test('production discovery rejects cross-lane aliases and preserves sibling data', () => {
  const fragment = leaf('evidence');
  const prior = leaf('prior').registration;
  prior.lane = 'L01';
  prior.gateway[0] = { ...fragment.registration.gateway[0], path: '/v1/evidence/:reference' };
  const source = () => ({ default: fragment });
  source.keys = () => ['./records/L17.registration.ts'];
  const siblings = () => ({ default: prior });
  siblings.keys = () => ['./L01.ts'];
  const snapshot = structuredClone(prior);
  assert.throws(() => composeDiscoveredL17(source, siblings), /overlapping/);
  assert.deepEqual(prior, snapshot);
  prior.gateway = [];
  prior.routes = [{ ...prior.routes[0], path: '/evidence' }];
  assert.throws(() => composeDiscoveredL17(source, siblings), /overlapping/);
  prior.routes = [];
  assert.equal(composeDiscoveredL17(source, siblings).routes.length, 1);
  siblings.keys = () => ['./L17.ts'];
  assert.throws(() => composeDiscoveredL17(source, siblings), /sibling/);
});

test('runtime requires the current registry and rejects overlap before any effects', async () => {
  const fragment = leaf();
  const prior = structuredClone(fragment.registration);
  prior.lane = 'L01';
  const calls = [];
  const runtime = {
    migrate: async () => { calls.push('migrate'); },
    subscribe: async () => { calls.push('subscribe'); },
    enable: async () => { calls.push('enable'); },
  };
  await assert.rejects(applyL17(runtime, [fragment]), /Existing registrations required/);
  await assert.rejects(applyL17(runtime, [fragment], [prior]), /overlapping/);
  assert.deepEqual(calls, []);
});

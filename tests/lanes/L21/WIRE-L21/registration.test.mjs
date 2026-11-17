import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import ts from '../../../../web/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../../../../web/registrations/L21.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { composeOutcomes, lanePattern, dependencyRecovery, createOutcomeAdapter, operations, default: registration } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`);
const fragment = (outcome = 'C14') => ({
  outcome, registration: { lane: 'L21', namespace: outcome.toLowerCase(),
    routes: [{ path: `/${outcome.toLowerCase()}`, roles: ['buyer'], area: 'account' }],
    dictionaries: { en: {}, ar: {} },
    gateway: [{ service: 'service-operations', path: `/v1/${outcome.toLowerCase()}/:id`, methods: ['GET'], roles: ['buyer'] }],
  }, migrations: [], receivers: [], destinations: [],
});

test('missing fragments remain unavailable and preserve existing registrations', () => {
  assert.deepEqual(registration.routes, []);
  assert.equal(registration.gateway.length, 0);
  const existing = fragment().registration;
  const before = JSON.stringify(existing);
  assert.deepEqual(composeOutcomes([], [existing]).registration.routes, []);
  assert.equal(JSON.stringify(existing), before);
});
test('current public registrations retain their canonical paths and remain unchanged', async () => {
  const directory = new URL('../../../../web/registrations/', import.meta.url);
  const files = (await readdir(directory)).filter(file => /^L(?:0[0-9]|1[01])\.ts$/.test(file)).sort();
  assert.equal(files.length, 12);
  const existing = [];
  for (const file of files) {
    let text = await readFile(new URL(file, directory), 'utf8');
    for (const match of text.matchAll(/import (\w+) from ['"]([^'"]+\.json)['"];?/g)) {
      const value = JSON.parse(await readFile(new URL(match[2], directory), 'utf8'));
      text = text.replace(match[0], `const ${match[1]} = ${JSON.stringify(value)};`);
    }
    text = text.replace(/import ['"][^'"]+\.css['"];?/g, '');
    const output = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
    existing.push((await import(`data:text/javascript;base64,${Buffer.from(output.outputText).toString('base64')}`)).default);
  }
  assert.ok(existing.some(item => item.routes.some(route => route.path === '/')));
  const loader = await readFile(new URL('../../../../web/registry-loader.ts', import.meta.url), 'utf8');
  const isolated = loader.replace(/^import \{ registrations \} from '\.\/registry\.generated';$/m,
    `const registrations = ${JSON.stringify(existing)};`);
  assert.notEqual(isolated, loader);
  const loaded = ts.transpileModule(isolated, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  const runtime = await import(`data:text/javascript;base64,${Buffer.from(loaded.outputText).toString('base64')}`);
  assert.deepEqual(runtime.validateRegistrations(existing), existing);
  assert.ok(runtime.registeredRoutes.some(route => route.path === '/'));
  const before = JSON.stringify(existing);
  assert.deepEqual(composeOutcomes([], existing).registration.routes, []);
  assert.equal(composeOutcomes([fragment()], existing).registration.routes.length, 1);
  assert.equal(JSON.stringify(existing), before);
  const duplicate = fragment();
  duplicate.registration.routes[0].path = '/';
  assert.throws(() => composeOutcomes([duplicate], existing), /Duplicate/);
  for (const path of ['//', '/a/../b', '/a/', '/a?query=test', '/a#test']) {
    const invalid = fragment();
    invalid.registration.routes[0].path = path;
    assert.throws(() => composeOutcomes([invalid]), /Invalid registration path/);
  }
});
test('lane range includes both boundaries and excludes malformed lanes', () => {
  for (let i = 0; i <= 25; i++) assert.ok(lanePattern.test(`L${String(i).padStart(2, '0')}`));
  for (const value of ['L26', 'L99', 'L1', '../L21']) assert.equal(lanePattern.test(value), false);
});
test('independent registrations are deterministic under concurrent reads', async () => {
  const candidates = await Promise.all(Array.from({ length: 20 }, async () => composeOutcomes([fragment(), fragment('S04')])));
  for (const candidate of candidates) assert.deepEqual(candidate, candidates[0]);
  assert.equal(candidates[0].registration.gateway.length, 2);
});
test('duplicate outcomes, namespaces, parameter aliases and slots fail closed', () => {
  assert.throws(() => composeOutcomes([fragment(), fragment()]));
  const item = fragment();
  const old = structuredClone(item.registration);
  old.namespace = 'older';
  old.routes = [];
  old.gateway[0].path = '/v1/c14/:other';
  assert.throws(() => composeOutcomes([item], [old]), /Duplicate/);
  old.gateway = [];
  old.namespace = item.registration.namespace;
  assert.throws(() => composeOutcomes([item], [old]), /Duplicate/);
  old.namespace = 'older';
  old.slots = [{ id: 'summary' }];
  item.registration.slots = [{ id: 'summary' }];
  assert.throws(() => composeOutcomes([item], [old]), /Duplicate/);
});
test('invalid private endpoint authority, paths and byte limits are rejected', () => {
  for (const patch of [{ roles: ['public'] }, { roles: [] }, { service: 'orders' },
    { path: '/internal/v1/action' }, { path: '/v1/a/../b' }, { forwardCookies: ['session'] },
    { maxBodyBytes: 1048577 }, { maxResponseBytes: 0 }, { maxBodyBytes: 1.5 }]) {
    const item = fragment();
    Object.assign(item.registration.gateway[0], patch);
    assert.throws(() => composeOutcomes([item]));
  }
});
test('receivers must be subscribed before destinations can be returned', () => {
  const item = fragment();
  item.receivers = ['job.changed.v1'];
  item.destinations = ['job.changed.v1'];
  assert.throws(() => composeOutcomes([item]), /Receiver pending/);
  assert.equal(composeOutcomes([item], [], new Set(item.receivers)).registration.routes.length, 1);
});
test('full migration dependency order rejects missing, duplicate and cyclic entries', () => {
  const item = fragment();
  item.migrations = [{ id: 'L21_0002_job', after: ['L21_0001_job'] }, { id: 'L21_0001_job', after: [] }];
  assert.deepEqual(composeOutcomes([item]).migrationOrder, ['L21_0001_job', 'L21_0002_job']);
  item.migrations[1].after = ['L21_0002_job'];
  assert.throws(() => composeOutcomes([item]), /dependency/);
  item.migrations.pop();
  assert.throws(() => composeOutcomes([item]), /dependency/);
  item.migrations.push(item.migrations[0]);
  assert.throws(() => composeOutcomes([item]), /migration/);
});
test('manifest does not invent executable operations or successful provider results', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(manifest.operation_lookup), Object.keys(operations));
  assert.equal(manifest.activation, 'unavailable');
  assert.deepEqual(manifest.fixtures.map(item => item.state), ['unavailable', 'denied', 'stale', 'pending']);
  assert.equal(manifest.fixtures.at(-1).operation_id, 'fixture-4');
  assert.deepEqual(manifest.contracts, []);
  assert.equal(manifest.adapter, 'web/registrations/L21.ts:createOutcomeAdapter');
});

const dependencySource = await readFile(new URL('../../../../web/gateway/dependency.ts', import.meta.url), 'utf8');
const dependencyCompiled = ts.transpileModule(dependencySource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { Dependency } = await import(`data:text/javascript;base64,${Buffer.from(dependencyCompiled.outputText).toString('base64')}`);

test('dependency timeout aborts once and retains the pending operation reference', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    calls++;
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
    });
  });
  const dependency = new Dependency('service-operations', 'https://example.test', 5);
  // Keep the deadline observable while the simulated transport is unresolved.
  const keepAlive = setTimeout(() => {}, 1000);
  try {
    assert.equal((await dependency.request('POST', '/v1/jobs', 'fixture-operation')).kind, 'unavailable');
    assert.equal(calls, 1);
    assert.equal(dependency.active, 0);
    const recovery = dependencyRecovery('fixture-operation', true);
    assert.equal(recovery.state, 'pending');
    assert.equal(recovery.operation_id, 'fixture-operation');
    assert.equal(recovery.next_action, 'check_same_operation');
    for (const locale of ['en', 'ar']) assert.ok(recovery.message[locale]);
  } finally { clearTimeout(keepAlive); }
});

test('shared dependency budget refuses excess work without blocking another dependency', async (t) => {
  let release;
  t.mock.method(globalThis, 'fetch', () => new Promise(resolve => { release = resolve; }));
  const dependency = new Dependency('service-operations', 'https://example.test', 100, 1);
  const pending = dependency.get('/v1/jobs', 'fixture-one');
  assert.equal((await dependency.get('/v1/jobs', 'fixture-two')).kind, 'unavailable');
  assert.equal(dependency.active, 1);
  const other = new Dependency('orders', 'https://example.test', 100, 1);
  assert.equal(other.active, 0);
  release(new Response('{}'));
  assert.equal((await pending).status, 200);
  assert.equal(dependency.active, 0);
  t.mock.method(globalThis, 'fetch', async () => new Response('oversized'));
  assert.equal((await dependency.request('GET', '/v1/jobs', 'fixture-body', { maxResponseBytes: 2 })).kind, 'unavailable');
});

test('circuit opens, permits one recovery probe and closes after success', async (t) => {
  let now = 100;
  let calls = 0;
  t.mock.method(Date, 'now', () => now);
  t.mock.method(globalThis, 'fetch', async () => { calls++; throw new Error('fixture failure'); });
  const dependency = new Dependency('service-operations', 'https://example.test', 100, 4, 10);
  for (let i = 0; i < 3; i++) await dependency.get('/v1/jobs', 'fixture-operation');
  await dependency.get('/v1/jobs', 'fixture-operation');
  assert.equal(calls, 3);
  now += 10;
  let release;
  t.mock.method(globalThis, 'fetch', () => new Promise(resolve => { calls++; release = resolve; }));
  const probe = dependency.get('/v1/jobs', 'fixture-operation');
  assert.equal((await dependency.get('/v1/jobs', 'fixture-operation')).kind, 'unavailable');
  assert.equal(calls, 4);
  release(new Response('{}'));
  await probe;
  assert.equal(dependency.openedAt, 0);
  assert.equal(dependency.failures, 0);
});

test('recovery distinguishes denied, stale and unavailable without guessing success', () => {
  for (const [command, status, expected] of [[true, 403, 'denied'], [true, 409, 'stale'], [false, undefined, 'unavailable'], [true, 503, 'pending']]) {
    const result = dependencyRecovery('fixture-operation', command, status);
    assert.equal(result.state, expected);
    assert.equal(result.operation_id, 'fixture-operation');
    for (const locale of ['en', 'ar']) assert.ok(result.message[locale]);
  }
  assert.throws(() => dependencyRecovery('', true));
});

test('production adapter binds provider results and retries the same reference', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  const envelope = manifest.provider_fixtures[0];
  const calls = [];
  let response = envelope;
  const adapter = createOutcomeAdapter({ request: async (...args) => {
    calls.push(args);
    return new Response(JSON.stringify(response));
  } });
  assert.deepEqual(await adapter('customization.reconcile.v1', envelope), envelope);
  assert.deepEqual(await adapter('customization.reconcile.v1', envelope), envelope);
  assert.equal(calls[0][2], calls[1][2]);
  assert.equal(calls[0][3].maxResponseBytes, 65536);
  assert.deepEqual(JSON.parse(calls[0][3].body), envelope);
  for (const key of ['operation_id', 'actor_id', 'subject_id', 'watch_id', 'organization_id', 'expected_revision']) {
    response = { ...envelope, [key]: 'fixture-conflict' };
    assert.equal((await adapter('customization.reconcile.v1', envelope)).state, 'pending');
  }
  response = { ...envelope, state: 'paid_held' };
  assert.equal((await adapter('customization.reconcile.v1', envelope)).state, 'pending');
  for (const fixture of manifest.provider_fixtures.slice(1)) {
    response = fixture;
    assert.deepEqual(await adapter('servicing.status.v1', envelope), fixture);
  }
});

test('production adapter fails closed on denied, stale, timeout and lost responses', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  const envelope = manifest.provider_fixtures[0];
  for (const [status, state] of [[403, 'denied'], [409, 'stale'], [503, 'pending']]) {
    const adapter = createOutcomeAdapter({ request: async () => new Response('{}', { status }) });
    const result = await adapter('servicing.reconcile.v1', envelope);
    assert.equal(result.state, state);
    assert.equal(result.operation_id, envelope.operation_id);
  }
  for (const request of [async () => ({ kind: 'unavailable' }), async () => { throw new Error('fixture lost response'); }, async () => new Response('invalid')]) {
    const adapter = createOutcomeAdapter({ request });
    assert.equal((await adapter('servicing.reconcile.v1', envelope)).state, 'pending');
    assert.equal((await adapter('servicing.status.v1', envelope)).state, 'unavailable');
  }
});

test('published outcome schema covers fixtures and rejects oversized requests before transport', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  const schema = manifest.outcome_schema;
  for (const fixture of manifest.provider_fixtures) {
    assert.deepEqual(Object.keys(fixture).sort(), [...schema.required].sort());
    for (const [key, rule] of Object.entries(schema.properties)) {
      const value = fixture[key];
      if (rule.const) assert.equal(value, rule.const);
      if (rule.enum) assert.ok(rule.enum.includes(value));
      if (rule.type === 'integer') assert.ok(Number.isSafeInteger(value) && value >= rule.minimum);
      if (rule.type === 'string') assert.ok(typeof value === 'string' && value.length >= (rule.minLength ?? 0));
      if (Array.isArray(rule.type)) assert.ok(value === null || typeof value === 'string');
    }
  }
  let calls = 0;
  const adapter = createOutcomeAdapter({ request: async () => { calls++; return { kind: 'unavailable' }; } });
  await assert.rejects(adapter('customization.reconcile.v1', { ...manifest.provider_fixtures[0], subject_id: 'ع'.repeat(9000) }), /budget/);
  await assert.rejects(adapter('customization.reconcile.v1', { ...manifest.provider_fixtures[0], extra: 'fixture' }), /envelope/);
  assert.equal(calls, 0);
});


test('provider responses reject extra fields and malformed recovery fields without exposing them', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  const envelope = manifest.provider_fixtures[0];
  const invalid = [null, [], { ...envelope, private_evidence_ref: 'fixture-private-reference' }];
  for (const field of ['organization_id', 'pending_reason', 'next_actor', 'next_review_at']) {
    for (const value of [{ reference: 'fixture-private-reference' }, [], 1, false]) {
      invalid.push({ ...envelope, [field]: value });
    }
    const missing = { ...envelope };
    delete missing[field];
    invalid.push(missing);
  }
  for (const response of invalid) {
    const adapter = createOutcomeAdapter({ request: async () => new Response(JSON.stringify(response)) });
    for (const [operation, command] of [['customization.reconcile.v1', true], ['servicing.status.v1', false]]) {
      assert.deepEqual(await adapter(operation, envelope), dependencyRecovery(envelope.operation_id, command));
    }
  }
  const valid = { ...envelope, pending_reason: 'fixture-follow-up', next_actor: 'fixture-operator', next_review_at: '2026-11-18T00:00:00Z' };
  const adapter = createOutcomeAdapter({ request: async () => new Response(JSON.stringify(valid)) });
  assert.deepEqual(await adapter('servicing.status.v1', envelope), valid);
});

test('production adapter without a provider retains the same operation reference', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  const envelope = manifest.provider_fixtures[0];
  const adapter = createOutcomeAdapter();
  for (const name of Object.keys(operations)) {
    const result = await adapter(name, envelope);
    assert.equal(result.operation_id, envelope.operation_id);
    assert.equal(result.state, operations[name].method === 'GET' ? 'unavailable' : 'pending');
  }
});


test('status provider receives the requested revision and returns current or stale', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  const envelope = manifest.provider_fixtures[0];
  const calls = [];
  const adapter = createOutcomeAdapter({ request: async (method, path, reference, options) => {
    calls.push({ method, path, reference, options });
    const query = new URLSearchParams(path.split('?')[1]);
    assert.equal(query.has('expected_revision'), true);
    const expected = Number(query.get('expected_revision'));
    return new Response(JSON.stringify({ ...envelope, operation_id: reference,
      subject_id: decodeURIComponent(path.split('?')[0].split('/').at(-1)),
      expected_revision: expected, revision: 2,
      state: expected === 2 ? 'current' : 'stale',
      pending_reason: expected === 2 ? null : 'revision_changed' }));
  } });
  for (const name of ['customization.status.v1', 'servicing.status.v1']) {
    assert.deepEqual(manifest.operation_lookup[name].revision_binding, {
      location: 'query', parameter: 'expected_revision', type: 'integer', minimum: 0,
      response: 'echo_expected_revision',
    });
    for (const expected of [1, 2, 0]) {
      const result = await adapter(name, { ...envelope, expected_revision: expected });
      assert.equal(result.expected_revision, expected);
      assert.equal(result.state, expected === 2 ? 'current' : 'stale');
      assert.equal(result.operation_id, envelope.operation_id);
    }
  }
  assert.notEqual(calls[0].path, calls[1].path);
  for (const call of calls) {
    assert.equal(call.method, 'GET');
    assert.equal(call.reference, envelope.operation_id);
    assert.equal(call.options.body, undefined);
  }
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { features } from './index.mjs';
import { control, receipt, finish, prepareDevice } from './browser.mjs';

test('publishes the sixteen assigned proof contracts in order', () => {
  assert.equal(features.length, 16);
  for (const [offset, feature] of features.entries()) {
    const number = offset + 33;
    assert.deepEqual(Object.keys(feature).sort(), [
      'feature_id', 'journey', 'negative', 'proof_id', 'proof_revision', 'recovery',
    ]);
    assert.equal(feature.feature_id, `F${number}`);
    assert.equal(feature.proof_id, `f${number}-proof`);
    assert.equal(feature.proof_revision, '1');
    for (const scenario of ['journey', 'negative', 'recovery']) {
      assert.equal(typeof feature[scenario], 'function');
    }
  }
});

test('every scenario enters the real identity boundary before accessing private pages', async () => {
  const roles = ['private-seller', 'operator', 'buyer', 'buyer', 'buyer', 'buyer',
    'buyer', 'buyer', 'buyer', 'buyer', 'buyer', 'buyer', 'brand', 'reviewer', 'brand', 'brand'];
  for (const [offset, feature] of features.entries()) {
    for (const scenario of ['journey', 'negative', 'recovery']) {
      const calls = [];
      const unavailable = new Error('test identity service unavailable');
      const ctx = {
        actor: async role => { calls.push(['actor', role]); return { actor_id: 'test-current-actor' }; },
        signIn: async role => { calls.push(['signIn', role]); throw unavailable; },
        page: { evaluate: async () => {} },
      };
      await assert.rejects(feature[scenario](ctx), error => {
        assert.equal(error.cause, unavailable);
        assert.ok(error.message.startsWith(`${feature.feature_id} ${scenario}:`));
        return true;
      });
      assert.deepEqual(calls, [['actor', roles[offset]], ['signIn', roles[offset]]]);
    }
  }
});

test('refused, anonymous, missing-reference and unresolved commands cannot certify success', () => {
  const actor = { actor_id: 'test-current-actor' };
  assert.throws(() => receipt({ status: 403, json: {} }, actor));
  assert.throws(() => receipt({ status: 200, json: {} }, actor));
  assert.throws(() => receipt({ status: 200, json: { operation_id: 'test-operation', actor_id: 'test-other-actor' } }, actor));
  assert.throws(() => receipt({ status: 200, json: { operation_id: 'test-operation', state: 'pending' } }, actor, ['confirmed']));
});

test('negative cases require a real refusal and returned support reference', async () => {
  for (const result of [
    { status: 200, json: { operation_id: 'test-operation' } },
    { status: 503, json: { error: { code: 'unavailable' } } },
    { status: 422, json: { error: { code: 'invalid_revision' } } },
  ]) {
    const ctx = { page: { evaluate: async () => result, waitFor: async () => {} } };
    await assert.rejects(finish(ctx, { actor_id: 'test-current-actor' }, 'negative'));
  }
});

test('an identical retry cannot change operation, actor or effect', async () => {
  const first = { status: 200, slot: 0, json: {
    operation_id: 'test-operation', actor_id: 'test-current-actor', state: 'confirmed', revision: 2,
  } };
  for (const changed of [
    { operation_id: 'test-other-operation' }, { actor_id: 'test-other-actor' }, { revision: 3 },
  ]) {
    let reads = 0;
    const ctx = { page: { evaluate: async () => ++reads === 1 ? first : {
      status: 200, json: { ...first.json, ...changed },
    } } };
    await assert.rejects(finish(ctx, { actor_id: 'test-current-actor' }, 'recovery', ['confirmed']));
  }
});

test('missing page compositions remain deferred rather than certifying a partial journey', async () => {
  for (const id of ['F33', 'F34', 'F41', 'F42', 'F45', 'F46', 'F48']) {
    const feature = features.find(item => item.feature_id === id);
    for (const scenario of ['journey', 'negative', 'recovery']) {
      const ctx = {
        actor: async () => ({ actor_id: 'test-current-actor' }),
        signIn: async () => {},
        page: { evaluate: async () => {} },
      };
      await assert.rejects(feature[scenario](ctx), error => {
        assert.equal(error.cause.code, 'connected_proof_deferred');
        assert.match(error.message, /Connected proof deferred/);
        return true;
      });
    }
  }
});


test('an unbound device needs no revoke command before opt-in', async () => {
  const calls = [];
  const ctx = { cell: { locale: 'en' }, page: {
    evaluate: async () => calls.push('read') === 1,
  } };
  await prepareDevice(ctx, { actor_id: 'test-current-actor' });
  assert.equal(calls.length, 2);
});

test('an active device must return a confirmed revoke receipt before opt-in', async () => {
  let reads = 0;
  const ctx = { cell: { locale: 'en' }, page: {
    evaluate: async () => {
      reads++;
      if (reads === 1 || reads === 2) return true;
      if (reads === 3 || reads === 4) return undefined;
      if (reads === 5) return '[data-n09-control="current"]';
      if (reads === 6) return false;
      if (reads === 7) return { status: 200, json: {
        operation_id: 'test-revoke', actor_id: 'test-current-actor', state: 'revoked',
      } };
      return true;
    },
    click: async () => {},
  } };
  await prepareDevice(ctx, { actor_id: 'test-current-actor' });
  assert.equal(reads, 8);
});

test('saved-watch scenarios update an existing row and retain the retry reference', async () => {
  const feature = features.find(item => item.feature_id === 'F36');
  for (const mode of ['journey', 'negative', 'recovery']) {
    const controls = [], requests = [];
    let responses = 0;
    const result = mode === 'negative'
      ? { status: 409, json: { code: 'stale', request_id: 'test-refusal' } }
      : { status: 200, slot: 0, json: {
        operation_id: 'test-save', actor_id: 'test-current-actor', state: 'saved', revision: 3,
      } };
    const ctx = {
      cell: { locale: 'en' },
      actor: async () => ({ actor_id: 'test-current-actor' }),
      signIn: async () => {},
      api: async (service, method, path) => {
        requests.push([service, method, path]);
        return { status: 200, json: { items: [{ watch_id: 'test-watch', title: 'Test watch', revision: 2 }] } };
      },
      page: {
        goto: async path => assert.equal(path, '/saved'),
        waitFor: async () => {},
        click: async () => {},
        fill: async () => assert.fail('an existing saved watch must use its row'),
        evaluate: async (fn, arg) => {
          if (arg?.name) { controls.push(arg.name); return '[data-n09-control="current"]'; }
          if (fn.toString().includes("element.matches(':disabled')")) return false;
          if (fn.toString().includes('if (state.records.length)') || typeof arg === 'number') {
            responses++;
            return result;
          }
          return true;
        },
      },
    };
    assert.deepEqual(await feature[mode](ctx), {
      operation_id: mode === 'negative' ? 'test-refusal' : 'test-save', actor_id: 'test-current-actor',
    });
    assert.deepEqual(requests, [['communications', 'GET', '/v1/saved-watches?offset=0&limit=20']]);
    assert.deepEqual(controls, ['Save alert choices']);
    assert.equal(responses, mode === 'recovery' ? 2 : 1);
  }
});


test('approval scenarios reserve distinct eligible requests without changing their prerequisites', async () => {
  const { eligibleApproval } = await import('./journeys.mjs');
  const selected = [];
  const ctx = { api: async (service, method, path, body, options) => {
    assert.equal(service, 'catalog');
    assert.equal(method, 'GET');
    assert.equal(body, undefined);
    assert.equal(options.as, 'brand');
    const url = new URL(path, 'http://test.example');
    assert.equal(url.searchParams.get('organization_id'), 'test-brand');
    if (url.pathname === '/v1/customization-requests') return { status: 200, json: {
      items: ['test-approved', 'test-unready', 'test-journey', 'test-negative', 'test-recovery']
        .map(id => ({ id, revision: 2 })), next_cursor: null,
    } };
    if (url.pathname.endsWith('/decision')) return { status: 200, json: {
      status: path.includes('test-approved') ? 'approved' : 'not_decided',
    } };
    return { status: 200, json: { status: path.includes('test-unready') ? 'unavailable' : 'available' } };
  } };
  for (let attempt = 0; attempt < 3; attempt++) selected.push((await eligibleApproval(ctx, 'test-brand')).id);
  assert.deepEqual(selected, ['test-journey', 'test-negative', 'test-recovery']);
  await assert.rejects(eligibleApproval(ctx, 'test-brand'), { code: 'connected_proof_deferred' });
});


test('named menu triggers and radio menu choices are discoverable in both languages', async () => {
  for (const name of ['Source', 'المصدر']) {
    for (const [kind, selector, attributes] of [
      ['field', 'button[aria-haspopup="menu"]', { 'aria-label': name, 'aria-haspopup': 'menu' }],
      ['choice', '[role=menuitemradio]', { role: 'menuitemradio' }],
      ['field', '[role=combobox]', { role: 'combobox', 'aria-label': `${name}: selected` }],
      ['choice', '[role=option]', { role: 'option' }],
    ]) {
      const element = {
        textContent: name,
        getAttribute: key => attributes[key] ?? null,
        getClientRects: () => [{}],
        matches: () => false,
        cloneNode: () => ({ textContent: name, querySelectorAll: () => [] }),
        setAttribute: (key, value) => { attributes[key] = value; },
      };
      const ctx = { page: { evaluate: async (fn, args) => runInNewContext(
        `(${fn.toString()})(args)`, {
          args,
          document: { querySelectorAll: query => {
            assert.ok(query.split(',').includes(selector), `Missing ${selector}`);
            return [element];
          } },
        },
      ) } };
      assert.equal(await control(ctx, name, kind), '[data-n09-control="current"]');
      assert.equal(attributes['data-n09-control'], 'current');
    }
  }
});

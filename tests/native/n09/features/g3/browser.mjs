import assert from 'node:assert/strict';

export function requireValue(value, message) {
  assert.ok(value, `Connected prerequisite: ${message}`);
  return value;
}

export async function signedIn(ctx, role) {
  const actor = await ctx.actor(role);
  requireValue(actor.actor_id, `${role} has no current identity`);
  await ctx.signIn(role);
  return actor;
}

export async function read(ctx, service, path, role = 'buyer') {
  const result = await ctx.api(service, 'GET', path, undefined, { as: role });
  assert.equal(result.status, 200, `${service} ${path}: current source unavailable`);
  return result.json;
}

// Resolve controls by their visible name, independent of shared composition tags.
export async function control(ctx, name, kind = 'button', index = 0) {
  const selector = await ctx.page.evaluate(({ name, kind, index }) => new Promise(resolve => {
    const visible = element => !!element.getClientRects().length;
    const text = element => {
      const copy = element.cloneNode(true);
      copy.querySelectorAll('[aria-hidden=true],svg').forEach(item => item.remove());
      return copy.textContent.trim();
    };
    const label = element => element.getAttribute('aria-label') ||
      (element.getAttribute('aria-labelledby') || '').split(' ').filter(Boolean)
        .map(id => document.getElementById(id)).filter(Boolean).map(text).join(' ') ||
      [...(element.labels || [])].map(text).join(' ').trim() || text(element);
    const query = kind === 'field' ? 'input:not([type=hidden]),textarea,select,[role=combobox],button[aria-haspopup="menu"]' :
      kind === 'choice' ? 'input[type=radio],[role=radio],[role=option],[role=menuitemradio]' :
      kind === 'switch' ? 'input[type=checkbox],[role=switch],[role=checkbox]' :
      'button,[role=button],a';
    const find = () => {
      const found = [...document.querySelectorAll(query)].filter(element => {
        const actual = label(element).replace(/\s+/g, ' ').trim();
        return visible(element) && (actual === name ||
          element.getAttribute('role') === 'combobox' && actual.startsWith(name + ': '));
      });
      const element = found[index];
      if (!element || element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true') return false;
      element.setAttribute('data-n09-control', 'current');
      return true;
    };
    if (find()) return resolve('[data-n09-control="current"]');
    const observer = new MutationObserver(() => { if (find()) finish('[data-n09-control="current"]'); });
    const timer = setTimeout(() => finish(null), 8000);
    const finish = value => { clearTimeout(timer); observer.disconnect(); resolve(value); };
    observer.observe(document.body, { subtree: true, childList: true, attributes: true });
  }), { name, kind, index });
  return requireValue(selector, `visible ${kind}: ${name}`);
}

export async function click(ctx, name, kind = 'button', index = 0) {
  await ctx.page.evaluate(() => document.querySelectorAll('[data-n09-control]').forEach(e => e.removeAttribute('data-n09-control')));
  const selector = await control(ctx, name, kind, index);
  const disabled = await ctx.page.evaluate(selector => {
    const element = document.querySelector(selector);
    return element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true';
  }, selector);
  assert.equal(disabled, false, `Connected prerequisite: ${name} is disabled`);
  await ctx.page.click(selector);
}

export async function fill(ctx, name, value) {
  await ctx.page.evaluate(() => document.querySelectorAll('[data-n09-control]').forEach(e => e.removeAttribute('data-n09-control')));
  await ctx.page.fill(await control(ctx, name, 'field'), value);
}

export async function visible(ctx, text, scope = 'body') {
  const found = await ctx.page.evaluate(({ text, scope }) => new Promise(resolve => {
    const check = () => (Array.isArray(text) ? text : [text]).some(value => document.querySelector(scope)?.innerText.includes(value));
    if (check()) return resolve(true);
    const observer = new MutationObserver(() => { if (check()) finish(true); });
    const timer = setTimeout(() => finish(false), 8000);
    const finish = value => { clearTimeout(timer); observer.disconnect(); resolve(value); };
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
  }), { text, scope });
  assert.ok(found, `Expected visible result: ${text}`);
}

export async function linkedPage(ctx, start, pathPattern) {
  await ctx.page.goto(start);
  await ctx.page.waitFor('h1', { timeout: 8000 });
  const href = await ctx.page.evaluate(pattern => {
    const links = [...document.querySelectorAll('a[href]')];
    return links.map(link => link.getAttribute('href')).find(href => new RegExp(pattern).test(href));
  }, pathPattern);
  requireValue(href, `published destination matching ${pathPattern}`);
  const url = new URL(href, ctx.origin);
  assert.equal(url.origin, new URL(ctx.origin).origin);
  await ctx.page.goto(url.pathname.replace(/^\/(en|ar)(?=\/)/, '') + url.search);
}

// The page sends every command. This observer preserves the actual response and
// retains request bytes only in that page's memory for one identical retry.
export async function observe(ctx, pattern, invalid = false) {
  await ctx.page.evaluate(({ pattern, invalid }) => {
    if (window.__btN09) window.fetch = window.__btN09.original;
    const original = window.fetch;
    const state = { original, records: [], requests: [], pattern, invalid };
    window.__btN09 = state;
    window.fetch = async function(input, init) {
      let request = new Request(input, init);
      const matches = new RegExp(pattern).test(new URL(request.url).pathname) && request.method !== 'GET';
      if (matches && state.invalid) {
        const body = await request.clone().json();
        const field = ['expected_revision', 'draft_revision', 'source_revision'].find(key => key in body);
        if (!field) throw new Error('No published revision field for this negative case');
        body[field] = -1;
        request = new Request(request, { body: JSON.stringify(body) });
        state.invalid = false;
      }
      const slot = matches ? state.requests.push(request.clone()) - 1 : -1;
      const response = await original.call(window, request);
      if (matches) {
        const json = await response.clone().json().catch(() => null);
        state.records.push({ slot, status: response.status, json,
          request_id: response.headers.get('x-request-id') });
        window.dispatchEvent(new Event('bt:n09-response'));
      }
      return response;
    };
  }, { pattern, invalid });
}

export async function response(ctx) {
  const result = await ctx.page.evaluate(() => new Promise(resolve => {
    const state = window.__btN09;
    if (state.records.length) return resolve(state.records.at(-1));
    const done = () => { clearTimeout(timer); window.removeEventListener('bt:n09-response', done); resolve(state.records.at(-1)); };
    const timer = setTimeout(() => { window.removeEventListener('bt:n09-response', done); resolve(null); }, 8000);
    window.addEventListener('bt:n09-response', done);
  }));
  return requireValue(result, 'the page did not return the feature command');
}

export function receipt(result, actor, states) {
  assert.ok(result.status >= 200 && result.status < 300, `Command refused: ${result.status}`);
  const value = requireValue(result.json, 'missing command receipt');
  const operation = value.operation_id || value.operation?.operation_id || value.id || value.draft?.id;
  requireValue(operation, 'receipt has no operation or durable resource reference');
  if (value.actor_id) assert.equal(value.actor_id, actor.actor_id);
  if (states) assert.ok(states.includes(value.state ?? value.status), `Unexpected result: ${value.state ?? value.status}`);
  return { operation_id: operation, actor_id: actor.actor_id };
}

export async function finish(ctx, actor, mode, states, expected) {
  const result = await response(ctx);
  if (mode === 'negative') {
    assert.ok([400, 409, 422].includes(result.status), `Invalid revision accepted: ${result.status}`);
    requireValue(result.json?.code || result.json?.error || result.json?.detail, 'missing refusal reason');
    await ctx.page.waitFor('[role=alert],[role=status]', { timeout: 8000 });
    const operation = result.json?.error?.request_id || result.json?.request_id || result.request_id;
    requireValue(operation, 'refusal has no returned request reference');
    return { operation_id: operation, actor_id: actor.actor_id };
  }
  const proof = receipt(result, actor, states);
  if (expected) await visible(ctx, expected);
  if (mode === 'recovery') {
    const again = await ctx.page.evaluate(async slot => {
      const state = window.__btN09;
      const request = new Request(state.requests[slot].clone(), { signal: AbortSignal.timeout(8000) });
      const response = await state.original.call(window, request);
      return { status: response.status, json: await response.json() };
    }, result.slot);
    assert.deepEqual(receipt(again, actor, states), proof, 'retry changed the durable reference');
    assert.deepEqual(again.json, result.json, 'identical retry changed the receipt');
    // The exact same request must resolve without another effect, while the
    // mounted page continues to show its confirmed user-visible outcome.
    if (expected) await visible(ctx, expected);
  }
  return proof;
}

export function deferred(feature, connection) {
  const error = new Error(`Connected proof deferred: ${feature}: ${connection}`);
  error.code = 'connected_proof_deferred';
  throw error;
}

// Use the real revoke command before another opt-in on the same installation.
export async function prepareDevice(ctx, actor) {
  const ar = ctx.cell.locale === 'ar';
  await visible(ctx, ar ? ['هذا الجهاز مرتبط.', 'هذا الجهاز غير مرتبط.', 'تمت إزالة ارتباط هذا الجهاز.'] :
    ['This device is connected.', 'This device is not connected.', 'This device binding has been removed.']);
  const active = await ctx.page.evaluate(() => [...document.querySelectorAll('button')]
    .some(element => ['Remove this device binding', 'إزالة ارتباط هذا الجهاز'].includes(element.textContent.trim()) && !element.disabled));
  if (!active) return;
  await observe(ctx, '/communications/v1/browser-push/devices$');
  await click(ctx, ar ? 'إزالة ارتباط هذا الجهاز' : 'Remove this device binding');
  receipt(await response(ctx), actor, ['revoked']);
  await visible(ctx, ar ? 'تمت إزالة ارتباط هذا الجهاز.' : 'This device binding has been removed.');
}

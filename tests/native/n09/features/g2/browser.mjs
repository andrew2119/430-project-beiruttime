import assert from 'node:assert/strict';

export async function enter(ctx, role, path) {
  const actor = await ctx.actor(role);
  assert.ok(actor.actor_id, 'The signed-in account must have a real identity');
  await ctx.signIn(role);
  await ctx.page.goto(path);
  await ctx.page.waitFor('h1', {timeout: 10000});
  const settings = await ctx.page.evaluate(() => ({
    language: document.documentElement.lang,
    direction: document.documentElement.dir,
    dark: document.documentElement.classList.contains('dark') || document.documentElement.dataset.theme === 'dark',
  }));
  assert.equal(settings.language.split('-')[0], ctx.cell.locale);
  assert.equal(settings.direction, ctx.cell.locale === 'ar' ? 'rtl' : 'ltr');
  assert.equal(settings.dark, ctx.cell.theme === 'dark');
  return actor;
}

export async function button(ctx, en, ar = en, occurrence) {
  const label = ctx.cell.locale === 'ar' ? ar : en;
  const selector = await ctx.page.evaluate(async (label, occurrence) => {
    const deadline = Date.now() + 10000;
    let matches;
    do {
      matches = [...document.querySelectorAll('button, a, [role="button"]')]
      .filter(node => node.textContent.trim() === label && node.getClientRects().length && !node.disabled);
      if (occurrence === undefined ? matches.length === 1 : matches.length > occurrence) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    } while (Date.now() < deadline);
    if (occurrence === undefined ? matches.length !== 1 : matches.length <= occurrence) throw new Error(`Expected one available control: ${label}; found ${matches.length}`);
    matches[occurrence ?? 0].setAttribute('data-n09-control', 'current');
    return '[data-n09-control="current"]';
  }, label, occurrence);
  await ctx.page.click(selector);
  await ctx.page.evaluate(() => document.querySelectorAll('[data-n09-control]').forEach(node => node.removeAttribute('data-n09-control')));
}

export async function field(ctx, en, ar, value) {
  const label = ctx.cell.locale === 'ar' ? ar : en;
  const selector = await ctx.page.evaluate(label => {
    const labels = [...document.querySelectorAll('label')].filter(node => node.textContent.trim() === label);
    const nodes = labels.map(node => node.control || node.querySelector('input,textarea'));
    if (nodes.length !== 1 || !nodes[0]) throw new Error(`Required field missing or ambiguous: ${label}`);
    nodes[0].setAttribute('data-n09-field', 'current');
    return '[data-n09-field="current"]';
  }, label);
  await ctx.page.fill(selector, String(value));
  await ctx.page.evaluate(() => document.querySelectorAll('[data-n09-field]').forEach(node => node.removeAttribute('data-n09-field')));
}

export async function check(ctx, scope = 'main') {
  const selectors = await ctx.page.evaluate(scope => {
    const nodes = [...document.querySelectorAll(`${scope} input[type="checkbox"], ${scope} [role="checkbox"]`)]
      .filter(node => node.getClientRects().length && !node.disabled && !node.checked && node.getAttribute('aria-checked') !== 'true');
    if (!nodes.length) throw new Error('Required acknowledgement is missing');
    return nodes.map((node, index) => {node.setAttribute('data-n09-check', String(index));return `[data-n09-check="${index}"]`;});
  }, scope);
  for (const selector of selectors) await ctx.page.click(selector);
}

// Observe only the selected operation. Session headers never leave the page.
export async function observe(ctx, path, method = 'POST', lose = false) {
  await ctx.page.evaluate((path, method, lose) => {
    window.__n09Restore?.();
    const original = window.fetch;
    const records = [];
    let dropped = false;
    window.__n09Records = records;
    window.__n09Restore = () => {window.fetch = original;delete window.__n09Restore;};
    window.fetch = async function(input, init) {
      const url = new URL(typeof input === 'string' ? input : input.url ?? String(input), location.origin);
      const verb = init?.method ?? input?.method ?? 'GET';
      const response = await original.call(this, input, init);
      const lookup = lose && verb.toUpperCase() === 'GET' && records[0]?.key &&
        url.pathname === `/api/web/v1/auction/v1/auction-operations/by-key/${encodeURIComponent(records[0].key)}`;
      if ((url.pathname === path && verb.toUpperCase() === method) || lookup) {
        let json;
        try {json = await response.clone().json();} catch {json = null;}
        const headers = new Headers(init?.headers);
        records.push({path: url.pathname + url.search, method: verb.toUpperCase(), body: typeof init?.body === 'string' ? init.body : null,
          key: headers.get('Idempotency-Key'), status: response.status, json});
        if (lose && !dropped && response.ok) {dropped = true;throw new TypeError('Response lost after acceptance');}
      }
      return response;
    };
  }, path, method, lose);
}

export async function received(ctx, count = 1) {
  return ctx.page.evaluate(async count => {
    const deadline = Date.now() + 15000;
    while ((window.__n09Records?.length ?? 0) < count) {
      if (Date.now() >= deadline) throw new Error('The page did not return the required operation');
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    return window.__n09Records[count - 1];
  }, count);
}

export function confirmed(record, states) {
  assert.ok(record.status >= 200 && record.status < 300, `Operation refused (${record.status})`);
  const value = record.json?.result ?? record.json;
  assert.ok(value && typeof value === 'object', 'Missing operation response');
  const state = value.status ?? value.state;
  if (states) assert.ok(states.includes(state), `Unconfirmed operation state: ${state}`);
  assert.ok(!['pending','denied','unavailable','failed','allocation_pending'].includes(state), `Unconfirmed operation: ${state}`);
  return value;
}

export function reference(value) {
  const id = value?.operation_id ?? value?.id ?? value?.request_id ?? value?.reference ?? value?.auction_id ?? value?.order_id;
  assert.ok(typeof id === 'string' && id.length > 0, 'The app must return an operation or request reference');
  return id;
}

export async function visible(ctx, text) {
  assert.ok(typeof text === 'string' && text.length > 0);
  const found = await ctx.page.evaluate(async text => {
    const deadline = Date.now() + 10000;
    while (!document.body.innerText.includes(text)) {
      if (Date.now() >= deadline) return false;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    return true;
  }, text);
  assert.ok(found, `Expected page content: ${text}`);
}

export async function api(ctx, service, path, role = 'buyer') {
  const result = await ctx.api(service, 'GET', path, undefined, {as: role});
  assert.equal(result.status, 200, `Required current record unavailable: ${service}${path}`);
  return result.json;
}

export async function refusal(ctx, record) {
  const actor = await ctx.actor('buyer2');
  const schedule = record.path.startsWith('/api/web/v2/auction-schedules');
  const service = schedule ? 'auction' : record.path.split('/')[4];
  let path = schedule ? '/v1/auctions' : record.path.replace(`/api/web/v1/${service}`, '');
  const url = new URL(path, 'http://localhost');
  const report = record.method === 'GET' && url.pathname === '/internal/v1/financial-reports';
  let request;
  if (report) {
    request = JSON.parse(url.searchParams.get('request'));
    assert.ok(request?.subject_id && request.order_id, 'A protected receipt scope is required');
    request = {...request, actor_id: actor.actor_id, operation_id: ctx.uniq('test-report-denied')};
    url.searchParams.set('request', JSON.stringify(request));
    path = url.pathname + url.search;
  }
  const result = await ctx.api(service, record.method, path, record.body ? JSON.parse(record.body) : undefined, {as: 'buyer2'});
  if (report) {
    assert.equal(result.status, 200, 'The report request must reach its scope check');
    assert.equal(result.json?.state, 'denied');
    assert.equal(result.json?.pending_reason, 'scope_denied');
    assert.equal(result.json?.operation_id, request.operation_id);
  }
  assert.ok([401,403,404,409,422].includes(result.status) || ['denied','invalid','stale'].includes(result.json?.state),
    `The unrelated account was not refused (${result.status})`);
  assert.ok(!result.json?.order && !result.json?.items && !result.json?.result?.subject_id, 'Refusal exposed private records');
  return {operation_id: reference(result.json?.error?.request_id ? result.json.error : result.json?.result ?? result.json), actor_id: actor.actor_id};
}

export async function mutate(ctx, mode, spec) {
  const actor = await spec.prepare(ctx);
  await observe(ctx, spec.path(ctx), 'POST', mode === 'recovery');
  try {
    await spec.submit(ctx);
    const first = await received(ctx);
    const value = confirmed(first, spec.states);
    if (mode === 'negative') return await refusal(ctx, first);
    let final = value;
    if (mode === 'recovery') {
      if (!spec.reconciles) await spec.retry(ctx);
      const second = await received(ctx, 2);
      if (spec.reconciles) {
        assert.ok(first.key, 'Reconciliation requires the original operation key');
        assert.equal(second.method, 'GET');
        assert.equal(new URL(second.path, ctx.origin).pathname,
          `/api/web/v1/auction/v1/auction-operations/by-key/${encodeURIComponent(first.key)}`);
      } else {
        assert.equal(second.body, first.body, 'Retry changed the original command');
        assert.equal(second.key, first.key, 'Retry changed its idempotency reference');
      }
      final = confirmed(second, spec.states);
      assert.equal(reference(final), reference(value), 'Retry created another operation');
    }
    await spec.verify(ctx, final);
    return {operation_id: reference(final), actor_id: actor.actor_id};
  } finally {
    await ctx.page.evaluate(() => window.__n09Restore?.());
  }
}

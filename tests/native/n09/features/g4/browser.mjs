import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

export const check = assert;
export async function words(ctx, feature) {
  return JSON.parse(await readFile(new URL(`../../../../../web/features/${feature}/${ctx.cell.locale}.json`, import.meta.url), 'utf8'));
}

export async function start(ctx, role, path) {
  const actor = await ctx.actor(role);
  assert.ok(actor.actor_id, 'The current account must have a returned identity');
  await ctx.signIn(role);
  await ctx.page.goto(path);
  await ctx.page.waitFor('main h1', { timeout: 10000 });
  const cell = await ctx.page.evaluate(() => ({locale:document.documentElement.lang,
    direction:document.documentElement.dir,theme:document.documentElement.dataset.theme,width:innerWidth}));
  assert.equal(cell.locale,ctx.cell.locale);
  assert.equal(cell.direction,ctx.cell.locale === 'ar' ? 'rtl' : 'ltr');
  assert.equal(cell.theme,ctx.cell.theme);
  assert.equal(cell.width,ctx.cell.width);
  await ctx.page.evaluate(() => {
    if (window.__g4Installed) { window.__g4Responses = []; return; }
    window.__g4Installed = true;
    const original = window.fetch;
    window.__g4Responses = [];
    window.fetch = async (...args) => {
      const response = await original(...args);
      const url = String(args[0]?.url ?? args[0]);
      if (/\/api\/web\/|\/passports\/.*\/read/.test(url)) {
        let json;
        try { json = await response.clone().json(); } catch { json = null; }
        window.__g4Responses.push({ url, method: args[1]?.method ?? args[0]?.method ?? 'GET', status: response.status, json,
          request_id: response.headers.get('x-request-id') });

      }
      return response;
    };
  });
  return actor;
}

// Resolve labels to controls without depending on shared component markup.
export async function control(ctx, label) {
  const selector = await ctx.page.evaluate(async (label) => {
    const end = Date.now()+8000;
    while (true) {
    const visible = el => el.getClientRects().length > 0;
    let element = [...document.querySelectorAll('input,textarea,select,[role="combobox"],[role="checkbox"]')]
      .find(el => visible(el) && (el.getAttribute('aria-label') === label ||
        [...(el.labels ?? [])].some(item => item.textContent.trim() === label) ||
        (el.getAttribute('aria-labelledby') ?? '').split(' ').some(id => document.getElementById(id)?.textContent.trim() === label)));
    if (!element) {
      const text = [...document.querySelectorAll('label')].find(el => visible(el) && el.textContent.trim() === label);
      element = text?.control ?? text?.querySelector('input,textarea,[role="checkbox"]');
    }
    if (!element) {
      if(Date.now()>end)return null;
      await new Promise(resolve=>setTimeout(resolve,40));
      continue;
    }
    element.setAttribute('data-g4-control', 'selected');
    return '[data-g4-control="selected"]';
    }
  }, label);
  assert.ok(selector, `Missing visible field: ${label}`);
  return selector;
}
export async function fill(ctx, label, value) {
  const selector = await control(ctx, label);
  await ctx.page.fill(selector, String(value));
  await clearMarker(ctx);
}
async function clearMarker(ctx) {
  await ctx.page.evaluate(() => document.querySelector('[data-g4-control]')?.removeAttribute('data-g4-control'));
}
export async function button(ctx, label) {
  const found = await ctx.page.evaluate(async label => {
    const end = Date.now()+8000;
    while(true) {
    const el = [...document.querySelectorAll('button,[role="button"],a')].find(el =>
      el.getClientRects().length && (el.textContent.trim() === label || el.getAttribute('aria-label') === label));
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') {
      if(Date.now()>end)return false;
      await new Promise(resolve=>setTimeout(resolve,40));
      continue;
    }
    el.setAttribute('data-g4-button', 'selected');
    return true;
    }
  }, label);
  assert.ok(found, `Missing enabled action: ${label}`);
  await ctx.page.click('[data-g4-button="selected"]');
  await ctx.page.evaluate(() => document.querySelector('[data-g4-button]')?.removeAttribute('data-g4-button'));
}
export async function choose(ctx, label, value) {
  const selector = await control(ctx, label);
  await chooseControl(ctx,selector,value);
  await clearMarker(ctx);
}
export async function chooseControl(ctx,selector,value) {
  const native = await ctx.page.evaluate(selector => document.querySelector(selector)?.tagName === 'SELECT', selector);
  if (native) {
    const option = await ctx.page.evaluate((selector,value) => [...document.querySelector(selector).options].find(item=>item.value===value || item.textContent.trim()===value)?.value,selector,value);
    assert.notEqual(option,undefined,`Missing current option: ${value}`);
    await ctx.page.select(selector, option);
  }
  else {
    await ctx.page.click(selector);
    await ctx.page.waitFor('[role="option"]', { timeout: 5000 });
    const found = await ctx.page.evaluate(value => {
      const el = [...document.querySelectorAll('[role="option"]')].find(el =>
        el.getAttribute('data-value') === value || el.textContent.trim() === value);
      if (!el) return false;
      el.setAttribute('data-g4-option', 'selected');
      return true;
    }, value);
    assert.ok(found, `Missing current option: ${value}`);
    await ctx.page.click('[data-g4-option="selected"]');
  }
}
export async function tick(ctx, label) {
  const selector = await control(ctx, label);
  const checked = await ctx.page.evaluate(selector => {
    const el = document.querySelector(selector);
    return el.checked || el.getAttribute('aria-checked') === 'true';
  }, selector);
  if (!checked) await ctx.page.click(selector);
  await clearMarker(ctx);
}
export async function visible(ctx, text) {
  await ctx.page.evaluate(async text => {
    const end = Date.now() + 8000;
    while (!document.querySelector('main')?.innerText.includes(text)) {
      if (Date.now() > end) throw new Error(`Expected visible result: ${text}`);
      await new Promise(resolve => setTimeout(resolve, 40));
    }
  }, text);
}
export async function answer(ctx, path, statuses = [200, 201], method = 'POST') {
  return ctx.page.evaluate(async (path, statuses, method) => {
    const end = Date.now() + 8000;
    while (true) {
      const row = window.__g4Responses?.find(row => row.url.includes(path) && statuses.includes(row.status) && row.method === method);
      if (row) return row;
      if (Date.now() > end) throw new Error(`No accepted response for ${path}`);
      await new Promise(resolve => setTimeout(resolve, 40));
    }
  }, path, statuses, method);
}
export function reference(row) {
  const id = row.json?.operation_id ?? row.json?.result?.operation_id ?? row.request_id ?? row.json?.id;
  assert.ok(typeof id === 'string' && id.length > 0, 'The response must return an operation or request reference');
  return id;
}
export function result(actor, row) {
  return { operation_id: reference(row), actor_id: actor.actor_id };
}
export async function api(ctx, service, method, path, body, role = 'buyer') {
  const response = await ctx.api(service, method, path, body, { as: role });
  assert.ok(response.status >= 200 && response.status < 300, `${service} ${path}: ${response.status}`);
  return response.json;
}
export async function publishedCopy(feature, name, locale) {
  const source = await readFile(new URL(`../../../../../web/features/${feature}`, import.meta.url), 'utf8');
  const declaration = `export const ${name}=`;
  assert.ok(source.startsWith(declaration), 'The published copy must retain its declaration');
  return runInNewContext('(' + source.slice(declaration.length).replace(/;\s*$/, '') + ')')[locale];
}

export async function ownedOrder(ctx) {
  await ctx.actor('buyer');
  await ctx.signIn('buyer');
  let listing;
  let cursor;
  const visited = new Set();
  do {
    const path = '/v1/discovery/watches?limit=24' + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : '');
    const catalog = await api(ctx, 'catalog', 'GET', path);
    for (const item of catalog.items) {
      const availability = await api(ctx, 'orders', 'GET', `/v1/listings/${item.id}/availability`);
      if (availability.status === 'available' && availability.sale_mode === 'fixed') {
        listing = item;
        break;
      }
    }
    if (listing) break;
    cursor = catalog.next_cursor;
    if (cursor) {
      assert.ok(!visited.has(cursor), 'Catalog pagination must advance');
      visited.add(cursor);
    }
  } while (cursor);
  assert.ok(listing, 'A currently available fixed-price watch is required for a fresh purchase');
  await start(ctx, 'buyer', `/checkout?listing_id=${encodeURIComponent(listing.id)}`);
  const t = await publishedCopy('buy-now/connected-copy.ts', 'connectedCopy', ctx.cell.locale);
  await button(ctx, t.review);
  await tick(ctx, t.terms);
  await button(ctx, t.accept);
  const reservation = await answer(ctx, '/exact-reservations');
  assert.equal(reservation.json.status, 'succeeded');
  const order = reservation.json.order;
  assert.ok(order?.id && order.watch_id, 'Reservation must return the purchased watch and order');
  await start(ctx, 'buyer', `/checkout/${order.id}`);
  const payment = await words(ctx, 'payments');
  await visible(ctx, payment.retained);
  if (await ctx.page.exists('input[type="checkbox"]')) await tick(ctx, payment.acceptQuote);
  await button(ctx, payment.card);
  await button(ctx, payment.start);
  await answer(ctx, '/payment-attempts');
  await button(ctx, payment.pay);
  await answer(ctx, '/simulate');
  await visible(ctx, payment.paid);
  const { order: retained } = await api(ctx, 'orders', 'GET', `/v1/orders/${order.id}`);
  assert.equal(retained.state, 'paid_held', 'Only confirmed simulated funds establish this purchase');
  assert.equal(retained.watch_id, order.watch_id);
  return retained;
}
export async function linked(ctx, pattern) {
  const path = await ctx.page.evaluate(pattern => [...document.querySelectorAll('main a[href]')]
    .map(el => el.getAttribute('href')).find(href => new RegExp(pattern).test(href)), pattern);
  assert.ok(path, `The current page must offer the connected destination: ${pattern}`);
  return path.replace(/^\/(en|ar)(?=\/)/, '');
}
export async function denied(ctx, service, path, role = 'buyer2') {
  const actor = await ctx.actor(role);
  await ctx.signIn(role);
  const response = await ctx.api(service, 'GET', path, undefined, { as: role });
  assert.equal(response.status, 403, 'A different account must be refused by current authority');
  const id = response.json?.request_id ?? response.json?.error?.request_id ?? response.json?.operation_id;
  assert.ok(id, 'The refused request must return its own reference');
  assert.ok(!response.json?.private_record && !response.json?.document, 'A refusal must not disclose the record');
  return { operation_id: id, actor_id: actor.actor_id };
}

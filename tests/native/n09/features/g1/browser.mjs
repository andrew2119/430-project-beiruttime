import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

export { assert };
export async function copy(ctx, feature) {
  return JSON.parse(await readFile(new URL(`../../../../../web/features/${feature}/${ctx.cell.locale}.json`, import.meta.url), 'utf8'));
}
export async function button(ctx, label) {
  await ctx.page.evaluate(async text => {
    const end = Date.now() + 10000;
    while (Date.now() < end) {
      const node = [...document.querySelectorAll('button,[role="tab"],[role="radio"]')]
      .find(item => item.textContent.trim() === text && !item.disabled && item.getClientRects().length);
      if (node) { node.click(); return; }
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    throw new Error(`Missing available control: ${text}`);
  }, label);
}
export async function field(ctx, label, value) {
  const selector = await ctx.page.evaluate(async text => {
    const end = Date.now() + 10000;
    while(Date.now() < end) {
      const label = [...document.querySelectorAll('label')].find(item => item.textContent.trim() === text);
      const input = label?.control ?? label?.querySelector('input,textarea');
      if(input && !input.disabled) {
        input.setAttribute('data-proof-field', 'current');
        return '[data-proof-field="current"]';
      }
      await new Promise(resolve => setTimeout(resolve,40));
    }
    throw new Error(`Missing field: ${text}`);
  }, label);
  await ctx.page.fill(selector, value);
  await ctx.page.evaluate(() => document.querySelector('[data-proof-field]')?.removeAttribute('data-proof-field'));
}
export async function visible(ctx, text) {
  await ctx.page.evaluate(async expected => {
    const end = Date.now() + 10000;
    while (Date.now() < end) {
      if (document.body.innerText.includes(expected)) return;
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    throw new Error(`Missing visible result: ${expected}`);
  }, text);
}
export async function open(ctx, path, role = 'buyer') {
  const actor = await ctx.actor(role);
  await ctx.signIn(role);
  await ctx.page.goto(path);
  await ctx.page.waitFor('h1', {timeout: 10000});
  await observe(ctx);
  return actor;
}
// Observe real responses only. Request bodies and authorization headers are never retained.
export async function observe(ctx) {
  await ctx.page.evaluate(() => {
    if (window.__btProof) { window.__btProof.records = []; return; }
    const state = window.__btProof = {records: []};
    const original = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await original(...args);
      const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
      if (url.origin === location.origin && url.pathname.startsWith('/api/web/')) {
        let json;
        try { json = await response.clone().json(); } catch { json = null; }
        // Session material stays out of the observation buffer.
        const clean = value => {
          if (Array.isArray(value)) return value.map(clean);
          if (!value || typeof value !== 'object') return value;
          return Object.fromEntries(Object.entries(value).filter(([key]) =>
            !/token|password|secret|recovery_codes|proof$/i.test(key)).map(([key, item]) => [key, clean(item)]));
        };
        state.records.push({path: url.pathname, method: (args[1]?.method ?? args[0]?.method ?? 'GET').toUpperCase(), status: response.status, json: clean(json),
          request_id: response.headers.get('x-request-id') ?? response.headers.get('x-correlation-id')});
      }
      if (response.ok && state.drop && url.pathname.includes(state.drop)) {
        state.drop = null;
        throw new TypeError('Test response interrupted after service commit');
      }
      return response;
    };
  });
}
export async function response(ctx, path, refused = false, method = 'POST') {
  return ctx.page.evaluate(async ({path, refused, method}) => {
    const end = Date.now() + 10000;
    while (Date.now() < end) {
      const record = window.__btProof?.records.find(item => item.path.includes(path) && item.method === method &&
        (refused ? [400,401,403,404,409,422,429].includes(item.status) : item.status >= 200 && item.status < 300));
      if (record) return record;
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    throw new Error(`No ${refused ? 'refused' : 'successful'} response for ${path}`);
  }, {path, refused, method});
}
export function reference(record) {
  const data = record.json;
  const id = data?.operation_id ?? data?.request_id ?? data?.error?.request_id ?? record.request_id ?? data?.application?.id ?? data?.account?.id ?? data?.id;
  assert.equal(typeof id, 'string', 'The service must return a real reference');
  assert.ok(id.length > 0);
  return id;
}
export function result(actor, id) {
  assert.equal(typeof actor.actor_id, 'string');
  assert.ok(actor.actor_id);
  assert.equal(typeof id, 'string');
  assert.ok(id);
  return {operation_id: id, actor_id: actor.actor_id};
}
export async function submit(ctx, selector = 'form button[type="submit"]') {
  await ctx.page.evaluate(async selector => {
    const end=Date.now()+10000;
    while(Date.now()<end) {
      const node=document.querySelector(selector);
      if(node && !node.disabled && node.getClientRects().length) return;
      await new Promise(resolve=>setTimeout(resolve,40));
    }
    throw new Error('Submission control is unavailable');
  },selector);
  await ctx.page.click(selector);
}
export async function uploadText(ctx, name, text = 'DEMO: synthetic Beirut Time proof') {
  await ctx.page.evaluate(({name, text}) => {
    const input = document.querySelector(`input[name="${name}"]`);
    if (!input) throw new Error('Missing private upload');
    const transfer = new DataTransfer();
    transfer.items.add(new File([text], 'test-proof.txt', {type: 'text/plain'}));
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles:true}));
  }, {name, text});
}
export async function formFor(ctx, name) {
  await ctx.page.evaluate(name => {
    const form = document.querySelector(`[name="${name}"]`)?.closest('form');
    if (!form) throw new Error('Missing form');
    for (const previous of document.querySelectorAll('[data-proof-form]')) previous.removeAttribute('data-proof-form');
    form.setAttribute('data-proof-form', 'current');
  }, name);
  await submit(ctx, '[data-proof-form="current"] button[type="submit"]');
}
export function feature(number, journey, negative, recovery) {
  return {feature_id:`F${number}`, proof_id:`f${String(number).padStart(2,'0')}-proof`,
    proof_revision:'1', journey, negative, recovery};
}

export async function loseResponse(ctx, path) {
  await ctx.page.evaluate(path => { window.__btProof.drop = path; }, path);
}
export async function choose(ctx, name, label, scope = '') {
  await ctx.page.evaluate(({name, scope}) => {
    const control=document.querySelector(`${scope} select[name="${name}"]`)?.parentElement?.querySelector('[role="combobox"]');
    if(!control) throw new Error('Missing choice control');
    control.click();
  },{name, scope});
  await ctx.page.waitFor('[role="option"]',{timeout:10000});
  await ctx.page.evaluate(label=>{
    const option=[...document.querySelectorAll('[role="option"]')].find(node=>node.textContent.trim()===label);
    if(!option || option.disabled) throw new Error('Missing available choice');
    option.click();
  },label);
}

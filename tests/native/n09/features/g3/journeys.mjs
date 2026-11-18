import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { requireValue, signedIn, read, click, fill, visible, observe, response, receipt, finish, deferred, prepareDevice } from './browser.mjs';

import { pending, disconnectedPage, runPending } from './pending-scenarios.mjs';

async function pendingScenario(ctx, mode, feature) {
  const actor = await signedIn(ctx, pending[feature].role);
  return runPending(feature, mode, actor, () => ctx.uniq('test-operation'), disconnectedPage(feature));
}

const language = (ctx, en, ar) => ctx.cell.locale === 'ar' ? ar : en;
const words = async (ctx, feature, prefix = '') => JSON.parse(await readFile(new URL(
  `../../../../../web/features/${feature}/${prefix}${ctx.cell.locale}.json`, import.meta.url), 'utf8'));
const start = async (ctx, route) => {
  await ctx.page.goto(route);
  await ctx.page.waitFor('h1', { timeout: 8000 });
};
const arm = (ctx, pattern, mode) => observe(ctx, pattern, mode === 'negative');

async function watch(ctx, fixed = false) {
  const result = await read(ctx, 'catalog', '/v1/discovery/watches?sort=newest');
  const item = requireValue(result.items?.find(item => !item.demo && item.sale_state === 'available' &&
    (!fixed || item.sale_mode === 'fixed')), 'an actual published available watch');
  return read(ctx, 'catalog', `/v1/discovery/watches/${encodeURIComponent(item.id)}`);
}

async function preview(ctx, actor) {
  const item = await watch(ctx, true), t = await words(ctx, 'pricing');
  await start(ctx, '/prices');
  await click(ctx, t.source, 'field');
  await click(ctx, t.listingSource, 'choice');
  await fill(ctx, t.subject, item.id);
  await fill(ctx, t.subjectRevision, String(item.revision));
  await fill(ctx, t.price, requireValue(item.price?.amount, 'published USD price'));
  await observe(ctx, '/pricing/v1/quotes$');
  await click(ctx, t.createQuote);
  const result = await response(ctx);
  receipt(result, actor);
  assert.equal(result.json.source_verified, true);
  return { quote: result.json.id, watch: item.id };
}

async function clickRecord(ctx, reference, name) {
  const selector = await ctx.page.evaluate(({ reference, name }) => {
    const leaf = [...document.querySelectorAll('*')].find(element =>
      element.children.length === 0 && element.textContent.trim() === reference);
    for (let parent = leaf?.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const button = [...parent.querySelectorAll('button,[role=button]')].find(item => item.textContent.trim() === name);
      if (button) {
        button.setAttribute('data-n09-record-action', 'current');
        return '[data-n09-record-action="current"]';
      }
    }
    return null;
  }, { reference, name });
  await ctx.page.click(requireValue(selector, `${name} on ${reference}`));
}


async function workspace(ctx) {
  await start(ctx, '/business/customizations');
  const t = await words(ctx, 'brand-decisions');
  await click(ctx, t.organization, 'field');
  await ctx.page.waitFor('[role=option],[role=menuitemradio]', { timeout: 8000 });
  const option = await ctx.page.evaluate(placeholder => [...document.querySelectorAll('[role=option],[role=menuitemradio]')]
    .find(item => item.getClientRects().length && !item.matches(':disabled') &&
      item.getAttribute('aria-disabled') !== 'true' && item.textContent.trim() &&
      item.textContent.trim() !== placeholder)?.textContent.trim(), t.chooseOrganization);
  await click(ctx, requireValue(option, 'current brand membership'), 'choice');
  const path = await ctx.page.evaluate(() => new Promise(resolve => {
    const timer = setInterval(() => {
      if (new URLSearchParams(location.search).get('organization_id')) done(location.pathname + location.search);
    }, 50);
    const deadline = setTimeout(() => done(null), 8000);
    const done = value => { clearInterval(timer); clearTimeout(deadline); resolve(value); };
  }));
  requireValue(path, 'selected brand workspace address');
  return path.replace(/^\/(en|ar)(?=\/)/, '');
}


export async function payouts(ctx, mode) {
  return pendingScenario(ctx, mode, 'F33');
}

export async function refunds(ctx, mode) {
  return pendingScenario(ctx, mode, 'F34');
}

export async function inbox(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer');
  const source = await preview(ctx, actor);
  let notice;
  for (let attempt = 0; attempt < 8 && !notice; attempt++) {
    const current = await read(ctx, 'communications', '/v1/inbox');
    notice = current.items.find(item => item.resource_id === source.quote);
    if (!notice) await new Promise(resolve => setTimeout(resolve, 250));
  }
  requireValue(notice, 'the fresh preview notice has reached the private inbox');
  await start(ctx, '/inbox');
  const t = await words(ctx, 'inbox');
  await visible(ctx, source.quote);
  await arm(ctx, '/communications/v1/inbox/[^/]+/read$', mode);
  await clickRecord(ctx, source.quote, t.markRead);
  if (mode !== 'negative') requireValue((await response(ctx)).json.read_at, 'confirmed read time');
  return finish(ctx, actor, mode, undefined, t.read);
}

export async function savedWatches(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer');
  const current = await read(ctx, 'communications', '/v1/saved-watches?offset=0&limit=20');
  const existing = current.items[0];
  const item = existing || await watch(ctx);
  await start(ctx, '/saved');
  if (existing) {
    // The row submits its current revision, including after an earlier save.
    await visible(ctx, existing.title || language(ctx, 'Watch details unavailable', 'تفاصيل الساعة غير متاحة'));
    await arm(ctx, '/communications/v1/saved-watches/[^/]+$', mode);
    await click(ctx, language(ctx, 'Save alert choices', 'حفظ خيارات التنبيهات'));
  } else {
    await fill(ctx, language(ctx, 'Public watch reference', 'مرجع الساعة المنشورة'), item.id);
    await click(ctx, language(ctx, 'Price changes', 'تغيّر السعر'), 'switch');
    await arm(ctx, '/communications/v1/saved-watches/[^/]+$', mode);
    await click(ctx, language(ctx, 'Save watch', 'حفظ الساعة'));
  }
  return finish(ctx, actor, mode, ['saved'], item.title);
}

export async function savedSearches(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer');
  await start(ctx, '/saved-searches');
  const name = ctx.uniq('test-search');
  await fill(ctx, language(ctx, 'Search name', 'اسم البحث'), name);
  await fill(ctx, language(ctx, 'Search words', 'كلمات البحث'), 'watch');
  await fill(ctx, language(ctx, 'Minimum price (USD)', 'السعر الأدنى بالدولار الأمريكي'), '1.00');
  await fill(ctx, language(ctx, 'Maximum price (USD)', 'السعر الأقصى بالدولار الأمريكي'), '10.00');
  await click(ctx, language(ctx, 'Notify me of new matches', 'أبلغني بالمطابقات الجديدة'), 'switch');
  await arm(ctx, '/communications/v1/saved-searches/commands$', mode);
  await click(ctx, language(ctx, 'Save search', 'احفظ البحث'));
  if (mode !== 'negative') {
    const result = (await response(ctx)).json.result;
    assert.equal(result.name, name);
    assert.equal(result.alerts_enabled, true);
    assert.equal(result.criteria.currency, 'USD');
    assert.equal(result.criteria.min_minor, 100);
    assert.equal(result.criteria.max_minor, 1000);
  }
  return finish(ctx, actor, mode, ['saved'], name);
}

export async function follows(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer'), item = await watch(ctx);
  requireValue(item.seller?.id, 'published seller identity');
  assert.notEqual(item.seller.id, actor.actor_id);
  await start(ctx, '/following');
  await fill(ctx, language(ctx, 'Seller reference', 'مرجع البائع'), item.seller.id);
  await click(ctx, language(ctx, 'New-publication alerts', 'تنبيهات المنشورات الجديدة'), 'switch');
  await arm(ctx, '/communications/v1/seller-follows$', mode);
  await click(ctx, language(ctx, 'Follow seller', 'متابعة البائع'));
  if (mode !== 'negative') {
    const result = (await response(ctx)).json.result;
    assert.equal(result.following, true);
    assert.equal(result.alerts_enabled, true);
  }
  return finish(ctx, actor, mode, ['accepted'], item.seller.id);
}

export async function questions(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer'), item = await watch(ctx);
  await start(ctx, '/questions');
  await fill(ctx, language(ctx, 'Listing reference', 'مرجع الإعلان'), item.id);
  await click(ctx, language(ctx, 'Open questions', 'فتح الأسئلة'));
  const question = `${ctx.uniq('test-question')} Which items are included with this watch?`;
  await fill(ctx, language(ctx, 'Your public question', 'سؤالك العلني'), question);
  await click(ctx, language(ctx, 'Find matching answers', 'البحث عن إجابات مطابقة'));
  await visible(ctx, language(ctx, 'Matching previous answers', 'إجابات سابقة مطابقة'));
  await arm(ctx, '/communications/v1/listing-questions/[^/]+/commands$', mode);
  await click(ctx, language(ctx, 'Send question anyway', 'إرسال السؤال على أي حال'));
  return finish(ctx, actor, mode, ['published'], question);
}

export async function messages(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer'), item = await watch(ctx);
  await start(ctx, '/messages');
  await fill(ctx, language(ctx, 'Record reference', 'مرجع السجل'), item.id);
  await click(ctx, language(ctx, 'Open record conversation', 'فتح محادثة السجل'));
  const body = `${ctx.uniq('test-message')} Please confirm the included watch items.`;
  await fill(ctx, language(ctx, 'Message', 'الرسالة'), body);
  await arm(ctx, '/communications/v1/messages/threads/[^/]+/commands$', mode);
  await click(ctx, language(ctx, 'Send', 'إرسال'));
  return finish(ctx, actor, mode, ['accepted'], body);
}

// A price preview creates an inbox notice, without capturing transaction email.
export async function email(ctx, mode) {
  await signedIn(ctx, 'buyer');
  deferred('F41', 'transaction email requires a connected authenticated producer, current source authority and mounted private record route');
}

export async function push(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer');
  try {
    await readFile(new URL('../../../../../web/app/(notification-devices)/notification-devices/page.tsx', import.meta.url), 'utf8');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    deferred('F42', 'notification-devices entry requires host route, device capability and subscription configuration');
  }
  await start(ctx, '/notification-devices');
  await prepareDevice(ctx, actor);
  await arm(ctx, '/communications/v1/browser-push/devices$', mode);
  await click(ctx, language(ctx, 'Enable on this device', 'تفعيل على هذا الجهاز'));
  return finish(ctx, actor, mode, ['active'], language(ctx, 'This device is connected.', 'هذا الجهاز مرتبط.'));
}

async function optionCatalog(ctx) {
  const brands = await read(ctx, 'catalog', '/v1/brand-options/brands');
  for (const brand of brands.items ?? []) {
    if (brand.sample) continue;
    const catalog = await read(ctx, 'catalog', `/v1/brand-options/brands/${encodeURIComponent(brand.organization_id)}`);
    const color = catalog.items.find(item => item.kind === 'color' && item.available);
    if (color) return { brand, catalog, color };
  }
  requireValue(null, 'a current official brand with actual supported options');
}

export async function options(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer');
  const { brand, catalog, color } = await optionCatalog(ctx);
  const base = requireValue(color.base_models[0], 'supported base model');
  const caliber = requireValue(color.calibers[0], 'supported caliber');
  const query = new URLSearchParams({ brand: brand.organization_id, base, caliber });
  await start(ctx, '/customize?' + query);
  const t = await words(ctx, 'brand-options');
  let result;
  for (const kind of ['color', 'material', 'dial', 'sophistication']) {
    const item = requireValue(catalog.items.find(item => item.kind === kind && item.available &&
      item.base_models.includes(base) && item.calibers.includes(caliber)), `supported ${kind} option`);
    await click(ctx, t[kind]);
    await click(ctx, item.label[ctx.cell.locale], 'choice');
    await arm(ctx, `/catalog/v1/brand-options/configurations/[^/]+/${kind}$`, mode);
    await click(ctx, t.save);
    result = await finish(ctx, actor, mode, ['saved_not_submitted'], t.saved);
    if (mode === 'negative') return result;
  }
  const movement = await words(ctx, 'movement-option');
  await arm(ctx, '/options/movement/selections$', mode);
  await click(ctx, movement.save);
  return finish(ctx, actor, mode, ['supported_for_review', 'manual_review'], [movement.saved, movement.manual]);
}

async function completeConfiguration(ctx) {
  const list = await read(ctx, 'catalog', '/v1/brand-options/configurations');
  for (const row of list.items ?? []) {
    const current = await read(ctx, 'catalog', `/v1/brand-options/configurations/${encodeURIComponent(row.id)}`);
    if (['color', 'material', 'dial', 'sophistication'].every(kind => current.selections.some(item => item.kind === kind && item.current))) return current;
  }
  requireValue(null, 'a complete current configuration saved through the option pages');
}

export async function requests(ctx, mode) {
  const actor = await signedIn(ctx, 'buyer'), config = await completeConfiguration(ctx);
  await start(ctx, `/custom-requests?configuration=${encodeURIComponent(config.id)}&revision=${config.revision}`);
  await fill(ctx, (await words(ctx, 'request-drafts')).scope, 'test customization review of the saved component choices');
  await fill(ctx, (await words(ctx, 'request-drafts')).notes, ctx.uniq('test-private-request'));
  await click(ctx, (await words(ctx, 'request-drafts')).save);
  await visible(ctx, (await words(ctx, 'request-drafts')).saved);
  await click(ctx, language(ctx, 'Review current dimensions', 'مراجعة الأبعاد الحالية'));
  await visible(ctx, [language(ctx, 'Supported for review', 'مدعوم للمراجعة'), language(ctx, 'Manual assessment required', 'يتطلب تقييماً يدوياً')]);
  await arm(ctx, '/catalog/v1/request-drafts/[^/]+/submit$', mode);
  await click(ctx, language(ctx, 'Submit reviewed revision', 'إرسال النسخة المراجعة'));
  if (mode !== 'negative') {
    const value = (await response(ctx)).json;
    assert.equal(value.request.buyer_id, actor.actor_id);
    assert.equal(value.resource_id, value.request.id);
  }
  return finish(ctx, actor, mode, ['succeeded'], language(ctx, 'Submitted for assessment', 'تم الإرسال للمراجعة'));
}

export async function assessmentQuote(ctx, mode) {
  return pendingScenario(ctx, mode, 'F45');
}

export async function eligibility(ctx, mode) {
  return pendingScenario(ctx, mode, 'F46');
}

// Reserve even refused attempts so each scenario exercises a separate request.
const approvalRequests = new WeakMap();

export async function eligibleApproval(ctx, organization) {
  let used = approvalRequests.get(ctx);
  if (!used) approvalRequests.set(ctx, used = new Set());
  let before;
  do {
    const query = new URLSearchParams({ organization_id: organization });
    if (before) query.set('before', before);
    const page = await read(ctx, 'catalog', `/v1/customization-requests?${query}`, 'brand');
    for (const request of page.items) {
      if (used.has(request.id)) continue;
      const base = `/v1/customization-requests/${encodeURIComponent(request.id)}`;
      const scope = `?organization_id=${encodeURIComponent(organization)}`;
      const decision = await read(ctx, 'catalog', base + '/decision' + scope, 'brand');
      if (decision.status !== 'not_decided') continue;
      const readiness = await ctx.api('catalog', 'GET', base + '/decision-readiness' + scope,
        undefined, { as: 'brand' });
      if (readiness.status !== 200 || readiness.json.status !== 'available') continue;
      used.add(request.id);
      return request;
    }
    before = page.next_cursor;
  } while (before);
  deferred('F47', 'a distinct undecided request with current approval prerequisites is required');
}

export async function approvals(ctx, mode) {
  const actor = await signedIn(ctx, 'brand');
  const address = await workspace(ctx);
  const organization = requireValue(new URL(address, ctx.origin).searchParams.get('organization_id'),
    'current brand workspace');
  const request = await eligibleApproval(ctx, organization);
  const t = await words(ctx, 'brand-decisions');
  // Locate the visible request reference within its own list item, including
  // requests reached through pagination. Never fall back to another card.
  await ctx.page.waitFor('[role=listitem]', { timeout: 8000 });
  let card;
  while (!card) {
    card = await ctx.page.evaluate(reference => {
      const matches = [...document.querySelectorAll('[role=listitem]')].filter(item =>
        [...item.querySelectorAll('h2')].some(heading => heading.textContent.includes(reference)));
      if (matches.length !== 1) return null;
      matches[0].setAttribute('data-n09-approval', 'current');
      return '[data-n09-approval="current"]';
    }, request.id.slice(0, 8));
    if (card) break;
    const count = await ctx.page.evaluate(() => document.querySelectorAll('[role=listitem]').length);
    await click(ctx, t.moreRequests);
    const loaded = await ctx.page.evaluate(count => new Promise(resolve => {
      const check = () => document.querySelectorAll('[role=listitem]').length > count;
      if (check()) return resolve(true);
      const observer = new MutationObserver(() => { if (check()) finish(true); });
      const timer = setTimeout(() => finish(false), 8000);
      const finish = value => { clearTimeout(timer); observer.disconnect(); resolve(value); };
      observer.observe(document.body, { childList: true, subtree: true });
    }), count);
    requireValue(loaded, 'the next requests page did not load');
  }
  const reason = `${card} textarea[name="decision_reason"]:not(:disabled)`;
  await ctx.page.waitFor(reason, { timeout: 8000 });
  await ctx.page.fill(reason, 'test approval of the exact current assessed scope');
  const button = await ctx.page.evaluate(({ card, name }) => {
    const button = [...document.querySelector(card).querySelectorAll('button')]
      .find(item => item.textContent.trim() === name);
    if (!button) return null;
    button.setAttribute('data-n09-approve', 'current');
    return '[data-n09-approve="current"]:not(:disabled)';
  }, { card, name: t.approve });
  await ctx.page.waitFor(requireValue(button, 'approval action on the selected request'), { timeout: 8000 });
  await arm(ctx, `/catalog/v1/customization-requests/${request.id}/decisions$`, mode);
  await ctx.page.click(button);
  const proof = await finish(ctx, actor, mode, ['approved']);
  await ctx.page.waitFor(mode === 'negative' ? `${card} [role=alert]` : card, { timeout: 8000 });
  if (mode !== 'negative') await visible(ctx, t.approved, card);
  return proof;
}

export async function productionChanges(ctx, mode) {
  return pendingScenario(ctx, mode, 'F48');
}

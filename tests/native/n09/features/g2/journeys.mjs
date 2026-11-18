import assert from 'node:assert/strict';
import {api, button, check, confirmed, enter, field, mutate, observe, received, reference, refusal, visible} from './browser.mjs';

import {handoverObservations} from './handover.mjs';
import {releasedPurchase} from './purchase.mjs';

const post = (service, path) => `/api/web/v1/${service}${path}`;
const amount = minor => (minor / 100).toFixed(2);
const retry = ctx => button(ctx, 'Retry the same operation', 'أعد العملية نفسها');
const submit = ctx => ctx.page.click('main form button[type="submit"]');
const shownReference = (ctx, value) => visible(ctx, reference(value));

async function listing(ctx, mode = 'fixed') {
  const page = await api(ctx, 'catalog', '/v1/discovery/watches?sort=newest');
  assert.ok(Array.isArray(page.items), 'Missing current marketplace listings');
  for (const row of page.items) {
    const id = row.id ?? row.listing_id;
    if (!id) continue;
    const current = await api(ctx, 'catalog', `/v1/listings/${encodeURIComponent(id)}`);
    if (current.status !== 'published' || current.facts?.currency !== 'USD' || current.facts.sale_mode !== ({fixed:'fixed_price',offer:'offer'}[mode] ?? mode)) continue;
    const availability = await api(ctx, 'orders', `/v1/listings/${id}/availability`);
    if (availability.status === 'available' && availability.sale_mode === ({offer:'seller_base'}[mode] ?? mode)) return current;
  }
  throw new Error(`No currently available ${mode} listing; connected prerequisite deferred`);
}

async function order(ctx, predicate, role = 'buyer') {
  await ctx.actor(role);
  const page = await api(ctx, 'orders', '/v1/orders', role);
  for (const current of page.items ?? []) if (await predicate(current)) return current;
  throw new Error('No eligible owned order; connected prerequisite deferred');
}

async function reservePreparation(ctx) {
  await ctx.actor('buyer');
  const current = await listing(ctx);
  const actor = await enter(ctx, 'buyer', `/watches/${current.id}`);
  const href = await ctx.page.evaluate(() => [...document.querySelectorAll('a[href]')]
    .find(node => node.getAttribute('href').includes('/checkout?listing_id='))?.getAttribute('href'));
  assert.ok(href, 'The watch must offer an actual purchase entry');
  await ctx.page.click(`a[href=${JSON.stringify(href)}]`);
  await button(ctx, 'Get current exact quote', 'احصل على عرض سعر دقيق حالي');
  await ctx.page.waitFor('main input[type="checkbox"], main [role="checkbox"]', {timeout: 10000});
  await check(ctx);
  return actor;
}

export function reservation() {
  return {
    prepare: reservePreparation,
    path: () => post('orders', '/v1/exact-reservations'), states: ['succeeded'],
    submit: ctx => button(ctx, 'Accept exact quote and reserve', 'اقبل العرض الدقيق واحجز'),
    retry: ctx => button(ctx, 'Retry the same operation', 'أعد العملية نفسها'),
    async verify(ctx, value) {
      assert.ok(value.order?.id && value.order.currency === 'USD');
      await button(ctx, 'Continue to simulated payment', 'تابع إلى الدفع التجريبي');
      assert.ok((await ctx.page.url()).includes(`/checkout/${value.order.id}`));
    },
  };
}

async function newOrder(ctx) {
  let created;
  const spec = reservation();
  const verify = spec.verify;
  spec.verify = async (ctx, value) => {created = value.order;await verify(ctx, value);};
  await mutate(ctx, 'journey', spec);
  return created;
}

export function auction(withReserve = false) {
  let current;
  return {
    async prepare(ctx) {
      const actor = await enter(ctx, 'private-seller', '/seller/auctions');
      const rows = await api(ctx, 'catalog', '/v1/seller/listings', 'private-seller');
      const lots = await api(ctx, 'auction', '/v1/seller/auctions', 'private-seller');
      current = rows.items?.find(row => row.status === 'published' && row.facts?.currency === 'USD' &&
        row.facts.sale_mode === 'auction' && !lots.items.some(lot => lot.listing_id === row.id));
      assert.ok(current, 'A published owned auction listing is required; connected prerequisite deferred');
      await field(ctx, 'Published listing ID', 'معرّف الإعلان المنشور', current.id);
      await field(ctx, 'Opening price (USD)', 'سعر الافتتاح (دولار أمريكي)', '100.00');
      await field(ctx, 'Minimum increment (USD)', 'الحد الأدنى للزيادة (دولار أمريكي)', '1.00');
      if (withReserve) await field(ctx, 'Private reserve (USD, optional)', 'الاحتياطي الخاص (دولار أمريكي، اختياري)', '101.00');
      const local = date => {
        const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Beirut',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
        const p = Object.fromEntries(parts.map(part => [part.type, part.value]));
        return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
      };
      const server = Date.parse(lots.server_time ?? new Date().toISOString());
      await field(ctx, 'Starts at (Beirut time)', 'البداية (بتوقيت بيروت)', local(new Date(server + 60000)));
      await field(ctx, 'Ends at (Beirut time)', 'النهاية (بتوقيت بيروت)', local(new Date(server + 180000)));
      await button(ctx, 'Review Beirut schedule', 'مراجعة الجدول بتوقيت بيروت');
      await visible(ctx, ctx.cell.locale === 'ar' ? 'أكّد تواريخ بيروت وفوارق توقيتها بفتح المزاد.' : 'Confirm these Beirut dates and offsets by opening the auction.');
      return actor;
    },
    reconciles: true,
    path: () => '/api/web/v2/auction-schedules', states: ['succeeded'],
    submit: ctx => button(ctx, 'Open auction', 'فتح المزاد'),
    retry: ctx => button(ctx, 'Try again', 'حاول مجدداً'),
    async verify(ctx, value) {
      assert.ok(value.auction_id);
      await visible(ctx, value.auction_id);
      const policy = await api(ctx, 'auction', `/v2/seller/auctions/${value.auction_id}/policy`, 'private-seller');
      assert.equal(policy.reserve_set, withReserve);
      assert.ok(policy.current_ends_at && Number.isInteger(policy.end_version));
    },
  };
}

export function bidding(auctionId) {
  let lot;
  return {
    async prepare(ctx) {
      await ctx.actor('buyer');
      const rows = await api(ctx, 'auction', '/v2/auctions');
      lot = rows.items?.find(row => (!auctionId || row.id === auctionId) && row.status === 'live' && row.currency === 'USD' && (!row.mode || row.mode === 'bidding'));
      assert.ok(lot, 'A live auction is required; connected prerequisite deferred');
      const actor = await enter(ctx, 'buyer', `/watches/${lot.listing_id}`);
      await field(ctx, 'Your bid (USD)', 'مزايدتك (دولار أمريكي)', amount(lot.next_minimum_minor));
      await button(ctx, 'Review exact fees', 'مراجعة الرسوم الدقيقة');
      await ctx.page.waitFor('main input[type="checkbox"], main [role="checkbox"]', {timeout:10000});
      await check(ctx);
      return actor;
    },
    reconciles: true,
    path: () => post('auction', `/v1/auctions/${lot.id}/bids`), states: ['succeeded'],
    submit: ctx => button(ctx, 'Place bid', 'تقديم مزايدة'),
    retry: ctx => button(ctx, 'Try again', 'حاول مجدداً'),
    async verify(ctx, value) {
      assert.ok(Number.isInteger(value.accepted_sequence));
      await shownReference(ctx, value);
      const history = await api(ctx, 'auction', `/v1/auctions/${lot.id}/history?limit=10`);
      assert.ok(history.items.some(row => row.sequence === value.accepted_sequence));
    },
  };
}

export function fees() {
  let current;
  return {
    async prepare(ctx) {
      await ctx.actor('buyer');current = await listing(ctx);
      const actor = await enter(ctx, 'buyer', '/prices');
      await ctx.page.fill('[name="subject"]', current.id);
      await ctx.page.fill('[name="subject_revision"]', String(current.revision));
      await ctx.page.fill('[name="price"]', amount(current.facts.price_minor));
      return actor;
    },
    path: () => post('pricing', '/v1/quotes'),
    submit: ctx => button(ctx, 'Save exact preview', 'احفظ المعاينة الدقيقة'),
    retry: ctx => button(ctx, 'Save exact preview', 'احفظ المعاينة الدقيقة'),
    async verify(ctx, value) {
      assert.equal(value.currency, 'USD');
      assert.equal(value.payable_minor, value.price_minor + value.buyer_fee_minor + value.shipping_minor + value.tax_minor);
      assert.equal(value.seller_net_minor, value.price_minor - value.seller_commission_minor);
      await visible(ctx, value.id);
      await button(ctx, 'Acknowledge this exact version', 'تأكيد مراجعة هذا الإصدار الدقيق');
    },
  };
}

export function offer() {
  return {
    async prepare(ctx) {
      await ctx.actor('buyer');
      const current = await listing(ctx);
      const actor = await enter(ctx, 'buyer', `/offers?listing=${encodeURIComponent(current.id)}`);
      await ctx.page.fill('[name="offer-amount"]', amount(current.facts.price_minor));
      await button(ctx, 'Review exact fees', 'مراجعة الرسوم الدقيقة');
      await ctx.page.waitFor('[data-offer-compose] dl', {timeout:10000});
      return actor;
    },
    path: () => post('pricing', '/v1/offers'), states: ['succeeded'],
    submit: ctx => button(ctx, 'Send this offer', 'إرسال هذا العرض'),
    retry: ctx => button(ctx, 'Send this offer', 'إرسال هذا العرض'),
    async verify(ctx, value) {
      const id = value.offer?.id ?? value.offer_id;
      assert.ok(id);
      await ctx.page.waitFor(`[data-offer-id=${JSON.stringify(id)}]`, {timeout:10000});
    },
  };
}

export function payment() {
  let attempt;
  return {
    async prepare(ctx) {
      const current = await newOrder(ctx);
      const actor = await enter(ctx, 'buyer', `/checkout/${current.id}`);
      const checkout = await api(ctx, 'orders', `/v1/orders/${current.id}/checkout`);
      assert.equal(checkout.simulated, true);
      assert.equal(checkout.financial_readiness?.movement_status, 'none');
      if (!checkout.quote.reviewed_at) await check(ctx);
      await observe(ctx, post('orders', `/v1/orders/${current.id}/payment-attempts`));
      await button(ctx, 'Create simulated attempt', 'أنشئ محاولة دفع تجريبية');
      const result = confirmed(await received(ctx), ['succeeded']);
      attempt = result.attempt;
      assert.equal(attempt?.simulated, true);
      assert.equal(attempt.order_id, current.id);
      return actor;
    },
    path: () => post('orders', `/v1/payment-attempts/${attempt.id}/simulate`), states: ['succeeded'],
    submit: ctx => button(ctx, 'Simulate confirmation', 'حاكِ تأكيد الدفع'), retry,
    async verify(ctx, value) {
      assert.equal(value.attempt?.simulated, true);
      assert.equal(value.attempt?.state, 'confirmed');
      assert.equal(value.attempt?.id, attempt.id);
      await visible(ctx, attempt.reference);
      const current = await api(ctx, 'orders', `/v1/orders/${attempt.order_id}/checkout`);
      assert.equal(current.financial_readiness.state, 'paid_held');
      assert.equal(current.financial_readiness.held_minor, attempt.total_minor);
    },
  };
}

export function cancellation() {
  let current;
  return {
    async prepare(ctx) {
      current = await newOrder(ctx);
      const actor = await enter(ctx, 'buyer', '/cancellations');
      for (const [id,value] of [['subject',current.id],['watch',current.watch_id],['revision',current.revision],['reason',ctx.uniq('test-cancellation')]]) {
        await ctx.page.fill(`#cancel-${id}`, String(value));
      }
      return actor;
    },
    path: () => post('orders', '/v1/cancellations'), states: ['accepted'],
    submit, retry: ctx => button(ctx, 'Resolve the same request', 'التحقق من الطلب نفسه'),
    verify: shownReference,
  };
}

export function returns() {
  return {
    async prepare(ctx) {
      const current = await order(ctx, row => ['paid_held','received'].includes(row.state));
      const actor = await enter(ctx, 'buyer', '/returns');
      await field(ctx, 'Order reference', 'مرجع الطلب', current.id);
      await field(ctx, 'Return reason', 'سبب الإرجاع', ctx.uniq('test-return'));
      return actor;
    },
    path: () => post('orders', '/v1/returns'), states: ['requested'],
    submit: ctx => button(ctx, 'Request return review', 'طلب مراجعة الإرجاع'),
    retry: ctx => button(ctx, 'Retry the same request', 'إعادة المحاولة بالطلب نفسه'),
    async verify(ctx) {await visible(ctx, ctx.cell.locale === 'ar' ? 'تم طلب الإرجاع' : 'Return requested');},
  };
}

export function review() {
  return {
    async prepare(ctx) {
      const subject = await releasedPurchase(ctx, async ctx => {
        const setup = payment(), verify = setup.verify;
        let orderId;
        setup.verify = async (ctx, value) => {
          await verify(ctx, value);
          orderId = value.attempt.order_id;
        };
        const result = await mutate(ctx, 'journey', setup);
        return {...result, order_id: orderId};
      });
      const actor = await enter(ctx, 'buyer', '/reviews');
      await ctx.page.fill('#review-subject', subject);
      await ctx.page.fill('#review-text', ctx.uniq('test-review'));
      return actor;
    },
    path: () => '',
    submit: ctx => button(ctx, 'Submit', 'إرسال'),
    retry: ctx => button(ctx, 'Retry', 'إعادة المحاولة'), states: ['confirmed'],
    verify: shownReference,
  };
}

export function inspection() {
  let current;
  return {
    async prepare(ctx) {
      current = await order(ctx, row => row.state === 'paid_held', 'buyer');
      const actor = await enter(ctx, 'reviewer', '/operations/inspections');
      await field(ctx, 'Order reference', 'مرجع الطلب', current.id);
      await button(ctx, 'Open current record', 'فتح السجل الحالي');
      await ctx.page.waitFor('main textarea', {timeout:10000});
      const workspace = await api(ctx, 'trust', `/v1/private-inspections/${current.id}/workspace`, 'reviewer');
      assert.ok(workspace.evidence_refs?.length && workspace.custody_receipt_id);
      await field(ctx, 'Actual findings and reason', 'النتائج الفعلية وسبب القرار', ctx.uniq('test-inconclusive'));
      await check(ctx);
      return actor;
    },
    path: () => post('trust', '/v1/private-inspections/results'), states: ['inconclusive'],
    submit: ctx => button(ctx, 'Record inspection result', 'تسجيل نتيجة الفحص'),
    retry: ctx => button(ctx, 'Retry the same action', 'إعادة محاولة الإجراء نفسه'),
    verify: shownReference,
  };
}

export function delivery() {
  let current;
  return {
    async prepare(ctx) {
      current = await order(ctx, row => row.state === 'paid_held');
      const actor = await enter(ctx, 'buyer', '/deliveries');
      await field(ctx, 'Order reference', 'مرجع الطلب', current.id);
      await button(ctx, 'View custody', 'عرض الحيازة');
      const record = (await api(ctx, 'orders', `/v1/custody/${current.id}`)).result;
      assert.ok(record && !record.held && !record.buyer_received_at && record.state !== 'returned');
      const proof = await handoverObservations(ctx, current, actor, record);
      for (const [en, ar, value] of [
        ['Actual watch reference', 'مرجع الساعة الفعلية', proof.watch_id],
        ['Actual recipient reference', 'مرجع المستلم الفعلي', proof.recipient],
        ['Actual condition', 'الحالة الفعلية', proof.condition],
        ['Accessories received, separated by commas', 'الملحقات المستلمة، مفصولة بفواصل', proof.accessories.join(', ')],
        ['Actual location', 'الموقع الفعلي', proof.location],
        ['Agreed address', 'العنوان المتفق عليه', proof.address],
      ]) await field(ctx, en, ar, value);
      await check(ctx);
      return actor;
    },
    path: () => post('orders', `/v1/custody/${current.id}/buyer-receipts`), states: ['received'],
    submit: ctx => button(ctx, 'Record actual receipt', 'تسجيل الاستلام الفعلي'),
    retry: ctx => button(ctx, 'Retry the same receipt', 'إعادة محاولة الاستلام نفسه'),
    async verify(ctx, value) {
      await shownReference(ctx, value);
      const record = (await api(ctx, 'orders', `/v1/custody/${current.id}`)).result;
      assert.equal(record.operation_id, reference(value));
      assert.equal(record.state, 'received');
      assert.equal(record.held, false);
      assert.ok(record.buyer_received_at && record.dispute_deadline);
      assert.equal(Date.parse(record.dispute_deadline)-Date.parse(record.buyer_received_at), record.window_hours * 3600000);
      assert.ok([72,168].includes(record.window_hours));
    },
  };
}

export function dispute() {
  return {
    async prepare(ctx) {
      const current = await order(ctx, row => row.state === 'paid_held' || row.state === 'received');
      const actor = await enter(ctx, 'buyer', '/disputes');
      await ctx.page.fill('#dispute-subject', current.id);
      await button(ctx, 'Open current record', 'فتح السجل الحالي');
      await ctx.page.waitFor('#dispute-reason', {timeout:10000});
      await ctx.page.fill('#dispute-reason', ctx.uniq('test-dispute'));
      return actor;
    },
    path: () => post('trust', '/v1/disputes/commands'), states: ['open'],
    submit: ctx => button(ctx, 'Submit current action', 'إرسال الإجراء الحالي'),
    retry: ctx => button(ctx, 'Retry the same reference', 'إعادة المحاولة بالمرجع نفسه'),
    verify: shownReference,
  };
}

export async function runMutation(ctx, mode, factory) {
  const spec = factory();
  if (factory === review) {
    const prepare = spec.prepare;
    let subject;
    spec.prepare = async ctx => {
      const actor = await prepare(ctx);
      subject = await ctx.page.evaluate(() => document.querySelector('#review-subject').value);
      return actor;
    };
    spec.path = () => post('trust', `/v1/transaction-reviews/purchases/${subject}`);
  }
  // Quote creation belongs to each account; its private read is the permission boundary.
  if (factory === fees && mode === 'negative') {
    const verify = spec.verify;
    let value;
    spec.verify = async (ctx, result) => {value=result;await verify(ctx,result);};
    await mutate(ctx, 'journey', spec);
    return refusal(ctx, {path:post('pricing', `/v1/quotes/${value.id}`),method:'GET',body:null});
  }
  return mutate(ctx, mode, spec);
}

export async function readFeature(ctx, mode, kind) {
  let actor, path, record, expected, createdOperation;
  if (kind === 'policy') {
    let created;
    const setup = auction(true), verify = setup.verify;
    setup.verify = async (ctx, value) => {created=value;await verify(ctx,value);};
    await mutate(ctx, 'journey', setup);
    createdOperation = created.operation_id;
    actor = await enter(ctx, 'private-seller', '/seller/auctions');
    const rows = await api(ctx, 'auction', '/v1/seller/auctions', 'private-seller');
    const lot = rows.items.find(row => row.id === created.auction_id);
    assert.ok(lot);
    path = post('auction', `/v2/seller/auctions/${lot.id}/policy`);
    expected = lot.ends_at;
    await observe(ctx, path, 'GET');
    record = await received(ctx);
    const policy = confirmed(record);
    assert.equal(policy.current_ends_at, expected);
    assert.equal(policy.reserve_set, true);
    await visible(ctx, expected);
  } else if (kind === 'closing') {
    let created;
    const setup = auction(), verify = setup.verify;
    setup.verify = async (ctx, value) => {created=value;await verify(ctx,value);};
    await mutate(ctx, 'journey', setup);
    createdOperation = created.operation_id;
    const waitForState = async status => {
      const deadline = Date.now() + 240000;
      while (Date.now() < deadline) {
        const lot = await api(ctx, 'auction', `/v1/auctions/${created.auction_id}`);
        if (lot.status === status) return lot;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      throw new Error(`Auction did not reach ${status} at its fixed deadline`);
    };
    await waitForState('live');
    await mutate(ctx, 'journey', bidding(created.auction_id));
    actor = await ctx.actor('buyer');
    path = post('auction', `/v1/auctions/${created.auction_id}/my-fixed-end-result`);
    await observe(ctx, path, 'GET');
    await waitForState('ended');
    record = await ctx.page.evaluate(async () => {
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        const record = window.__n09Records?.find(row => row.status === 200 && row.json?.status === 'closed');
        if (record) return record;
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      throw new Error('The live page did not receive a final auction result');
    });
    const result = confirmed(record, ['closed']);
    assert.equal(result.won, true, 'The buyer must complete the winner journey');
    assert.ok(result.order_id);
    await button(ctx, 'Continue to simulated payment', 'تابع إلى الدفع التجريبي');
    assert.ok((await ctx.page.url()).includes(`/checkout/${result.order_id}`));
    expected = result.order_id;
  } else if (kind === 'timeline') {
    const created = await newOrder(ctx);
    actor = await enter(ctx, 'buyer', '/orders');
    await ctx.page.waitFor(`a[href$="/orders/${created.id}"]`, {timeout:10000});
    path = post('communications', `/v1/order-timeline/${encodeURIComponent(created.id)}`);
    await observe(ctx, path, 'GET');
    await ctx.page.click(`a[href$="/orders/${created.id}"]`);
    record = await received(ctx);
    const value = confirmed(record);
    assert.equal(value.order_id, created.id);
    assert.ok(value.milestones?.length && value.waiting?.party);
    expected = value.reference;
    await visible(ctx, expected);
  } else {
    actor = await enter(ctx, 'private-seller', '/receipts');
    path = post('orders', '/internal/v1/financial-reports');
    await observe(ctx, path, 'GET');
    await button(ctx, 'Retry', 'إعادة المحاولة');
    record = await received(ctx);
    const value = confirmed(record, ['ready']);
    assert.equal(value.simulated, true);
    assert.equal(value.currency, 'USD');
    assert.ok(value.items?.length, 'A real receipt is required');
    await button(ctx, 'Read receipt', 'قراءة الإيصال', 0);
    record = await received(ctx, 2);
    const receipt = confirmed(record, ['ready']);
    assert.equal(receipt.items.length, 1);
    assert.equal(receipt.items[0].order_id, value.items[0].order_id);
    expected = value.items[0].order_id;
    await visible(ctx, expected);
  }
  try {
    if (mode === 'negative') {
      if (kind === 'closing') {
        const other = await ctx.actor('buyer2');
        const result = await ctx.api('auction','GET',path.replace('/api/web/v1/auction',''),undefined,{as:'buyer2'});
        assert.equal(result.status,200);
        assert.equal(result.json.won,false);
        assert.equal(result.json.order_id,null);
        return {operation_id:result.json.auction_id,actor_id:other.actor_id};
      }
      return await refusal(ctx, record);
    }
    if (mode === 'recovery') {
      await ctx.page.reload();
      await visible(ctx, expected);
      const service = path.split('/')[4];
      const result = await api(ctx, service, record.path.replace(`/api/web/v1/${service}`, ''), kind === 'policy' || kind === 'reports' ? 'private-seller' : 'buyer');
      if (kind === 'policy') assert.equal(result.current_ends_at, expected);
      if (kind === 'timeline') assert.equal(result.reference, expected);
      if (kind === 'closing') assert.equal(result.order_id, expected);
      if (kind === 'reports') assert.ok(result.items.some(row => row.order_id === expected));
    }
    // For a read, use a stable reference actually rendered by the page.
    return {operation_id:createdOperation ?? (kind === 'reports' ? reference(record.json) : expected),actor_id:actor.actor_id};
  } finally {await ctx.page.evaluate(() => window.__n09Restore?.());}
}

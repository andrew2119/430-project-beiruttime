import { listing } from './catalog.mjs';
import { assert, button, copy, field, loseResponse, observe, open, reference, response, result, visible } from './browser.mjs';

async function check(ctx, label) {
  await ctx.page.evaluate(text => {
    const label = [...document.querySelectorAll('label')].find(node => node.textContent.trim() === text);
    const input = label?.querySelector('input[type="checkbox"]');
    if (!input || input.disabled) throw new Error('Missing available acknowledgement');
    if (!input.checked) input.click();
  }, label);
}

async function publish(ctx) {
  const created = await listing(ctx, 'journey');
  const t = await copy(ctx, 'listing-editor');
  await field(ctx, t.case, 'Synthetic test wear');
  await check(ctx, t.ownership);
  await check(ctx, t.noDocuments);
  await button(ctx, t.disclosure);
  await ctx.page.evaluate(() => {
    const control = document.querySelector('[role="combobox"]');
    if (!control) throw new Error('Missing modification choice');
    control.click();
  });
  await ctx.page.waitFor('[role="option"]', {timeout:10000});
  await ctx.page.evaluate(text => {
    const option = [...document.querySelectorAll('[role="option"]')].find(node => node.textContent.trim() === text);
    if (!option) throw new Error('Missing disclosure answer');
    option.click();
  }, t.no);
  await observe(ctx); await button(ctx, t.save);
  await response(ctx, `/seller/listings/${created.operation_id}`, false, 'PUT');
  await visible(ctx, t.saved);
  await button(ctx, t.photos);
  await check(ctx, t.photoSafety);
  await observe(ctx);
  await ctx.page.evaluate(async label => {
    const input = [...document.querySelectorAll('input[type="file"]')].find(node => node.getAttribute('aria-label') === label);
    if (!input || input.disabled) throw new Error('Missing watch photo upload');
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 320;
    const paint = canvas.getContext('2d');
    paint.fillStyle = '#eeeeee'; paint.fillRect(0, 0, 320, 320);
    paint.fillStyle = '#333333'; paint.fillRect(130, 20, 60, 280);
    paint.fillStyle = '#aaaaaa'; paint.beginPath(); paint.arc(160, 160, 70, 0, Math.PI * 2); paint.fill();
    paint.fillStyle = '#111111'; paint.fillText('Synthetic test watch', 90, 165);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    const transfer = new DataTransfer();
    transfer.items.add(new File([blob], 'test-watch.png', {type:'image/png'}));
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles:true}));
  }, t.addPhoto);
  await response(ctx, `/seller/listings/${created.operation_id}/media`);
  await button(ctx, t.review);
  await observe(ctx); await button(ctx, t.feeReview);
  await response(ctx, '/quotes');
  await observe(ctx); await button(ctx, `${t.publish} ↗`);
  const published = await response(ctx, `/seller/listings/${created.operation_id}/publish`);
  assert.equal(published.json.status, 'published');
  await visible(ctx, t.published);
  await button(ctx, t.facts);
  return {actor:{actor_id:created.actor_id}, row:published.json, t};
}

export function revisionOutcome(receipt, row, price) {
  assert.equal(receipt.json.status, 'succeeded');
  assert.equal(receipt.json.listing.id, row.id);
  assert.equal(receipt.json.listing.status, 'published');
  assert.equal(receipt.json.listing.revision, row.revision + 1);
  assert.equal(receipt.json.listing.facts.price_minor, price);
  return reference(receipt);
}

export async function management(ctx, mode) {
  const {actor, row, t} = await publish(ctx);
  const reason = ctx.uniq('test price correction');
  const price = row.facts.price_minor + 100;
  if (mode === 'negative') {
    await open(ctx, `/checkout?listing_id=${row.id}`, 'buyer');
    const words = ctx.cell.locale === 'ar'
      ? {review:'احصل على عرض سعر دقيق حالي', accept:'اقبل العرض الدقيق واحجز', terms:'أوافق على عرض السعر الدقيق بالدولار والرسوم المحصّلة غير القابلة للاسترداد لهذه الساعة ونسختها.'}
      : {review:'Get current exact quote', accept:'Accept exact quote and reserve', terms:'I accept this exact USD quote and non-refundable collected fees for this watch and revision.'};
    await button(ctx, words.review);
    await check(ctx, words.terms);
    await observe(ctx); await button(ctx, words.accept);
    const reserved = await response(ctx, '/exact-reservations');
    assert.equal(reserved.json.status, 'succeeded');
    await open(ctx, `/seller/listings/${row.id}`, 'private-seller');
    await ctx.page.waitFor('input', {timeout:10000});
  }
  await field(ctx, t.price, (price / 100).toFixed(2));
  await field(ctx, ctx.cell.locale === 'ar' ? 'سبب التعديل' : 'Revision reason', reason);
  await observe(ctx);
  if (mode === 'recovery') await loseResponse(ctx, `/seller/listings/${row.id}/revisions`);
  await button(ctx, t.saveRevision);
  const receipt = await response(ctx, `/seller/listings/${row.id}/revisions`);
  if (mode === 'negative') {
    assert.equal(receipt.json.status, 'denied');
    assert.equal(receipt.json.listing.revision, row.revision);
    assert.equal(receipt.json.listing.facts.price_minor, row.facts.price_minor);
    await visible(ctx, t.revisionBlocked);
    await ctx.page.reload();
    const current = await ctx.api('catalog', 'GET', `/v1/seller/listings/${row.id}`, undefined, {as:'private-seller'});
    assert.equal(current.status, 200);
    assert.equal(current.json.revision, row.revision);
    assert.equal(current.json.facts.price_minor, row.facts.price_minor);
    return result(actor, reference(receipt));
  }
  const id = revisionOutcome(receipt, row, price);
  if (mode === 'recovery') {
    await observe(ctx); await button(ctx, t.saveRevision);
    const repeated = await response(ctx, `/seller/listings/${row.id}/revisions`);
    assert.equal(reference(repeated), id);
    assert.deepEqual(repeated.json, receipt.json);
  }
  await visible(ctx, t.revisionSaved);
  await visible(ctx, reason);
  await ctx.page.reload();
  await visible(ctx, reason);
  const history = await ctx.api('catalog', 'GET', `/v1/seller/listings/${row.id}/revisions`, undefined, {as:'private-seller'});
  assert.equal(history.status, 200);
  const entries = history.json.items.filter(item => item.reason === reason);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].actor_id, actor.actor_id);
  assert.equal(entries[0].revision, row.revision + 1);
  assert.equal(entries[0].before_facts.price_minor, row.facts.price_minor);
  assert.equal(entries[0].after_facts.price_minor, price);
  return result(actor, id);
}

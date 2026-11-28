import { assert, button, copy, feature, field, observe, open, reference, response, result, submit, visible } from './browser.mjs';

export async function auditedChange(ctx) {
  const target = await ctx.actor('buyer2');
  await open(ctx, '/operations/moderation', 'reviewer');
  const t = await copy(ctx, 'moderation');
  await ctx.page.evaluate(label => {
    const node = [...document.querySelectorAll('label')].find(node => node.textContent.trim() === label);
    const control = node?.parentElement?.querySelector('[role="combobox"]');
    if (!control) throw new Error('Missing content type control');
    control.click();
  }, t.targetKind);
  await ctx.page.waitFor('[role="option"]', {timeout:10000});
  await ctx.page.evaluate(label => {
    const option = [...document.querySelectorAll('[role="option"]')].find(node => node.textContent.trim() === label);
    if (!option) throw new Error('Missing account content type');
    option.click();
  }, t.user);
  await field(ctx, t.targetId, target.actor_id);
  await field(ctx, t.evidence, ctx.uniq('Beirut Time synthetic review'));
  await observe(ctx);
  await button(ctx, t.submitReport);
  const reported = await response(ctx, '/moderation/reports');
  const subject = reported.json.id;
  assert.ok(subject, 'Report must return the new case reference');
  const actor = await open(ctx, '/operations/moderation', 'operator');
  await visible(ctx, subject);
  await ctx.page.evaluate(({subject, label}) => {
    const row = [...document.querySelectorAll('li')].find(node =>
      [...node.querySelectorAll('bdi')].some(value => value.textContent.trim() === subject));
    const control = [...(row?.querySelectorAll('button') ?? [])].find(node => node.textContent.trim() === label);
    if (!control || control.disabled) throw new Error('New case cannot be claimed');
    control.click();
  }, {subject, label:t.claim});
  const changed = await response(ctx, `/moderation/cases/${subject}/claim`);
  assert.equal(changed.json.id, subject);
  assert.equal(changed.json.status, 'assigned');
  assert.equal(changed.json.actor_id, actor.actor_id);
  return {actor, subject, operation_id:reference(changed), revision:changed.json.revision};
}

export function changeReference(receipt, change) {
  const item = receipt.json.results.find(part => part.source === 'trust' && part.state === 'ready')
    ?.page?.items.find(item => item.operation_id === change.operation_id);
  assert.ok(item, 'The new audited change must be returned by its owner');
  assert.equal(item.subject_id, change.subject);
  assert.equal(item.actor_id, change.actor.actor_id);
  assert.equal(item.revision, change.revision);
  assert.ok(item.reason_reference);
  return item;
}

export async function trustResponse(ctx, change) {
  const receipt = await ctx.page.evaluate(async operation => {
    const end = Date.now() + 10000;
    while (Date.now() < end) {
      const record = window.__btProof?.records.find(record =>
        record.path.endsWith('/audit-references') && record.method === 'GET' &&
        record.status >= 200 && record.status < 300 &&
        record.json?.results?.some(part => part.source === 'trust' && part.state === 'ready' &&
          part.page?.items?.some(item => item.operation_id === operation)));
      if (record) return record;
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    throw new Error('No current review response for the new change');
  }, change.operation_id);
  changeReference(receipt, change);
  return receipt;
}

export async function retryTrust(ctx) {
  await ctx.page.evaluate(async ({panel, retry}) => {
    const end = Date.now() + 10000;
    while (Date.now() < end) {
      const section = [...document.querySelectorAll('section[aria-label]')]
        .find(node => node.getAttribute('aria-label') === panel);
      const control = [...(section?.querySelectorAll('button') ?? [])]
        .find(node => node.textContent.trim() === retry && !node.disabled);
      if (control) { control.click(); return; }
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    throw new Error('No available retry for review records');
  }, ctx.cell.locale === 'ar' ? {panel:'سجلات المراجعة', retry:'أعد المحاولة'} : {panel:'Review records', retry:'Retry'});
}

async function audit(ctx,mode) {
  const started = new Date(Date.now() - 1000);
  const change = await auditedChange(ctx);
  const actor=await open(ctx,'/operations/audit','operator');
  const ar=ctx.cell.locale==='ar';
  const after=ar?'من توقيت UTC (شامل)':'From UTC (inclusive)';
  const before=ar?'حتى توقيت UTC (غير شامل)':'Until UTC (exclusive)';
  const operation=ar?'مرجع عملية الاستعلام':'Query operation reference';
  await ctx.page.waitFor('form',{timeout:10000});
  const end=new Date(Date.now() + 1000);
  await field(ctx,after,started.toISOString().replace(/\.\d{3}Z$/,'Z'));
  await field(ctx,before,end.toISOString().replace(/\.\d{3}Z$/,'Z'));
  await field(ctx,ar?'مرجع السجل (اختياري)':'Resource reference (optional)',change.subject);
  await observe(ctx); await submit(ctx);
  const receipt=await trustResponse(ctx, change);
  const id=reference(receipt);
  const item = changeReference(receipt, change);
  const organization=await ctx.page.evaluate(()=>document.querySelector('input[readonly]').value);
  if(mode==='negative') {
    const other=await ctx.actor('buyer');
    await ctx.signIn('buyer'); await ctx.page.goto('/operations/audit');
    await visible(ctx,ar?'رُفض الوصول الخاص':'Private access denied');
    const denied=await ctx.api('communications','GET',`/v1/audit-references?${new URLSearchParams({
      schema_version:'audit-references.v1',source:'trust',operation_id:id,organization_id:organization,
      after:started.toISOString(),before:end.toISOString(),offset:'0',limit:'20',
    })}`,undefined,{as:'buyer'});
    assert.equal(denied.status,403);
    return result(other,id);
  }
  await visible(ctx,ar?'سجلات المراجعة':'Review records');
  if(mode==='recovery') {
    await observe(ctx);
    await retryTrust(ctx);
    const repeated=await trustResponse(ctx, change);
    assert.equal(reference(repeated),id);
    assert.deepEqual(changeReference(repeated, change), item);
    await visible(ctx,ar?'سجلات المراجعة':'Review records');
  }
  await visible(ctx, change.operation_id);
  await observe(ctx);
  await ctx.page.evaluate(operation => {
    const row = [...document.querySelectorAll('li')].find(node =>
      [...node.querySelectorAll('bdi')].some(value => value.textContent.trim() === operation));
    const control = row?.querySelector('button');
    if (!control || control.disabled) throw new Error('Missing inspection for the new change');
    control.click();
  }, change.operation_id);
  const detail=await response(ctx,'/audit-references/operations/',false,'GET');
  assert.equal(detail.json.state,'ready');
  assert.deepEqual(detail.json.item,item);
  await ctx.page.waitFor('[role="dialog"]',{timeout:10000});
  assert.ok((await ctx.page.text('[role="dialog"]')).includes(item.reason_reference));
  // Query binding is shown on the form and returned by the service.
  await ctx.page.evaluate(label=>{
    const node=[...document.querySelectorAll('label')].find(node=>node.textContent.trim()===label);
    if(!node) throw new Error('Missing query reference field');
  },operation);
  return result(actor,id);
}
export const auditFeature=feature(7,ctx=>audit(ctx,'journey'),ctx=>audit(ctx,'negative'),ctx=>audit(ctx,'recovery'));

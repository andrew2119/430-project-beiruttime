import { management } from './management.mjs';
import { randomUUID } from 'node:crypto';
import { assert, button, copy, feature, field, loseResponse, observe, open, reference, response, result, submit, visible } from './browser.mjs';

async function draft(ctx) {
  const actor = await open(ctx,'/seller/listings','private-seller');
  const t = await copy(ctx,'listing-editor');
  await button(ctx,t.newListing);
  const created = await response(ctx,'/seller/listings');
  assert.equal(created.json.status,'draft');
  const id = created.json.id;
  assert.ok(id);
  await ctx.page.waitFor('input',{timeout:10000});
  return {actor,id,t};
}
export async function listing(ctx, mode, edit = false) {
  const {actor,id,t} = await draft(ctx);
  const name = ctx.uniq('Beirut Time test');
  await field(ctx,t.brand,'Beirut Time');
  await field(ctx,t.model,name);
  await field(ctx,t.reference,ctx.uniq('test-reference'));
  await field(ctx,t.location,'New York');
  await field(ctx,t.year,'2024');
  await field(ctx,t.price,'5000.00');
  await field(ctx,t.condition,'Synthetic test watch in good condition');
  await observe(ctx);
  await button(ctx,t.save);
  const saved = await response(ctx,`/seller/listings/${id}`,false,'PUT');
  assert.equal(saved.json.id,id);
  assert.equal(saved.json.facts.model,name);
  await visible(ctx,t.saved);
  if (edit) {
    await field(ctx,t.model,`${name} revised`);
    await observe(ctx); await button(ctx,t.save);
    const changed = await response(ctx,`/seller/listings/${id}`,false,'PUT');
    assert.ok(changed.json.revision > saved.json.revision);
    assert.equal(changed.json.facts.model,`${name} revised`);
    await visible(ctx,t.saved);
  }
  if (mode === 'negative') {
    const other = await open(ctx,`/seller/listings/${id}`,'buyer2');
    await visible(ctx,t.forbidden);
    assert.ok(!(await ctx.page.text('body')).includes(name));
    const denied = await ctx.api('catalog','GET',`/v1/seller/listings/${id}`,undefined,{as:'buyer2'});
    assert.ok([403,404].includes(denied.status));
    return result(other,id);
  }
  if (mode === 'recovery') {
    await ctx.page.reload();
    await ctx.page.waitFor('input',{timeout:10000});
    const expected = edit ? `${name} revised` : name;
    await ctx.page.evaluate(async expected => {
      const end=Date.now()+10000;
      while(Date.now()<end) {
        if([...document.querySelectorAll('input')].some(input=>input.value===expected)) return;
        await new Promise(resolve=>setTimeout(resolve,40));
      }
      throw new Error('Saved draft did not survive reload');
    },expected);
  }
  return result(actor,id);
}
export async function organization(ctx) {
  // Actor setup already performs onboarding; this reads its current selected scope.
  const answer = await ctx.api('identity','POST','/v1/accounts/refresh',undefined,{as:'dealer'});
  assert.equal(answer.status,200);
  const principal = answer.json?.principal;
  const grant = principal?.organization_grants?.find(item =>
    principal.organizations?.includes(item.organization_id) &&
    item.permissions?.includes('business.stock.write'));
  const id = grant?.organization_id;
  assert.ok(id,'Dealer must have a current organization');
  return id;
}
async function dealerImport(ctx,mode) {
  await ctx.actor('dealer');
  const org = await organization(ctx);
  const actor = await open(ctx,`/seller/import?organization_id=${encodeURIComponent(org)}`,'dealer');
  await ctx.page.waitFor('textarea',{timeout:10000});
  const serial = ctx.uniq('test-serial');
  const header='brand,model,reference,year,condition,location,price_usd,serial';
  const row=`Beirut Time,Test watch,${ctx.uniq('test-ref')},2024,Good,New York,5000.00,${serial}`;
  await ctx.page.fill('textarea',`${header}\n${mode==='negative' ? '=1,Test,test,2024,Good,New York,-1.00,test-serial' : row}`);
  await observe(ctx);
  if(mode==='recovery') await loseResponse(ctx,'/seller/imports');
  await button(ctx,ctx.cell.locale==='ar'?'إنشاء مسودات خاصة':'Create private drafts');
  const receipt=await response(ctx,'/seller/imports');
  assert.equal(receipt.json.items.length,1);
  const item=receipt.json.items[0];
  assert.equal(item.state,mode==='negative'?'invalid':'draft');
  if(mode==='negative') assert.ok(!item.listing_id);
  else {
    assert.ok(item.listing_id);
    if(mode!=='recovery') await visible(ctx,ctx.cell.locale==='ar'?'مسودة خاصة':'Private draft');
  }
  const id=reference(receipt);
  if(mode==='recovery') {
    await observe(ctx);
    await button(ctx,ctx.cell.locale==='ar'?'إعادة الاستيراد نفسه':'Retry the same import');
    const repeated=await response(ctx,'/seller/imports');
    assert.equal(reference(repeated),id);
    assert.deepEqual(repeated.json.items,receipt.json.items);
    await ctx.page.goto(`/seller/listings/${item.listing_id}?organization_id=${org}`);
    await ctx.page.waitFor('h1',{timeout:10000});
    await ctx.page.reload();
    await visible(ctx,'Beirut Time');
  }
  return result(actor,id);
}
async function publicWatches(ctx, count=1) {
  const answer=await ctx.api('catalog','GET','/v1/discovery/watches?currency=USD&sort=newest',undefined,{as:'buyer'});
  assert.equal(answer.status,200);
  assert.ok(answer.json.items?.length>=count,'Current public watches are required');
  return answer.json.items.slice(0,count);
}
async function browse(ctx,mode) {
  const actor=await open(ctx,'/search');
  const t=await copy(ctx,'discovery');
  const [watch]=await publicWatches(ctx);
  await ctx.page.waitFor('[name="q"]',{timeout:10000});
  await ctx.page.fill('[name="q"]',watch.brand);
  await observe(ctx); await submit(ctx);
  const receipt=await response(ctx,'/discovery/watches',false,'GET');
  assert.ok(receipt.json.items.some(item=>item.id===watch.id));
  await visible(ctx,watch.title);
  if(mode==='negative') {
    await ctx.page.fill('[name="min_price"]','200');
    await ctx.page.fill('[name="max_price"]','100');
    await observe(ctx); await submit(ctx);
    await visible(ctx,t.rangeError);
    assert.ok((await ctx.page.text('[role="alert"]')).includes(t.rangeError));
    assert.equal(await ctx.page.evaluate(()=>window.__btProof.records.filter(item=>item.path.includes('/discovery/watches')).length),0);
  }
  if(mode==='recovery') { await ctx.page.reload(); await visible(ctx,watch.title); }
  return result(actor,watch.id);
}
async function detail(ctx,mode) {
  const actor=await open(ctx,'/watches');
  const t=await copy(ctx,'discovery');
  if(mode==='negative') {
    // A genuine private draft is never exposed by a public detail or related read.
    const privateDraft=await draft(ctx);
    await ctx.signIn('buyer');
    await ctx.page.goto(`/watches/${privateDraft.id}`);
    await visible(ctx,t.listingUnavailable);
    return result(actor,privateDraft.id);
  }
  const [watch]=await publicWatches(ctx);
  await ctx.page.goto(`/watches/${watch.id}`);
  await visible(ctx,watch.title);
  await visible(ctx,t.details);
  if(mode==='recovery') { await ctx.page.reload(); await visible(ctx,watch.title); }
  return result(actor,watch.id);
}
async function similarWatches(ctx,mode) {
  const actor=await open(ctx,'/watches');
  const ar=ctx.cell.locale==='ar';
  let subject;
  if(mode==='negative') {
    const created=await draft(ctx);
    subject={id:created.id,revision:1};
    await ctx.signIn('buyer');
  } else {
    [subject]=await publicWatches(ctx);
    await ctx.page.goto(`/watches/${subject.id}`);
    await visible(ctx,subject.title);
  }
  const operation=randomUUID();
  const path=`/similar?${new URLSearchParams({subject_id:subject.id,expected_revision:String(subject.revision),operation_id:operation,offset:'0'})}`;
  await ctx.page.goto(path);
  await visible(ctx,ar?'ساعات مشابهة':'Similar watches');
  if(mode==='negative') {
    await visible(ctx,ar?'الساعة غير متاحة':'Watch unavailable');
    const links=await ctx.page.evaluate(()=>[...document.querySelectorAll('a')].map(node=>node.getAttribute('href')));
    assert.ok(!links.some(href=>href?.includes('/seller/listings/')));
  } else {
    // A complete empty result is valid; a pending or unavailable result is not.
    await ctx.page.evaluate(async ({count,empty})=>{
      const end=Date.now()+10000;
      while(Date.now()<end) {
        if(document.body.innerText.includes(count)||document.body.innerText.includes(empty)) return;
        await new Promise(resolve=>setTimeout(resolve,40));
      }
      throw new Error('No complete current similar-watch result');
    },{count:ar?'الساعات المطابقة':'Matching watches',empty:ar?'لا توجد ساعات مشابهة':'No similar watches'});
    const links=await ctx.page.evaluate(()=>[...document.querySelectorAll('a')].map(node=>node.getAttribute('href')));
    // The source cannot appear as its own alternative. The empty-state back link is allowed.
    const alternatives=await ctx.page.evaluate(label=>[...document.querySelectorAll('a')].filter(node=>node.textContent.trim()===label).map(node=>node.getAttribute('href')),ar?'عرض الساعة':'View watch');
    assert.ok(!alternatives.some(href=>href.endsWith(`/watches/${subject.id}`)));
    assert.ok(links.every(href=>!href?.includes('/seller/listings/')));
    if(mode==='recovery') {
      const before=await ctx.page.text('body');
      await ctx.page.reload();
      await visible(ctx,ar?'ساعات مشابهة':'Similar watches');
      await visible(ctx,before.includes(ar?'لا توجد ساعات مشابهة':'No similar watches') ? (ar?'لا توجد ساعات مشابهة':'No similar watches') : (ar?'الساعات المطابقة':'Matching watches'));
      assert.equal(new URL(await ctx.page.url()).searchParams.get('operation_id'),operation);
    }
  }
  return result(actor,await similarReference(ctx,subject,operation,mode));
}
export async function similarReference(ctx,subject,operation,mode) {
  const receipt=await ctx.api('catalog','GET',`/v1/similar-watches/${encodeURIComponent(subject.id)}?${new URLSearchParams({
    operation_id:operation,expected_revision:String(subject.revision),offset:'0',
  })}`,undefined,{as:'buyer'});
  assert.equal(receipt.status,200);
  const id=reference(receipt);
  assert.equal(id,operation);
  assert.equal(receipt.json.subject_id,subject.id);
  assert.equal(receipt.json.expected_revision,subject.revision);
  assert.equal(receipt.json.offset,0);
  assert.ok((mode==='negative' ? ['denied'] : ['ready','empty']).includes(receipt.json.state));
  return id;
}
export async function settledComparison(ctx) {
  const label=ctx.cell.locale==='ar'?'مرجع المقارنة':'Comparison reference';
  const retry=ctx.cell.locale==='ar'?'التحقق مجددًا':'Check again';
  return ctx.page.evaluate(async ({label,retry})=>{
    const end=Date.now()+10000;
    while(Date.now()<end) {
      const line=[...document.querySelectorAll('p')].find(node=>node.textContent.trim().startsWith(`${label}:`));
      const id=line?.querySelector('bdi')?.textContent.trim();
      const control=[...document.querySelectorAll('button')].find(node=>node.textContent.trim()===retry);
      const record=window.__btProof?.records.findLast(item=>item.path.includes('/comparison/operations/') &&
        item.method==='POST' && item.status>=200 && item.status<300 && item.json?.operation_id===id);
      if(record && control && !control.disabled && record.json.columns.every(column=>column.state==='available')) return record;
      await new Promise(resolve=>setTimeout(resolve,40));
    }
    throw new Error('No settled current comparison result');
  },{label,retry});
}
async function comparison(ctx,mode) {
  const actor=await open(ctx,'/compare');
  const watches=await publicWatches(ctx,2);
  await ctx.page.waitFor('#comparison-reference',{timeout:10000});
  let receipt;
  for(const watch of watches) {
    await ctx.page.fill('#comparison-reference',watch.id);
    await observe(ctx); await submit(ctx);
    receipt=await response(ctx,'/comparison/operations/');
    const column=receipt.json.columns.find(column=>column.watch_id===watch.id);
    assert.equal(column?.state,'available');
    await visible(ctx,column.facts.title[ctx.cell.locale]);
  }
  receipt=await settledComparison(ctx);
  const id=reference(receipt);
  if(mode==='negative') {
    await ctx.page.fill('#comparison-reference',watches[0].id);
    await observe(ctx); await submit(ctx);
    await visible(ctx,ctx.cell.locale==='ar'?'أدخل مرجع إعلان صالحًا وغير مكرر. اختر ثلاث ساعات كحد أقصى.':'Enter a valid, distinct listing reference. Choose at most three watches.');
    assert.equal(await ctx.page.evaluate(()=>window.__btProof.records.filter(item=>item.path.includes('/comparison/operations/')).length),0);
  }
  if(mode==='recovery') {
    await observe(ctx);
    await button(ctx,ctx.cell.locale==='ar'?'التحقق مجددًا':'Check again');
    const repeated=await response(ctx,'/comparison/operations/');
    assert.equal(reference(repeated),id);
    assert.deepEqual(repeated.json.columns.map(item=>item.watch_id),watches.map(item=>item.id));
    for(const column of repeated.json.columns) { assert.equal(column.state,'available'); await visible(ctx,column.facts.title[ctx.cell.locale]); }
  }
  return result(actor,id);
}
async function dashboard(ctx,mode) {
  const created=await draft(ctx);
  const actor=await open(ctx,'/seller/dashboard','private-seller');
  const title=ctx.cell.locale==='ar'?'مساحة المبيعات':'Sales workspace';
  await visible(ctx,title);
  await button(ctx,ctx.cell.locale==='ar'?'مسودة':'Draft');
  await visible(ctx,ctx.cell.locale==='ar'?'سجلات الإعلانات الحالية':'Current listing records');
  await ctx.page.waitFor(`a[href*="/seller/listings/${created.id}"]`,{timeout:10000});
  if(mode==='negative') {
    const other=await open(ctx,'/seller/dashboard','buyer2');
    assert.ok(!(await ctx.page.evaluate(()=>[...document.querySelectorAll('a')].map(link=>link.href))).some(href=>href.includes(created.id)));
    const denied=await ctx.api('catalog','GET',`/v1/seller/listings/${created.id}`,undefined,{as:'buyer2'});
    assert.ok([403,404].includes(denied.status));
    return result(other,created.id);
  }
  if(mode==='recovery') {
    await ctx.page.reload(); await visible(ctx,title);
    await ctx.page.waitFor(`a[href*="/seller/listings/${created.id}"]`,{timeout:10000});
  }
  await ctx.page.click(`a[href*="/seller/listings/${created.id}"]`);
  await ctx.page.waitFor('input',{timeout:10000});
  assert.ok((await ctx.page.url()).includes(created.id));
  return result(actor,created.id);
}
async function sellerProfile(ctx,mode) {
  const actor=await open(ctx,'/watches');
  const [watch]=await publicWatches(ctx);
  const answer=await ctx.api('catalog','GET',`/v1/discovery/watches/${watch.id}`,undefined,{as:'buyer'});
  assert.equal(answer.status,200);
  const seller=answer.json.seller;
  assert.ok(seller.id);
  if(mode==='negative') {
    const buyer=await ctx.actor('buyer2');
    await ctx.page.goto(`/sellers/${buyer.actor_id}`);
    await visible(ctx,ctx.cell.locale==='ar'?'الصفحة غير متاحة للزوار':'Profile unavailable to visitors');
    assert.ok(!(await ctx.page.text('body')).includes(buyer.name));
    return result(actor,buyer.actor_id);
  }
  await ctx.page.goto(`/sellers/${seller.id}`);
  await visible(ctx,seller.display_name);
  const id=await ctx.page.evaluate(()=>new URL(location.href).searchParams.get('profile_read'));
  assert.ok(id,'Public profile must expose its actual read reference');
  if(mode==='recovery') {
    await ctx.page.reload(); await visible(ctx,seller.display_name);
    assert.equal(await ctx.page.evaluate(()=>new URL(location.href).searchParams.get('profile_read')),id);
  }
  return result(actor,id);
}
export const catalog = [
  feature(8,ctx=>listing(ctx,'journey'),ctx=>listing(ctx,'negative'),ctx=>listing(ctx,'recovery')),
  feature(9,ctx=>management(ctx,'journey'),ctx=>management(ctx,'negative'),ctx=>management(ctx,'recovery')),
  feature(10,ctx=>dealerImport(ctx,'journey'),ctx=>dealerImport(ctx,'negative'),ctx=>dealerImport(ctx,'recovery')),
  feature(11,ctx=>browse(ctx,'journey'),ctx=>browse(ctx,'negative'),ctx=>browse(ctx,'recovery')),
  feature(12,ctx=>detail(ctx,'journey'),ctx=>detail(ctx,'negative'),ctx=>detail(ctx,'recovery')),
  feature(13,ctx=>comparison(ctx,'journey'),ctx=>comparison(ctx,'negative'),ctx=>comparison(ctx,'recovery')),
  feature(14,ctx=>similarWatches(ctx,'journey'),ctx=>similarWatches(ctx,'negative'),ctx=>similarWatches(ctx,'recovery')),
  feature(15,ctx=>dashboard(ctx,'journey'),ctx=>dashboard(ctx,'negative'),ctx=>dashboard(ctx,'recovery')),
  feature(16,ctx=>sellerProfile(ctx,'journey'),ctx=>sellerProfile(ctx,'negative'),ctx=>sellerProfile(ctx,'recovery')),
];

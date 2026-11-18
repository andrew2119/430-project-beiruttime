import assert from 'node:assert/strict';
import test from 'node:test';
import {features} from './index.mjs';
import {confirmed, mutate, observe, received, reference, refusal} from './browser.mjs';
import {releasedPurchase} from './purchase.mjs';

test('review preparation completes a distinct new purchase on every invocation', async () => {
  const events = [];
  let sequence = 0;
  const ctx = {actor:async()=>({actor_id:'test-buyer'})};
  const create = async () => {
    const purchase = {actor_id:'test-buyer',order_id:`test-order-${++sequence}`,operation_id:`test-payment-${sequence}`};
    events.push(['paid',purchase.order_id]);
    return purchase;
  };
  const complete = async (context, purchase) => {
    assert.equal(context,ctx);
    events.push(['completed',purchase.order_id]);
    return {...purchase,state:'released',operation_id:`test-release-${sequence}`};
  };
  const subjects = [];
  for (let index = 0; index < 3; index++) subjects.push(await releasedPurchase(ctx,create,complete));
  assert.equal(new Set(subjects).size,3);
  assert.deepEqual(events,subjects.flatMap(id=>[['paid',id],['completed',id]]));
});

test('review preparation refuses incomplete, foreign or substituted purchases', async () => {
  const ctx = {actor:async()=>({actor_id:'test-buyer'})};
  const purchase = {actor_id:'test-buyer',order_id:'test-new-order',operation_id:'test-payment'};
  for (const patch of [
    {state:'paid_held'}, {actor_id:'test-other'}, {order_id:'test-old-order'}, {operation_id:null},
  ]) {
    await assert.rejects(releasedPurchase(ctx,async()=>purchase,
      async()=>({...purchase,state:'released',operation_id:'test-release',...patch})));
  }
  let completed = false;
  await assert.rejects(releasedPurchase(ctx,async()=>({...purchase,actor_id:'test-other'}),async()=>{completed=true;}));
  assert.equal(completed,false);
  await assert.rejects(releasedPurchase(ctx,async()=>purchase), /handover and release composition unavailable; connected proof deferred/);
});

test('timeline observation captures the detail read through its owning gateway', async () => {
  const previousWindow = globalThis.window;
  const previousLocation = globalThis.location;
  const path = '/api/web/v1/communications/v1/order-timeline/test-order';
  const timeline = {order_id:'test-order',reference:'test-order-reference',operation_id:'test-order-operation'};
  globalThis.location = {origin:'http://localhost'};
  globalThis.window = {fetch:async()=>new Response(JSON.stringify(timeline))};
  const ctx = {page:{evaluate:async(fn,...args)=>fn(...args)}};
  try {
    await observe(ctx,path,'GET');
    await window.fetch('http://localhost/api/web/v1/communications/v1/order-timeline?offset=0&limit=20');
    assert.equal(window.__n09Records.length,0);
    await window.fetch(`http://localhost${path}?`);
    const record = await received(ctx);
    assert.equal(record.method,'GET');
    assert.equal(new URL(record.path,location.origin).pathname,path);
    assert.equal(reference(confirmed(record)),'test-order-operation');
    assert.equal(window.__n09Records.length,1);
  } finally {
    window.__n09Restore?.();
    globalThis.window = previousWindow;
    globalThis.location = previousLocation;
  }
});

test('exports the sixteen assigned entries with the published scenario contract', () => {
  assert.equal(features.length, 16);
  assert.equal(new Set(features.map(feature => feature.feature_id)).size, 16);
  for (const [offset, feature] of features.entries()) {
    const number = offset + 17;
    assert.deepEqual(Object.keys(feature).sort(), [
      'feature_id', 'proof_id', 'proof_revision', 'journey', 'negative', 'recovery',
    ].sort());
    assert.equal(feature.feature_id, `F${number}`);
    assert.equal(feature.proof_id, `f${number}-proof`);
    assert.equal(feature.proof_revision, '1');
    for (const scenario of ['journey', 'negative', 'recovery']) assert.equal(typeof feature[scenario], 'function');
  }
});

test('every scenario starts with the supplied live session', async () => {
  for (const feature of features) {
    for (const scenario of ['journey','negative','recovery']) {
      let accessed = false;
      const unavailable = new Error('test-session-unavailable');
      const ctx = new Proxy({}, {get() {accessed = true;throw unavailable;}});
      await assert.rejects(feature[scenario](ctx), error => error === unavailable);
      assert.equal(accessed, true, `${feature.feature_id} ${scenario}`);
    }
  }
});

test('pending, refused, malformed and server errors cannot become proof', () => {
  for (const state of ['pending','denied','unavailable','failed','allocation_pending']) {
    assert.throws(() => confirmed({status:200,json:{state}}, ['confirmed']));
  }
  assert.throws(() => confirmed({status:503,json:{state:'confirmed'}}));
  assert.throws(() => confirmed({status:200,json:null}));
  assert.throws(() => reference({}));
  assert.throws(() => reference({operation_id:42}));
  assert.equal(reference({operation_id:'test-real-operation'}), 'test-real-operation');
});

test('an unavailable service or a permitted foreign request is not a negative proof', async () => {
  const record = {path:'/api/web/v1/orders/v1/cancellations',method:'POST',body:'{}'};
  for (const status of [200,202,500,503]) {
    const ctx = {actor:async()=>({actor_id:'test-buyer2'}),api:async()=>({status,json:{request_id:'test-request'}})};
    await assert.rejects(refusal(ctx,record));
  }
});

test('lost response recovery repeats the actual command and requires one returned operation', async () => {
  const previous = globalThis.window;
  let sends = 0;
  globalThis.window = {fetch:async()=>{
    sends++;
    return new Response(JSON.stringify({operation_id:'test-operation',state:'confirmed'}),{status:200});
  }};
  const ctx = {page:{evaluate:async(fn,...args)=>fn(...args)}};
  const send = async()=>{
    try {await window.fetch('http://localhost/api/web/v1/orders/v1/cancellations',{
      method:'POST',headers:{'Idempotency-Key':'test-retained-key'},body:'{"reason":"test-reason"}',
    });} catch(error) {assert.equal(error.message,'Response lost after acceptance');}
  };
  globalThis.location = {origin:'http://localhost'};
  try {
    let verified = false;
    const result = await mutate(ctx,'recovery',{
      prepare:async()=>({actor_id:'test-buyer'}),path:()=>'/api/web/v1/orders/v1/cancellations',
      states:['confirmed'],submit:send,retry:send,verify:async()=>{verified=true;},
    });
    assert.deepEqual(result,{operation_id:'test-operation',actor_id:'test-buyer'});
    assert.equal(sends,2);
    assert.equal(verified,true);
  } finally {
    globalThis.window = previous;
    delete globalThis.location;
  }
});

test('a refusal requires its own returned reference', async () => {
  const record = {path:'/api/web/v1/orders/v1/cancellations',method:'POST',body:'{}',
    json:{operation_id:'test-success'}};
  const ctx = {actor:async()=>({actor_id:'test-buyer2'}),
    api:async()=>({status:422,json:{error:{code:'invalid'}}})};
  await assert.rejects(refusal(ctx,record), /reference/);
  ctx.api = async()=>({status:422,json:{error:{request_id:'test-refused-request'}}});
  assert.deepEqual(await refusal(ctx,record), {
    operation_id:'test-refused-request',actor_id:'test-buyer2',
  });
});

test('a protected receipt refusal binds the new actor and preserves the selected scope', async () => {
  const request = {operation_id:'test-original',actor_id:'test-seller',organization_id:null,
    subject_id:'test-seller',expected_revision:1,page:1,page_size:25,
    order_id:'test-order',view:'seller',action:'receipt'};
  const record = {path:`/api/web/v1/orders/internal/v1/financial-reports?${new URLSearchParams({request:JSON.stringify(request)})}`,
    method:'GET',body:null,json:{operation_id:'test-original'}};
  let response = {status:200,json:{state:'denied',pending_reason:'scope_denied',operation_id:'test-negative'}};
  const ctx = {actor:async()=>({actor_id:'test-buyer2'}),uniq:()=> 'test-negative',
    api:async(service,method,path,body,options)=>{
      assert.equal(service,'orders');
      assert.equal(method,'GET');
      assert.equal(body,undefined);
      assert.deepEqual(options,{as:'buyer2'});
      const url = new URL(path,'http://localhost');
      assert.equal(url.pathname,'/internal/v1/financial-reports');
      assert.deepEqual(JSON.parse(url.searchParams.get('request')),
        {...request,actor_id:'test-buyer2',operation_id:'test-negative'});
      return response;
    }};
  assert.deepEqual(await refusal(ctx,record),{operation_id:'test-negative',actor_id:'test-buyer2'});
  for (const invalid of [
    {status:422,json:{request_id:'test-validation'}},
    {status:200,json:{state:'denied',pending_reason:'invalid_request',operation_id:'test-negative'}},
    {status:200,json:{state:'denied',pending_reason:'operation_conflict',operation_id:'test-negative'}},
    {status:200,json:{state:'denied',pending_reason:'scope_denied',operation_id:'test-original'}},
  ]) {
    response = invalid;
    await assert.rejects(refusal(ctx,record));
  }
});

test('offer entry uses the page listing query before composing', async () => {
  const {offer} = await import('./journeys.mjs');
  const visits = [], fields = [];
  const current = {id:'test-listing',status:'published',revision:1,
    facts:{currency:'USD',sale_mode:'fixed_price',price_minor:10000}};
  const ctx = {cell:{locale:'en',theme:'light'},actor:async()=>({actor_id:'test-buyer'}),
    signIn:async()=>{},api:async(service,method,path)=>({status:200,json:
      path.includes('discovery') ? {items:[current]} : service === 'orders'
        ? {status:'available',sale_mode:'fixed'} : current}),
    page:{goto:async path=>visits.push(path),waitFor:async()=>{},
      evaluate:async(fn,...args)=>args.length ? '[data-n09-control="current"]'
        : String(fn).includes('language:') ? {language:'en',direction:'ltr',dark:false} : undefined,
      fill:async(selector,value)=>fields.push([selector,value]),click:async()=>{}}};
  await offer().prepare(ctx);
  assert.deepEqual(visits,['/offers?listing=test-listing']);
  assert.deepEqual(fields,[['[name="offer-amount"]','100.00']]);
});


test('inspection selects the buyer order before switching to the independent reviewer', async () => {
  const {inspection} = await import('./journeys.mjs');
  const events = [], filled = [];
  const ctx = {cell:{locale:'en',theme:'light'},
    actor:async role=>{events.push(['actor',role]);return {actor_id:`test-${role}`};},
    signIn:async role=>events.push(['signIn',role]),uniq:()=> 'test-inconclusive',
    api:async(service,method,path,body,options)=>{
      events.push(['read',service,path,options.as]);
      if (path === '/v1/orders') {
        assert.equal(options.as,'buyer');
        return {status:200,json:{items:[{id:'test-unpaid',state:'reserved'},{id:'test-order',state:'paid_held'}]}};
      }
      assert.equal(path,'/v1/private-inspections/test-order/workspace');
      assert.equal(options.as,'reviewer');
      return {status:200,json:{evidence_refs:['test-evidence'],custody_receipt_id:'test-receipt'}};
    },
    page:{goto:async path=>events.push(['goto',path]),waitFor:async()=>{},
      evaluate:async(fn,...args)=>String(fn).includes('language:')
        ? {language:'en',direction:'ltr',dark:false}
        : String(fn).includes('Required acknowledgement') ? ['test-check']
          : args.length ? 'test-control' : undefined,
      fill:async(selector,value)=>filled.push(value),click:async()=>{}}};
  const spec = inspection();
  assert.deepEqual(await spec.prepare(ctx),{actor_id:'test-reviewer'});
  assert.deepEqual(events.slice(0,5),[
    ['actor','buyer'],['read','orders','/v1/orders','buyer'],
    ['actor','reviewer'],['signIn','reviewer'],['goto','/operations/inspections'],
  ]);
  assert.deepEqual(filled,['test-order','test-inconclusive']);
  assert.equal(spec.path(),'/api/web/v1/trust/v1/private-inspections/results');
});

test('receipt proof defers before observations or acknowledgement without handover evidence', async () => {
  const {delivery} = await import('./journeys.mjs');
  const filled = [], clicked = [], reads = [];
  const ctx = {cell:{locale:'en',theme:'light'},actor:async()=>({actor_id:'test-buyer'}),
    signIn:async()=>{},api:async(service,method,path)=>{
      reads.push([service,method,path]);
      return {status:200,json:path === '/v1/orders'
        ? {items:[{id:'test-order',state:'paid_held'}]}
        : {result:{watch_id:'test-watch',held:false,buyer_received_at:null}}};
    },page:{goto:async()=>{},waitFor:async()=>{},
      evaluate:async(fn,...args)=>args.length
        ? String(fn).includes('Required field') ? 'test-order-field' : 'test-view-custody'
        : {language:'en',direction:'ltr',dark:false},
      fill:async(selector,value)=>filled.push([selector,value]),
      click:async selector=>clicked.push(selector)}};
  await assert.rejects(delivery().prepare(ctx), /handover evidence.*deferred/);
  assert.deepEqual(filled,[['test-order-field','test-order']]);
  assert.deepEqual(clicked,['test-view-custody']);
  assert.deepEqual(reads,[['orders','GET','/v1/orders'],['orders','GET','/v1/custody/test-order']]);
});

test('stored buyer acknowledgement cannot establish a new handover', async () => {
  const {delivery} = await import('./journeys.mjs');
  const proof = {watch_id:'test-watch',recipient:'test-buyer',condition:'test-observed-condition',
    accessories:['test-box'],location:'test-collection-desk',address:'test-agreed-address',
    received_at:'2026-01-01T00:00:00Z',signed_handoff:true,source:'buyer_acknowledgement'};
  let record = {watch_id:'test-watch',state:'ready_for_pickup',held:false,buyer_received_at:null,proof};
  const filled = [], clicked = [];
  const actor = {actor_id:'test-buyer'};
  const ctx = {cell:{locale:'en',theme:'light'},actor:async()=>actor,signIn:async()=>{},
    api:async(service,method,path)=>({status:200,json:path === '/v1/orders'
      ? {items:[{id:'test-order',state:'paid_held'}]} : {result:record}}),
    page:{goto:async()=>{},waitFor:async()=>{},
      evaluate:async(fn,...args)=>String(fn).includes('Required acknowledgement') ? ['test-signed-handoff'] : args.length
        ? String(fn).includes('Required field') ? `field:${args[0]}` : 'test-view-custody'
        : String(fn).includes('language:') ? {language:'en',direction:'ltr',dark:false}
          : String(fn).includes('Required acknowledgement') ? ['test-signed-handoff'] : undefined,
      fill:async(selector,value)=>filled.push([selector,value]),click:async selector=>clicked.push(selector)}};
  await assert.rejects(delivery().prepare(ctx), /handover evidence.*deferred/);
  assert.deepEqual(filled.map(([,value])=>value),['test-order']);
  assert.deepEqual(clicked,['test-view-custody']);
});

for (const path of ['/api/web/v2/auction-schedules', '/api/web/v1/auction/v1/auctions/test-lot/bids']) {
  test(`lost response reconciles the original operation without another submission: ${path}`, async () => {
    const previousWindow = globalThis.window;
    const previousLocation = globalThis.location;
    const requests = [];
    globalThis.location = {origin:'http://localhost'};
    globalThis.window = {fetch:async(input, init)=>{
      requests.push([input,init]);
      return new Response(JSON.stringify({operation_id:'test-operation',status:'succeeded'}));
    }};
    const ctx = {origin:'http://localhost',page:{evaluate:async(fn,...args)=>fn(...args)}};
    let verified = false;
    try {
      const result = await mutate(ctx,'recovery',{
        prepare:async()=>({actor_id:'test-buyer'}),path:()=>path,reconciles:true,states:['succeeded'],
        submit:async()=>{
          try {
            await window.fetch(`http://localhost${path}`,{method:'POST',
              headers:{'Idempotency-Key':'test-original-key'},body:'{}'});
          } catch {
            await window.fetch('http://localhost/api/web/v1/auction/v1/auction-operations/by-key/test-original-key');
          }
        },
        retry:async()=>assert.fail('Resolved operation must not be submitted again'),
        verify:async()=>{verified=true;},
      });
      assert.deepEqual(result,{operation_id:'test-operation',actor_id:'test-buyer'});
      assert.equal(requests.length,2);
      assert.equal(verified,true);
    } finally {
      globalThis.window=previousWindow;
      globalThis.location=previousLocation;
    }
  });
}

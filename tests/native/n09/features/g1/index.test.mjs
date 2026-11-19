import assert from 'node:assert/strict';
import { test } from 'node:test';
import { features } from './index.mjs';
import { copy, loseResponse, observe, reference, response, result } from './browser.mjs';

test('similar-watch references come from the bound current response', async () => {
  const {similarReference}=await import('./catalog.mjs');
  const subject={id:'test-source',revision:2};
  const json={operation_id:'test-operation',subject_id:subject.id,expected_revision:2,offset:0,state:'ready'};
  const ctx={api:async(service,method,path,body,options)=>{
    assert.deepEqual([service,method,body,options],['catalog','GET',undefined,{as:'buyer'}]);
    const url=new URL(path,'http://localhost');
    assert.equal(url.pathname,'/v1/similar-watches/test-source');
    assert.equal(url.searchParams.get('operation_id'),'test-operation');
    assert.equal(url.searchParams.get('expected_revision'),'2');
    assert.equal(url.searchParams.get('offset'),'0');
    return {status:200,json};
  }};
  for(const [mode,state] of [['journey','ready'],['journey','empty'],['negative','denied'],['recovery','ready']]) {
    json.state=state;
    assert.equal(await similarReference(ctx,subject,'test-operation',mode),'test-operation');
  }
  for(const [key,value] of Object.entries({operation_id:subject.id,subject_id:'test-other',expected_revision:3,offset:1,state:'unavailable'})) {
    const previous=json[key]; json[key]=value;
    await assert.rejects(similarReference(ctx,subject,'test-operation','recovery'));
    json[key]=previous;
  }
});

test('F1 through F16 expose the published scenario contract', () => {
  assert.equal(features.length, 16);
  for (const [index, feature] of features.entries()) {
    assert.deepEqual(Object.keys(feature).sort(), [
      'feature_id', 'journey', 'negative', 'proof_id', 'proof_revision', 'recovery',
    ]);
    assert.equal(feature.feature_id, `F${index + 1}`);
    assert.equal(feature.proof_id, `f${String(index + 1).padStart(2, '0')}-proof`);
    assert.equal(feature.proof_revision, '1');
    for (const scenario of ['journey', 'negative', 'recovery']) {
      assert.equal(typeof feature[scenario], 'function');
    }
  }
});

test('returned references are real service or record identifiers', () => {
  assert.equal(reference({json:{operation_id:'test-operation'}}),'test-operation');
  assert.equal(reference({json:{error:{request_id:'test-refused-request'}}}),'test-refused-request');
  assert.equal(reference({json:{application:{id:'test-case'}}}),'test-case');
  assert.throws(()=>reference({json:{state:'ready'}}));
  assert.throws(()=>result({actor_id:''},'test-operation'));
  assert.throws(()=>result({actor_id:'test-actor'},''));
  assert.deepEqual(result({actor_id:'test-actor'},'test-operation'),{
    operation_id:'test-operation',actor_id:'test-actor',
  });
});

test('every scenario starts by obtaining a real signed-in actor', async () => {
  const unavailable=new Error('test session unavailable');
  const ctx={actor:async()=>{throw unavailable;}};
  for (const feature of features) {
    for (const scenario of ['journey','negative','recovery']) {
      await assert.rejects(feature[scenario](ctx),error=>error===unavailable);
    }
  }
});


test('localized form names resolve from the current product dictionaries', async () => {
  for(const locale of ['en','ar']) {
    for(const feature of ['identity','business','listing-editor','discovery']) {
      const words=await copy({cell:{locale}},feature);
      assert.ok(Object.keys(words).length>0);
    }
  }
});

test('observation keeps real response references, omits session material and distinguishes methods', async () => {
  const previousWindow=globalThis.window;
  const previousLocation=globalThis.location;
  let calls=0;
  globalThis.location={href:'http://localhost:3000/account',origin:'http://localhost:3000'};
  globalThis.window={fetch:async()=>{
    calls++;
    return new Response(JSON.stringify({operation_id:'test-operation',revision:1,
      access_token:'test-token',secret:'test-secret',recovery_codes:['test-recovery'],
      account:{id:'test-account',password:'test-password'},
    }),{status:200,headers:{'Content-Type':'application/json','X-Request-ID':'test-request'}});
  }};
  const ctx={page:{evaluate:async(fn,...args)=>fn(...args)}};
  try {
    await observe(ctx);
    await window.fetch('/api/web/v1/catalog/v1/seller/imports');
    await loseResponse(ctx,'/seller/imports');
    await assert.rejects(window.fetch('/api/web/v1/catalog/v1/seller/imports',{method:'POST'}),/interrupted/);
    const accepted=await response(ctx,'/seller/imports');
    assert.equal(accepted.method,'POST');
    assert.equal(reference(accepted),'test-operation');
    assert.equal(accepted.request_id,'test-request');
    assert.equal(accepted.json.access_token,undefined);
    assert.equal(accepted.json.secret,undefined);
    assert.equal(accepted.json.recovery_codes,undefined);
    assert.equal(accepted.json.account.password,undefined);
    await observe(ctx);
    await window.fetch('/api/web/v1/catalog/v1/seller/imports',{method:'POST'});
    assert.equal(reference(await response(ctx,'/seller/imports')),'test-operation');
    assert.equal(calls,3);
  } finally {
    if(previousWindow===undefined) delete globalThis.window; else globalThis.window=previousWindow;
    if(previousLocation===undefined) delete globalThis.location; else globalThis.location=previousLocation;
  }
});

test('comparison waits for the current bound reference before retry', async () => {
  const {settledComparison}=await import('./catalog.mjs');
  const previousWindow=globalThis.window;
  const previousDocument=globalThis.document;
  try {
    for(const locale of ['en','ar']) {
      const first={path:'/comparison/operations/test-first',method:'POST',status:200,
        json:{operation_id:'test-first',columns:[{state:'available'}]}};
      const current={...first,path:'/comparison/operations/test-current',
        json:{operation_id:'test-current',columns:[{state:'available'}]}};
      const control={textContent:locale==='ar'?'التحقق مجددًا':'Check again',disabled:true};
      const line={textContent:`${locale==='ar'?'مرجع المقارنة':'Comparison reference'}: test-current`,
        querySelector:()=>({textContent:'test-current'})};
      globalThis.window={__btProof:{records:[first]}};
      globalThis.document={querySelectorAll:selector=>selector==='p'?[line]:[control]};
      const pending=settledComparison({cell:{locale},page:{evaluate:(fn,args)=>fn(args)}});
      setTimeout(()=>{window.__btProof.records.push(current);control.disabled=false;},0);
      assert.equal(await pending,current);
    }
  } finally {
    if(previousWindow===undefined) delete globalThis.window; else globalThis.window=previousWindow;
    if(previousDocument===undefined) delete globalThis.document; else globalThis.document=previousDocument;
  }
});

test('successive submissions target only the requested form', async () => {
  const {formFor}=await import('./browser.mjs');
  const previousDocument=globalThis.document;
  const forms=['recipient','code'].map(name=>({name,marked:false,
    setAttribute(){this.marked=true;},removeAttribute(){this.marked=false;}}));
  const clicked=[];
  globalThis.document={
    querySelectorAll:()=>forms.filter(form=>form.marked),
    querySelector:selector=>selector.includes('button')
      ? {disabled:false,getClientRects:()=>[{}]}
      : {closest:()=>forms.find(form=>selector.includes(form.name))},
  };
  try {
    const ctx={page:{evaluate:async(fn,arg)=>fn(arg),click:async()=>{
      clicked.push(forms.filter(form=>form.marked).map(form=>form.name));
    }}};
    await formFor(ctx,'recipient');
    await formFor(ctx,'code');
    assert.deepEqual(clicked,[['recipient'],['code']]);
  } finally {
    if(previousDocument===undefined) delete globalThis.document; else globalThis.document=previousDocument;
  }
});

test('import scope uses a current membership with stock permission', async () => {
  const {organization}=await import('./catalog.mjs');
  const principal={actor:{organization_id:null},organizations:['test-read','test-stock'],
    organization_grants:[
      {organization_id:'test-stale',permissions:['business.stock.write']},
      {organization_id:'test-read',permissions:[]},
      {organization_id:'test-stock',permissions:['business.stock.write']},
    ]};
  const ctx={api:async(service,method,path,body,options)=>{
    assert.deepEqual([service,method,path,body,options],
      ['identity','POST','/v1/accounts/refresh',undefined,{as:'dealer'}]);
    return {status:200,json:{principal}};
  }};
  assert.equal(await organization(ctx),'test-stock');
  principal.organizations=[];
  await assert.rejects(organization(ctx),/current organization/);
});

test('audit inspection requires the change created by this scenario', async () => {
  const {changeReference} = await import('./audit.mjs');
  const change = {operation_id:'test-change', subject:'test-case', actor:{actor_id:'test-operator'}, revision:2};
  const item = {operation_id:change.operation_id, subject_id:change.subject,
    actor_id:change.actor.actor_id, revision:2, reason_reference:'test-reason'};
  const receipt = items => ({json:{results:[{source:'trust',state:items.length?'ready':'empty',page:{items}}]}});
  assert.equal(changeReference(receipt([item]),change),item);
  assert.throws(()=>changeReference(receipt([]),change),/new audited change/);
  assert.throws(()=>changeReference(receipt([{...item,operation_id:'test-unrelated'}]),change),/new audited change/);
  assert.throws(()=>changeReference(receipt([{...item,subject_id:'test-other-case'}]),change));
  assert.throws(()=>changeReference(receipt([{...item,revision:3}]),change));
});

test('audit selection waits for the bound review record across response orderings', async () => {
  const {trustResponse} = await import('./audit.mjs');
  const previous = globalThis.window;
  const change = {operation_id:'test-change',subject:'test-case',actor:{actor_id:'test-operator'},revision:2};
  const item = {operation_id:change.operation_id,subject_id:change.subject,actor_id:change.actor.actor_id,revision:2,reason_reference:'test-reason'};
  const record = (source, items) => ({path:'/api/web/v1/communications/v1/audit-references',method:'GET',status:200,
    json:{operation_id:'test-query',results:[{source,state:'ready',page:{items}}]}});
  const trust = record('trust',[item]);
  try {
    for (const records of [
      [record('orders',[]),record('service-operations',[]),trust],
      [trust,record('orders',[])],
      [record('trust',[{...item,operation_id:'test-old'}]),trust],
    ]) {
      globalThis.window = {__btProof:{records}};
      assert.equal(await trustResponse({page:{evaluate:(fn,arg)=>fn(arg)}},change),trust);
    }
    globalThis.window = {__btProof:{records:[record('orders',[])]}};
    const pending = trustResponse({page:{evaluate:(fn,arg)=>fn(arg)}},change);
    setTimeout(()=>window.__btProof.records.push(trust),0);
    assert.equal(await pending,trust);
  } finally {
    if (previous === undefined) delete globalThis.window; else globalThis.window = previous;
  }
});

test('audit recovery retries only its named source panel in each language', async () => {
  const {retryTrust} = await import('./audit.mjs');
  const previous = globalThis.document;
  try {
    for (const locale of ['en','ar']) {
      const clicked = [];
      const panels = ['Order records', locale==='ar'?'سجلات المراجعة':'Review records', 'Service records']
        .map(name=>({getAttribute:()=>name,querySelectorAll:()=>[{
          textContent:locale==='ar'?'أعد المحاولة':'Retry',disabled:false,click:()=>clicked.push(name),
        }]}));
      globalThis.document = {querySelectorAll:()=>panels};
      await retryTrust({cell:{locale},page:{evaluate:(fn,arg)=>fn(arg)}});
      assert.deepEqual(clicked,[locale==='ar'?'سجلات المراجعة':'Review records']);
    }
  } finally {
    if (previous === undefined) delete globalThis.document; else globalThis.document = previous;
  }
});

test('published revisions require confirmed next facts and a real edit reference', async () => {
  const {revisionOutcome} = await import('./management.mjs');
  const row = {id:'test-listing',revision:3};
  const json = {id:'test-edit',status:'succeeded',listing:{...row,status:'published',revision:4,facts:{price_minor:50100}}};
  assert.equal(revisionOutcome({json},row,50100),'test-edit');
  for (const invalid of [
    {...json,status:'pending'}, {...json,status:'denied'},
    {...json,listing:{...json.listing,revision:3}},
    {...json,listing:{...json.listing,facts:{price_minor:50000}}},
    {...json,listing:{...json.listing,status:'draft'}},
  ]) assert.throws(()=>revisionOutcome({json:invalid},row,50100));
});

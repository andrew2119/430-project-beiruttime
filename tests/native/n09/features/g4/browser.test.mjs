import assert from 'node:assert/strict';
import test from 'node:test';
import { api, denied, reference, result, words, publishedCopy, ownedOrder } from './browser.mjs';

test('references must come from returned operations, requests or records', () => {
  assert.equal(reference({json:{operation_id:'test-operation'},request_id:'test-request'}),'test-operation');
  assert.equal(reference({json:{result:{operation_id:'test-retained-operation'}}}),'test-retained-operation');
  assert.equal(reference({json:{},request_id:'test-refused-request'}),'test-refused-request');
  assert.equal(reference({json:{id:'test-saved-record'}}),'test-saved-record');
  assert.throws(()=>reference({json:{state:'pending'}}),/reference/);
  assert.deepEqual(result({actor_id:'test-buyer'},{json:{operation_id:'test-operation'}}),{
    operation_id:'test-operation',actor_id:'test-buyer',
  });
});

function refusal(status, json) {
  const calls=[];
  return {calls,actor:async role=>{calls.push(['actor',role]);return {actor_id:'test-other-buyer'};},
    signIn:async role=>calls.push(['signIn',role]),
    api:async(...args)=>{calls.push(['api',...args]);return {status,json};}};
}
test('permission negatives switch account and require a referenced refusal without private content',async()=>{
  const ctx=refusal(403,{error:{code:'denied',request_id:'test-refused-operation'}});
  assert.deepEqual(await denied(ctx,'service-operations','/v1/history/operations/test-record'),{
    operation_id:'test-refused-operation',actor_id:'test-other-buyer',
  });
  assert.deepEqual(ctx.calls.slice(0,2),[['actor','buyer2'],['signIn','buyer2']]);
  assert.deepEqual(ctx.calls[2],['api','service-operations','GET','/v1/history/operations/test-record',undefined,{as:'buyer2'}]);
  for(const status of [200,404,422,500,503]) {
    await assert.rejects(denied(refusal(status,{request_id:'test-request'}),'trust','/v1/cases/test-record'));
  }
  await assert.rejects(denied(refusal(403,{}),'trust','/v1/cases/test-record'),/reference/);
  await assert.rejects(denied(refusal(403,{request_id:'test-request',private_record:{serial:'test-private'}}),'trust','/v1/cases/test-record'),/disclose/);
});

test('setup cannot treat an unavailable or rejected prerequisite as success',async()=>{
  for(const status of [401,403,409,422,503]) {
    await assert.rejects(api({api:async()=>({status,json:{}})},'orders','GET','/v1/orders'));
  }
});

test('translated labels resolve from the candidate for both languages',async()=>{
  for(const locale of ['en','ar']) {
    for(const feature of ['service-directory','maintenance','appointments','service-history','moderation','discovery','care-progress']) {
      const copy=await words({cell:{locale}},feature);
      assert.ok(Object.keys(copy).length);
    }
  }
});

 test('purchase controls use the published labels in each language', async () => {
  for (const locale of ['en', 'ar']) {
    const copy = await publishedCopy('buy-now/connected-copy.ts', 'connectedCopy', locale);
    for (const field of ['review', 'terms', 'accept']) assert.ok(copy[field]);
  }
});


test('purchase discovery follows returned cursors with a permitted page size', async () => {
  const calls = [];
  const reachedCheckout = new Error('test-checkout-reached');
  const ctx = {
    actor: async () => ({actor_id:'test-buyer'}), signIn: async () => {},
    page: {goto: async path => { calls.push(path); throw reachedCheckout; }},
    api: async (service, method, path) => {
      calls.push(path);
      if (service === 'catalog') return {status:200,json:path.includes('cursor=')
        ? {items:[{id:'test-fixed'}],next_cursor:null}
        : {items:[{id:'test-unavailable'},{id:'test-auction'}],next_cursor:'test-cursor/+='}};
      return {status:200,json:{status:path.includes('unavailable') ? 'reserved' : 'available',
        sale_mode:path.includes('auction') ? 'auction' : 'fixed'}};
    },
  };
  await assert.rejects(ownedOrder(ctx), error => error === reachedCheckout);
  assert.deepEqual(calls, [
    '/v1/discovery/watches?limit=24',
    '/v1/listings/test-unavailable/availability',
    '/v1/listings/test-auction/availability',
    '/v1/discovery/watches?limit=24&cursor=test-cursor%2F%2B%3D',
    '/v1/listings/test-fixed/availability',
    '/checkout?listing_id=test-fixed',
  ]);
});

test('purchase discovery refuses an exhausted catalog', async () => {
  const ctx = {actor:async()=>({actor_id:'test-buyer'}),signIn:async()=>{},
    api:async()=>({status:200,json:{items:[],next_cursor:null}})};
  await assert.rejects(ownedOrder(ctx), /currently available fixed-price watch/);
});

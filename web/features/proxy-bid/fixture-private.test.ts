import {expect,it} from 'vitest';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
import {buyerFixture} from './browser-fixture.mjs';
import {provePrivateMaximum} from './fixture-private-proof.mjs';

async function request(path:string,authorization='',key='',body?:object,serverTime?:string) {
    let status=0;
    let result:unknown;
    await buyerFixture({
      url:path,method:body?'POST':'GET',headers:{authorization,'idempotency-key':key},
      async *[Symbol.asyncIterator]() {if(body) yield JSON.stringify(body);},
    },{
      writeHead(code:number) {status=code;},
      end(value:string) {result=JSON.parse(value);},
    },serverTime===undefined?undefined:()=>serverTime);
    return {status,body:result};
  }

it('binds preview review, admission and receipt recovery to the exact buyer request',async()=>{
  await request('/__proof?reset=1');
  const initial=await request('/v1/auctions');
  expect(initial.status).toBe(200);
  const auction=(initial.body as {items:AuctionSnapshot[]}|undefined)?.items[0];
  if (!auction) throw new Error('Missing initial auction');
  await provePrivateMaximum(request,auction);
});

it('keeps auction stock, checkout inventory and the existing held order exclusive',async()=>{
  const ref=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
  const buyer='Bearer synthetic-visual-proof-only';
  await request('/__proof?reset=1');
  const auction=(await request('/v1/auctions/'+ref(8))).body as AuctionSnapshot;
  const held=(await request('/v1/orders/'+ref(5),buyer)).body as {order:{watch_id:string;listing_id:string}};
  const maximum=(await request('/v1/auctions/'+auction.id+'/maximum',buyer,'',{action:'read_v2'})).body as {watch_id:string};
  const availability=(id:string)=>request('/v1/watches/'+id+'/availability');
  expect(new Set([maximum.watch_id,ref(6),held.order.watch_id]).size).toBe(3);
  expect(new Set([auction.listing_id,ref(14),held.order.listing_id]).size).toBe(3);
  expect((await availability(maximum.watch_id)).body).toMatchObject({sale_mode:'auction',listing_id:auction.listing_id});
  expect((await availability(held.order.watch_id)).body).toMatchObject({sale_mode:'fixed',status:'reserved'});
  expect((await availability(ref(6))).body).toMatchObject({sale_mode:'fixed',status:'available'});
  expect((await request('/v1/auctions?listing_id='+ref(14))).body).toEqual({items:[]});

  const body={watch_id:ref(6),quote_id:ref(21),expected_revision:1};
  const reserve=(key:string,watch_id=body.watch_id)=>request('/v1/reservations',buyer,key,{...body,watch_id});
  expect((await reserve('test-auction',maximum.watch_id)).status).toBe(409);
  for(const [authorization,quoteId] of [
    [buyer,ref(4)],
    [buyer,ref(19)],
    ['Bearer synthetic-incumbent-token',body.quote_id],
  ]) {
    const denied=await request('/v1/reservations',authorization,'test-wrong-quote',{...body,quote_id:quoteId});
    expect(denied.status).toBe(authorization===buyer?409:403);
    expect(denied.body).not.toHaveProperty('order');
    if(authorization===buyer) expect(denied.body).toMatchObject({error:{code:'quote_not_authoritative'}});
  }
  expect((await availability(ref(6))).body).toMatchObject({status:'available'});
  const reviewed=(await request('/v1/quotes/'+body.quote_id,buyer)).body;
  expect(reviewed).toMatchObject({source:'listing',source_verified:true,
    subject_id:ref(14),reviewed_at:'2030-01-01T10:00:00Z'});
  const result=await reserve('test-checkout');
  expect(result.status).toBe(200);
  expect(result.body).toMatchObject({order:{watch_id:ref(6),listing_id:ref(14),quote_id:body.quote_id,total_minor:515000}});
  expect(await reserve('test-checkout')).toEqual(result);
  expect((await reserve('test-duplicate')).status).toBe(409);
  expect((await availability(ref(6))).body).toMatchObject({status:'reserved'});
});

it('scopes the order list and each order history to the current participant',async()=>{
  const buyer='Bearer synthetic-visual-proof-only';
  const other='Bearer synthetic-incumbent-token';
  const ref=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
  await request('/__proof?reset=1');
  const reservation=await request('/v1/reservations',buyer,'test-order-read',{
    watch_id:ref(6),quote_id:ref(21),expected_revision:1,
  });
  expect(reservation.status).toBe(200);

  const list='/v1/orders';
  expect((await request(list,buyer)).body).toEqual({
    items:[expect.objectContaining({id:ref(5)}),expect.objectContaining({id:ref(20)})],
  });
  expect(await request(list,other)).toEqual({status:200,body:{items:[]}});
  expect((await request(list)).status).toBe(401);
  for(const orderId of [ref(5),ref(20)]){
    const detail=list+'/'+orderId;
    expect(await request(detail,buyer)).toMatchObject({
      status:200,body:{order:{id:orderId},history:[{action:'reserve'}]},
    });
    for(const [authorization,status] of [['',401],[other,403]] as const){
      const response=await request(detail,authorization);
      expect(response.status).toBe(status);
      expect(response.body).not.toHaveProperty('order');
      expect(response.body).not.toHaveProperty('history');
    }
  }
  await request('/__proof?mode=signed-out');
  for(const path of [list,list+'/'+ref(5),list+'/'+ref(20)]){
    expect((await request(path,buyer)).status).toBe(401);
  }
  await request('/__proof?reset=1');
});

it.each([
  ['bid', -1], ['bid', 0], ['bid', 1],
  ['purchase', -1], ['purchase', 0], ['purchase', 1],
] as const)('checks %s preview expiry at server offset %i ms', async (purpose, offset) => {
  await request('/__proof?reset=1');
  const buyer = 'Bearer synthetic-visual-proof-only';
  const auction = (await request('/v1/auctions/00000000-0000-4000-8000-000000000008')).body as AuctionSnapshot;
  const created = Date.parse(auction.server_time);
  const deadline = created + 900_000;
  const binding = {
    subject_id: purpose === 'bid' ? auction.id : '00000000-0000-4000-8000-000000000014',
    subject_revision: purpose === 'bid' ? auction.revision : 1, purpose,
    currency: 'USD', price_minor: 500000, schedule_id: 'usd-v2', source: 'sample',
  };
  const preview = await request('/v1/quotes', buyer, 'test-preview', binding, auction.server_time);
  expect(preview.status).toBe(200);
  expect(preview.body).toMatchObject({currency:'USD',policy:{currency_exponents:{USD:2}}});
  expect((preview.body as {policy:{currency_exponents:object}}).policy.currency_exponents).toEqual({USD:2});
  const quote = preview.body as {id:string;revision:number;payable_minor:number;created_at:string;expires_at:string};
  expect(Date.parse(quote.created_at)).toBe(created);
  expect(Date.parse(quote.expires_at)).toBe(deadline);
  const review = {...binding, quote_revision:quote.revision, payable_minor:quote.payable_minor};
  const path = '/v1/quotes/' + quote.id + '/review';
  const reviewedAt = new Date(deadline + offset).toISOString();
  const result = await request(path, buyer, 'test-review', review, reviewedAt);
  if (offset < 0) {
    expect(result.body).toMatchObject({reviewed_at: reviewedAt});
    expect(await request(path, buyer, 'test-review', review, new Date(deadline).toISOString())).toEqual(result);
  } else {
    expect(result.status).toBe(409);
    expect(result.body).toMatchObject({error:{code:'quote_expired'}});
  }
});

it.each([-1,0,1])('gates a fresh maximum at server offset %i ms from auction end and preserves its receipt',async offset=>{
  const buyer='Bearer synthetic-visual-proof-only';
  await request('/__proof?reset=1');
  const path='/v1/auctions/00000000-0000-4000-8000-000000000008';
  const auction=(await request(path)).body as AuctionSnapshot;
  const end=Date.parse(auction.ends_at);
  const serverTime=new Date(end+offset).toISOString();
  const binding={subject_id:auction.id,subject_revision:auction.revision,purpose:'bid',
    currency:'USD',price_minor:450000,schedule_id:'usd-v2',source:'sample'};
  const preview=await request('/v1/quotes',buyer,'test-deadline-preview',binding,serverTime);
  expect(preview.status).toBe(200);
  const quote=preview.body as {id:string;revision:number;payable_minor:number};
  const reviewed=await request('/v1/quotes/'+quote.id+'/review',buyer,'test-deadline-review',
    {...binding,quote_revision:quote.revision,payable_minor:quote.payable_minor},serverTime);
  expect(reviewed.status).toBe(200);

  const operation='00000000-0000-4000-8000-000000000023';
  const body={action:'submit_v2',command:{amount_minor:binding.price_minor,fee_quote_id:quote.id,
    expected_revision:auction.revision,watch_id:'00000000-0000-4000-8000-000000000016',
    quote_revision:quote.revision,policy_revision:String(quote.policy.revision)}};
  const result=await request(path+'/maximum',buyer,operation,body,serverTime);
  expect(result.status).toBe(200);
  expect(result.body).toMatchObject({operation_id:operation,state:offset<0?'accepted':'denied'});
  const history=(await request(path+'/history')).body;
  expect(history).toMatchObject({items:offset<0?[expect.objectContaining({amount_minor:auction.opening_minor})]:[]});
  expect(await request(path+'/maximum',buyer,operation,body,new Date(end+1000).toISOString())).toEqual(result);
});

it('admits an opening manual bid only with a reviewed quote bound to that auction',async()=>{
  await request('/__proof?reset=1');
  const actor='Bearer synthetic-incumbent-token';
  const {items:[auction]}=(await request('/v1/auctions')).body as {items:AuctionSnapshot[]};
  const path='/v1/auctions/'+auction.id;
  const binding={subject_id:auction.id,subject_revision:auction.revision,purpose:'bid',
    currency:'USD',price_minor:auction.opening_minor,schedule_id:'usd-v2',source:'sample'};

  async function preview(fields:typeof binding,key:string) {
    const result=await request('/v1/quotes',actor,key+'-preview',fields);
    expect(result.status).toBe(200);
    return result.body as {id:string;revision:number;payable_minor:number};
  }

  async function review(quote:Awaited<ReturnType<typeof preview>>,fields:typeof binding,key:string) {
    const result=await request('/v1/quotes/'+quote.id+'/review',actor,key+'-review',
      {...fields,quote_revision:quote.revision,payable_minor:quote.payable_minor});
    expect(result.status).toBe(200);
  }

  const bid=(quoteId:string,key:string)=>request(path+'/bids',actor,key,{
    amount_minor:auction.opening_minor,expected_revision:auction.revision,fee_quote_id:quoteId,
  });
  for(const [key,subject_id] of [['test-purchase-same',auction.id],['test-purchase-other',auction.listing_id]]) {
    const purchase={...binding,purpose:'purchase',subject_id};
    const quote=await preview(purchase,key);
    await review(quote,purchase,key);
    expect((await bid(quote.id,key)).status).toBe(409);
  }

  const quote=await preview(binding,'test-bid');
  expect((await bid(quote.id,'test-unreviewed')).status).toBe(409);
  expect((await request(path+'/history')).body).toMatchObject({
    snapshot:{revision:auction.revision,accepted_sequence:0},items:[],
  });

  await review(quote,binding,'test-bid');
  const accepted=await bid(quote.id,'test-bid');
  expect(accepted.body).toMatchObject({status:'succeeded',current_minor:auction.opening_minor});
  expect(await bid(quote.id,'test-bid')).toEqual(accepted);
  expect((await request(path+'/history')).body).toMatchObject({
    snapshot:{revision:auction.revision+1,accepted_sequence:1},
    items:[{amount_minor:auction.opening_minor,automatic:false}],
  });
});

it('delivers one revision-bound outbid notice to the displaced leader only',async()=>{
  await request('/__proof?reset=1');
  const incumbent='Bearer synthetic-incumbent-token';
  const challenger='Bearer synthetic-visual-proof-only';
  const {items:[auction]}=(await request('/v1/auctions')).body as {items:AuctionSnapshot[]};
  const path='/v1/auctions/'+auction.id;

  async function reviewedQuote(actor:string,revision:number,amount:number,key:string) {
    const binding={subject_id:auction.id,subject_revision:revision,purpose:'bid',
      currency:'USD',price_minor:amount,schedule_id:'usd-v2',source:'sample'};
    const preview=await request('/v1/quotes',actor,key+'-preview',binding);
    expect(preview.status).toBe(200);
    const quote=preview.body as {id:string;revision:number;payable_minor:number};
    expect((await request('/v1/quotes/'+quote.id+'/review',actor,key+'-review',
      {...binding,quote_revision:quote.revision,payable_minor:quote.payable_minor})).status).toBe(200);
    return quote;
  }

  const opening=await reviewedQuote(incumbent,auction.revision,auction.opening_minor,'test-opening');
  const manual=await request(path+'/bids',incumbent,'test-opening',{
    amount_minor:auction.opening_minor,expected_revision:auction.revision,fee_quote_id:opening.id,
  });
  expect(manual.body).toMatchObject({status:'succeeded',revision:auction.revision+1});
  expect((await request('/v1/inbox',incumbent)).body).toMatchObject({items:[],unread_count:0});

  const revision=auction.revision+1;
  const amount=500000;
  const quote=await reviewedQuote(challenger,revision,amount,'test-challenge');
  const operation='00000000-0000-4000-8000-000000000024';
  const command={action:'submit_v2',command:{amount_minor:amount,expected_revision:revision,
    fee_quote_id:quote.id,quote_revision:quote.revision,policy_revision:String(quote.policy.revision),
    watch_id:'00000000-0000-4000-8000-000000000016'}};
  const serverTime='2030-01-01T10:01:00Z';
  const submit=()=>request(path+'/maximum',challenger,operation,command,serverTime);
  const accepted=await submit();
  expect(accepted.body).toMatchObject({state:'accepted',revision:revision+1});
  expect(await submit()).toEqual(accepted);

  const inbox=await request('/v1/inbox',incumbent);
  expect(inbox).toMatchObject({status:200,body:{unread_count:1,items:[{
    kind:'outbid',resource_id:auction.id,resource_revision:revision+1,event_time:serverTime,
    required:true,sample:true,
  }]}});
  const {items:[notice]}=inbox.body as {items:{id:string}[]};
  expect(notice).not.toHaveProperty('recipient_id');
  const destination='/v1/inbox/'+notice.id+'/destination';
  expect(await request(destination,incumbent)).toEqual({status:200,body:{url:'/buyer'}});
  expect((await request(destination,challenger)).status).toBe(404);
  expect((await request('/v1/inbox',challenger)).body).not.toMatchObject({
    items:expect.arrayContaining([expect.objectContaining({id:notice.id})]),
  });
  expect((await request('/v1/inbox')).status).toBe(401);
});

it('accepts the Pricing ceiling in exact cents and rejects one cent above it',async()=>{
  await request('/__proof?reset=1');
  const buyer='Bearer synthetic-visual-proof-only';
  const {body}=await request('/v1/auctions');
  const {id,revision}=(body as {items:AuctionSnapshot[]}).items[0];
  const preview=(price_minor:number)=>request('/v1/quotes',buyer,'test-preview-limit',{
    subject_id:id,subject_revision:revision,purpose:'bid',currency:'USD',
    schedule_id:'usd-v2',source:'sample',price_minor,
  });
  expect((await preview(9_000_000_000_001)).status).toBe(422);
  const valid=await preview(9_000_000_000_000);
  expect(valid.status).toBe(200);
  expect(valid.body).toMatchObject({
    price_minor:9_000_000_000_000,
    buyer_fee_minor:270_000_000_000,
    payable_minor:9_270_000_000_000,
  });
  expect(await preview(9_000_000_000_000)).toEqual(valid);
});

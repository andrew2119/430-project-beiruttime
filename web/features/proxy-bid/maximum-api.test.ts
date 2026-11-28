import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
import type {Quote} from '@contracts/contracts-pricing/quotes';
import {ApiError} from '@/lib/api/client';
import {lookupMaximum,lookupMaximumV1,readOwnMaximum,MAX_QUOTE_MINOR,previewMaximum,reviewMaximum,recoverLegacyMaximum,restoreMaximumIntent,restoreMaximumReview,sendMaximum,type MaximumIntent} from './maximum-api';
import {confirmMissingQuote} from './quote-availability';
const invoke=vi.hoisted(()=>vi.fn());
vi.mock('./session',()=>({authenticatedRequest:invoke}));
const owner={subjectId:'00000000-0000-0000-0000-000000000001',accessFingerprint:'scope-6'};
const auctionId='00000000-0000-0000-0000-000000000006';
const intent:MaximumIntent=Object.freeze({key:'00000000-0000-0000-0000-000000000009',amount_minor:450000,fee_quote_id:'00000000-0000-0000-0000-000000000008',revision:4,owner:'private-owner-fingerprint',actor_id:owner.subjectId,watch_id:'00000000-0000-0000-0000-000000000007',quote_revision:1,policy_revision:'policy-6'});
const accepted={schema_version:2,operation_id:intent.key,actor_id:intent.actor_id,organization_id:null,
  subject_id:auctionId,watch_id:intent.watch_id,expected_revision:intent.revision,quote_id:intent.fee_quote_id,
  quote_revision:intent.quote_revision,policy_revision:intent.policy_revision,revision:5,state:'accepted',pending_reason:null,next_actor:null,next_review_at:null};
const previewKey='test-preview-key';
beforeEach(()=>{invoke.mockReset();});
afterEach(()=>{vi.restoreAllMocks();});
const auction:AuctionSnapshot={id:'00000000-0000-0000-0000-000000000006',listing_id:'00000000-0000-0000-0000-000000000007',currency:'USD',opening_minor:400000,current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2025-12-31T00:00:00Z',ends_at:'2026-01-02T00:00:00Z',server_time:'2026-01-01T00:00:00Z',revision:4,accepted_sequence:1,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:'bidder-1',status:'live'};
const binding={subject_id:auction.id,subject_revision:4,purpose:'bid',currency:'USD',price_minor:450000,schedule_id:'usd-v2',source:'sample'} as const;
const quote:Quote={...binding,source_verified:false,
  id:'00000000-0000-0000-0000-000000000008',owner_id:owner.subjectId,revision:1,minor_unit_exponent:2,
  buyer_fee_minor:13500,seller_commission_minor:22500,seller_net_minor:427500,shipping_minor:0,tax_minor:0,
  payable_minor:463500,sample:true,rounding:'half_up',fx:null,commission_basis:'price_excluding_buyer_fee_shipping_tax',
  policy:{revision:2,buyer_fee_bps:300,seller_commission_bps:500,shipping:'sample_zero',tax:'sample_zero',fx:'not_applied',currency_exponents:{USD:2,LBP:2}},
  created_at:'2026-01-01T00:00:00Z',expires_at:'2026-01-01T00:15:00Z',reviewed_at:null};

describe('pricing.quotes.v1 maximum preview',()=>{
  it('binds exact bid-purpose fields and labels the selected sample policy',async()=>{
    invoke.mockResolvedValue({...quote,private_internal_field:'not-projected'});
    const signal=new AbortController().signal;
    const preview=await previewMaximum(auction,450000,owner,signal,previewKey);
    const [path,options]=invoke.mock.calls[0];
    expect(path).toBe('/api/web/v1/pricing/v1/quotes');expect(options.signal).toBe(signal);
    expect(JSON.parse(options.body)).toEqual(binding);
    expect(options.headers['Idempotency-Key']).toBe(previewKey);
    expect(preview).toMatchObject({fee_quote_id:quote.id,amount_minor:450000,buyer_fee_minor:13500,total_minor:463500,
      expires_at:quote.expires_at,auction_revision:4,quote_revision:1,policy_revision:'2',owner_id:owner.subjectId,access_fingerprint:owner.accessFingerprint,sample:true,binding});
    expect(preview).not.toHaveProperty('private_internal_field');
    expect(JSON.stringify(options)).not.toContain(owner.subjectId);
    expect(options.accessFingerprint).toBe(owner.accessFingerprint);
  });
  it.each([
    {owner_id:'another-owner'},{subject_id:'another-subject'},{subject_revision:3},{purpose:'purchase'},{currency:'LBP'},
    {price_minor:449999},{schedule_id:'production'},{source:'listing'},{source_verified:true},{sample:false},
    {minor_unit_exponent:0},{revision:0},{buyer_fee_minor:-1},{buyer_fee_minor:1.5},{payable_minor:449999},
    {payable_minor:Number.MAX_SAFE_INTEGER+1},{shipping_minor:1},{tax_minor:1},{rounding:'floor'},{fx:1},
    {seller_net_minor:1},{policy:{...quote.policy,buyer_fee_bps:200}},
    {policy:{...quote.policy,revision:1}},{schedule_id:'sample-v1'},
    {buyer_fee_minor:0,payable_minor:450000},{seller_commission_minor:0,seller_net_minor:450000},
    {expires_at:'not-a-time'},{expires_at:'2050-01-01T00:00:00'},{created_at:'2051-01-01T00:00:00Z'},
  ])('refuses wrong-scope, unbalanced or stale preview %j',async changes=>{
    invoke.mockResolvedValue({...quote,...changes});
    await expect(previewMaximum(auction,450000,owner,new AbortController().signal,previewKey)).rejects.toBeInstanceOf(ApiError);
  });
  it.each([
    [450049,13501,22502],
    [450050,13502,22503],
    [450051,13502,22503],
  ])('validates half-up fees at %i cents',async (price_minor,buyer_fee_minor,seller_commission_minor)=>{
    const snapshot={...quote,price_minor,buyer_fee_minor,seller_commission_minor,
      payable_minor:price_minor+buyer_fee_minor,seller_net_minor:price_minor-seller_commission_minor};
    invoke.mockResolvedValueOnce(snapshot).mockResolvedValueOnce({...snapshot,buyer_fee_minor:buyer_fee_minor-1,
      payable_minor:snapshot.payable_minor-1});
    const signal=new AbortController().signal;
    await expect(previewMaximum(auction,price_minor,owner,signal,previewKey)).resolves.toMatchObject({buyer_fee_minor});
    await expect(previewMaximum(auction,price_minor,owner,signal,previewKey)).rejects.toMatchObject({code:'invalid_fee_preview'});
  });
  it.each([0,NaN,MAX_QUOTE_MINOR+1])('refuses invalid maximum before quote transport %s',async amount=>{
    await expect(previewMaximum(auction,amount,owner,new AbortController().signal,previewKey)).rejects.toBeInstanceOf(ApiError);
    expect(invoke).not.toHaveBeenCalled();
  });
  it('rejects a non-USD auction before asking for a preview',async()=>{
    await expect(previewMaximum({...auction,currency:'LBP'},450000,owner,new AbortController().signal,previewKey))
      .rejects.toMatchObject({status:422,code:'invalid_currency'});
    expect(invoke).not.toHaveBeenCalled();
  });
  it('fails closed on a null preview',async()=>{
    invoke.mockResolvedValue(null);
    await expect(previewMaximum(auction,450000,owner,new AbortController().signal,previewKey)).rejects.toBeInstanceOf(ApiError);
  });
  it.each([-1,0,1])('validates the preview lifetime at offset %i ms',async offset=>{
    const expires_at=new Date(Date.parse(quote.expires_at)+offset).toISOString();
    invoke.mockResolvedValue({...quote,expires_at});
    const result=previewMaximum(auction,450000,owner,new AbortController().signal,previewKey);
    if(offset===0) await expect(result).resolves.toHaveProperty('expires_at',expires_at);
    else await expect(result).rejects.toMatchObject({code:'invalid_fee_preview'});
  });
  it.each(['000123','000124'])('validates submillisecond server precision %s',async fraction=>{
    invoke.mockResolvedValue({...quote,created_at:'2026-01-01T00:00:00.000123Z',
      expires_at:`2026-01-01T00:15:00.${fraction}Z`});
    const result=previewMaximum(auction,450000,owner,new AbortController().signal,previewKey);
    if(fraction==='000123') await expect(result).resolves.toHaveProperty('fee_quote_id',quote.id);
    else await expect(result).rejects.toMatchObject({code:'invalid_fee_preview'});
  });
  it.each([-1,0,1])('lets Pricing decide expiry at server offset %i despite a fast browser clock',async offset=>{
    const expires=Date.parse(quote.expires_at);
    vi.spyOn(Date,'now').mockReturnValue(expires+86_400_000);
    const signal=new AbortController().signal;
    invoke.mockResolvedValueOnce(quote);
    const preview=await previewMaximum(auction,450000,owner,signal,previewKey);
    const serverTime=expires+offset;
    if(serverTime>=expires) invoke.mockRejectedValueOnce(new ApiError(409,'quote_expired',''));
    else invoke.mockResolvedValueOnce({...quote,reviewed_at:new Date(serverTime).toISOString()});
    const result=reviewMaximum(preview,'test-review-key',signal);
    if(offset<0) await expect(result).resolves.toBeUndefined();
    else await expect(result).rejects.toMatchObject({code:'quote_expired'});
  });

});

describe('retained fee review acknowledgement',()=>{
  it('acknowledges the exact retained version and payable without payment authority',async()=>{
    const signal=new AbortController().signal;
    invoke.mockResolvedValueOnce(quote).mockResolvedValueOnce({...quote,reviewed_at:'2026-01-01T00:00:00Z'});
    const preview=await previewMaximum(auction,450000,owner,signal,previewKey);
    await reviewMaximum(preview,'review-key-6',signal);
    const [path,options]=invoke.mock.calls[1];
    expect(path).toBe(`/api/web/v1/pricing/v1/quotes/${quote.id}/review`);expect(options.signal).toBe(signal);
    expect(options.headers['Idempotency-Key']).toBe('review-key-6');
    expect(options.accessFingerprint).toBe(owner.accessFingerprint);
    expect(JSON.parse(options.body)).toEqual({...binding,quote_revision:1,payable_minor:463500});
  });
  it.each([null,quote.expires_at,'2025-12-31T23:59:59Z'])('refuses a missing/equal-expiry/before-create review %s',async reviewed_at=>{
    invoke.mockResolvedValueOnce(quote).mockResolvedValueOnce({...quote,reviewed_at});
    const signal=new AbortController().signal,preview=await previewMaximum(auction,450000,owner,signal,previewKey);
    await expect(reviewMaximum(preview,'review-key-6',signal)).rejects.toBeInstanceOf(ApiError);
  });
  it('permits reconciliation of the original review acknowledgement after expiry',async()=>{
    invoke.mockResolvedValueOnce(quote).mockResolvedValueOnce({...quote,reviewed_at:'2026-01-01T00:00:00Z'});
    const signal=new AbortController().signal,preview=await previewMaximum(auction,450000,owner,signal,previewKey);
    vi.spyOn(Date,'now').mockReturnValue(Date.parse('2051-01-01T00:00:00Z'));
    await expect(reviewMaximum(preview,'review-key-6',signal)).resolves.toBeUndefined();
  });
});

describe('private maximum transport fencing',()=>{
  it('sends the exact frozen Auction command without a caller-supplied identity',async()=>{
    invoke.mockResolvedValue(accepted);
    const signal=new AbortController().signal;
    await sendMaximum(auctionId,intent,signal);
    const [path,options]=invoke.mock.calls[0];
    expect(path).toBe(`/api/web/v1/auction/v1/auctions/${auctionId}/maximum`);expect(options.signal).toBe(signal);
    expect(options.headers['Idempotency-Key']).toBe(intent.key);
    expect(JSON.parse(options.body)).toEqual({action:'submit_v2',command:{amount_minor:450000,fee_quote_id:'00000000-0000-0000-0000-000000000008',expected_revision:4,watch_id:'00000000-0000-0000-0000-000000000007',quote_revision:1,policy_revision:'policy-6'}});
    expect(options.accessFingerprint).toBe(intent.owner);
    expect(JSON.stringify(JSON.parse(options.body))).not.toContain(intent.owner);
  });
  it('retains the original body/key after an uncertain acknowledgement',async()=>{
    invoke.mockRejectedValueOnce(new ApiError(503,'unavailable','request-6')).mockResolvedValueOnce(accepted);
    const signal=new AbortController().signal;
    await expect(sendMaximum(auctionId,intent,signal)).rejects.toBeInstanceOf(ApiError);
    await sendMaximum(auctionId,intent,signal);
    expect(invoke.mock.calls[0]).toEqual(invoke.mock.calls[1]);
  });
  it('refuses network admission after the originating account is cleared',()=>{
    const controller=new AbortController();controller.abort();
    expect(()=>sendMaximum(auctionId,intent,controller.signal)).toThrow();expect(invoke).not.toHaveBeenCalled();
  });
  it('propagates account-switch cancellation through a coordinated request',async()=>{
    invoke.mockImplementation((_path:string,options:RequestInit)=>new Promise((_resolve,reject)=>{
      options.signal?.addEventListener('abort',()=>reject(options.signal?.reason),{once:true});
    }));
    const controller=new AbortController(),request=sendMaximum(auctionId,intent,controller.signal);
    controller.abort();await expect(request).rejects.toMatchObject({name:'AbortError'});
  });
});


describe('private ceiling read-back',()=>{
  const stored={schema_version:2,auction_id:auction.id,actor_id:owner.subjectId,watch_id:auction.listing_id,revision:4,amount_minor:450000,active:false,standing:'outbid'};
  it('reads only the authenticated own auction record',async()=>{
    invoke.mockResolvedValue(stored);
    expect(await readOwnMaximum(auction.id,owner,new AbortController().signal)).toEqual(stored);
    expect(invoke.mock.calls[0][1].accessFingerprint).toBe(owner.accessFingerprint);
    expect(JSON.parse(invoke.mock.calls[0][1].body)).toEqual({action:'read_v2'});
  });
  it.each([{actor_id:'other'},{auction_id:'other'},{revision:0},{amount_minor:Infinity},{amount_minor:0},{amount_minor:null,active:true},{standing:undefined},{standing:'unknown'},{active:true,standing:'outbid'}])('refuses mismatched or invalid private records %j',async change=>{
    invoke.mockResolvedValue({...stored,...change});
    await expect(readOwnMaximum(auction.id,owner,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
});


describe('private command receipt binding',()=>{
  it('reads the original reference in its original access partition',async()=>{
    invoke.mockResolvedValue(accepted);
    expect(await lookupMaximum(auctionId,intent,new AbortController().signal)).toEqual(accepted);
    expect(invoke.mock.calls[0][0]).toBe(`/api/web/v1/auction/v1/auctions/${auctionId}/maximum`);
    expect(invoke.mock.calls[0][1].accessFingerprint).toBe(intent.owner);
    expect(invoke.mock.calls[0][1].method).toBe('POST');
    expect(JSON.parse(invoke.mock.calls[0][1].body)).toEqual({action:'lookup_v2',operation_id:intent.key});
  });
  it.each([{actor_id:'other'},{operation_id:'other'},{subject_id:'other'},{organization_id:'business'},
    {expected_revision:2},{quote_id:'other'},{revision:4},{state:'unknown'},{watch_id:'other'},
    {quote_revision:2},{policy_revision:'other'},{pending_reason:'x'.repeat(101)},{next_actor:'other'},
    {next_review_at:'2030-02-30T00:00:00Z'},{next_review_at:'2030-01-01T00:00:00+02:00'},
    {private_evidence:'test-evidence'}])('rejects an unbound receipt through either path %j',async change=>{
    invoke.mockResolvedValue({...accepted,...change});
    const signal=new AbortController().signal;
    await expect(sendMaximum(auctionId,intent,signal)).rejects.toBeInstanceOf(ApiError);
    await expect(lookupMaximum(auctionId,intent,signal)).rejects.toBeInstanceOf(ApiError);
  });
  it.each(['pending_reason','next_actor','next_review_at'] as const)('rejects a receipt missing %s',async field=>{
    const receipt:Partial<typeof accepted>={...accepted};
    delete receipt[field];
    invoke.mockResolvedValue(receipt);
    const signal=new AbortController().signal;
    await expect(sendMaximum(auctionId,intent,signal)).rejects.toMatchObject({code:'invalid_operation'});
    await expect(lookupMaximum(auctionId,intent,signal)).rejects.toMatchObject({code:'invalid_operation'});
  });

  it('rejects an invalid actor even when it matches the local intent',async()=>{
    const malformed={...intent,actor_id:'test-buyer'};
    invoke.mockResolvedValue({...accepted,actor_id:malformed.actor_id});
    await expect(lookupMaximum(auctionId,malformed,new AbortController().signal))
      .rejects.toMatchObject({code:'invalid_operation'});
  });

});

it('checks an earlier receipt by its original key through the scoped receipt action',async()=>{
  const receipt={operation_id:owner.subjectId,auction_id:auction.id,revision:5,status:'succeeded',code:'bid_accepted'};
  invoke.mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValue(receipt);
  const signal=new AbortController().signal;
  const command={amount_minor:intent.amount_minor,fee_quote_id:intent.fee_quote_id,expected_revision:intent.revision};
  const lookup=()=>lookupMaximumV1(auction.id,intent.key,command,intent.owner,signal);
  await expect(lookup()).rejects.toMatchObject({status:503});
  await expect(lookup()).resolves.toBe('accepted');
  expect(invoke.mock.calls[0]).toEqual(invoke.mock.calls[1]);
  expect(invoke.mock.calls[0]).toEqual([
    `/api/web/v1/auction/v1/auctions/${auction.id}/maximum`,
    {signal,accessFingerprint:intent.owner,cache:'no-store',method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'lookup_v1',operation_key:intent.key,command})},
  ]);
  invoke.mockResolvedValue({...receipt,auction_id:'another-auction'});
  await expect(lookup()).rejects.toMatchObject({code:'invalid_operation'});
});

it('requires the legacy transition marker to bind the current buyer and auction',async()=>{
  const signal=new AbortController().signal;
  const marker={schema_version:1,auction_id:auction.id,actor_id:owner.subjectId,revision:4};
  invoke.mockResolvedValueOnce(marker).mockResolvedValueOnce({...marker,actor_id:'test-other-buyer'});
  await expect(readOwnMaximum(auction.id,owner,signal)).resolves.toEqual(marker);
  await expect(readOwnMaximum(auction.id,owner,signal)).rejects.toMatchObject({code:'invalid_private_maximum'});
});

it('binds historical recovery to the original command and operation key until a pending fence resolves',async()=>{
  const signal=new AbortController().signal;
  const receipt={operation_id:owner.subjectId,auction_id:auction.id,revision:5};
  invoke.mockResolvedValueOnce({...receipt,status:'pending',code:'first_bid_fenced_bid_not_confirmed',commitment_status:'succeeded'})
    .mockResolvedValueOnce({...receipt,status:'denied',code:'auction_ended'});
  const replay=()=>recoverLegacyMaximum(auction.id,{...intent,watch_id:null},signal);
  await expect(replay()).resolves.toBe('pending');
  await expect(replay()).resolves.toBe('denied');
  expect(invoke.mock.calls[0]).toEqual(invoke.mock.calls[1]);
  const [path,options]=invoke.mock.calls[0];
  expect(path.endsWith('/auctions/'+auction.id+'/maximum')).toBe(true);
  expect(options.headers['Idempotency-Key']).toBe(intent.key);
  expect(JSON.parse(options.body)).toEqual({
    action:'recover_v1',command:{
      amount_minor:intent.amount_minor,fee_quote_id:intent.fee_quote_id,expected_revision:intent.revision,
    },
  });
});

it.each([
  ['00:00:00.000122',false],
  ['00:00:00.000123',true],
  ['00:00:00.000124',true],
  ['00:15:00.000122',true],
  ['00:15:00.000123',false],
  ['00:15:00.000124',false],
])('validates the exact server review instant %s',async(time,valid)=>{
  const precise={...quote,created_at:'2026-01-01T00:00:00.000123Z',expires_at:'2026-01-01T00:15:00.000123Z'};
  invoke.mockResolvedValueOnce(precise).mockResolvedValueOnce({...precise,reviewed_at:`2026-01-01T${time}Z`});
  const signal=new AbortController().signal;
  const preview=await previewMaximum(auction,450000,owner,signal,previewKey);
  const review=reviewMaximum(preview,'test-review-key',signal);
  if(valid) await expect(review).resolves.toBeUndefined();
  else await expect(review).rejects.toBeInstanceOf(ApiError);
});

it('finds earlier bid decisions without a command, quote or operation key',async()=>{
  const {listEarlierBids}=await import('./maximum-api');
  const page={auction_id:auction.id,items:[{operation_id:owner.subjectId,
    recorded_at:'2030-01-01T12:00:00Z',state:'accepted'}],next_cursor:null};
  invoke.mockResolvedValueOnce(page).mockResolvedValueOnce({...page,auction_id:'another-auction'});
  const signal=new AbortController().signal;
  await expect(listEarlierBids(auction.id,intent.owner,null,signal)).resolves.toEqual(page);
  expect(JSON.parse(invoke.mock.calls[0][1].body)).toEqual({action:'list_bid_receipts_v1',before:null});
  await expect(listEarlierBids(auction.id,intent.owner,null,signal)).rejects.toMatchObject({code:'invalid_operation'});
});

it.each([
  ['not_found','Quote not found.',404,'quote_not_found',true],
  ['not_found','The request could not be completed.',404,'not_found',true],
  ['not_found','Resource not found.',404,'not_found',true],
  ['not_found','Quote not found.',503,'not_found',true],
  ['not_found','Access denied.',403,'quote_read_denied',true],
  ['http_error','The request could not be completed.',404,'http_error',false],
] as const)('classifies review recovery with %s and Pricing response %s (%i)',async(code,message,status,expected,probes)=>{
  invoke.mockResolvedValueOnce(quote).mockRejectedValueOnce(new ApiError(404,code,'test-review'));
  const fetchQuote=vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({
    error:{code:'not_found',message,request_id:'test-read',details:{}},
  },{status}));
  const signal=new AbortController().signal;
  const preview=await previewMaximum(auction,450000,owner,signal,previewKey);
  const verify=vi.fn((quoteId:string,_access:string,signal:AbortSignal)=>
    confirmMissingQuote(quoteId,'synthetic-buyer-token',signal));

  await expect(reviewMaximum(preview,'test-review-key',signal,verify)).rejects.toMatchObject({code:expected});
  expect(invoke).toHaveBeenCalledTimes(2);
  expect(fetchQuote).toHaveBeenCalledTimes(Number(probes));
  if(probes) {
    expect(verify).toHaveBeenCalledWith(quote.id,owner.accessFingerprint,signal);
    expect(fetchQuote).toHaveBeenCalledWith('/api/web/v1/pricing/v1/quotes/'+quote.id,
      expect.objectContaining({cache:'no-store',redirect:'error'}));
  }
});

describe('reload bid replay',()=>{
  const reference={key:intent.key,fee_quote_id:quote.id,revision:auction.revision,owner:owner.accessFingerprint,
    actor_id:owner.subjectId,watch_id:intent.watch_id,quote_revision:quote.revision,policy_revision:'2'};
  const reviewed={...quote,reviewed_at:quote.created_at};
  it('recovers the exact amount from the original reviewed quote through a private read',async()=>{
    invoke.mockResolvedValueOnce(reviewed);
    const signal=new AbortController().signal;
    await expect(restoreMaximumIntent(auction.id,reference,signal)).resolves.toEqual({...reference,amount_minor:450000});
    expect(invoke).toHaveBeenCalledWith('/api/web/v1/pricing/v1/quotes/'+quote.id,{
      signal,accessFingerprint:owner.accessFingerprint,cache:'no-store',
    });
  });
  it.each([null,quote.created_at])('reconstructs the same fee review before or after acknowledgement (%s)',async reviewed_at=>{
    const snapshot={...quote,reviewed_at};
    invoke.mockResolvedValueOnce(snapshot);
    const signal=new AbortController().signal;
    const recovered=await restoreMaximumReview(auction.id,reference,signal);
    invoke.mockResolvedValueOnce(reviewed);
    await reviewMaximum(recovered,'test-review-reference',signal);
    expect(invoke).toHaveBeenLastCalledWith('/api/web/v1/pricing/v1/quotes/'+quote.id+'/review',expect.objectContaining({
      headers:expect.objectContaining({'Idempotency-Key':'test-review-reference'}),
      body:JSON.stringify({...recovered.binding,quote_revision:quote.revision,payable_minor:quote.payable_minor}),
    }));
  });
  it.each([
    {id:auction.id},{owner_id:auction.id},{subject_id:quote.id},{subject_revision:3},{revision:2},
    {reviewed_at:null},{reviewed_at:quote.expires_at},
  ])('fails closed when a recovered quote is unbound or unreviewed %j',async changes=>{
    invoke.mockResolvedValueOnce({...reviewed,...changes});
    await expect(restoreMaximumIntent(auction.id,reference,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
});

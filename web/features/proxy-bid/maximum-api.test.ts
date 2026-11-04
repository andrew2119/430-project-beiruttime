import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
import type {Quote} from '@contracts/contracts-pricing/quotes';
import {ApiError} from '@/lib/api/client';
import {MAX_QUOTE_MINOR,previewMaximum,reviewMaximum,sendMaximum,type MaximumIntent} from './maximum-api';
const invoke=vi.hoisted(()=>vi.fn());
vi.mock('./session',()=>({authenticatedRequest:invoke}));
const owner={subjectId:'00000000-0000-0000-0000-000000000001',accessFingerprint:'scope-6'};
const intent:MaximumIntent=Object.freeze({key:'logical-command-6',amount_minor:450000,fee_quote_id:'quote-6',revision:4,owner:'private-owner-fingerprint'});
beforeEach(()=>{invoke.mockReset();});
afterEach(()=>{vi.restoreAllMocks();});
const auction:AuctionSnapshot={id:'00000000-0000-0000-0000-000000000006',listing_id:'00000000-0000-0000-0000-000000000007',currency:'USD',opening_minor:400000,current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2020-01-01T00:00:00Z',ends_at:'2050-01-01T00:00:00Z',server_time:'2026-01-01T00:00:00Z',revision:4,accepted_sequence:1,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:'bidder-1',status:'live'};
const binding={subject_id:auction.id,subject_revision:4,purpose:'bid',currency:'USD',price_minor:450000,schedule_id:'sample-v1',source:'sample'};
const quote:Quote={...binding,purpose:'bid',currency:'USD',schedule_id:'sample-v1',source:'sample',source_verified:false,
  id:'00000000-0000-0000-0000-000000000008',owner_id:owner.subjectId,revision:1,minor_unit_exponent:2,
  buyer_fee_minor:13500,seller_commission_minor:22500,seller_net_minor:427500,shipping_minor:0,tax_minor:0,
  payable_minor:463500,sample:true,rounding:'half_up',fx:null,commission_basis:'price_excluding_buyer_fee_shipping_tax',
  policy:{buyer_fee_bps:300,seller_commission_bps:500,shipping:'sample_zero',tax:'sample_zero',fx:'not_applied',currency_exponents:{USD:2,LBP:2}},
  created_at:'2020-01-01T00:00:00Z',expires_at:'2050-01-01T00:00:00Z',reviewed_at:null};

describe('pricing.quotes.v1 maximum preview',()=>{
  it('binds exact bid-purpose fields and labels the selected sample policy',async()=>{
    invoke.mockResolvedValue({...quote,private_internal_field:'not-projected'});
    const signal=new AbortController().signal;
    const preview=await previewMaximum(auction,450000,owner,signal);
    const [path,options]=invoke.mock.calls[0];
    expect(path).toBe('/api/web/v1/pricing/v1/quotes');expect(options.signal).toBe(signal);
    expect(JSON.parse(options.body)).toEqual(binding);
    expect(preview).toMatchObject({fee_quote_id:quote.id,amount_minor:450000,buyer_fee_minor:13500,total_minor:463500,
      expires_at:quote.expires_at,auction_revision:4,quote_revision:1,owner_id:owner.subjectId,access_fingerprint:owner.accessFingerprint,sample:true,binding});
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
    {expires_at:'not-a-time'},{expires_at:'2050-01-01T00:00:00'},{created_at:'2051-01-01T00:00:00Z'},
  ])('refuses wrong-scope, unbalanced or stale preview %j',async changes=>{
    invoke.mockResolvedValue({...quote,...changes});
    await expect(previewMaximum(auction,450000,owner,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
  it.each([0,NaN,MAX_QUOTE_MINOR+1])('refuses invalid maximum before quote transport %s',async amount=>{
    await expect(previewMaximum(auction,amount,owner,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
    expect(invoke).not.toHaveBeenCalled();
  });
  it('fails closed on a null preview',async()=>{
    invoke.mockResolvedValue(null);
    await expect(previewMaximum(auction,450000,owner,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
  it.each([-1,0,1])('checks before/equal/after expiry boundary %i',async offset=>{
    vi.spyOn(Date,'now').mockReturnValue(1000);
    invoke.mockResolvedValue({...quote,created_at:new Date(0).toISOString(),expires_at:new Date(1000+offset).toISOString()});
    const result=previewMaximum(auction,450000,owner,new AbortController().signal);
    if(offset>0) await expect(result).resolves.toHaveProperty('fee_quote_id',quote.id);
    else await expect(result).rejects.toBeInstanceOf(ApiError);
  });
});

describe('retained fee review acknowledgement',()=>{
  it('acknowledges the exact retained version and payable without payment authority',async()=>{
    const signal=new AbortController().signal;
    invoke.mockResolvedValueOnce(quote).mockResolvedValueOnce({...quote,reviewed_at:'2026-01-01T00:00:00Z'});
    const preview=await previewMaximum(auction,450000,owner,signal);
    await reviewMaximum(preview,'review-key-6',signal);
    const [path,options]=invoke.mock.calls[1];
    expect(path).toBe(`/api/web/v1/pricing/v1/quotes/${quote.id}/review`);expect(options.signal).toBe(signal);
    expect(options.headers['Idempotency-Key']).toBe('review-key-6');
    expect(options.accessFingerprint).toBe(owner.accessFingerprint);
    expect(JSON.parse(options.body)).toEqual({...binding,quote_revision:1,payable_minor:463500});
  });
  it.each([null,'2050-01-01T00:00:00Z','2019-01-01T00:00:00Z'])('refuses a missing/equal-expiry/before-create review %s',async reviewed_at=>{
    invoke.mockResolvedValueOnce(quote).mockResolvedValueOnce({...quote,reviewed_at});
    const signal=new AbortController().signal,preview=await previewMaximum(auction,450000,owner,signal);
    await expect(reviewMaximum(preview,'review-key-6',signal)).rejects.toBeInstanceOf(ApiError);
  });
  it('permits reconciliation of the original review acknowledgement after expiry',async()=>{
    invoke.mockResolvedValueOnce(quote).mockResolvedValueOnce({...quote,reviewed_at:'2026-01-01T00:00:00Z'});
    const signal=new AbortController().signal,preview=await previewMaximum(auction,450000,owner,signal);
    vi.spyOn(Date,'now').mockReturnValue(Date.parse('2051-01-01T00:00:00Z'));
    await expect(reviewMaximum(preview,'review-key-6',signal)).resolves.toBeUndefined();
  });
});

describe('private maximum transport fencing',()=>{
  it('sends the exact frozen Auction command without a caller-supplied identity',async()=>{
    invoke.mockResolvedValue({status:'succeeded'});
    const signal=new AbortController().signal;
    await sendMaximum('auction-6',intent,signal);
    const [path,options]=invoke.mock.calls[0];
    expect(path).toBe('/api/web/v1/auction/v1/auctions/auction-6/maximum');expect(options.signal).toBe(signal);
    expect(options.headers['Idempotency-Key']).toBe(intent.key);
    expect(JSON.parse(options.body)).toEqual({amount_minor:450000,fee_quote_id:'quote-6',expected_revision:4});
    expect(options.accessFingerprint).toBe(intent.owner);
    expect(JSON.stringify(JSON.parse(options.body))).not.toContain(intent.owner);
  });
  it('retains the original body/key after an uncertain acknowledgement',async()=>{
    invoke.mockRejectedValueOnce(new ApiError(503,'unavailable','request-6')).mockResolvedValueOnce({status:'succeeded'});
    const signal=new AbortController().signal;
    await expect(sendMaximum('auction-6',intent,signal)).rejects.toBeInstanceOf(ApiError);
    await sendMaximum('auction-6',intent,signal);
    expect(invoke.mock.calls[0]).toEqual(invoke.mock.calls[1]);
  });
  it('refuses network admission after the originating account is cleared',()=>{
    const controller=new AbortController();controller.abort();
    expect(()=>sendMaximum('auction-6',intent,controller.signal)).toThrow();expect(invoke).not.toHaveBeenCalled();
  });
  it('propagates account-switch cancellation through a coordinated request',async()=>{
    invoke.mockImplementation((_path:string,options:RequestInit)=>new Promise((_resolve,reject)=>{
      options.signal?.addEventListener('abort',()=>reject(options.signal?.reason),{once:true});
    }));
    const controller=new AbortController(),request=sendMaximum('auction-6',intent,controller.signal);
    controller.abort();await expect(request).rejects.toMatchObject({name:'AbortError'});
  });
});

import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
import {ApiError} from '@/lib/api/client';
import {previewMaximum,sendMaximum,type MaximumIntent} from './maximum-api';
const invoke=vi.hoisted(()=>vi.fn());
vi.mock('./session',()=>({authenticatedRequest:invoke}));
const intent:MaximumIntent=Object.freeze({key:'logical-command-6',amount_minor:450000,fee_quote_id:'quote-6',revision:4,owner:'private-owner-fingerprint'});
beforeEach(()=>{invoke.mockReset();});
afterEach(()=>{vi.restoreAllMocks();});
const auction:AuctionSnapshot={id:'00000000-0000-0000-0000-000000000006',listing_id:'00000000-0000-0000-0000-000000000007',currency:'USD',opening_minor:400000,current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2020-01-01T00:00:00Z',ends_at:'2050-01-01T00:00:00Z',server_time:'2026-01-01T00:00:00Z',revision:4,accepted_sequence:1,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:'bidder-1',status:'live'};
const quote={id:'00000000-0000-0000-0000-000000000008',buyer_fee_minor:9000,total_minor:459000,expires_at:'2050-01-01T00:00:00Z',auction_revision:4};
describe('current bound maximum fee preview',()=>{
  it('uses the published quote request shape and binds every Auction prerequisite',async()=>{
    invoke.mockResolvedValue({...quote,private_internal_field:'not-projected'});
    const signal=new AbortController().signal;
    const preview=await previewMaximum(auction,450000,signal);
    const [path,options]=invoke.mock.calls[0];
    expect(path).toBe('/api/web/v1/pricing/v1/quotes');expect(options.signal).toBe(signal);
    expect(JSON.parse(options.body)).toEqual({auction_id:auction.id,listing_id:auction.listing_id,amount_minor:450000,currency:'USD',rules_version:'ordinary.v1',auction_revision:4});
    expect(preview).toEqual({fee_quote_id:quote.id,amount_minor:450000,currency:'USD',buyer_fee_minor:9000,total_minor:459000,expires_at:quote.expires_at,auction_revision:4});
    expect(preview).not.toHaveProperty('private_internal_field');
  });
  it.each([{auction_revision:3},{buyer_fee_minor:-1},{buyer_fee_minor:1.5},{total_minor:449999},{total_minor:Number.MAX_SAFE_INTEGER+1},{id:'unbound'},{expires_at:'not-a-time'},{expires_at:'2050-01-01T00:00:00'}])('refuses malformed or stale preview %j',async changes=>{
    invoke.mockResolvedValue({...quote,...changes});
    await expect(previewMaximum(auction,450000,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
  it.each([0,NaN,Number.MAX_SAFE_INTEGER])('refuses an invalid maximum before quote transport %s',async amount=>{
    await expect(previewMaximum(auction,amount,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
    expect(invoke).not.toHaveBeenCalled();
  });
  it('fails closed on a null preview without projecting an untrusted error',async()=>{
    invoke.mockResolvedValue(null);
    await expect(previewMaximum(auction,450000,new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
  it.each([-1,0,1])('checks before/equal/after expiry boundary %i',async offset=>{
    vi.spyOn(Date,'now').mockReturnValue(1000);
    invoke.mockResolvedValue({...quote,expires_at:new Date(1000+offset).toISOString()});
    const result=previewMaximum(auction,450000,new AbortController().signal);
    if(offset>0) await expect(result).resolves.toHaveProperty('fee_quote_id',quote.id);
    else await expect(result).rejects.toBeInstanceOf(ApiError);
  });
});
describe('private maximum transport fencing',()=>{
  it('sends the exact frozen v1 command without a caller-supplied identity',async()=>{
    invoke.mockResolvedValue({status:'succeeded'});
    const signal=new AbortController().signal;
    await sendMaximum('auction-6',intent,signal);
    const [path,options]=invoke.mock.calls[0];
    expect(path).toBe('/api/web/v1/auction/v1/auctions/auction-6/maximum');
    expect(options.signal).toBe(signal);
    expect(options.headers['Idempotency-Key']).toBe(intent.key);
    expect(JSON.parse(options.body)).toEqual({amount_minor:450000,fee_quote_id:'quote-6',expected_revision:4});
    expect(JSON.stringify(options)).not.toContain(intent.owner);
  });
  it('retains the original body/key after an uncertain acknowledgement',async()=>{
    invoke.mockRejectedValueOnce(new ApiError(503,'unavailable','request-6')).mockResolvedValueOnce({status:'succeeded'});
    const signal=new AbortController().signal;
    await expect(sendMaximum('auction-6',intent,signal)).rejects.toBeInstanceOf(ApiError);
    await sendMaximum('auction-6',intent,signal);
    expect(invoke.mock.calls[0]).toEqual(invoke.mock.calls[1]);
  });
  it('refuses a new network attempt after the originating account is cleared',()=>{
    const controller=new AbortController();controller.abort();
    expect(()=>sendMaximum('auction-6',intent,controller.signal)).toThrow();
    expect(invoke).not.toHaveBeenCalled();
  });
  it('propagates account-switch cancellation into an in-flight coordinated request',async()=>{
    invoke.mockImplementation((_path:string,options:RequestInit)=>new Promise((_resolve,reject)=>{
      options.signal?.addEventListener('abort',()=>reject(options.signal?.reason),{once:true});
    }));
    const controller=new AbortController();
    const request=sendMaximum('auction-6',intent,controller.signal);
    controller.abort();
    await expect(request).rejects.toMatchObject({name:'AbortError'});
  });
});

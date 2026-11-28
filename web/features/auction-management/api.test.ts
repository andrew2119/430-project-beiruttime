import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn()}));
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { command, displayMinor, incrementBands, minor, quotePreview } from './api';
import en from './en.json';
import ar from './ar.json';
const send=vi.mocked(authenticatedRequest);
beforeEach(()=>send.mockReset());
describe('exact localized money',()=>{
  it.each([['4100',410000],['٤١٠٠',410000],['۴۱۰۰٫۱۲',410012],['0.01',1],['90000000000000',9000000000000000]])('normalizes %s without binary arithmetic',(text,want)=>expect(minor(text)).toBe(want));
  it.each(['NaN','Infinity','-10','1.111','1e3','1,000','','0','90000000000000.01'])('refuses %s',text=>expect(()=>minor(text)).toThrow());
  it('formats both languages with a currency',()=>{expect(displayMinor(410000,'USD','en')).toContain('4,100.00');expect(displayMinor(410000,'USD','ar')).toContain('٤');});
  it('retains every cent at the maximum supported magnitude',()=>expect(displayMinor(8999999999999999,'USD','en')).toBe('$89,999,999,999,999.99'));
  it('localizes the exact two-digit Arabic fraction',()=>expect(displayMinor(410001,'USD','ar')).toContain('٫٠١'));
  it('keeps historic non-USD money outside active dollar displays',()=>expect(()=>displayMinor(410000,'LBP','en')).toThrow());
  it.each([NaN,Infinity,-1,1.5,9000000000000001])('refuses malformed display money %s',value=>expect(()=>displayMinor(value,'USD','en')).toThrow());
});
describe('disclosed increment bands',()=>{
  it('retains exact ascending thresholds and Arabic values',()=>expect(incrementBands('100',[{from:'٥٠٠٠',step:'٢٠٠'}])).toEqual([{from_minor:0,step_minor:10000},{from_minor:500000,step_minor:20000}]));
  it.each([{bands:[{from:'0',step:'100'}]},{bands:[{from:'5000',step:'100'},{from:'5000',step:'200'}]},{bands:[{from:'5000',step:'100'},{from:'4000',step:'200'}]},{bands:[{from:'5000',step:'0'}]}])('rejects unordered or zero bands $bands',({bands})=>expect(()=>incrementBands('100',bands)).toThrow());
  it('enforces the twenty-band contract bound',()=>expect(()=>incrementBands('100',Array.from({length:20},(_,i)=>({from:String(i+1),step:'100'})))).toThrow());
});
describe('stored acknowledgements, never optimistic bids',()=>{
  it('returns only the stored response',async()=>{send.mockResolvedValueOnce({status:'succeeded',operation_id:'stored'});expect(await command('/auctions/a/bids',{amount_minor:410000},'logical-operation')).toEqual({status:'succeeded',operation_id:'stored'});expect(send.mock.calls[0][1]?.headers).toMatchObject({'Idempotency-Key':'logical-operation'});});
  it('reconciles an uncertain response by the same operation key',async()=>{send.mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValueOnce({status:'succeeded',operation_id:'stored'});expect(await command('/auctions/a/bids',{},'lost-response')).toMatchObject({operation_id:'stored'});expect(send.mock.calls[1][0]).toContain('/auction-operations/by-key/lost-response');});
  it('preserves the verified organization selector during uncertain reconciliation',async()=>{send.mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValueOnce({status:'succeeded',operation_id:'stored'});await command('/auctions?organization_id=org',{},'scoped');expect(send.mock.calls[1][0]).toContain('/by-key/scoped?organization_id=org');});
  it('never converts absent reconciliation into a denial or success',async()=>{send.mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockRejectedValueOnce(new ApiError(404,'not_found',''));await expect(command('/auctions/a/bids',{},'uncertain')).rejects.toMatchObject({status:503});expect(send).toHaveBeenCalledTimes(2);});
  it('does not retry deterministic policy denials',async()=>{send.mockRejectedValueOnce(new ApiError(403,'forbidden',''));await expect(command('/auctions/a/bids',{},'denied')).rejects.toMatchObject({status:403});expect(send).toHaveBeenCalledTimes(1);});
  it('does not reconcile after the account scope cancels the invocation',async()=>{const controller=new AbortController();controller.abort();send.mockRejectedValueOnce(new ApiError(503,'unavailable',''));await expect(command('/auctions/a/bids',{},'cancelled',controller.signal)).rejects.toMatchObject({status:503});expect(send).toHaveBeenCalledTimes(1);});
});
it('schedules local times through server interpretation under the same operation and business scope',async()=>{
 send.mockResolvedValueOnce({status:'succeeded'});
 const body={starts_local:'2026-11-16T19:00',ends_local:'2026-11-17T19:00'};
 await command('/auctions?organization_id=business',body,'schedule-key',undefined,'seller-session');
 expect(send.mock.calls[0][0]).toBe('/api/web/v2/auction-schedules?organization_id=business');
 expect(send.mock.calls[0][1]).toMatchObject({accessFingerprint:'seller-session',headers:{'Idempotency-Key':'schedule-key'},body:JSON.stringify(body)});
});
describe('a real fee preview is required before confirmation',()=>{
  const auction='00000000-0000-4000-8000-000000000010',owner='00000000-0000-4000-8000-000000000001';
  const preview={id:'00000000-0000-4000-8000-000000000003',owner_id:owner,subject_id:auction,subject_revision:2,revision:1,purpose:'bid',currency:'USD',price_minor:410000,buyer_fee_minor:12300,shipping_minor:0,tax_minor:0,payable_minor:422300,schedule_id:'usd-v2',source:'sample',source_verified:false,sample:true,minor_unit_exponent:2,rounding:'half_up',expires_at:'2026-11-04T12:00:00Z'};
  const validate=(value:unknown)=>quotePreview(value,410000,2,auction,owner,'USD');
  it('retains exact fees, sample disclosure and the original review binding',()=>expect(validate(preview)).toMatchObject({id:preview.id,total_minor:422300,auction_revision:2,quote_revision:1,sample:true,request:{subject_id:auction,subject_revision:2,purpose:'bid',currency:'USD',price_minor:410000,schedule_id:'usd-v2',source:'sample'}}));
  it.each([{id:'not-a-uuid'},{owner_id:auction},{subject_id:owner},{subject_revision:1},{purpose:'purchase'},{currency:'LBP'},{price_minor:410001},{sample:false},{source_verified:true},{schedule_id:'sample-v1'},{schedule_id:'production-v1'},{revision:0},{minor_unit_exponent:0},{buyer_fee_minor:NaN},{payable_minor:Infinity},{payable_minor:409999},{payable_minor:9000000000000001},{expires_at:'2026-11-04T12:00:00'}])('rejects malformed, cross-owner or stale preview %s',change=>expect(()=>validate({...preview,...change})).toThrow(ApiError));
});
it('has complete Arabic and English feature keys',()=>expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort()));

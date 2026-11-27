import { describe,expect,it } from 'vitest';
import { paymentDeadline } from '../../../../web/features/pricing/readiness';
import { exactPaymentReadiness } from '../../../../web/features/pricing/payment-readiness';
import { stableOperation } from '../../../../web/features/pricing/quote-commands';
import type { PlatformPaymentReadinessV3 } from '../../../../packages/contracts-pricing/quotes/current-v3';

describe('Order-owned readiness',()=>{
 it.each([undefined,'', 'invalid',0, false])('keeps missing or malformed time unavailable: %s',value=>{
  expect(paymentDeadline(value)).toEqual({state:'unavailable'});
 });
 it('keeps notification pending separate from a running clock',()=>{
  expect(paymentDeadline(null)).toEqual({state:'notification_pending'});
  expect(paymentDeadline('2026-11-17T12:00:00Z')).toEqual({state:'known',value:'2026-11-17T12:00:00Z'});
 });
 const binding={buyer_id:'buyer-1',order_id:'order-1',order_kind:'brand',watch_id:'watch-1',quote_id:'quote-1',quote_revision:2,currency:'USD',total_minor:500000} as const;
 const proof:PlatformPaymentReadinessV3={...binding,payment_operation_id:'payment-1',payment_revision:1,state:'paid_held'};
 it('requires confirmed exact held principal without a buyer surcharge',()=>{
  expect(exactPaymentReadiness(proof,binding)).toBe('ready');
  expect(exactPaymentReadiness(null,binding)).toBe('unavailable');
  expect(exactPaymentReadiness({...proof,state:'pending'},binding)).toBe('pending');
  expect(exactPaymentReadiness({...proof,state:'unpaid'},binding)).toBe('unpaid');
 });
 it.each(Object.keys(binding) as (keyof typeof binding)[])('rejects changed %s',key=>{
  expect(exactPaymentReadiness({...proof,[key]:typeof binding[key]==='number'?999:'other'},binding)).toBe('unavailable');
 });
 it('rejects missing confirmation and stale payment revision',()=>{
  expect(exactPaymentReadiness({...proof,payment_operation_id:null},binding)).toBe('unavailable');
  expect(exactPaymentReadiness({...proof,payment_revision:0},binding)).toBe('unavailable');
 });
 it('recovers a lost response using the original operation after another action',()=>{
  const keys=new Map<string,string>();let next=0;
  const create=()=>String(++next);
  const original=stableOperation(keys,{quote:'one',revision:1},create);
  stableOperation(keys,{quote:'two',revision:2},create);
  expect(stableOperation(keys,{quote:'one',revision:1},create)).toBe(original);
  expect(next).toBe(2);
 });
});

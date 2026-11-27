import { describe,it,expect } from 'vitest';
import { selectedAmounts } from '../../../web/features/pricing/assessed-amounts';
import { quoteDecision, stableOperation } from '../../../web/features/pricing/quote-commands';
import { parseMinor, money, editableAmount } from '../../../web/features/pricing/money';
import { offerRoute } from '../../../web/features/offers/admission';
import type { AssessedQuote } from '../../../packages/contracts-pricing/quotes/assessed';
import en from '../../../web/features/pricing/s2-en.json';
import ar from '../../../web/features/pricing/s2-ar.json';
const quote={revision:1,terms_digest:'a'.repeat(64),lines:[{id:'required',kind:'part',amount_minor:400000,mandatory:true},{id:'optional',kind:'labor',amount_minor:100000,mandatory:false}],assessment_fee_minor:0,policy:{revision:2,buyer_fee_bps:0,business_fee_bps:500,seller_commission_bps:500}} as AssessedQuote;
describe('exact USD job terms',()=>{
 it('does not charge an unselected optional line',()=>{const result=selectedAmounts(quote,['required']);expect(result.payable_minor).toBe(400000);expect(result.labor_minor).toBe(0);expect(result.seller_net_minor+result.seller_commission_minor).toBe(400000);});
 it('deducts the business fee once without a buyer surcharge',()=>{const result=selectedAmounts(quote,['required','optional']);expect(result.payable_minor).toBe(500000);expect(result.platform_fee_minor).toBe(25000);expect(result.seller_net_minor).toBe(475000);});
 it('rounds half up to one cent',()=>{expect(selectedAmounts({...quote,lines:[{...quote.lines[0],amount_minor:10}]},['required']).platform_fee_minor).toBe(1);});
 it('retains old accepted dollar terms without implicit repricing',()=>{const accepted={payable_minor:515000} as AssessedQuote['full_total'];expect(selectedAmounts({...quote,policy:{...quote.policy,revision:1},decision:{amounts:accepted} as NonNullable<AssessedQuote['decision']>},['required'])).toBe(accepted);});
});
describe('dollars in both languages',()=>{
 it('uses exact cents and rejects currency or fractional-cent reinterpretation',()=>{expect(parseMinor('٥٠٠٠٫٠١','USD')).toBe(500001);expect(parseMinor('5000.01','USD')).toBe(500001);expect(()=>parseMinor('1.001','USD')).toThrow();expect(()=>parseMinor('100','LBP')).toThrow();expect(editableAmount(500001,'USD')).toBe('5000.01');expect(money(500001,'USD','en')).toBe('5,000.01 USD');expect(money(500001,'USD','ar')).toContain('USD');});
 it('keeps exact selected scope, fee choices, amount and operation when copy changes',()=>{const keys=new Map<string,string>();const selected=['required','optional'];const before=quoteDecision(quote,'accept',selected,true,true);const first=stableOperation(keys,before,()=> 'intent-1');expect(en.accept).not.toBe(ar.accept);const after=quoteDecision(quote,'accept',selected,true,true);expect(after).toEqual(before);expect(stableOperation(keys,after,()=> 'must-not-replace')).toBe(first);expect(after.payable_minor).toBe(500000);expect(after.selected_line_ids).toEqual(selected);expect(after.accept_return_fee).toBe(true);const issueFields={amount:'٥٠٠٠٫٠١',warranty:'شروط خاصة',basis:'Unchanged basis'};const issueKey=stableOperation(keys,issueFields,()=> 'issue-1');expect(stableOperation(keys,{...issueFields},()=> 'no-new-issue')).toBe(issueKey);});
 it('keeps bilingual copy complete',()=>{expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort());});
});
describe('offer routes',()=>{
 it('permits offers-only and fixed-price but never an auction or mismatched commitment',()=>{expect(offerRoute('fixed_price','fixed')).toBe(true);expect(offerRoute('offer','seller_base')).toBe(true);expect(offerRoute('auction','auction')).toBe(false);expect(offerRoute('fixed_price','seller_base')).toBe(false);});
});

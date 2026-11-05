import { describe,it,expect } from 'vitest';
import { selectedAmounts } from '../../../web/features/pricing/assessed-amounts';
import type { AssessedQuote } from '../../../packages/contracts-pricing/quotes/assessed';
const quote={lines:[{id:'required',kind:'part',amount_minor:10000,mandatory:true},{id:'optional',kind:'labor',amount_minor:5000,mandatory:false}],assessment_fee_minor:1000,policy:{buyer_fee_bps:300,seller_commission_bps:500}} as AssessedQuote;
describe('exact diagnosed selection',()=>{
 it('does not charge an unselected optional line',()=>{const result=selectedAmounts(quote,['required']);expect(result.payable_minor).toBe(11330);expect(result.labor_minor).toBe(0);expect(result.seller_net_minor+result.seller_commission_minor).toBe(11000);});
 it('uses Pricing policy and one half-up rounding boundary',()=>{expect(selectedAmounts(quote,['required','optional']).payable_minor).toBe(16480);expect(selectedAmounts({...quote,lines:[{...quote.lines[0],amount_minor:1}],assessment_fee_minor:0,policy:{...quote.policy,buyer_fee_bps:5000}},['required']).payable_minor).toBe(2);});
});

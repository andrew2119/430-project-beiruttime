import type { AssessedQuote, Amounts } from '@contracts/contracts-pricing/quotes/assessed';
export function selectedAmounts(quote:AssessedQuote,selected:string[]):Amounts{
 if(quote.policy.revision===1)return quote.decision?.amounts??quote.full_total;
 const lines=quote.lines.filter(line=>selected.includes(line.id));
 const parts=lines.filter(line=>line.kind==='part').reduce((sum,line)=>sum+line.amount_minor,0);
 const labor=lines.filter(line=>line.kind==='labor').reduce((sum,line)=>sum+line.amount_minor,0);
 const base=parts+labor+quote.assessment_fee_minor;
 const rate=(bps:number)=>Number((BigInt(base)*BigInt(bps)+5000n)/10000n);
 const commission=rate(quote.policy.business_fee_bps??quote.policy.seller_commission_bps);
 return {parts_minor:parts,labor_minor:labor,assessment_fee_minor:quote.assessment_fee_minor,platform_fee_minor:commission,seller_commission_minor:commission,seller_net_minor:base-commission,payable_minor:base};
}

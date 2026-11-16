import type { AssessedQuote } from '@contracts/contracts-pricing/quotes/assessed';
import { selectedAmounts } from './assessed-amounts';

export function quoteDecision(quote:AssessedQuote,action:'accept'|'decline',selected:string[],assessment:boolean,returnTransport:boolean){
 return {quote_revision:quote.revision,terms_digest:quote.terms_digest,accept_assessment_fee:assessment,accept_return_fee:returnTransport,
  ...(action==='accept'?{selected_line_ids:selected,payable_minor:selectedAmounts(quote,selected).payable_minor}:{})};
}
export function stableOperation(keys:Map<string,string>,payload:unknown,create:()=>string=()=>crypto.randomUUID()):string{
 const fingerprint=JSON.stringify(payload);
 if(!keys.has(fingerprint))keys.set(fingerprint,create());
 return keys.get(fingerprint)!;
}

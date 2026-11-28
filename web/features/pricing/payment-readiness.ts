import type { PlatformPaymentReadinessV3 } from '@contracts/contracts-pricing/quotes/current-v3';

type Binding=Pick<PlatformPaymentReadinessV3,'buyer_id'|'order_id'|'order_kind'|'watch_id'|'quote_id'|'quote_revision'|'currency'|'total_minor'>;
export function exactPaymentReadiness(proof:PlatformPaymentReadinessV3|null,binding:Binding):'ready'|'pending'|'unpaid'|'unavailable' {
  if(!proof)return 'unavailable';
  if((Object.keys(binding) as (keyof Binding)[]).some(key=>proof[key]!==binding[key])||
     proof.currency!=='USD'||!Number.isSafeInteger(proof.total_minor)||proof.total_minor<=0||
     !Number.isSafeInteger(proof.quote_revision)||proof.quote_revision<1||
     !Number.isSafeInteger(proof.payment_revision)||proof.payment_revision<0)return 'unavailable';
  if(proof.state==='pending'||proof.state==='unpaid')return proof.state;
  if(proof.state!=='paid_held'||!proof.payment_operation_id||proof.payment_revision<1)return 'unavailable';
  return 'ready';
}

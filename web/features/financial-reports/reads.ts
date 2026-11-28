import { numberFormatter } from '@beirut-time/ui/foundation';
import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { Report, ReportRequest, Totals } from '@contracts/contracts-orders/financial-reports';

export const totalKeys = ['gross','buyer_fee_collected','fee_collected','fee_owed','refund','net','payout'] as const;
const ref = /^[A-Za-z0-9_-]{1,100}$/;
const minor = (value:unknown, negative=false):value is number=>typeof value === 'number' && Number.isSafeInteger(value) && (negative || value >= 0);
export function validTotals(value:unknown):value is Totals {
  return !!value && typeof value === 'object' && totalKeys.every(key=>minor((value as Totals)[key],key === 'net'));
}
export function validateReport(value:Report, request:ReportRequest):Report {
  if (!value || value.schema_version !== 'financial-reports.v1' || value.operation_id !== request.operation_id || !['ready','pending','denied','stale','unavailable','drift'].includes(value.state)) throw new Error('Invalid report');
  if (value.state !== 'ready') {
    if (value.items !== undefined || value.totals !== undefined || value.trial_balance !== undefined) throw new Error('Invalid private state');
    return value;
  }
  if (value.actor_id !== request.actor_id || value.organization_id !== request.organization_id || value.subject_id !== request.subject_id || value.expected_revision !== request.expected_revision || value.revision !== request.expected_revision || value.currency !== 'USD' || value.simulated !== true || !minor(value.checkpoint) || !value.checked_at?.endsWith('Z') || !Number.isFinite(Date.parse(value.checked_at)) || !minor(value.total_count) || !validTotals(value.totals) || !Array.isArray(value.items) || value.items.length > request.page_size || value.page !== request.page || value.page_size !== request.page_size) throw new Error('Invalid report');
  const seen = new Set<string>();
  for (const row of value.items) {
    if (!validTotals(row) || !ref.test(row.order_id) || seen.has(row.order_id) || !ref.test(row.watch_id) || !ref.test(row.quote_id) || !ref.test(row.policy_revision) || !minor(row.revision) || !minor(row.quote_revision) || !row.occurred_at.endsWith('Z') || !Number.isFinite(Date.parse(row.occurred_at)) || (request.order_id !== null && row.order_id !== request.order_id)) throw new Error('Invalid receipt');
    seen.add(row.order_id);
  }
  if (request.view === 'operator') {
    if (!value.trial_balance || !Object.entries(value.trial_balance).every(([key,amount])=>ref.test(key) && minor(amount,true)) || Object.values(value.trial_balance).reduce((sum,amount)=>sum+amount,0) !== 0 || (value.take_rate !== null && (!value.take_rate || !minor(value.take_rate.numerator) || !minor(value.take_rate.denominator) || value.take_rate.denominator === 0))) throw new Error('Invalid reconciliation');
  } else if (value.trial_balance !== undefined || value.take_rate !== undefined) throw new Error('Invalid scope');
  return value;
}
export const reportsRead = definePageRead({
  key:(fingerprint:string,body:ReportRequest)=>['financial-reports.v1',fingerprint,JSON.stringify(body)],
  warm:'open-only',fresh:0,
  ask:async(signal:AbortSignal,fingerprint:string,body:ReportRequest)=>{
    const query = new URLSearchParams({request:JSON.stringify(body)});
    const answer = await authenticatedRequest<Report>(`/api/web/v1/orders/internal/v1/financial-reports?${query}`,{signal,accessFingerprint:fingerprint});
    return validateReport(answer,body);
  },
});
export function dollars(value:number,locale:'en'|'ar') {
  if (!minor(value,true)) throw new Error('Invalid amount');
  // Integer parts preserve every cent even at the safe integer limit.
  const whole = numberFormatter(locale,{useGrouping:true,maximumFractionDigits:0}).format(Math.floor(Math.abs(value)/100));
  const cents = numberFormatter(locale,{useGrouping:false,minimumIntegerDigits:2}).format(Math.abs(value)%100);
  return `${value < 0 ? '−' : ''}$${whole}.${cents}`;
}

/** Bounded request identities only; answers remain in the shared read cache. */
export class ReportIdentities {
  private requests=new Map<string,ReportRequest>();
  private clear=()=>{this.requests.clear();};
  constructor(private events:EventTarget) {events.addEventListener('bt:access-change',this.clear);}
  retain(fingerprint:string,draft:ReportRequest):ReportRequest {
    const key=JSON.stringify([fingerprint,{...draft,operation_id:null}]);
    const prior=this.requests.get(key);
    if (prior) return prior;
    if (this.requests.size>=1000) this.requests.delete(this.requests.keys().next().value!);
    this.requests.set(key,draft);
    return draft;
  }
  dispose() {this.clear();this.events.removeEventListener('bt:access-change',this.clear);}
}
let identities:ReportIdentities|undefined;
export function retainedReportRequest(fingerprint:string,draft:ReportRequest):ReportRequest {
  if (typeof window==='undefined') return draft;
  identities??=new ReportIdentities(window);
  return identities.retain(fingerprint,draft);
}

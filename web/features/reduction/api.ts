import type { ReductionCommand, ReductionContext, ReductionResult } from '@contracts/contracts-service/reduction/v1';
import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
export type Answer = {record:ReductionResult|null;context:ReductionContext};
const base='/api/web/v1/service-operations/v1/reduction';
export const recordRead=definePageRead({key:(record:string,organization:string,access:string)=>['reduction.v1',access,organization,record],warm:'open-only',fresh:0,
  ask:(signal:AbortSignal,record:string,organization:string,access:string)=>authenticatedRequest<Answer>(`${base}/records/${encodeURIComponent(record)}?organization_id=${encodeURIComponent(organization)}`,{signal,accessFingerprint:access})});
export function send(record:string,access:string,body:ReductionCommand) {
  return authenticatedRequest<ReductionResult>(`${base}/records/${encodeURIComponent(record)}/commands`,{method:'POST',accessFingerprint:access,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
export function validReference(value:string) {return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);}
export function measurement(value:string,unit:'cm'|'mm') {
  if(!/^[0-9]{1,3}(\.[0-9])?$/.test(value))return false;
  const tenths=Math.round(Number(value)*10)*(unit==='cm'?10:1);
  return tenths>=800&&tenths<=3500;
}

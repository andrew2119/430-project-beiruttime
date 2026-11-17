import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { Command, Evidence, History, Review } from '@contracts/contracts-eligibility/private-review';
const base = '/api/web/v1/eligibility/v1/private-reviews';
const url = (caseId:string) => `${base}/${encodeURIComponent(caseId)}`;
export const reviewRead = definePageRead({
  key: (access:string, caseId:string) => ['private-review-v1',access,caseId], warm:'open-only', fresh:0,
  ask: (signal:AbortSignal, access:string, caseId:string) => authenticatedRequest<Review>(url(caseId), {signal,accessFingerprint:access,cache:'no-store'}),
});
export const historyRead = definePageRead({
  key: (access:string, caseId:string, revision:number, page:number) => ['private-review-history-v1',access,caseId,revision,page], warm:'open-only', fresh:0,
  ask: (signal:AbortSignal, access:string, caseId:string, _revision:number, page:number) => authenticatedRequest<History>(`${url(caseId)}/history?page=${page}`, {signal,accessFingerprint:access,cache:'no-store'}),
});
export function sendCommand(access:string, command:Command) {
  return authenticatedRequest<Review>(`${url(command.case_id)}/commands`, {method:'POST',accessFingerprint:access,cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
}
export function readEvidence(access:string, caseId:string) {
  return authenticatedRequest<Evidence>(`${url(caseId)}/evidence`, {accessFingerprint:access,cache:'no-store'});
}

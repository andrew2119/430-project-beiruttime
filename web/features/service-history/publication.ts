import type { PublicationResult as BoundPublicationResult } from '@contracts/contracts-service/history';
import { authenticatedRequest } from '@/features/identity/session';
export type PublicationAttempt = {operation_id:string;expected_revision:number;job_ids:string[];watch:string};
export type PublicationResult = Pick<BoundPublicationResult,'state'|'operation_id'>;
export function publishSelection(fingerprint:string,attempt:PublicationAttempt,signal:AbortSignal) {
  const {watch,...body}=attempt;
  return authenticatedRequest<BoundPublicationResult>(`/api/web/v1/service-operations/v1/history/${encodeURIComponent(watch)}/publication`,{method:'POST',signal,accessFingerprint:fingerprint,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

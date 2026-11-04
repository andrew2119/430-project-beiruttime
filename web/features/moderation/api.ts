import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';

export type { CaseSummaryV1 as CaseSummary } from '@contracts/contracts-trust/moderation/v1';
import type { CaseSummaryV1 as CaseSummary } from '@contracts/contracts-trust/moderation/v1';
export type CaseDetail = CaseSummary & { evidence?:string; can_decide:boolean; can_appeal:boolean; review_signals:string[]; audit_older_available:boolean; last_action:string|null; delivery:string; preserve_transaction_duties:boolean; audit:{ kind:string; reason:string; revision:number; created_at:string }[] };
export type Queue = { id:string; route:string; state:'ready'|'empty'|'denied'|'unavailable'|'awaiting_prerequisite'; commands:boolean; items:{id:string;status:string;revision:number}[]; prerequisites:string[] };
export type { IntakeCommandV1 as IntakeBody } from '@contracts/contracts-service/intake/v1';
import type { IntakeCommandV1 as IntakeBody } from '@contracts/contracts-service/intake/v1';
export type IntakeSummary = { id:string; order_id:string; state:string; revision:number };
export type IntakeDetail = IntakeSummary & { private_record:Omit<IntakeBody,'order_id'|'custody_receipt_id'>; custody_receipt_id:string|null; custody_verification:'awaiting_intake'|'current'|'unconfirmed'|'unavailable'; diagnosis_allowed:boolean };

export function operationsRequest<T>(accessFingerprint:string, service:'trust'|'communications'|'service-operations',path:string,options:RequestInit={}) {
  // Identity fences both request admission and late responses to this view owner;
  // only the shared coordinator handles credentials and refresh.
  // A form/file read can outlive its keyed account or business view. Never let
  // that late continuation acquire the newly signed-in account's credentials.
  if(options.signal?.aborted)return Promise.reject(new ApiError(401,'session_changed',''));
  const headers=new Headers(options.headers);
  if(options.body) headers.set('Content-Type','application/json');
  return authenticatedRequest<T>(`/api/web/v1/${service}/v1/${path}`,{...options,headers,accessFingerprint});
}

export function mutation(method:string,key:string,body?:unknown,revision?:number,signal?:AbortSignal):RequestInit {
  return {method,signal,headers:{'Idempotency-Key':key,...(revision?{'If-Match':String(revision)}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})};
}

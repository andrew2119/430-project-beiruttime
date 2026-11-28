import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { WorkContext } from '@contracts/contracts-service/authorized-work/v1';
export const workRead = definePageRead({
  key:(fingerprint:string,subject:string)=>['authorized-work.v1',fingerprint,subject],
  ask:(signal:AbortSignal,fingerprint:string,subject:string)=>authenticatedRequest<WorkContext>(
    `/api/web/v1/service-operations/internal/v1/authorized-work/subjects/${encodeURIComponent(subject)}`,
    {signal,accessFingerprint:fingerprint}),
  warm:'open-only',fresh:0,
});

export type History = {items:{operation_id:string;kind:string;note:string;observed_at:string;next_action:string}[];total:number;next_offset:number|null;complete:boolean;release_eligible:false};
export const historyRead = definePageRead({
  key:(fingerprint:string,subject:string,offset:number)=>['authorized-work-history.v1',fingerprint,subject,offset],
  ask:(signal:AbortSignal,fingerprint:string,subject:string,offset:number)=>authenticatedRequest<History>(
    `/api/web/v1/service-operations/internal/v1/authorized-work/subjects/${encodeURIComponent(subject)}/observations?offset=${offset}`,
    {signal,accessFingerprint:fingerprint}),
  warm:'open-only',fresh:0,
});

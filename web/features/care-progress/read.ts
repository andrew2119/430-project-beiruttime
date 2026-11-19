import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { Progress } from './contracts';
export const progressRead = definePageRead({
  key:(subject:string,offset:number,fingerprint:string)=>['care-progress-v1',fingerprint,subject,offset],
  ask:(signal:AbortSignal,subject:string,offset:number,fingerprint:string)=>authenticatedRequest<Progress>(`/api/web/v1/service-operations/v1/progress/${encodeURIComponent(subject)}?offset=${offset}`,{signal,accessFingerprint:fingerprint}),
  warm:'open-only',fresh:0,
});

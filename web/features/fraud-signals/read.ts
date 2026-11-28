import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { SignalPage } from '@contracts/contracts-trust/fraud-signals/v1';
export const signalRead = definePageRead({
  key:(fingerprint:string,page:number)=>['fraud-signals.v1',fingerprint,page],
  warm:'open-only', fresh:0,
  ask:(signal:AbortSignal,fingerprint:string,page:number)=>authenticatedRequest<SignalPage>(
    `/api/web/v1/trust/v1/fraud-signals?page=${page}&page_size=20`,
    {signal,accessFingerprint:fingerprint})
});

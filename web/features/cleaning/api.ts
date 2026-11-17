import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { CleaningCommand, CleaningRead, CleaningResult } from '@contracts/contracts-service/cleaning/v1';
export const cleaningPath = '/api/web/v1/service-operations/v1/cleaning';
export const cleaningRead = definePageRead({
  key:(subject:string, access:string)=>['cleaning.v1',subject,access],
  warm:'open-only', fresh:0,
  ask:(signal:AbortSignal,subject:string,access:string)=>authenticatedRequest<CleaningRead>(`${cleaningPath}/requests/${encodeURIComponent(subject)}`,{signal,accessFingerprint:access}),
});
export function sendCleaning(command:CleaningCommand, access:string, signal:AbortSignal) {
  return authenticatedRequest<CleaningResult>(`${cleaningPath}/requests/${encodeURIComponent(command.subject_id)}`,{
    method:'POST',signal,accessFingerprint:access,headers:{'Content-Type':'application/json'},body:JSON.stringify(command),
  });
}
export function lookupCleaning(command:CleaningCommand, access:string, signal:AbortSignal) {
  return authenticatedRequest<{result:CleaningResult|null;state:'recorded'|'unknown'}>(`${cleaningPath}/operations/${command.operation_id}?subject_id=${encodeURIComponent(command.subject_id)}`,{signal,accessFingerprint:access});
}

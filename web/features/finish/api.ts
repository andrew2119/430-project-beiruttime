import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import { validateDetail, validateResult } from './model';
import type { Command } from '@contracts/contracts-service/finish';
export const base='/api/web/v1/service-operations/v1/finish';
export const finishRead=definePageRead({key:(subject:string,fingerprint:string)=>['finish.v1',subject,fingerprint],
  ask:async(signal:AbortSignal,subject:string,fingerprint:string)=>validateDetail(await authenticatedRequest<unknown>(`${base}/subjects/${encodeURIComponent(subject)}`,{signal,accessFingerprint:fingerprint}),subject),warm:'open-only',fresh:0});
export async function record(command:Command,fingerprint:string,signal:AbortSignal) {
  const result=await authenticatedRequest<unknown>(`${base}/consents`,{method:'POST',signal,accessFingerprint:fingerprint,
    headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
  return validateResult(result,command);
}

export async function lookup(command:Command,fingerprint:string,signal:AbortSignal) {
  return validateResult(await authenticatedRequest<unknown>(`${base}/subjects/${encodeURIComponent(command.subject_id)}/operations/${encodeURIComponent(command.operation_id)}`,{signal,accessFingerprint:fingerprint}),command);
}

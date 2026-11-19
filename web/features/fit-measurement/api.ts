import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { FitCommand, FitContext, FitRecord } from '@contracts/contracts-service/fit-measurement/v1';
export const base='/api/web/v1/service-operations/v1/fit-measurement';
export type Scope={subject_id:string;watch_id:string;organization_id:string};
export const contextKey=(scope:Scope,access:string)=>['fit-measurement.v1',access,scope.subject_id,scope.watch_id,scope.organization_id] as const;
function validRecord(record:FitRecord,scope:Scope):boolean {
  return Boolean(record && record.schema_version==='fit-measurement.v1' && record.state==='recorded' && record.final_fit_pass===false && record.source==='buyer_measured'
    && record.subject_id===scope.subject_id && record.watch_id===scope.watch_id && record.organization_id===scope.organization_id && record.actor_id===scope.subject_id
    && Number.isSafeInteger(record.revision) && record.revision>=1 && Number.isSafeInteger(record.source_revision) && record.source_revision>=1
    && Number.isSafeInteger(record.expected_revision) && record.expected_revision===record.revision-1
    && Number.isSafeInteger(record.circumference_mm) && record.circumference_mm>=80 && record.circumference_mm<=300
    && ['tape','string_and_ruler'].includes(record.method) && ['close','comfortable','loose'].includes(record.target)
    && typeof record.operation_id==='string' && /^[0-9a-f-]{36}$/i.test(record.operation_id)
    && typeof record.recorded_at==='string' && /(?:Z|\+00:00)$/.test(record.recorded_at) && Number.isFinite(Date.parse(record.recorded_at))
    && record.pending_reason===null && record.next_actor===null && record.next_review_at===null);
}
export function parseContext(answer:FitContext,scope:Scope):FitContext {
  if(!answer||answer.subject_id!==scope.subject_id||answer.watch_id!==scope.watch_id||answer.organization_id!==scope.organization_id||!Number.isSafeInteger(answer.source_revision)||answer.source_revision<1||!(answer.record===null||validRecord(answer.record,scope))) throw new ApiError(503,'unavailable','');
  return answer;
}
export async function readContext(scope:Scope,access:string,signal:AbortSignal) {
  return parseContext(await authenticatedRequest<FitContext>(`${base}/context?${new URLSearchParams(scope)}`,{accessFingerprint:access,signal}),scope);
}
export async function saveMeasurement(command:FitCommand,access:string,signal:AbortSignal) {
  const answer=await authenticatedRequest<FitRecord>(`${base}/records`,{method:'POST',accessFingerprint:access,signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
  if(!validRecord(answer,command)||answer.operation_id!==command.operation_id||answer.source_revision!==command.source_revision||answer.expected_revision!==command.expected_revision) throw new ApiError(503,'unavailable','');
  return answer;
}

export const contextRead=definePageRead({
  key:contextKey,
  ask:(signal:AbortSignal,scope:Scope,access:string)=>readContext(scope,access,signal),
  warm:'open-only',
  fresh:0,
});

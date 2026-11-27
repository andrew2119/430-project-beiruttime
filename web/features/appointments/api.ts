import type { Command, Visit } from '@contracts/contracts-service/appointments';
import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';

const base = '/api/web/v1/service-operations/v1/appointments';
export const visitRead = definePageRead({
  key:(fingerprint:string,id:string,organization:string)=>['appointments.v1',fingerprint,organization,id],
  ask:(signal:AbortSignal,fingerprint:string,id:string,organization:string)=>authenticatedRequest<Visit>(
    `${base}/${encodeURIComponent(id)}?organization_id=${encodeURIComponent(organization)}`,
    {signal,accessFingerprint:fingerprint}),
  warm:'open-only',fresh:0,
});
export function sendVisit(command:Command,fingerprint:string,signal:AbortSignal) {
  return authenticatedRequest<Visit>(`${base}/commands`,{method:'POST',signal,accessFingerprint:fingerprint,
    headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
}
export function findOperation(command:Command,fingerprint:string,signal:AbortSignal) {
  return authenticatedRequest<Visit>(`${base}/operations/${encodeURIComponent(command.operation_id)}?appointment_id=${encodeURIComponent(command.appointment_id)}&organization_id=${encodeURIComponent(command.organization_id)}`,
    {signal,accessFingerprint:fingerprint});
}

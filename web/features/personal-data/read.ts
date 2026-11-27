import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { DataPage, DataCommand, DataOperation } from '@contracts/contracts-identity/data-requests';
export const path = '/api/web/v1/identity/v1/data-requests';
export const personalDataRead = definePageRead({
  key:(fingerprint:string,page:number)=>['personal-data.v1',fingerprint,page], warm:'open-only', fresh:0,
  ask:(signal:AbortSignal,fingerprint:string,page:number)=>authenticatedRequest<DataPage>(`${path}?page=${page}&page_size=20`,{signal,accessFingerprint:fingerprint}),
});
export function submitDataRequest(fingerprint:string, command:DataCommand) {
  return authenticatedRequest<DataOperation>(path,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':command.operation_id},body:JSON.stringify(command)});
}
export function lookupDataRequest(fingerprint:string, operation:string) {
  return authenticatedRequest<DataOperation>(`${path}/operations/${encodeURIComponent(operation)}`,{accessFingerprint:fingerprint});
}

import type { Command } from '@contracts/contracts-orders/releases';
import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
import { operation, preview, restoredOperation } from './model';
const base = '/api/web/v1/orders/v1/releases';
const scope = (organization:string|null)=>organization ? '?organization_id='+encodeURIComponent(organization) : '';
export const releaseRead = definePageRead({
  key:(order:string,organization:string|null,fingerprint:string)=>['orders.releases.v1',fingerprint,organization,order],
  warm:'open-only',fresh:0,
  ask:async(signal,order:string,organization:string|null,fingerprint:string)=>preview(
    await authenticatedRequest<unknown>(base+'/'+encodeURIComponent(order)+scope(organization),{signal,accessFingerprint:fingerprint}),order,organization),
});
export async function submit(command:Command,fingerprint:string) {
  return operation(await authenticatedRequest<unknown>(base+scope(command.organization_id),{
    method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':command.operation_id},
    body:JSON.stringify(command),accessFingerprint:fingerprint,
  }),command);
}
export async function recover(command:Command,fingerprint:string) {
  return operation(await authenticatedRequest<unknown>(base+'/operations/'+encodeURIComponent(command.operation_id)+'/recover'+scope(command.organization_id),{
    method:'POST',accessFingerprint:fingerprint,
  }),command);
}

export const operationRead = definePageRead({
  key:(id:string,actor:string,organization:string|null,subject:string,fingerprint:string)=>['orders.releases.operation.v1',fingerprint,actor,organization,subject,id],
  warm:'open-only',fresh:0,
  ask:async(signal,id:string,actor:string,organization:string|null,subject:string,fingerprint:string)=>restoredOperation(
    await authenticatedRequest<unknown>(base+'/operations/'+encodeURIComponent(id)+scope(organization),{signal,accessFingerprint:fingerprint}),
    id,actor,organization,subject),
});

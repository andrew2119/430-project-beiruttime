import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
import type { AuditQuery, AuditResult, OperationResult, Source } from '@contracts/contracts-comms/audit-references';
const base = '/api/web/v1/communications/v1/audit-references';
export const auditRead = definePageRead({
  key:(scope:string,source:Source,query:AuditQuery)=>['audit-references.v1',scope,source,query],
  ask:(signal:AbortSignal,scope:string,source:Source,query:AuditQuery)=>{
    const params = new URLSearchParams({source});
    for (const [key,value] of Object.entries(query)) if (value !== undefined) params.set(key,String(value));
    return authenticatedRequest<AuditResult>(`${base}?${params}`,{signal,accessFingerprint:scope});
  },warm:'open-only',fresh:0,
});
export const operationRead = definePageRead({
  key:(scope:string,source:Source,organization:string,id:string,revision:number)=>['audit-operation.v1',scope,source,organization,id,revision],
  ask:(signal:AbortSignal,scope:string,source:Source,organization:string,id:string,revision:number)=>authenticatedRequest<OperationResult>(
    `${base}/operations/${encodeURIComponent(id)}?${new URLSearchParams({source,organization_id:organization,expected_revision:String(revision)})}`,{signal,accessFingerprint:scope}),
  warm:'open-only',fresh:0,
});

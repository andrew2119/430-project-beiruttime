import { request, ApiError } from '@/lib/api/client';
import { authenticatedRequest } from '@/features/identity/session';
import type { ConfigurePolicy, PolicySnapshot, PrebidCommand, PrebidOutcome } from '@contracts/contracts-auction/policy';
export const root='/api/web/v1/auction/v1';
export const readPolicy=(id:string,signal?:AbortSignal)=>request<PolicySnapshot>(`${root}/auctions/${encodeURIComponent(id)}/policy`,{signal});
export const savePolicy=(id:string,body:ConfigurePolicy,revision:number,key:string,owner:string,signal?:AbortSignal,organization='')=>authenticatedRequest<{status:string;policy:PolicySnapshot}>(`${root}/auctions/${encodeURIComponent(id)}/policy${organization?'?organization_id='+encodeURIComponent(organization):''}`,{method:'PATCH',accessFingerprint:owner,signal,headers:{'Content-Type':'application/json','If-Match':String(revision),'Idempotency-Key':key},body:JSON.stringify(body)});
export async function prebid(id:string,body:PrebidCommand,key:string,owner:string,signal?:AbortSignal):Promise<PrebidOutcome>{
  try { return await authenticatedRequest<PrebidOutcome>(`${root}/auctions/${encodeURIComponent(id)}/prebid-buy-now`,{method:'POST',accessFingerprint:owner,signal,headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)}); }
  catch(error){
    if(!(error instanceof ApiError)||error.status>=500){
      try{return await authenticatedRequest<PrebidOutcome>(`${root}/prebid-operations/${encodeURIComponent(key)}`,{accessFingerprint:owner,signal});}catch{/* Unknown stays pending with the same key. */}
    }
    throw error;
  }
}

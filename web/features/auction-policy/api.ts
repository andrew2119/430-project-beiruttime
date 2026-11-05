import { request } from '@/lib/api/client';
import { authenticatedRequest } from '@/features/identity/session';
import type { ConfigurePolicy, PolicySnapshot } from '@contracts/contracts-auction/policy';
export const root='/api/web/v1/auction/v1';
export const readPolicy=(id:string,signal?:AbortSignal)=>request<PolicySnapshot>(`${root}/auctions/${encodeURIComponent(id)}/policy`,{signal});
export const savePolicy=(id:string,body:ConfigurePolicy,revision:number,key:string,owner:string,signal?:AbortSignal,organization='')=>authenticatedRequest<{status:string;policy:PolicySnapshot}>(`${root}/auctions/${encodeURIComponent(id)}/policy${organization?'?organization_id='+encodeURIComponent(organization):''}`,{method:'PATCH',accessFingerprint:owner,signal,headers:{'Content-Type':'application/json','If-Match':String(revision),'Idempotency-Key':key},body:JSON.stringify(body)});

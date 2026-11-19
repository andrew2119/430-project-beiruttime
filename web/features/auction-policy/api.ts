import { request } from '@/lib/api/client';
import { authenticatedRequest } from '@/features/identity/session';
import type { PolicySnapshot, SellerPolicySnapshot, LegacyOperationSnapshot } from '@contracts/contracts-auction/policy';
export const root='/api/web/v1/auction/v1';
const current='/api/web/v1/auction/v2';
export const readPolicy=(id:string,signal?:AbortSignal)=>request<PolicySnapshot>(`${current}/auctions/${encodeURIComponent(id)}/policy`,{signal});
export const readSellerPolicy=(id:string,owner:string,signal?:AbortSignal,organization='')=>authenticatedRequest<SellerPolicySnapshot>(`${current}/seller/auctions/${encodeURIComponent(id)}/policy${organization?'?organization_id='+encodeURIComponent(organization):''}`,{accessFingerprint:owner,signal});
export const readLegacyOperation=(id:string,owner:string,signal?:AbortSignal)=>authenticatedRequest<{operation:LegacyOperationSnapshot|null}>(`${current}/auctions/${encodeURIComponent(id)}/my-prebid`,{accessFingerprint:owner,signal});

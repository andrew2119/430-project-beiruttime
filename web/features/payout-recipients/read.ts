'use client';
import type {QueryClient} from '@tanstack/react-query';
import {authenticatedRequest} from '@/features/identity/session';

export type Result={schema_version:1;state:'succeeded'|'denied'|'pending';revision:number;operation_id?:string|null;code?:string;subject_id:string;organization_id:string|null;method?:string;reference?:string;pending_reason?:string};
export type RecipientScope={owner:string;subject:string;organization:string|null};
export const root='/api/web/v1/orders/internal/v1/payout-recipients';
export function recipientRead(scope:RecipientScope){
 return {
  queryKey:['payout-recipients',scope.owner,scope.subject,scope.organization] as const,
  staleTime:30000,
  gcTime:300000,
  retry:false as const,
  queryFn:async ({signal}:{signal:AbortSignal})=>{
   const result=await authenticatedRequest<Result>(root,{signal,accessFingerprint:scope.owner});
   if(result.schema_version!==1||!Number.isSafeInteger(result.revision)||result.revision<0||
      result.subject_id!==scope.subject||result.organization_id!==scope.organization||
      !['succeeded','denied','pending'].includes(result.state))throw Error('invalid_recipient_response');
   return result;
  },
 };
}
// Called on focus, pointer intent or touch intent with the current private scope.
export function warmRecipient(client:QueryClient,scope:RecipientScope){
 return client.prefetchQuery(recipientRead(scope));
}

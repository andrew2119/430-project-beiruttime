'use client';
import {authenticatedRequest} from '@/features/identity/session';

// Compatibility boundary until the shared page/read exports are available.
export {PageLayout as PageFrame, PageHeader} from '@/shell/page-header';
export const cancellationRead = {
 scope: 'private',
 key: (access:string,subject:string,operation:string,organization:string|null) =>
  ['cancellations',access,subject,operation,organization] as const,
};
export function usePageRead(accessFingerprint:string){
 return <T>(url:string) => authenticatedRequest<T>(url,{
  method:'GET',cache:'no-store',accessFingerprint,
 });
}

import type { Inbox } from '@contracts/contracts-comms/inbox';
import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
export const inboxBase = '/api/web/v1/communications/v1/inbox';
export type NoticePreferences = {optional_enabled:boolean;revision:number};
export const inboxRead = definePageRead({
  key:(scope:string,cursor:string|null)=>['inbox',scope,'notices',cursor],
  ask:(signal:AbortSignal,scope:string,cursor:string|null)=>authenticatedRequest<Inbox>(inboxBase+(cursor?'?cursor='+encodeURIComponent(cursor):''),{signal,accessFingerprint:scope}),
  warm:'open-only',
});
export const noticePreferencesRead = definePageRead({
  key:(scope:string)=>['inbox',scope,'preferences'],
  ask:(signal:AbortSignal,scope:string)=>authenticatedRequest<NoticePreferences>(inboxBase+'/preferences',{signal,accessFingerprint:scope}),
  warm:'open-only',
});

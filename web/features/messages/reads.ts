import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { Conversation, ThreadPage, Thread } from '@contracts/contracts-comms/messages';
export const base = '/api/web/v1/communications/v1/messages';
export const threadRead = definePageRead({key:(cursor:number)=>['messages','threads',cursor],warm:'open-only',fresh:0,ask:(signal,cursor:number)=>authenticatedRequest<ThreadPage>(`${base}/threads?cursor=${cursor}&limit=20`,{signal})});
export const conversationRead = definePageRead({key:(id:string,cursor:number)=>['messages',id,cursor],warm:'open-only',fresh:0,ask:(signal,id:string,cursor:number)=>authenticatedRequest<Conversation>(`${base}/threads/${encodeURIComponent(id)}?cursor=${cursor}&limit=20`,{signal})});
export const statusRead = definePageRead({key:(id:string)=>['messages',id,'status'],warm:'open-only',fresh:0,ask:(signal,id:string)=>authenticatedRequest<{thread:Thread;blocked:string[]}>(`${base}/threads/${encodeURIComponent(id)}/status`,{signal})});
export const deliveryRead = definePageRead({key:(id:string)=>['messages',id,'delivery'],warm:'open-only',fresh:0,ask:(signal,id:string)=>authenticatedRequest<{items:{actor:string;value:string}[]}>(`${base}/threads/${encodeURIComponent(id)}/delivery`,{signal})});

import { definePageRead } from '@/lib/page-speed/definition';
import { authenticatedRequest } from '@/features/identity/session';
import type { FollowPage } from '@contracts/contracts-comms/seller-follows';
export const base = '/api/web/v1/communications/v1/seller-follows';
export type Notices = {items:{id:string;watch:string;occurred:string;sample:boolean;read_at:string|null;cleared_at:string|null;notice_revision:number}[];total:number;page:number;page_size:50};
export const followingRead = definePageRead({key:(scope:string,page:number)=>['seller-follows.v1',scope,page],ask:(signal,scope,page)=>authenticatedRequest<FollowPage>(`${base}?page=${page}`,{signal,accessFingerprint:scope}),warm:'open-only'});
export const noticesRead = definePageRead({key:(scope:string,page:number)=>['seller-publications.v1',scope,page],ask:(signal,scope,page)=>authenticatedRequest<Notices>(`${base}/notices?page=${page}`,{signal,accessFingerprint:scope}),warm:'open-only'});

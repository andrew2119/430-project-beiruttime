'use client';
import { authenticatedRequest } from '@/features/identity/session';
import type { DraftInput,RequestDraft,DraftReadiness,ConfigurationIntent,DraftPage } from '@contracts/contracts-catalog/request-drafts';
const root='/api/web/v1/catalog/v1';
export const draftApi={
  list:(signal?:AbortSignal,before:string|null=null)=>authenticatedRequest<DraftPage>(`${root}/request-drafts?limit=50${before?'&before='+encodeURIComponent(before):''}`,{signal}),
  get:(id:string,signal?:AbortSignal)=>authenticatedRequest<RequestDraft>(`${root}/request-drafts/${encodeURIComponent(id)}`,{signal}),
  readiness:(id:string,signal?:AbortSignal)=>authenticatedRequest<DraftReadiness>(`${root}/request-drafts/${encodeURIComponent(id)}/readiness`,{signal}),
  configuration:(id:string,revision:number,signal?:AbortSignal)=>authenticatedRequest<ConfigurationIntent>(`${root}/request-draft-configurations/${encodeURIComponent(id)}?revision=${revision}`,{signal}),
  catalogue:(kind:DraftInput['kind'],after:string|null,signal?:AbortSignal)=>authenticatedRequest<{status:string;data?:{items:Business[];next_after:string|null}}>(`${root}/request-draft-catalogue?purpose=${kind==='service'?'servicing':'customization'}${after?'&after='+encodeURIComponent(after):''}`,{signal}),
  save:(body:DraftInput,id:string|null,revision:number,key:string)=>authenticatedRequest<{status:'succeeded';draft:RequestDraft}>(`${root}/request-drafts${id?'/'+encodeURIComponent(id):''}`,{method:id?'PATCH':'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({...body,...(id?{expected_revision:revision}:{})})})
};
export type Business={id:string;name:string;kind?:string;sample_content?:boolean};
export type BusinessOption={id:string;label:string|{en:string;ar:string};dimension:string;available?:boolean};

import type { Context, Command, Result, Evidence } from '@contracts/contracts-trust/disputes/v1';
import { useEffect, useState } from 'react';
import { authenticatedRequest } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
const root='/api/web/v1/trust/v1/disputes';
export function request<T>(scope:string,path:string,options:RequestInit={}) {
 return authenticatedRequest<T>(root+path,{...options,accessFingerprint:scope});
}
export function subjectPath(subject:string,organization:string) {
 return `/${encodeURIComponent(subject)}${organization?`?organization_id=${encodeURIComponent(organization)}`:''}`;
}
export const disputeRead=definePageRead({key:(scope:string,subject:string,organization:string)=>['disputes.v1',scope,subject,organization],ask:(signal,scope:string,subject:string,organization:string)=>request<Context>(scope,subjectPath(subject,organization),{signal}),warm:'open-only',fresh:0});
export function send(scope:string,body:Command,signal:AbortSignal) {
 return request<Result>(scope,'/commands',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
export async function stage(scope:string,subject:string,organization:string,file:File,operation:string,signal:AbortSignal) {
 if(file.size<1||file.size>5000000||!['image/jpeg','image/png','application/pdf'].includes(file.type))throw new Error('evidence');
 const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
 const checksum=Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join('');
 return request<Evidence>(scope,`/evidence${subjectPath(subject,organization)}`,{method:'POST',signal,headers:{'Content-Type':file.type,'X-Content-SHA256':checksum,'Idempotency-Key':operation},body:file});
}

export function useDisputeResource(scope:string,selected:{subject:string;organization:string}|null) {
 const subject=selected?.subject??'',organization=selected?.organization??'';
 const [version,setVersion]=useState(0);
 const key=JSON.stringify([scope,subject,organization,version]);
 const [state,setState]=useState<{key:string;data?:Context;error?:unknown;pending:boolean}>({key:'',pending:false});
 useEffect(()=>{
  if(!subject)return;
  const controller=new AbortController();
  disputeRead(scope,subject,organization).ask(controller.signal).then(data=>{if(!controller.signal.aborted)setState({key,data,pending:false});},error=>{if(!controller.signal.aborted)setState({key,error,pending:false});});
  return ()=>controller.abort();
 },[scope,subject,organization,key,version]);
 const matched=state.key===key;
 return {data:matched?state.data:undefined,error:matched?state.error:undefined,isError:matched&&!!state.error,isPending:!!subject&&(!matched||state.pending),refetch:()=>setVersion(value=>value+1)};
}

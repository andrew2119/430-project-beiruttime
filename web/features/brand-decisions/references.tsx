'use client';
import Image from 'next/image';
import { useEffect, useState } from 'react';
import { Button, Skeleton } from '@beirut-time/ui';
import { requestBlob, ApiError } from '@/lib/api/client';
import { useSession, refreshSession } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import { readPrivatePng } from '@/features/brand-options/images';
export default function References({requestId,ids,organization}:{requestId:string;ids:string[];organization:string}){
 const session=useSession(),locale=useLocale(),[attempt,setAttempt]=useState(0);
 const scope=JSON.stringify([session?.access_fingerprint,requestId,organization,ids,attempt]);
 const[result,setResult]=useState<{scope:string;images:string[];failed:boolean}|null>(null);
 useEffect(()=>{
  if(!session||!ids.length)return;
  const controller=new AbortController(),token=session.access_token,fingerprint=session.access_fingerprint;
  const clear=()=>controller.abort();window.addEventListener('bt:access-change',clear);
  async function read(id:string){const path=`/api/web/v1/catalog/v1/customization-requests/${requestId}/references/${id}?organization_id=${encodeURIComponent(organization)}`;let blob:Blob;
   try{blob=await requestBlob(path,{signal:controller.signal,headers:{Authorization:`Bearer ${token}`}});}
   catch(e){if(!(e instanceof ApiError)||e.status!==401)throw e;const current=await refreshSession();if(current?.access_fingerprint!==fingerprint)throw new ApiError(401,'unauthorized','');blob=await requestBlob(path,{signal:controller.signal,headers:{Authorization:`Bearer ${current.access_token}`}});}
   return readPrivatePng(blob,controller.signal);
  }
  void Promise.all(ids.map(read)).then(images=>{if(!controller.signal.aborted)setResult({scope,images,failed:false});}).catch(()=>{if(!controller.signal.aborted)setResult({scope,images:[],failed:true});});
  return()=>{controller.abort();window.removeEventListener('bt:access-change',clear);};
 },[session,requestId,organization,ids,scope]);
 if(!ids.length)return null;
 const label=locale==='ar'?'المراجع الخاصة':'Private references',error=locale==='ar'?'تعذر تحميل المراجع الخاصة':'Private references unavailable';
 return <section aria-label={label}><h3>{label}</h3>{result?.scope===scope?result.failed?<><p role="status">{error}</p><Button variant="outline" onClick={()=>setAttempt(v=>v+1)}>{locale==='ar'?'إعادة المحاولة':'Retry'}</Button></>:<div className="bd-actions">{result.images.map((src,i)=><Image unoptimized key={ids[i]} src={src} className="bd-private-reference" width={120} height={120} alt={`${label} ${i+1}`}/>)}</div>:<Skeleton label={label}/>}</section>;
}

'use client';
import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState, refreshSession, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { BidiReference, Button, ButtonLink, Card, HeaderTabs, LoadingRows, Notice, Select, State } from '@beirut-time/ui';
import en from './s2-en.json';
import ar from './s2-ar.json';
export function useQuoteCopy(){ const locale=useLocale();return {locale,t:locale==='ar'?ar:en}; }
export function QuoteDesk({kind,children,refresh}:{kind:'offers'|'brand-quotes'|'repair-quotes';children:React.ReactNode;refresh?:()=>void}){
 const {locale,t}=useQuoteCopy();
 const titles={'offers':t.offers,'brand-quotes':t.brandQuotes,'repair-quotes':t.repairQuotes};
 return <PageLayout className="l14-desk"><PageHeader title={titles[kind]} count={t.intro} actions={refresh?[{id:'refresh',label:t.refresh,icon:RefreshCw,onSelect:refresh}]:[]} nav={<HeaderTabs nav label={t.review} value={kind} onChange={()=>{}} items={Object.entries(titles).map(([id,label])=>({id,label,href:`/${locale}/${id}`}))}/>}/>{children}</PageLayout>;
}
export function QuoteGate({children,next}:{children:React.ReactNode;next:string}){
 const session=useSession(),state=useSessionState(),{locale,t}=useQuoteCopy();
 if(session)return children;
 if(state==='restoring')return <Card><LoadingRows label={t.loading}/></Card>;
 return <Card><State kind={state==='unavailable'?'error':'empty'} title={t.signIn} body={state==='unavailable'?t.unavailable:t.signInBody}>{state==='unavailable'?<Button onClick={()=>void refreshSession().catch(()=>null)}>{t.retry}</Button>:<ButtonLink href={signInHref(next,locale)}>{t.signIn}</ButtonLink>}</State></Card>;
}
export function QuoteFailure({error,retry}:{error:unknown;retry?:()=>void}){
 const {t}=useQuoteCopy();if(!error)return null;const e=error instanceof ApiError?error:null;
 const invalid=error instanceof Error&&['invalidMoney','invalidFields'].includes(error.message);
 return <State kind="error" title={invalid?t.requiredFields:e?.status===403?t.denied:e?.status===409?t.conflict:t.unavailable} body={e?.status===422||invalid?t.requiredFields:t.noExecution}>{e?.requestId&&<p>{t.support}: <BidiReference>{e.requestId}</BidiReference></p>}{retry&&<Button variant="outline" onClick={retry}>{t.retry}</Button>}</State>;
}
export function useQuoteScope(){
 const session=useSession();const [organization,setOrganizationState]=useState(()=>{
  if(typeof window==='undefined')return '';const value=new URLSearchParams(window.location.search).get('organization_id')??'';
  return /^[a-f0-9-]{36}$/i.test(value)?value:'';
 });
 const setOrganization=(value:string)=>{const url=new URL(window.location.href);if(value)url.searchParams.set('organization_id',value);else url.searchParams.delete('organization_id');window.history.replaceState(window.history.state,'',url);setOrganizationState(value);};
 // Only non-secret scope goes in the URL. Money, decisions and operation
 // outcomes remain service-owned; no financial record enters browser storage.
 return {session,organization,setOrganization,scope:`${session?.access_fingerprint}:${organization}`,
  suffix:organization?`?organization_id=${encodeURIComponent(organization)}`:'',
  asBusiness:!!organization};
}
export function QuoteScope({value,onChange}:{value:string;onChange:(v:string)=>void}){
 const session=useSession(),{t}=useQuoteCopy();const orgs=session?.principal.organizations??[];
 return <label className="l14-scope">{t.scope}<Select aria-label={t.scope} value={value} onValueChange={onChange} options={[{value:'',label:t.personal},...orgs.map(id=>({value:id,label:`${t.business} · ${id.slice(0,8)}`}))]}/></label>;
}
export function SamplePolicy(){const {t}=useQuoteCopy();return <Notice>{t.sample}</Notice>;}
export const quoteBase='/api/web/v1/pricing/v1';
export function post(body:unknown,key:string):RequestInit{return {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)};}
export function expiry(value:string,locale:string){return new Date(value).toLocaleString(locale==='ar'?'ar-LB':'en-GB',{timeZone:'Asia/Beirut'});}

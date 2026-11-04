'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { useSession, refreshSession, signInHref } from '@/features/identity/session';
import { BidiReference, Button } from '@beirut-time/ui';
import en from './en.json';
import ar from './ar.json';
export function useCopy() { const locale=useLocale(); return {locale,t:locale==='ar'?ar:en}; }
export function Desk({children,title,intro,current}:{children:React.ReactNode;title:string;intro:string;current:'prices'|'inbox'|'buying'}) {
  const {locale,t}=useCopy();
  return <div className="l07"><header><p className="eyebrow">{t.eyebrow}</p><h1 tabIndex={-1}>{title}</h1><p>{intro}</p></header><nav className="l07-tabs" aria-label={t.eyebrow}>{(['prices','inbox'] as const).map(path=><Link key={path} href={`/${locale}/${path}`} className={`button ${current===path?'':'button-secondary'}`} aria-current={current===path?'page':undefined}>{path==='prices'?t.allQuotes:path==='inbox'?t.inbox:t.buying}</Link>)}</nav>{children}</div>;
}
export function PrivateGate({children,next}:{children:React.ReactNode;next:string}) {
  const session=useSession(),{locale,t}=useCopy();
  const [checked,setChecked]=useState(false),[restoreError,setRestoreError]=useState<unknown>(null);
  useEffect(()=>{if(session)return;let active=true;void refreshSession().then(()=>{if(active){setRestoreError(null);setChecked(true);}}).catch(error=>{if(active){setRestoreError(error);setChecked(true);}});return()=>{active=false;};},[session]);
  if(!session&&!checked) return <p role="status">{t.loading}</p>;
  if(!session) return <section className="card l07-stack"><h2>{t.signIn}</h2><p>{t.signInBody}</p><Link className="button" href={signInHref(next,locale)}>{t.signIn}</Link><Failure error={restoreError} retry={()=>{setRestoreError(null);setChecked(false);void refreshSession().then(()=>setChecked(true)).catch(error=>{setRestoreError(error);setChecked(true);});}}/></section>;
  return children;
}
export function Failure({error,retry}:{error:unknown;retry?:()=>void}) {
  const {locale,t}=useCopy();
  if(!error) return null;
  const e=error instanceof ApiError?error:null;
  const message=e?(e.code==='quote_expired'||e.code==='quote_binding_mismatch'?t.reviewCurrent:e.status===401?t.unauthorized:e.status===403?t.forbidden:e.status===409?t.conflict:e.status===422||e.status===400?t.checkFields:t.unavailable):error instanceof Error&&error.message==='invalidMoney'?t.invalidMoney:error instanceof Error&&error.message==='invalidReference'?t.invalidReference:t.unavailable;
  return <div role="alert" className="l07-error"><p>{message}</p>{e?.requestId&&<small>{t.support}: <BidiReference>{e.requestId}</BidiReference></small>}<div className="l07-actions">{e?.status===401?<Link className="button" href={signInHref('/prices',locale)}>{t.signIn}</Link>:retry&&<Button className="button-secondary" onClick={retry}>{t.retry}</Button>}</div></div>;
}
export function command(body:unknown,key:string,method='POST'):RequestInit { return {method,headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)}; }

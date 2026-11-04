'use client';
import { useEffect, useState } from 'react';
import { CreditCard, Inbox, ReceiptText } from 'lucide-react';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { LoadingRows, SectionState } from '@beirut-time/ui';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { useSession, refreshSession, signInHref } from '@/features/identity/session';
import { BidiReference, Button, ButtonLink, Card, HeaderTabs } from '@beirut-time/ui';
import en from './en.json';
import ar from './ar.json';
export function useCopy() { const locale=useLocale(); return {locale,t:locale==='ar'?ar:en}; }
export function Desk({children,title,intro,current}:{children:React.ReactNode;title:string;intro:string;current:'prices'|'inbox'|'buying'}) {
  const {locale,t}=useCopy();
  return <PageLayout className="l07"><PageHeader title={title} count={intro} tag={<span className="hx-tag">{t.eyebrow}</span>} nav={<WorkspaceTabs current={current} locale={locale} labels={{prices:t.allQuotes,inbox:t.inbox,buying:t.buying}} label={t.eyebrow}/>}/>{children}</PageLayout>;
}
/** The shared CP Pane tabs retain real locale-aware links and keyboard semantics. */
function WorkspaceTabs({current,locale,labels,label}:{current:'prices'|'inbox'|'buying';locale:string;labels:Record<'prices'|'inbox'|'buying',string>;label:string}) {
  const icons={prices:ReceiptText,inbox:Inbox,buying:CreditCard};
  return <HeaderTabs nav label={label} value={current} onChange={()=>{}} items={(['prices','inbox','buying'] as const).map(path=>({id:path,label:labels[path],icon:icons[path],href:`/${locale}/${path}`}))}/>;
}
export function PrivateGate({children,next}:{children:React.ReactNode;next:string}) {
  const session=useSession(),{locale,t}=useCopy();
  const [checked,setChecked]=useState(false),[restoreError,setRestoreError]=useState<unknown>(null);
  useEffect(()=>{if(session)return;let active=true;void refreshSession().then(()=>{if(active){setRestoreError(null);setChecked(true);}}).catch(error=>{if(active){setRestoreError(error);setChecked(true);}});return()=>{active=false;};},[session]);
  if(!session&&!checked) return <Card><LoadingRows label={t.loading}/></Card>;
  if(!session) return <Card className="l07-stack"><SectionState title={t.signIn} body={t.signInBody} kind="locked"><ButtonLink href={signInHref(next,locale)}>{t.signIn}</ButtonLink></SectionState><Failure error={restoreError} retry={()=>{setRestoreError(null);setChecked(false);void refreshSession().then(()=>setChecked(true)).catch(error=>{setRestoreError(error);setChecked(true);});}}/></Card>;
  return children;
}
export function Failure({error,retry}:{error:unknown;retry?:()=>void}) {
  const {locale,t}=useCopy();
  if(!error) return null;
  const e=error instanceof ApiError?error:null;
  const message=e?(e.code==='quote_expired'||e.code==='quote_binding_mismatch'?t.reviewCurrent:e.status===401?t.unauthorized:e.status===403?t.forbidden:e.status===409?t.conflict:e.status===422||e.status===400?t.checkFields:t.unavailable):error instanceof Error&&error.message==='invalidMoney'?t.invalidMoney:error instanceof Error&&error.message==='invalidReference'?t.invalidReference:t.unavailable;
  return <div role="alert" className="l07-error"><p>{message}</p>{e?.requestId&&<small>{t.support}: <BidiReference>{e.requestId}</BidiReference></small>}<div className="l07-actions">{e?.status===401?<ButtonLink href={signInHref('/prices',locale)}>{t.signIn}</ButtonLink>:retry&&<Button chonk size="sm" variant="outline" onClick={retry}>{t.retry}</Button>}</div></div>;
}
export function command(body:unknown,key:string,method='POST'):RequestInit { return {method,headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)}; }

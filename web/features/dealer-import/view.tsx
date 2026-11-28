'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button, ButtonLink, Card, Segmented, State, Textarea, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame as PageLayout, PageHeader } from '@/shell/foundation/page';
import { LocaleContext, useLocale } from '@/shell/locale-context';
import { authenticatedRequest, useSession } from '@/features/identity/session';
import type { ImportResult } from '@contracts/contracts-catalog/dealer-import';
import { copy } from './copy';
import { ApiError } from '@/lib/api/client';
import { recovery } from './recovery';
import { retainImportLanguage, type ImportLocale } from './language';

export function DealerImport() {
 const router=useRouter();
 const initialLocale=useLocale();
 const [locale,setLocale]=useState(initialLocale);
 const session=useSession(), organization=useSearchParams().get('organization_id') ?? '';
 const scope=(session?.access_fingerprint ?? '')+':'+organization;
 const changeLanguage=useCallback((next: ImportLocale, target?: URL) => {
  const url=target ?? new URL(window.location.href);
  url.pathname=url.pathname.replace(/^\/(en|ar)(?=\/)/, '/'+next);
  window.history.replaceState(window.history.state,'',url);
  document.documentElement.lang=next;
  document.documentElement.dir=next==='ar'?'rtl':'ltr';
  setLocale(next);
  router.refresh();
 },[router]);
 useEffect(()=>{
  function capture(event: MouseEvent) {
   const anchor=event.target instanceof Element ? event.target.closest('a[href]') : null;
   if(anchor instanceof HTMLAnchorElement)retainImportLanguage(event,new URL(window.location.href),anchor,changeLanguage);
  }
  document.addEventListener('click',capture,true);
  return ()=>document.removeEventListener('click',capture,true);
 },[changeLanguage]);
 return <LocaleContext value={locale}><div lang={locale} dir={locale==='ar'?'rtl':'ltr'}>
 <Segmented label={locale==='ar'?'اللغة':'Language'} locale={locale} value={locale} onValueChange={value=>{if(value==='en'||value==='ar')changeLanguage(value);}} options={[{value:'en',label:'English'},{value:'ar',label:'العربية'}]}/>
 <ImportForm key={scope} fingerprint={session?.access_fingerprint ?? ''} organization={organization}/>
 </div></LocaleContext>;
}
function ImportForm({fingerprint,organization}:{fingerprint:string;organization:string}) {
 const locale=useLocale(),t=copy[locale];
 const [text,setText]=useState(''),[operation,setOperation]=useState(''),[answer,setAnswer]=useState<ImportResult|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(false),[offset,setOffset]=useState(0);
 const flight=useRef(false);
 const root='/api/web/v1/catalog/v1/seller/imports', scope='?organization_id='+encodeURIComponent(organization);
 async function submit(nextOffset?:number) {
  if(flight.current)return;
  if(new TextEncoder().encode(text).length>1000000){setError(true);return;}
  flight.current=true;setBusy(true);setError(false);
  const key=operation||crypto.randomUUID();setOperation(key);
  try {
   const result=await authenticatedRequest<ImportResult>(nextOffset===undefined?root+scope:root+'/'+encodeURIComponent(key)+scope+'&offset='+nextOffset,{accessFingerprint:fingerprint,...(nextOffset===undefined?{method:'POST',headers:{'Content-Type':'text/csv','Idempotency-Key':key,'If-Match':'0'},body:text}:{})});
   setAnswer(result);setOffset(result.offset);
  }catch(cause){
   const action=recovery(cause instanceof ApiError?cause.status:undefined);
   if(action==='clear'){setAnswer(null);setText('');setOperation('');setOffset(0);}
   if(action==='correct'){setOperation('');}
   setError(true);
  }finally{flight.current=false;setBusy(false);}
 }
 return <PageLayout><PageHeader title={t.title} lead={t.intro}/><PageBody>
 {!fingerprint||!organization?<State kind="error" title={t.denied} body={t.intro}/>:<>
 <Textarea label={t.table} hint={t.help} value={text} onValueChange={setText} disabled={!!operation} rows={10}/>
 <Button disabled={busy||!text||!!answer} busy={busy} onClick={()=>void submit()}>{operation?t.retry:t.send}</Button>
 {operation&&!answer&&<State kind={error?'error':'loading'} title={error?t.error:t.pending} body={operation}><Button disabled={busy} onClick={()=>void submit()}>{t.retry}</Button></State>}
 {!operation&&<State title={t.empty} body={error?t.error:t.emptyBody}/>}
 {answer&&<><State title={t.registration} body={t.registrationBody}/><p className="bt-number">{t.total}: {formatNumber(answer.total,locale)}</p>
 {error&&<State kind="error" title={t.error} body={t.pending}/>}
 {answer.items.map(row=><Card key={row.row}><h2 className="bt-heading">{t.row} {formatNumber(row.row,locale)}</h2><p>{t[row.state]}</p>{row.listing_id&&<ButtonLink href={`/${locale}/seller/listings/${encodeURIComponent(row.listing_id)}?organization_id=${encodeURIComponent(organization)}`}>{t.open}</ButtonLink>}</Card>)}
 <Button disabled={busy||offset===0} onClick={()=>void submit(offset-50)}>{t.previous}</Button><Button disabled={busy||offset+50>=answer.total} onClick={()=>void submit(offset+50)}>{t.next}</Button>
 <Button disabled={busy} onClick={()=>{setAnswer(null);setOperation('');setText('');setError(false);setOffset(0);}}>{t.reset}</Button></>}
 </>}
 </PageBody></PageLayout>;
}

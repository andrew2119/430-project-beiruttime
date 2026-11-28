'use client';
import { flushSync } from 'react-dom';
import { printCurrent } from './print-current';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, ButtonLink, Card, RowSkeleton, Segmented, Select, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame as PageLayout, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { usePageRead } from '@/lib/page-speed/read';
import { useSession } from '@/features/identity/session';
import { ApiError, requestBlob } from '@/lib/api/client';
import type { Receipt, Report, ReportRequest } from '@contracts/contracts-orders/financial-reports';
import { ExportFence } from './export-fence';
import { copy, type Copy } from './copy';
import { dollars, reportsRead, retainedReportRequest, totalKeys } from './reads';
import './styles.css';

export type ReportScope = {actor_id:string;organization_id:string|null;subject_id:string;revision:number;operator:boolean;fingerprint:string};
/** The host supplies current selected scope and its shared read provider. */
export default function Receipts({scope,reloadAccess}:{scope:ReportScope|null;reloadAccess:()=>void}) {
  const locale=useLocale(),t=copy[locale],session=useSession();
  const current=scope && session?.access_fingerprint === scope.fingerprint && session.principal.actor.subject_id === scope.actor_id ? scope : null;
  return <PageLayout><PageHeader title={t.title} lead={t.lead}/><PageBody>{current ? <ScopedReports key={`${current.fingerprint}:${current.organization_id}:${current.subject_id}:${current.revision}`} scope={current} reloadAccess={reloadAccess}/> : <State title={t.scope} body={t.scopeBody}><Button onClick={reloadAccess}>{t.reload}</Button></State>}</PageBody></PageLayout>;
}
function ScopedReports({scope,reloadAccess}:{scope:ReportScope;reloadAccess:()=>void}) {
  const locale=useLocale(),t=copy[locale],session=useSession();
  const [printAnswer,setPrintAnswer]=useState<Report|null>(null);
  const [printState,setPrintState]=useState<'idle'|'loading'|'unavailable'>('idle');
  const [exportState,setExportState]=useState<'idle'|'loading'|'unavailable'>('idle');
  const exportFence=useRef<ExportFence|null>(null);
  useEffect(()=>{const fence=new ExportFence(window);exportFence.current=fence;return()=>{fence.dispose();if(exportFence.current===fence)exportFence.current=null;};},[]);
  const [page,setPage]=useState(1),[size,setSize]=useState(25),[order,setOrder]=useState<string|null>(null),[view,setView]=useState<'seller'|'operator'>('seller');
  const draft=useMemo<ReportRequest>(()=>({operation_id:crypto.randomUUID(),actor_id:scope.actor_id,organization_id:scope.organization_id,subject_id:scope.subject_id,expected_revision:scope.revision,page,page_size:size,order_id:order,view,action:order?'receipt':'read'}),[scope.actor_id,scope.organization_id,scope.subject_id,scope.revision,page,size,order,view]);
  const body=useMemo(()=>retainedReportRequest(scope.fingerprint,draft),[scope.fingerprint,draft]);
  const read=usePageRead(reportsRead(scope.fingerprint,body));
  const error=read.error instanceof ApiError ? read.error : null;
  const state=read.error ? error?.status===403 || error?.status===401 ? 'denied' : error?.status===409 ? 'stale' : 'unavailable' : read.data?.state;
  const answer=state==='ready'?read.data:undefined;
  const exportBody=useMemo(()=>({...body,operation_id:crypto.randomUUID(),page:1,action:'export' as const}),[body]);
  async function download() {
    if (!session || session.access_fingerprint!==scope.fingerprint) return;
    const fence=exportFence.current,controller=fence?.begin();if(!fence || !controller)return;
    setExportState('loading');
    try {
      const query=new URLSearchParams({request:JSON.stringify(exportBody),locale});
      const blob=await requestBlob(`/api/web/v1/orders/internal/v1/financial-reports/export?${query}`,{signal:controller.signal,headers:{Authorization:`Bearer ${session.access_token}`}});
      if(!fence.accepts(controller))return;
      if(blob.size>1048576 || !blob.type.startsWith('text/csv'))throw new Error('Invalid export');
      const url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='receipts.csv';link.click();URL.revokeObjectURL(url);setExportState('idle');
    } catch {if(fence.accepts(controller))setExportState('unavailable');}
    finally {fence.finish(controller);}
  }
  async function print() {
    const fence=exportFence.current;
    if (!fence || !session || session.access_fingerprint!==scope.fingerprint)return;
    setPrintState('loading');
    const printed=await printCurrent(fence,signal=>reportsRead(scope.fingerprint,body).ask(signal),body,fresh=>{
      flushSync(()=>setPrintAnswer(fresh));
      try {window.print();} finally {setPrintAnswer(null);}
    });
    setPrintState(printed?'idle':'unavailable');
  }
  function choosePage(value:number) {setPage(value);}
  const selectMessages={placeholder:t.select,filter:t.filter,emptyTitle:t.noOptions,emptyBody:t.noOptionsBody,close:t.close,loading:t.loading,errorTitle:t.unavailable,errorBody:t.unavailableBody,retry:t.retry};
  return <div className="financial-reports">
    {scope.operator && <Segmented label={t.view} value={view} onValueChange={value=>{setView(value==='operator'?'operator':'seller');setPage(1);setOrder(null);}} options={[{value:'seller',label:t.seller},{value:'operator',label:t.operator}]} locale={locale}/>}
    <Select label={t.size} value={String(size)} onValueChange={value=>{setSize(Number(value));setPage(1);}} options={[25,50].map(value=>({value:String(value),label:formatNumber(value,locale)}))} messages={selectMessages}/>
    {order && <Button onClick={()=>{setOrder(null);setPage(1);}}>{t.all}</Button>}
    {read.isPending && <div role="status" aria-label={t.loading}><RowSkeleton/><RowSkeleton/></div>}
    {state && state!=='ready' && <State kind={state==='pending'?'loading':'error'} title={t[state]} body={t[`${state}Body`]}><Button onClick={()=>state==='stale'?reloadAccess():void read.refetch()}>{state==='stale'?t.reload:t.retry}</Button><ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink></State>}
    {answer && <>
      {read.isFetching && <p role="status">{t.retained}</p>}
      <ReportContent answer={printAnswer??answer} locale={locale} onReceipt={id=>{setOrder(id);setPage(1);}}/>
      <div className="financial-actions">
        <Button disabled={read.isFetching || printState==='loading'} onClick={()=>void print()}>{t.print}</Button>
        <Button disabled={read.isFetching || exportState==='loading' || (answer.total_count??0)>1000} onClick={()=>void download()}>{exportState==='loading'?t.loading:t.export}</Button>
        <Button disabled={read.isFetching} onClick={()=>void read.refetch()}>{t.retry}</Button>
      </div>
      {printState==='unavailable' && <State kind="error" title={t.unavailable} body={t.unavailableBody}><Button onClick={()=>void print()}>{t.retry}</Button></State>}
      {exportState==='unavailable' && <State kind="error" title={t.unavailable} body={t.unavailableBody}><Button onClick={()=>void download()}>{t.retry}</Button></State>}
      {(answer.total_count??0)>1000 && <p>{t.exportLimit}</p>}
      <nav className="financial-actions" aria-label={t.page}><Button disabled={page===1 || read.isFetching} onClick={()=>choosePage(page-1)}>{t.previous}</Button><span className="bt-number">{t.page} {formatNumber(page,locale)}</span><Button disabled={page*size>=(answer.total_count??0) || read.isFetching} onClick={()=>choosePage(page+1)}>{t.next}</Button></nav>
    </>}
    <p className="financial-reference">{t.reference}: <bdi>{body.operation_id}</bdi></p>
  </div>;
}
export function ReportContent({answer,locale,onReceipt}:{answer:Report;locale:'en'|'ar';onReceipt:(id:string)=>void}) {
  const t=copy[locale];
  if(answer.state!=='ready' || !answer.totals || !answer.items)return null;
  return <div className="financial-print">
    <p>{t.simulated} · {t.notAuthority}</p>
    <p>{t.count}: <span className="bt-number">{formatNumber(answer.total_count??0,locale)}</span> · {t.checkpoint}: <bdi className="bt-number">{answer.checkpoint}</bdi></p>
    <Amounts value={answer.totals} t={t} locale={locale}/>
    {answer.items.length===0 && <State title={t.empty} body={t.emptyBody}/>}
    <div className="financial-receipts">{answer.items.map(row=><Card key={row.order_id}><ReceiptContent row={row} locale={locale}/><Button onClick={()=>onReceipt(row.order_id)}>{t.receipt}</Button></Card>)}</div>
    {answer.trial_balance && <Card><h2>{t.trial}</h2><dl className="financial-amounts">{Object.entries(answer.trial_balance).map(([account,amount])=><div key={account}><dt><bdi>{account}</bdi></dt><dd className="bt-number"><bdi>{dollars(amount,locale)}</bdi></dd></div>)}</dl><p>{t.take}: {answer.take_rate ? <bdi className="bt-number">{dollars(answer.take_rate.numerator,locale)} / {dollars(answer.take_rate.denominator,locale)}</bdi> : t.zero}</p></Card>}
  </div>;
}
function Amounts({value,t,locale}:{value:Receipt|NonNullable<Report['totals']>;t:Copy;locale:'en'|'ar'}) {
  return <dl className="financial-amounts">{totalKeys.map(key=><div key={key}><dt>{t[key]}</dt><dd className="bt-number"><bdi>{dollars(value[key],locale)}</bdi></dd></div>)}</dl>;
}
function ReceiptContent({row,locale}:{row:Receipt;locale:'en'|'ar'}) {
  const t=copy[locale];
  return <article><h2>{t.order} <bdi>{row.order_id}</bdi></h2><dl className="financial-details">
    <div><dt>{t.watch}</dt><dd><bdi>{row.watch_id}</bdi></dd></div>
    <div><dt>{t.quote}</dt><dd><bdi>{row.quote_id}</bdi> · {t.revision} <span className="bt-number">{formatNumber(row.quote_revision,locale)}</span></dd></div>
    <div><dt>{t.policy}</dt><dd><bdi>{row.policy_revision}</bdi></dd></div>
    <div><dt>{t.revision}</dt><dd className="bt-number">{formatNumber(row.revision,locale)}</dd></div>
    <div><dt>{t.time}</dt><dd><time dateTime={row.occurred_at}>{new Intl.DateTimeFormat(locale,{timeZone:'Asia/Beirut',dateStyle:'medium',timeStyle:'short'}).format(new Date(row.occurred_at))}</time></dd></div>
  </dl><Amounts value={row} t={t} locale={locale}/></article>;
}

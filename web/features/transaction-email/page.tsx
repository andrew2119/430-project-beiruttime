'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button, ButtonLink, RowSkeleton, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { usesFoundationShell } from '@/shell/foundation/path';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { replacePageQuery } from '@/lib/page-speed/address';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest, refreshSession, useSession, useSessionState } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { EmailRecord } from '@contracts/contracts-comms/transaction-email';
import { base, emailRead, operationRead, operationReference, safeDestination } from './reads';
import { copy } from './copy';
import { RecordCard } from './record';
import './styles.css';

function Records({scope}: {scope:string}) {
  const locale = useLocale(), t = copy[locale], search = useSearchParams(), router = useRouter();
  const currentLocale = useRef(locale);
  useEffect(()=>{currentLocale.current = locale;},[locale]);
  const requested = search.get('operation_id'), operation = operationReference(requested);
  const rawOffset = Number(search.get('offset') ?? 0), offset = Number.isInteger(rawOffset) && rawOffset >= 0 && rawOffset <= 100000 ? rawOffset : 0;
  const list = usePageRead(requested === null ? emailRead(scope, offset) : null);
  const detail = usePageRead(operation ? operationRead(scope, operation) : null);
  const [opening, setOpening] = useState(false), [openError, setOpenError] = useState(false), flight = useRef(false);
  const query = requested === null ? list : detail;
  const error = query.error, denied = error instanceof ApiError && [401,403,404,409].includes(error.status);
  const records = requested === null ? list.data?.items : detail.data ? [detail.data] : undefined;
  async function open(record:EmailRecord) {
    if (flight.current) return;
    flight.current = true; setOpening(true); setOpenError(false);
    try {
      const result = await authenticatedRequest<{url:string}>(`${base}/operations/${record.operation_id}/destination`, {method:'POST', accessFingerprint:scope});
      if (!safeDestination(result.url)) throw new Error('unavailable');
      router.push(`/${currentLocale.current}${result.url}`);
    } catch { setOpenError(true); }
    finally { flight.current = false; setOpening(false); }
  }
  async function refresh() {const result = await query.refetch(); if (!result.isError) setOpenError(false);}
  const move = (next:number)=>{setOpenError(false); replacePageQuery({offset:String(next)});};
  return <PageFrame><PageHeader title={t.title} lead={t.intro} count={list.data && !error && !openError ? `${t.total}: ${formatNumber(list.data.total,locale)}` : undefined}
    actions={<Button variant="outline" busy={query.isFetching} onClick={()=>void refresh()}>{t.refresh}</Button>}/><PageBody>
    {requested !== null && <ButtonLink href={`/${locale}/notification-email`}>{t.back}</ButtonLink>}
    {requested !== null && !operation ? <State kind="error" title={t.invalid} body={t.invalidBody}/> : openError ? <State kind="error" title={t.denied} body={t.deniedBody}><Button onClick={()=>void refresh()}>{t.retry}</Button></State> : error ? <State kind="error" title={denied?t.denied:t.error} body={denied?t.deniedBody:t.errorBody}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State> : records ? <AnswerArrival view="transaction-email"><div className="transaction-email-records">
      {records.length ? records.map(record=><RecordCard key={record.operation_id} record={record} locale={locale} opening={opening} open={()=>void open(record)}/>) : <State title={t.empty} body={t.emptyBody}/>}
      {requested === null && list.data && <nav aria-label={t.title} className="transaction-email-pagination"><Button variant="outline" disabled={offset===0||query.isFetching} onClick={()=>move(Math.max(0,offset-20))}>{t.previous}</Button><Button variant="outline" disabled={offset+20>=list.data.total||query.isFetching} onClick={()=>move(offset+20)}>{t.next}</Button></nav>}
    </div></AnswerArrival> : <div role="status" aria-label={t.loading} aria-busy="true"><RowSkeleton/><RowSkeleton/></div>}
    {opening && <p role="status" className="bt-text">{t.opening}</p>}

    <ButtonLink href={`/${locale}/inbox`}>{locale==='ar'?'فتح الصندوق الخاص':'Open private inbox'}</ButtonLink>
  </PageBody></PageFrame>;
}
export default function TransactionEmailPage() {
  const session = useSession(), state = useSessionState(), locale = useLocale(), t = copy[locale];
  if (!usesFoundationShell('/notification-email')) return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody><State kind="error" title={t.error} body={t.errorBody}><Button onClick={()=>window.location.reload()}>{t.retry}</Button><ButtonLink href={`/${locale}/inbox`}>{locale==='ar'?'فتح الصندوق الخاص':'Open private inbox'}</ButtonLink></State></PageBody></PageFrame>;
  if (session) return <Records key={session.access_fingerprint} scope={session.access_fingerprint}/>;
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>{state==='restoring' ? <div role="status" aria-label={t.loading}><RowSkeleton/></div> : <State kind="error" title={state==='unavailable'?t.error:t.denied} body={state==='unavailable'?t.errorBody:t.deniedBody}><ButtonLink href={`/${locale}/account`}>{t.signIn}</ButtonLink><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></State>}</PageBody></PageFrame>;
}

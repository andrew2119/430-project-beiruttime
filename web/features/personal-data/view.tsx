'use client';
import { useEffect, useRef, useState } from 'react';
import { Badge, Button, ButtonLink, Card, Dialog, DialogContent, DialogTrigger, Segmented, Skeleton, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame as PageLayout, PageBody, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState } from '@/features/identity/session';
import { requestBlob, ApiError } from '@/lib/api/client';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { domains, type DataCommand, type DataOperation, type RequestKind } from '@contracts/contracts-identity/data-requests';
import { personalDataRead, submitDataRequest, lookupDataRequest } from './read';
import { copy } from './copy';

type Copy = typeof copy.en | typeof copy.ar;
export default function PersonalDataView() {
  const session = useSession(), sessionState = useSessionState(), locale = useLocale(), t = copy[locale];
  return <PageLayout><PageHeader title={t.title} lead={t.intro}/><PageBody>
    {!session ? <State title={sessionState === 'restoring' ? t.loading : t.unavailable} body={t.signin} kind={sessionState === 'restoring' ? 'loading' : 'error'}><ButtonLink href={`/${locale}/account`}>{t.signIn}</ButtonLink></State> : <Requests key={session.access_fingerprint} fingerprint={session.access_fingerprint} accessToken={session.access_token}/>}
  </PageBody></PageLayout>;
}
export function Requests({fingerprint,accessToken}:{fingerprint:string;accessToken:string}) {
  const locale = useLocale(), t = copy[locale];
  const [kind,setKind] = useState<RequestKind>('export'), [page,setPage] = useState(0), [open,setOpen] = useState(false);
  const [busy,setBusy] = useState(false), [error,setError] = useState<unknown>(null), [current,setCurrent] = useState<DataOperation|null>(null);
  const [command,setCommand] = useState<DataCommand|null>(null);
  const flight = useRef(false);
  const [quarantined,setQuarantined] = useState(false);
  const downloadController = useRef<AbortController|null>(null);
  useEffect(()=>()=>downloadController.current?.abort(),[]);
  const query = usePageRead(personalDataRead(fingerprint,page),{keep:true});
  const denied = (error instanceof ApiError && [401,403].includes(error.status)) || (query.error instanceof ApiError && [401,403].includes(query.error.status));
  if (denied && !quarantined) setQuarantined(true);
  async function refreshAccess() {
    setCurrent(null);
    const result = await query.refetch();
    if (result.isSuccess) {setQuarantined(false); setError(null);}
  }
  async function run(lookup=false) {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError(null);
    const pending = command ?? {schema_version:'data-requests.v1' as const,operation_id:crypto.randomUUID(),kind,expected_revision:0 as const};
    setCommand(pending);
    try {
      const result = lookup ? await lookupDataRequest(fingerprint,pending.operation_id) : await submitDataRequest(fingerprint,pending);
      setCurrent(result); setCommand(null); setOpen(false); await query.refetch();
    } catch (failure) {setError(failure);} finally {flight.current = false; setBusy(false);}
  }
  async function download(operation:DataOperation) {
    if (flight.current) return;
    flight.current=true; setBusy(true); setError(null);
    const controller=new AbortController(); downloadController.current=controller;
    try {
      await lookupDataRequest(fingerprint,operation.operation_id);
      if (controller.signal.aborted) return;
      const blob=await requestBlob(`/api/web/v1/identity/v1/data-requests/operations/${encodeURIComponent(operation.operation_id)}/export`,{signal:controller.signal,headers:{Authorization:`Bearer ${accessToken}`}});
      if (controller.signal.aborted) return;
      if (blob.size > 25*1024*1024) throw new ApiError(413,'limit','');
      const url=URL.createObjectURL(blob), link=document.createElement('a');
      link.href=url; link.download='personal-data.zip'; link.click(); URL.revokeObjectURL(url);
    } catch (failure) {if (!controller.signal.aborted) setError(failure);} finally {flight.current=false; setBusy(false);}
  }
  if (denied || quarantined) return <State title={t.denied} body={t.deniedBody} kind="error"><Button onClick={()=>void refreshAccess()}>{t.retry}</Button></State>;
  return <>
    <Card><p>{t.policy}</p><Segmented label={t.kind} locale={locale} value={kind} disabled={busy || command !== null} onValueChange={value=>setKind(value as RequestKind)} options={[{value:'export',label:t.export},{value:'delete',label:t.delete}]}/>
      {kind === 'delete' && !command ? <Dialog open={open} onOpenChange={setOpen}><DialogTrigger>{t.submit}</DialogTrigger><DialogContent title={t.confirm} description={t.confirmBody} closeLabel={t.close}><Button disabled={busy} onClick={()=>void run()}>{t.confirm}</Button></DialogContent></Dialog> : <Button disabled={busy} onClick={()=>void run()}>{busy?t.pending:t.submit}</Button>}
      {command && <><p>{t.reference}: <bdi>{command.operation_id}</bdi></p><Button disabled={busy} onClick={()=>void run(true)}>{t.lookup}</Button></>}
      {error != null && <Failure error={error} t={t}/>}
    </Card>
    {current && <DataRecord operation={current} t={t} locale={locale} busy={busy} onDownload={download}/>}
    <h2>{t.history}</h2>
    {query.isPending && <State title={t.loading} body={t.intro} kind="loading"><Skeleton size="card"/></State>}
    {query.error && <><Failure error={query.error} t={t}/><Button onClick={()=>void query.refetch()}>{t.retry}</Button></>}
    {query.data && <AnswerArrival view="personal-data"><p>{t.total}: {formatNumber(query.data.total,locale)}</p>
      {query.data.items.length === 0 ? <State title={t.empty} body={t.emptyBody}/> : query.data.items.map(operation=><DataRecord key={operation.operation_id} operation={operation} t={t} locale={locale} busy={busy} onDownload={download}/>)}
      <Button disabled={page === 0 || query.isFetching} onClick={()=>setPage(value=>value-1)}>{t.previous}</Button>
      <Button disabled={query.isFetching || (page+1)*20 >= query.data.total} onClick={()=>setPage(value=>value+1)}>{t.next}</Button>
    </AnswerArrival>}
    <Card><h2>{t.support}</h2><p>{t.supportBody}</p><ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink></Card>
  </>;
}
function Failure({error,t}:{error:unknown;t:Copy}) {
  const code = error instanceof ApiError ? error.code : 'unavailable';
  const known = code === 'stale' || code === 'conflict' || code === 'invalid' || code === 'limit' ? code : 'unavailable';
  const body = known === 'unavailable' ? t.recovery : t[`${known}Body`];
  return <State kind="error" title={t[known]} body={body}/>;
}
export function DataRecord({operation,t,locale,busy,onDownload}:{operation:DataOperation;t:Copy;busy:boolean;onDownload:(operation:DataOperation)=>void;locale:'en'|'ar'}) {
  function date(value:string|null) {
    if (!value || !Number.isFinite(Date.parse(value))) return t.unknown;
    return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-LB-u-nu-arab' : 'en-US-u-nu-latn',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(value));
  }
  return <Card><h3>{t[operation.kind]}</h3><Badge>{t[operation.state]}</Badge><p>{t.reference}: <bdi>{operation.operation_id}</bdi></p><p>{t.revision}: {formatNumber(operation.revision,locale)}</p><p>{t.due}: {date(operation.due_at)}</p>
    {operation.next_review_at && <p>{t.review}: {date(operation.next_review_at)}</p>}
    <dl>{domains.map(domain=>{const receipt=operation.domains[domain];return <div key={domain}><dt>{t[domain]}</dt><dd>{receipt?t[receipt.state]:t.waiting}{receipt?.reasons.map(reason=><p key={reason}>{t[reason]}</p>)}</dd></div>;})}</dl>
    {operation.next_action && <p>{t.nextAction}: {t[operation.next_action]}</p>}
    <p>{t.support}: <bdi>{operation.responsible_operator_id}</bdi></p><p>{t.responseDue}: {date(operation.support_due_at)}</p><p>{t.escalation}: {date(operation.escalation_at)}</p>
    {operation.export_available && <Button disabled={busy} onClick={()=>onDownload(operation)}>{t.download}</Button>}
    {operation.kind === 'export' && <p>{operation.export_available ? `${t.expires}: ${date(operation.export_expires_at)}` : t.expired}</p>}
  </Card>;
}

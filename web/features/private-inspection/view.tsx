'use client';
import { useRef, useState } from 'react';
import { Button, ButtonLink, Checkbox, formatNumber, Input, Segmented, State, Textarea } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { usesFoundationShell } from '@/shell/foundation/path';
import { useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { copy } from './copy';
import { deriveResult, inspectionRead, submitInspection, type Command, type Receipt, type Verdict, type Workspace, sameWorkspace } from './api';

const items = ['identity','movement','case','provenance'] as const;
const reference = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function InspectionUnavailable() {
  const locale = useLocale(), t = copy[locale];
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    <State title={t.unavailable} body={t.routeUnavailable}><ButtonLink href={`/${locale}/account`}>{t.account}</ButtonLink></State>
  </PageBody></PageFrame>;
}

export default function InspectionView() {
  const locale = useLocale(), t = copy[locale], session = useSession(), status = useSessionState();
  if (session && !usesFoundationShell('/operations/inspections')) return <InspectionUnavailable/>;
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    {session ? <RecordLookup key={session.access_fingerprint} access={session.access_fingerprint}/> : status === 'restoring' ? <PageLoading label={t.loading}/> :
      <State title={status === 'unavailable' ? t.unavailable : t.signIn} body={status === 'unavailable' ? t.unavailableBody : t.signInBody}>
        {status === 'unavailable' ? <Button onClick={()=>{void refreshSession().catch(()=>{});}}>{t.retry}</Button> : <ButtonLink href={`/${locale}/account`}>{t.account}</ButtonLink>}
      </State>}
  </PageBody></PageFrame>;
}

function RecordLookup({access}:{access:string}) {
  const locale = useLocale(), t = copy[locale];
  const [typed,setTyped] = useState(''), [subject,setSubject] = useState(''), [blocked,setBlocked] = useState(false);
  const read = usePageRead(subject ? inspectionRead(access,subject) : null);
  const invalid = !!typed && !reference.test(typed);
  const denied = read.error instanceof ApiError && [401,403].includes(read.error.status);
  return <>
    {blocked && <State kind="error" title={t.denied} body={t.deniedBody}/>}
    <form onSubmit={event=>{event.preventDefault();if(!subject && reference.test(typed)){setBlocked(false);setSubject(typed);}}}>
      <Input label={t.subject} value={typed} onValueChange={setTyped} disabled={!!subject} error={invalid?t.invalid:undefined} required/>
      <Button type="submit" disabled={invalid || !typed || !!subject}>{t.open}</Button>
    </form>
    {!subject ? <State title={t.empty} body={t.emptyBody}/> : <>
      {!!read.error && <State kind="error" title={denied?t.denied:t.unavailable} body={denied?t.deniedBody:t.unavailableBody}><Button onClick={()=>{void read.refetch();}}>{t.retry}</Button></State>}
      {!denied && read.data ? <InspectionForm key={subject} access={access} workspace={read.data} deny={()=>{setBlocked(true);setSubject('');setTyped('');}} available={!read.error && !read.isFetching} exit={()=>{setSubject('');setTyped('');}} refresh={()=>{void read.refetch();}}/> :
        read.isPending ? <PageLoading label={t.loading}/> : !read.error ? <State title={t.empty} body={t.emptyBody}/> : null}
      {(denied || (!read.data && !read.isPending)) && <Button onClick={()=>{setSubject('');setTyped('');}}>{t.newRecord}</Button>}
    </>}

  </>;
}

export function InspectionForm({access,workspace,available,refresh,exit,deny}:{access:string;workspace:Workspace;available:boolean;refresh:()=>void;exit:()=>void;deny:()=>void}) {
  const locale = useLocale(), t = copy[locale];
  const [checks,setChecks] = useState<Verdict[]>(items.map(()=>'inconclusive'));
  const [reason,setReason] = useState(''), [evidence,setEvidence] = useState(false);
  const [pending,setPending] = useState(false), [error,setError] = useState<unknown>(), [receipt,setReceipt] = useState<Receipt>();
  const [operation,setOperation] = useState<Command|null>(null);
  const [reviewed,setReviewed] = useState(workspace);
  const changed = !sameWorkspace(reviewed,workspace);
  const busy = useRef(false);
  const definitive = error instanceof ApiError && [400,403,409,413,422].includes(error.status);
  async function send() {
    if(busy.current || (!operation && (!available || changed)))return;
    const {current_state: _current, ...binding} = reviewed;
    void _current;
    const payload = operation ?? {...binding,operation_id:crypto.randomUUID(),checklist:items.map((item,index)=>({item,verdict:checks[index]})),result:deriveResult(checks),reason};
    setOperation(payload);
    busy.current=true;setPending(true);setError(undefined);
    try {setReceipt(await submitInspection(access,payload));}
    catch(failure) {if(failure instanceof ApiError && [401,403].includes(failure.status)){deny();return;}setError(failure);}
    finally {busy.current=false;setPending(false);}
  }
  if(receipt)return <State title={t.saved} body={t.savedBody}><p>{t[receipt.state]}</p><p>{t.reference}: <bdi>{receipt.operation_id}</bdi></p><Button onClick={()=>{setReceipt(undefined);setOperation(null);refresh();}}>{t.refresh}</Button><Button onClick={exit}>{t.newRecord}</Button></State>;
  return <form onSubmit={event=>{event.preventDefault();void send();}} aria-busy={pending}>
    <Button type="button" onClick={exit} disabled={!!operation}>{t.newRecord}</Button>
    <p>{t.caution}</p>
    {workspace.current_state && <p role="status">{t.current}: {t[workspace.current_state]}</p>}
    {changed && !operation && <State title={t.stale} body={t.reviewChanged}><Button type="button" disabled={!available} onClick={()=>{setReviewed(workspace);setChecks(items.map(()=>'inconclusive'));setReason('');setEvidence(false);}}>{t.reviewAgain}</Button></State>}
    {items.map((item,index)=><div key={item}><p>{t[item]}</p><Segmented locale={locale} label={t[item]} value={checks[index]} disabled={!!operation || changed}
      options={(['passed','failed','inconclusive'] as const).map(value=>({value,label:t[value]}))}
      onValueChange={value=>setChecks(previous=>previous.map((entry,i)=>i===index?value as Verdict:entry))}/></div>)}
    <Textarea label={t.reason} value={reason} onValueChange={value=>setReason(value.slice(0,2000))} required disabled={!!operation || changed}/>
    <p>{t.evidenceCount}: {formatNumber(reviewed.evidence_refs.length,locale)}</p>
    <Checkbox label={t.evidence} checked={evidence} onCheckedChange={setEvidence} disabled={!!operation || changed}/>
    {!reviewed.evidence_refs.length && <p role="status">{t.missing}</p>}
    {operation && <p>{t.reference}: <bdi>{operation.operation_id}</bdi></p>}
    {(pending || !!error) && <p role={error?'alert':'status'}>{definitive?t.stale:t.pending}</p>}
    {definitive ? <Button type="button" onClick={()=>{setOperation(null);setError(undefined);refresh();}}>{t.refresh}</Button> :
      <Button type="submit" disabled={pending || (!operation && (!available || changed || !reason.trim() || !evidence || !reviewed.evidence_refs.length))}>{error?t.retryAction:t.submit}</Button>}
  </form>;
}

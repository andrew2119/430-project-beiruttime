'use client';
import { useRef, useState } from 'react';
import { Button, ButtonLink, Card, Input, Select, State, formatAmount, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { signInHref, useSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { enlargementRead, submit, type RecordView } from './api';
import { Actions, emptyActionDraft, type ActionDraft } from './actions';
import { PendingOperation } from './pending';
import en from './en.json';
import ar from './ar.json';
import './styles.css';

export default function Enlargement() {
  const session = useSession();
  return <Content key={session?.access_fingerprint ?? 'signed-out'} signedIn={Boolean(session)}/>;
}
function Content({signedIn}:{signedIn:boolean}) {
  const locale = useLocale(), t = locale === 'ar' ? ar : en;
  const [draft,setDraft] = useState({watch:'',business:'',sourceRevision:'',measurement:'',unit:'cm',method:'',source:'',target:'',choice:'links'});
  const [opened,setOpened] = useState(''), [lookup,setLookup] = useState('');
  const read = usePageRead(signedIn && opened ? enlargementRead(opened) : null);
  const [answer,setAnswer] = useState<RecordView|null>(null);
  const [status,setStatus] = useState('');
  const [actionPending,setActionPending] = useState<object|null>(null);
  const [actionError,setActionError] = useState('');
  const [actionDrafts,setActionDrafts] = useState<Record<string,ActionDraft>>({});
  const actionOperation=useRef(new PendingOperation());
  async function submitAction(body:object) {
    if (actionOperation.current.busy) return;
    setActionPending(actionOperation.current.body ?? body);setActionError('');
    try {
      const result=await actionOperation.current.run(body,submit);
      if (!result) return;
      setAnswer(result);setOpened(result.request_id);setActionPending(null);
      void read.refetch();
    } catch(error) {
      if(error instanceof ApiError && [400,403,409,422].includes(error.status)) {actionOperation.current.clear();setActionPending(null);}
      setActionError(error instanceof ApiError && error.status===403?'denied':error instanceof ApiError && error.status===409?'stale':error instanceof ApiError && error.status===422?'invalid':'actionPending');
    }
  }
  const [busy,setBusy] = useState(false);
  const [reference,setReference] = useState<{operation:string;request:string}|null>(null);
  const pending = useRef<{body:object;operation:string;request:string}|null>(null);
  const record = read.data && (!answer || read.data.revision >= answer.revision) ? read.data : answer;
  const actionKind=record?.allowed_operations?.find(value=>['assess','accept','work','fit'].includes(value));
  const actionDraftKey=JSON.stringify([record?.request_id,actionKind]);
  const update = (name:keyof typeof draft,value:string)=>setDraft(previous=>({...previous,[name]:value}));
  const inFlight=useRef(false);
  async function send() {
    if (inFlight.current) return;
    inFlight.current=true;
    setBusy(true); setStatus('pending');
    if (!pending.current) {
      const operation = crypto.randomUUID(), id = crypto.randomUUID();
      pending.current = {operation,request:id,body:{schema_version:'enlargement.v1',operation_id:operation,request_id:id,watch_id:draft.watch,organization_id:draft.business,expected_revision:0,source_revision:Number(draft.sourceRevision),kind:'request',payload:{measurement:draft.measurement,unit:draft.unit,method:draft.method,source:draft.source,target:draft.target,choice:draft.choice}}};
    }
    setReference({operation:pending.current.operation,request:pending.current.request});
    try {const result=await submit(pending.current.body);setAnswer(result);setOpened(result.request_id);setStatus('saved');pending.current=null;setReference(null);}
    catch(error) {if(error instanceof ApiError && [400,403,409,422].includes(error.status)){pending.current=null;setReference(null);}
      setStatus(error instanceof ApiError && error.status===403 ? 'denied' : error instanceof ApiError && error.status===409 ? 'stale' : error instanceof ApiError && error.status===422 ? 'invalid' : 'error');}
    finally {inFlight.current=false;setBusy(false);}
  }
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody><div className="enlargement-content">
    {!signedIn ? <State title={t.title} body={t.signin}><ButtonLink href={signInHref('/care/enlargement',locale)}>{t.signin}</ButtonLink></State> : <>
      <form onSubmit={event=>{event.preventDefault();if(!actionPending) void send();}}>
        {(['watch','business','sourceRevision','measurement','method','source','target'] as const).map(name=><Input key={name} label={t[name]} value={draft[name]} required disabled={busy||Boolean(reference)} onValueChange={value=>update(name,value)}/>)}
        <Select label={t.unit} value={draft.unit} messages={t.select} disabled={busy||Boolean(reference)} options={(['cm','mm'] as const).map(value=>({value,label:t[value]}))} onValueChange={value=>update('unit',value)}/>
        <Select label={t.choice} value={draft.choice} messages={t.select} disabled={busy||Boolean(reference)} options={(['links','strap','clasp'] as const).map(value=>({value,label:t[value]}))} onValueChange={value=>update('choice',value)}/>
        <Button type="submit" disabled={busy||Boolean(actionPending)} aria-busy={busy}>{reference?t.retry:t.send}</Button>
      </form>
      {reference && <p>{t.reference}: <bdi>{reference.request}</bdi> · {t.operation}: <bdi>{reference.operation}</bdi></p>}
      {status && <State kind={status==='saved'?'empty':status==='pending'?'loading':'error'} title={t.title} body={t[status as 'saved'|'pending'|'denied'|'stale'|'invalid'|'error']}/>}
      <form onSubmit={event=>{event.preventDefault();if(!actionPending){setAnswer(null);setOpened(lookup);}}}><Input label={t.requestId} required value={lookup} onValueChange={setLookup}/><Button type="submit" disabled={Boolean(actionPending)}>{t.load}</Button></form>
      {actionPending && <State kind="error" title={t.operation} body={t.actionPending}><p><bdi>{(actionPending as {operation_id:string}).operation_id}</bdi></p><Button onClick={()=>void submitAction(actionPending)}>{t.retry}</Button></State>}
      {actionError && <State kind="error" title={t.operation} body={t[actionError as 'denied'|'stale'|'invalid'|'actionPending']}/>}
      {opened && read.isPending && <State kind="loading" title={t.assessment} body={t.loading}/>}
      {read.isError && <State kind="error" title={t.assessment} body={read.error instanceof ApiError && read.error.status===403?t.denied:t.error}><Button onClick={()=>void read.refetch()}>{t.refresh}</Button></State>}
      {record && !read.isError && <Card><h2>{t.states[record.state]}</h2><p>{t.reference}: <bdi>{record.request_id}</bdi></p>
        {record.state==='waiting' && <p role="status">{t.waiting} {t.reviewAt}: <bdi>{record.next_review_at}</bdi></p>}
        {record.request && <section aria-label={t.requestContext}><h3>{t.requestContext}</h3>
          <p>{t.measurement}: <bdi>{record.request.measurement}</bdi> {t[record.request.unit]} · <bdi>{record.request.measurement_mm}</bdi> {t.mm}</p>
          <p>{t.method}: {record.request.method}</p><p>{t.source}: {record.request.source}</p>
          <p>{t.target}: {record.request.target}</p><p>{t.choice}: {t[record.request.choice]}</p>
        </section>}
        {(record.state==='waiting'||record.state==='rework') && <><p>{t.reviewAt}: <bdi>{record.next_review_at}</bdi></p><p>{t.operator}: <bdi>{record.responsible_operator_id}</bdi></p><p>{t.nextAction}: {record.next_action?.[locale]}</p><p>{t.responseDue}: <bdi>{record.first_response_due_at}</bdi></p><p>{t.escalation}: <bdi>{record.escalation_at}</bdi></p></>}
        {record.assessment ? <><p>{record.assessment.target}</p><p>{t.limitations}: {record.assessment.limitations}</p><p>{t.cost}: {formatAmount((record.assessment.total_minor/100).toFixed(2),locale,'USD','—')} USD</p><ul>{record.assessment.parts.map(part=><li key={part.id}><bdi>{part.id}</bdi> · {t[part.kind]} · {t.statuses[part.status]} · {formatNumber(part.quantity,locale)}</li>)}</ul><p>{t.terms}</p></> : <p>{t.empty}</p>}
        {record.state==='rework' && <p role="status">{t.rework}</p>}
        {record.quality && <p>{t.fit}: {record.quality.fit}</p>}
        {!actionPending && !reference && <Actions key={`${record.request_id}:${record.revision}`} record={record} submitAction={submitAction} draft={actionDrafts[actionDraftKey]??emptyActionDraft()} onDraftChange={draft=>setActionDrafts(previous=>({...previous,[actionDraftKey]:draft}))}/>}
      </Card>}
    </>}
  </div></PageBody></PageFrame>;
}

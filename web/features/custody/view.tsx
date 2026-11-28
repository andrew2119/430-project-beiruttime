'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AnimatedList, Button, ButtonLink, Card, Checkbox, Input, RowSkeleton, State, formatNumber } from '@beirut-time/ui/foundation';
import type { BuyerReceiptCommand, CustodyRecord } from '@contracts/contracts-orders/custody';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { usePageRead } from '@/lib/page-speed/read';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest, signInHref, useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { buyerCommand, reference, ReceiptAttempt } from './model';
import { custodyHistoryRead, custodyPath, custodyRead } from './reads';
import { copy } from './copy';

export default function CustodyView() {
  const locale = useLocale(), t = copy[locale], session = useSession();
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    {session ? <Delivery key={session.access_fingerprint} fingerprint={session.access_fingerprint}/> :
      <State title={t.signIn} body={t.deniedBody}><ButtonLink href={signInHref('/deliveries',locale)}>{t.signIn}</ButtonLink></State>}
  </PageBody></PageFrame>;
}

type ReceiptDraft = {watch:string;recipient:string;condition:string;accessories:string;location:string;address:string;signed:boolean};
const emptyDraft = ():ReceiptDraft => ({watch:'',recipient:'',condition:'',accessories:'',location:'',address:'',signed:false});

function Delivery({fingerprint}:{fingerprint:string}) {
  const locale = useLocale(), t = copy[locale];
  const [order,setOrder] = useState(''), [selected,setSelected] = useState('');
  const [invalid,setInvalid] = useState(false), [busy,setBusy] = useState(false);
  const [message,setMessage] = useState<'pending'|'stale'|'denied'|'invalid'|'saved'|null>(null);
  const [operationReference,setOperationReference] = useState<string|null>(null);
  const [draft,setDraft] = useState<ReceiptDraft>(emptyDraft);
  const attempt = useRef(new ReceiptAttempt());
  const active = useRef<AbortController|null>(null);
  const locked = busy || message === 'pending';
  const query = usePageRead(selected ? custodyRead(selected,fingerprint) : null);
  useEffect(()=>{
    const retained = attempt.current;
    const clear = () => {active.current?.abort();active.current=null;retained.clear();setDraft(emptyDraft());setOrder('');setSelected('');setInvalid(false);setBusy(false);setMessage(null);setOperationReference(null);};
    window.addEventListener('bt:access-change',clear);
    return ()=>{window.removeEventListener('bt:access-change',clear);active.current?.abort();retained.clear();};
  },[]);
  const error = query.error instanceof ApiError && [401,403].includes(query.error.status) ? 'denied' : 'unavailable';
  function load(event:FormEvent) {
    event.preventDefault();
    if (attempt.current.unresolved()) return;
    if (!reference(order)) {setInvalid(true);return;}
    setInvalid(false);
    if (selected === order) void query.refetch();
    else {setDraft(emptyDraft());setSelected(order);}
  }
  async function send(command?:BuyerReceiptCommand) {
    if (active.current) return;
    const pending = attempt.current.capture(command);
    if (!pending) return;
    const controller = new AbortController();
    active.current=controller;setBusy(true);setMessage('pending');setOperationReference(pending.operation);
    try {
      const response = await authenticatedRequest<{schema_version?:string;result?:{operation_id?:string;subject_id?:string;revision?:number}}>(`${custodyPath}/${encodeURIComponent(pending.order)}/buyer-receipts`,{
        method:'POST',signal:controller.signal,accessFingerprint:fingerprint,
        headers:{'Content-Type':'application/json'},body:pending.body,
      });
      if (controller.signal.aborted) return;
      if (response.schema_version !== 'custody.v1' || response.result?.operation_id !== pending.operation || response.result.subject_id !== pending.order || response.result.revision !== pending.revision + 1) throw new Error('invalid');
      attempt.current.clear();setMessage('saved');void query.refetch();
    } catch(error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status < 500 && error.status !== 408 && error.status !== 429) {
        attempt.current.clear();
        setMessage(error.status === 409 ? 'stale' : error.status === 422 ? 'invalid' : 'denied');
      } else setMessage('pending');
    } finally {
      if (!controller.signal.aborted) {setBusy(false);active.current=null;}
    }
  }
  return <>
    <Card><form onSubmit={load} autoComplete="off">
      <Input label={t.order} value={order} onValueChange={setOrder} required disabled={locked} error={invalid?t.invalid:undefined}/>
      <Button type="submit" busy={query.isFetching} disabled={locked}>{t.load}</Button>
    </form></Card>
    {operationReference && <p className="bt-text">{t.operation}: <bdi>{operationReference}</bdi></p>}
    {message && (message === 'saved' ? <p role="status" className="bt-text">{t.saved}</p> : <State kind={message === 'pending'?'loading':'error'} title={t[message]} body={t[`${message}Body`]}>
      {message === 'pending' && <Button busy={busy} onClick={()=>void send()}>{t.retry}</Button>}
    </State>)}
    {selected && query.isPending && !query.isError && <div role="status" aria-label={t.loading}><RowSkeleton/></div>}
    {selected && query.isError && <State kind="error" title={t[error]} body={t[`${error}Body`]}><Button onClick={()=>void query.refetch()}>{t.refresh}</Button></State>}
    {selected && !query.isError && query.data === null && <State title={t.empty} body={t.emptyBody}/>}
    {selected && !query.isError && query.data && <AnswerArrival view="custody"><Record key={selected} record={query.data} draft={draft} setDraft={setDraft} locked={locked} send={command=>void send(command)} refresh={()=>void query.refetch()}/></AnswerArrival>}
    {selected && !query.isError && <Timeline key={selected} order={selected} fingerprint={fingerprint} revision={query.data?.revision}/>}
    <p className="bt-caption">{t.simulated}</p>
    <ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink>
  </>;
}

function Timeline({order,fingerprint,revision}:{order:string;fingerprint:string;revision?:number}) {
  const locale = useLocale(), t = copy[locale], [offset,setOffset] = useState(0);
  const query = usePageRead(custodyHistoryRead(order,fingerprint,offset),{keep:true});
  const refresh = query.refetch;
  useEffect(()=>{if (revision !== undefined) void refresh();},[revision,refresh]);
  if (query.isError) {
    const denied = query.error instanceof ApiError && [401,403].includes(query.error.status);
    return <State kind="error" title={denied?t.denied:t.unavailable} body={denied?t.deniedBody:t.unavailableBody}><Button onClick={()=>void refresh()}>{t.refresh}</Button></State>;
  }
  if (!query.data) return <div role="status" aria-label={t.loading}><RowSkeleton/></div>;
  const answer = query.data;
  return <Card><h2 className="bt-heading">{t.timeline}</h2><p className="bt-text">{t.total}: {formatNumber(answer.total,locale)}</p>
    <AnimatedList scopeKey={`${fingerprint}:${order}`} items={answer.items} getKey={row=>row.operation_id} empty={<State title={t.empty} body={t.emptyBody}/>}>
      {row=><p className="bt-text">{t.states[row.state]} · <bdi>{row.operation_id}</bdi>{row.held ? ` · ${t.held}` : ''}</p>}
    </AnimatedList>
    <Button variant="outline" onClick={()=>setOffset(value=>Math.max(0,value-25))} disabled={offset === 0 || query.isFetching}>{t.previous}</Button>
    <Button variant="outline" onClick={()=>setOffset(value=>value+25)} disabled={offset+25 >= answer.total || query.isFetching}>{t.more}</Button>
  </Card>;
}

function Record({record,draft,setDraft,locked,send,refresh}:{record:CustodyRecord;draft:ReceiptDraft;setDraft:(draft:ReceiptDraft)=>void;locked:boolean;send:(command:BuyerReceiptCommand)=>void;refresh:()=>void}) {
  const locale = useLocale(), t = copy[locale];
  const {watch,recipient,condition,accessories,location,address,signed} = draft;
  const [invalid,setInvalid] = useState(false);
  const update = <K extends keyof ReceiptDraft>(key:K,value:ReceiptDraft[K]) => setDraft({...draft,[key]:value});
  const time = (value:string|null) => value ? new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(value)) : t.absent;
  const reason = record.pending_reason && record.pending_reason in t.reasons ? t.reasons[record.pending_reason as keyof typeof t.reasons] : t.held;
  function submit(event:FormEvent) {
    event.preventDefault();
    if (locked || !signed) return;
    try {
      const command = buyerCommand(record,{watch_id:watch,recipient,condition,
        accessories:accessories.split(/[,،]/).map(value=>value.trim()).filter(Boolean),location,address,
        received_at:new Date().toISOString(),signed_handoff:true,source:'buyer_acknowledgement'},crypto.randomUUID());
      setInvalid(false);send(command);
    } catch {setInvalid(true);}
  }
  return <>
    <Card><h2 className="bt-heading">{t.states[record.state]}</h2>
      <dl className="bt-text">
        <dt>{t.custodian}</dt><dd><bdi>{record.custodian}</bdi></dd>
        <dt>{t.receipt}</dt><dd>{time(record.buyer_received_at)}</dd>
        <dt>{t.deadline}</dt><dd>{time(record.dispute_deadline)}</dd>
        <dt>{t.operation}</dt><dd><bdi>{record.operation_id}</bdi></dd>
        {record.next_actor && <><dt>{t.next}</dt><dd><bdi>{record.next_actor}</bdi></dd><dt>{t.review}</dt><dd>{time(record.next_review_at)}</dd></>}
      </dl>
      {record.held && <State kind="error" title={t.held} body={reason}/>}
      {record.due_actions.map(action=><p className="bt-text" key={action.code}>{t.due[action.code as keyof typeof t.due] ?? t.held} · <bdi>{action.next_actor}</bdi> · {time(action.due_at)}</p>)}
      <Button onClick={refresh} variant="outline" disabled={locked}>{t.refresh}</Button>
    </Card>
    {!record.buyer_received_at && !record.held && record.state !== 'returned' && <Card><form onSubmit={submit} autoComplete="off">
      <p className="bt-text">{t.intro}</p>
      <Input label={t.watch} value={watch} onValueChange={value=>update('watch',value)} disabled={locked} required/>
      <Input label={t.recipient} value={recipient} onValueChange={value=>update('recipient',value)} disabled={locked} required/>
      <Input label={t.condition} value={condition} onValueChange={value=>update('condition',value)} disabled={locked} required/>
      <Input label={t.accessories} value={accessories} onValueChange={value=>update('accessories',value)} disabled={locked}/>
      <Input label={t.location} value={location} onValueChange={value=>update('location',value)} disabled={locked} required/>
      <Input label={t.address} value={address} onValueChange={value=>update('address',value)} disabled={locked} required/>
      <Checkbox label={t.signed} checked={signed} onCheckedChange={value=>update('signed',value)} disabled={locked} required/>
      {invalid && <State kind="error" title={t.invalid} body={t.invalidBody}/>}
      <Button type="submit" disabled={locked || !signed}>{t.received}</Button>
    </form></Card>}
  </>;
}

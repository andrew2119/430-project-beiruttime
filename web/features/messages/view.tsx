'use client';

import { useRef, useState } from 'react';
import { useLocale } from '@/shell/locale-context';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { Button, Card, formatNumber, Input, RowSkeleton, Segmented, State, Textarea } from '@beirut-time/ui/foundation';
import { useSession } from '@/features/identity/session';
import { authenticatedRequest } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { ApiError } from '@/lib/api/client';
import type { Command, Receipt, Thread } from '@contracts/contracts-comms/messages';
import { base, conversationRead, deliveryRead, statusRead, threadRead } from './reads';
import { copy } from './copy';
import { PendingCommand } from './operation';
import './styles.css';

/** Mounted by the shared private page scope; identity replaces the whole form. */
export function MessagesView() {
  const session = useSession(), locale = useLocale(), t = copy[locale];
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>{session ? <Workspace key={session.access_fingerprint} scope={session.access_fingerprint}/> : <State title={t.signIn} body={t.signBody}/>}</PageBody></PageFrame>;
}

function Workspace({scope}:{scope:string}) {
  const locale = useLocale(), t = copy[locale];
  const [thread,setThread] = useState<Thread|null>(null), [cursor,setCursor] = useState(0), [subject,setSubject] = useState(''), [kind,setKind] = useState('listing');
  const [error,setError] = useState<unknown>(null), [opening,setOpening] = useState(false);
  const listing = usePageRead(threadRead(cursor));
  const listingDenied = listing.error instanceof ApiError && [401,403,404].includes(listing.error.status);
  const open = async()=>{setOpening(true);setError(null);try {const value = await authenticatedRequest<Thread>(`${base}/threads`,{accessFingerprint:scope,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,subject_id:subject})});setThread(value);}catch(cause){setError(cause);}finally{setOpening(false);}};
  if (thread) return <Conversation key={thread.id} initial={thread} scope={scope} back={()=>setThread(null)}/>;
  return <>
    <Card><Segmented label={t.kind} value={kind} onValueChange={setKind} options={[{value:'listing',label:t.listing},{value:'order',label:t.order},{value:'business',label:t.business}]}/><Input label={t.subject} value={subject} onValueChange={setSubject}/><Button disabled={!subject.trim() || subject.length>160} busy={opening} onClick={()=>void open()}>{t.open}</Button></Card>
    <Problem error={error || listing.error} retry={()=>void listing.refetch()}/>
    {listing.isPending && <div aria-busy="true" aria-label={t.loading}><RowSkeleton/><RowSkeleton/></div>}
    {!listingDenied && listing.data && <AnswerArrival view="messages"><p>{t.total}: {formatNumber(listing.data.total,locale)}</p>{listing.data.items.length===0 && <State title={t.empty} body={t.emptyBody}/>}{listing.data.items.map(item=><Card key={item.id}><Button variant="outline" onClick={()=>setThread(item)}>{t[item.kind]} · <bdi>{item.subject_id}</bdi></Button>{item.original_work_id && <p>{t.original}: <bdi>{item.original_work_id}</bdi></p>}</Card>)}{cursor>0 && <Button variant="outline" onClick={()=>setCursor(0)}>{t.back}</Button>}{listing.data.next_cursor!==null && <Button onClick={()=>setCursor(listing.data!.next_cursor!)}>{t.next}</Button>}</AnswerArrival>}
  </>;
}

function Problem({error,retry}:{error:unknown;retry:()=>void}) {
  const t = copy[useLocale()];
  if (!error) return null;
  const denied = error instanceof ApiError && [401,403,404].includes(error.status);
  return <State kind="error" title={denied?t.denied:t.unavailable} body={denied?t.deniedBody:t.recovery}><Button variant="outline" onClick={retry}>{t.retry}</Button></State>;
}

function Conversation({initial,scope,back}:{initial:Thread;scope:string;back:()=>void}) {
  const locale=useLocale(),t=copy[locale], [cursor,setCursor]=useState(0), [draft,setDraft]=useState(''), [reason,setReason]=useState(''), [target,setTarget]=useState(''), [delivery,setDelivery]=useState('');
  const [error,setError]=useState<unknown>(null), [busy,setBusy]=useState(false), [confirmed,setConfirmed]=useState(false), [deliveryRevision,setDeliveryRevision]=useState(0), [accessDenied,setAccessDenied]=useState(false);
  const pending=useRef<PendingCommand|null>(null), [reference,setReference]=useState(''), [canCorrect,setCanCorrect]=useState(false);
  const read=usePageRead(conversationRead(initial.id,cursor));
  const status=usePageRead(statusRead(initial.id));
  const refresh=async()=>{const [currentStatus,currentRead]=await Promise.all([status.refetch(),read.refetch()]);if(!currentStatus.error && !currentRead.error)setAccessDenied(false);};
  const submit=async(kind:Command['kind'], body?:string, sequence?:number)=>{
    const thread=status.error ? undefined : status.data?.thread;if ((!thread && !pending.current) || busy) return;
    setBusy(true);setError(null);setConfirmed(false);setCanCorrect(false);
    const operation=pending.current ?? new PendingCommand({operation_id:crypto.randomUUID(),kind,body,...(kind==='block' || kind==='unblock'?{target}:{}),sequence,expected_revision:thread!.revision,source_revision:thread!.source_revision,quote_revision:thread!.quote_revision,policy_revision:thread!.policy_revision});
    const command=operation.body;
    pending.current=operation;setReference(command.operation_id);
    const path=`${base}/threads/${encodeURIComponent(initial.id)}`;
    try {
      await operation.run({send:value=>authenticatedRequest<Receipt>(`${path}/commands`,{accessFingerprint:scope,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}),lookup:operation=>authenticatedRequest<Receipt|{state:'pending'}>(`${path}/operations/${operation}`,{accessFingerprint:scope})});
      pending.current=null;setReference('');setConfirmed(true);if(command.kind==='send')setDraft('');if(command.kind==='delivery')setDeliveryRevision(value=>value+1);
      await refresh();
    }catch(cause){setError(cause);setCanCorrect(!operation.uncertain && cause instanceof ApiError && cause.status<500);if(cause instanceof ApiError && [401,403,404].includes(cause.status))setAccessDenied(true);}finally{setBusy(false);}
  };
  const denied=accessDenied || !!read.error || !!status.error || error instanceof ApiError && [401,403,404].includes(error.status);
  return <div className="l22-conversation">
    <Button variant="outline" onClick={back} disabled={!!reference}>{t.back}</Button>
    <Problem error={read.error || status.error || error || (accessDenied?new ApiError(403,'scope',''):null)} retry={()=>void refresh()}/>
    {!status.error && status.data && <Card><Input label={t.target} value={target} onValueChange={setTarget} disabled={!!reference}/><div className="l22-actions"><Button variant="outline" disabled={busy || !!reference || !target || status.data.thread.active_support} onClick={()=>void submit('block')}>{t.block}</Button><Button variant="outline" disabled={busy || !!reference || !target} onClick={()=>void submit('unblock')}>{t.unblock}</Button></div></Card>}
    {read.isPending && <div aria-busy="true" aria-label={t.loading}><RowSkeleton/><RowSkeleton/></div>}
      {reference && <State kind="loading" title={t.pending} body={t.recovery}><p>{t.operation}: <bdi>{reference}</bdi></p><Button busy={busy} onClick={()=>void submit(pending.current!.body.kind)}>{t.retry}</Button>{canCorrect && <Button onClick={()=>{pending.current=null;setReference('');setError(null);}}>{t.correct}</Button>}</State>}
    {!denied && read.data && <>
      <p>{t.total}: {formatNumber(read.data.total,locale)} · {t.unread}: {formatNumber(read.data.unread,locale)}</p>
      {read.data.thread.original_work_id && <p>{t.original}: <bdi>{read.data.thread.original_work_id}</bdi></p>}
      {read.data.thread.active_support && <State title={t.support} body={t.recovery}/>}
      {read.data.items.length===0 && <State title={t.empty} body={t.emptyBody}/>}
      <div className="l22-message-list">{read.data.items.map(message=><Card key={message.sequence}><p><bdi>{message.actor_id}</bdi> · <time dateTime={message.sent_at}>{new Date(message.sent_at).toLocaleString(locale==='ar'?'ar-LB':'en-GB',{timeZone:'Asia/Beirut'})}</time></p><p className="l22-message-body" dir="auto">{message.correction_required?message.preview:message.body}</p>{message.correction_required && <p role="status">{t.warning}</p>}<div className="l22-actions"><Button variant="outline" disabled={busy || !!reference || !reason.trim()} onClick={()=>void submit('report',reason,message.sequence)}>{t.report}</Button>{message.correction_required && <Button variant="outline" disabled={busy || !!reference || !reason.trim()} onClick={()=>void submit('appeal',reason,message.sequence)}>{t.appeal}</Button>}</div></Card>)}</div>
      <div className="l22-actions">{cursor>0 && <Button variant="outline" onClick={()=>setCursor(0)}>{t.back}</Button>}{read.data.next_cursor!==null && <Button onClick={()=>setCursor(read.data!.next_cursor!)}>{t.next}</Button>}<Button variant="outline" disabled={busy || !!reference || !read.data.items.length} onClick={()=>void submit('read',undefined,read.data!.items.at(-1)!.sequence)}>{t.read}</Button></div>
      <Textarea label={t.reason} value={reason} onValueChange={setReason} disabled={!!reference}/>
      <Textarea label={t.draft} hint={t.limit} value={draft} onValueChange={setDraft} disabled={!!reference}/>
      <Button busy={busy} disabled={!!reference || !draft.trim() || draft.length>4000} onClick={()=>void submit('send',draft)}>{t.send}</Button>

      {confirmed && <p role="status">{t.saved}</p>}

      {read.data.thread.paid_held && <Card><DeliveryValues key={deliveryRevision} id={initial.id}/><Textarea label={t.delivery} value={delivery} onValueChange={setDelivery} disabled={!!reference}/><Button disabled={busy || !!reference || !delivery.trim() || delivery.length>500} onClick={()=>void submit('delivery',delivery)}>{t.saveDelivery}</Button></Card>}
    </>}
  </div>;
}

function DeliveryValues({id}:{id:string}) {
  const t=copy[useLocale()], read=usePageRead(deliveryRead(id));
  return <><Problem error={read.error} retry={()=>void read.refetch()}/>{!read.error && read.data?.items.map(item=><p key={item.actor} dir="auto"><bdi>{item.actor}</bdi>: {item.value}</p>)}{read.isPending && <RowSkeleton/>}{read.data?.items.length===0 && <p>{t.empty}</p>}</>;
}

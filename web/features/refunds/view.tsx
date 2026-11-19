'use client';
import { useState, useSyncExternalStore } from 'react';
import { Button, Card, Input, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { definePageRead } from '@/lib/page-speed/definition';
import { usePageRead } from '@/lib/page-speed/read';
import { useLocale } from '@/shell/locale-context';
import { useSession } from '@/features/identity/session';
import { formatQuotedMoney } from '@/features/buy-now/money';
import { copy } from './copy';
import { RefundDraft, RefundFailure, unavailablePort, type RefundPort } from './model';

export default function RefundView({port=unavailablePort}:{port?:RefundPort}) {
  const session=useSession(),locale=useLocale(),t=copy[locale];
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    {session ? <RefundForm key={session.access_fingerprint} fingerprint={session.access_fingerprint} port={port}/> :
      <State title={t.title} body={t.signIn}/>}
  </PageBody></PageFrame>;
}
function RefundForm({fingerprint,port}:{fingerprint:string;port:RefundPort}) {
  const locale=useLocale(),t=copy[locale];
  const [accessDenied,setAccessDenied]=useState(false);
  const [definition]=useState(()=>definePageRead({key:()=>['refunds.v1','current',fingerprint],
    ask:async(signal:AbortSignal)=>{
      try {return await port.current(signal);}
      catch (error) {
        if (error instanceof RefundFailure && error.code==='denied') setAccessDenied(true);
        throw error;
      }
    },warm:'open-only'}));
  const read=usePageRead(definition());
  const [store]=useState(()=>new RefundDraft());
  const draft=useSyncExternalStore(store.subscribe,store.read,store.read);
  const [invalid,setInvalid]=useState(false);
  async function act(lookup=false) {
    if (draft.busy || !read.data || accessDenied || read.error) return;
    const command=store.begin(read.data.binding,crypto.randomUUID());
    if (!command) {setInvalid(true);return;}
    setInvalid(false);
    try {
      const signal=AbortSignal.timeout(5000);
      const result=lookup ? await port.lookup(command,signal) : await port.request(command,signal);
      if (result) {store.accept(result);void read.refetch();}
      else store.fail('pending');
    } catch (error) {
      if (error instanceof RefundFailure && error.code==='denied') setAccessDenied(true);
      store.fail(error instanceof RefundFailure ? error.code : 'pending',!lookup && error instanceof RefundFailure && error.noEffect);}
    finally {store.finish();}
  }
  const operation=draft.operation;
  const terminal=operation?.state==='confirmed' || operation?.state==='declined';
  if (accessDenied || (read.error instanceof RefundFailure && read.error.code==='denied'))
    return <State kind="error" title={t.title} body={t.denied}>
      <Button disabled={read.isFetching} onClick={()=>{
        void read.refetch().then(result=>{if (result.data && !result.error) setAccessDenied(false);});
      }}>{t.load}</Button>
    </State>;
  if (!read.data) return <State title={t.title} kind={read.isPending?'loading':'error'}
    body={read.isPending?t.loading:read.error instanceof RefundFailure ? t[read.error.code] : t.unavailable}>
    {!read.isPending && <Button onClick={()=>void read.refetch()}>{t.load}</Button>}
  </State>;
  const data=read.data;
  if (!Number.isSafeInteger(data.remaining_minor) || data.remaining_minor<0 || data.remaining_minor>9000000000000000)
    return <State kind="error" title={t.title} body={t.unavailable}/>;
  return <Card>
    {read.isFetching && <p role="status">{t.refresh}</p>}
    {read.error && <State kind="error" title={t.title} body={t.unavailable}/>}
    <p>{read.isFetching || read.error ? t.lastKnown : t.remaining}: <bdi>{formatQuotedMoney(data.remaining_minor,'USD',locale)}</bdi></p>
    {data.remaining_minor===0 && !draft.command ? <State title={t.title} body={t.empty}/> :
    <form onSubmit={event=>{event.preventDefault();void act();}} aria-busy={draft.busy}>
      <Input label={t.amount} hint={t.hint} value={draft.amount} inputMode="decimal" required
        disabled={!!draft.command || draft.busy} error={invalid?t.invalid:undefined}
        onValueChange={value=>{store.setAmount(value);setInvalid(false);}}/>
      {!terminal && <Button type="submit" disabled={draft.busy || draft.rejected || !!read.error || read.isFetching}>
        {draft.busy?t.working:draft.command?t.retry:t.submit}</Button>}
    </form>}
    {draft.command && <p>{t.reference}: <bdi>{draft.command.operation_id}</bdi></p>}
    {(draft.code || operation) && <State title={t.title} kind={draft.code && draft.code!=='pending'?'error':'empty'}
      body={draft.code?t[draft.code]:operation?.state==='confirmed'?t.confirmed:operation?.state==='declined'?t.declined:t.pending}/>}
    {operation?.state==='pending' && <p>{t.review}: <bdi>{operation.next_review_at}</bdi></p>}
    {draft.command && !terminal && !draft.rejected && <Button disabled={draft.busy || !!read.error} onClick={()=>void act(true)}>{t.lookup}</Button>}
    {draft.rejected && <Button disabled={draft.busy || read.isFetching} onClick={()=>{void read.refetch().then(result=>{if (result.data && !result.error) store.reviewRejected();});}}>{t.load}</Button>}
    {terminal && <Button disabled={read.isFetching} onClick={()=>{store.reset();void read.refetch();}}>{t.newRequest}</Button>}
    {(!draft.command || (!!read.error && !draft.rejected)) && <Button disabled={read.isFetching} onClick={()=>void read.refetch()}>{t.load}</Button>}
  </Card>;
}

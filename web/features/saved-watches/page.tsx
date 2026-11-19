'use client';

import { useRef, useState } from 'react';
import { Button, ButtonLink, Card, Checkbox, Input, RowSkeleton, State, formatAmount, formatNumber } from '@beirut-time/ui/foundation';
import type { AlertKind, SaveCommand, SavedWatch } from '@contracts/contracts-comms/saved-watches';
import { authenticatedRequest, useSession, useSessionState } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { savedBase, savedRead } from './read';
import { copy } from './copy';

type Copy = typeof copy.en;
type Pending = {watch:string;command:SaveCommand};
const kinds:AlertKind[] = ['price','bid','ending','sold'];
function Choices({value,onChange,disabled,c}:{value:AlertKind[];onChange:(value:AlertKind[])=>void;disabled:boolean;c:Copy}) {
  return <fieldset disabled={disabled}><legend className="bt-text">{c.update}</legend>{kinds.map(kind=><Checkbox key={kind} label={kind==='sold'?c.soldAlert:c[kind]} checked={value.includes(kind)} onCheckedChange={checked=>onChange(checked?[...value,kind]:value.filter(item=>item!==kind))}/>)}</fieldset>;
}
function WatchRow({watch,busy,change,c,locale}:{watch:SavedWatch;busy:boolean;change:(watch:string,revision:number,saved:boolean,alerts:AlertKind[])=>void;c:Copy;locale:'en'|'ar'}) {
  const [alerts,setAlerts] = useState(watch.alerts);
  return <Card><h2 className="bt-heading">{watch.title || c.unnamed}</h2><p className="bt-text">{c[watch.status]}</p>
    <p className="bt-number">{watch.price_minor===null?c.priceMissing:`${c.amount}: ${formatAmount(`${Math.floor(watch.price_minor/100)}.${String(watch.price_minor%100).padStart(2,'0')}`,locale,locale==='ar'?'دولار أمريكي':'USD',c.priceMissing)}`}</p>
    <ButtonLink href={`/${locale}/watches/${encodeURIComponent(watch.watch_id)}`}>{c.open}</ButtonLink>
    <Choices value={alerts} onChange={setAlerts} disabled={busy} c={c}/>
    <Button disabled={busy} onClick={()=>change(watch.watch_id,watch.revision,true,alerts)}>{c.update}</Button>
    <Button disabled={busy} onClick={()=>change(watch.watch_id,watch.revision,false,[])}>{c.remove}</Button>
  </Card>;
}
function SavedView({access}:{access:string}) {
  const locale=useLocale(),c=copy[locale];
  const [offset,setOffset]=useState(0),[reference,setReference]=useState(''),[alerts,setAlerts]=useState<AlertKind[]>([]);
  const [pending,setPending]=useState<Pending|null>(null),[error,setError]=useState<unknown>(null),[sending,setSending]=useState(false);
  const flight=useRef(false),read=usePageRead(savedRead(access,offset));
  async function send(action:Pending) {
    if(flight.current) return;
    flight.current=true;setSending(true);setPending(action);setError(null);
    try {
      await authenticatedRequest(`${savedBase}/${encodeURIComponent(action.watch)}`,{method:'PUT',accessFingerprint:access,headers:{'Content-Type':'application/json'},body:JSON.stringify(action.command)});
      setPending(null);await read.refetch();
    } catch(failure) {
      setError(failure);
      if(failure instanceof ApiError && [400,403,409,422].includes(failure.status)) setPending(null);
    } finally {flight.current=false;setSending(false);}
  }
  async function change(watch:string,revision:number,saved:boolean,choices:AlertKind[]) {
    if(pending || flight.current) return;
    if(revision===0) {
      flight.current=true;setSending(true);setError(null);
      try {
        const current=await authenticatedRequest<{revision:number}>(`${savedBase}/${encodeURIComponent(watch)}`,{accessFingerprint:access});
        revision=current.revision;
      } catch(failure) {setError(failure);return;}
      finally {flight.current=false;setSending(false);}
    }
    void send({watch,command:{schema_version:'communications.saved-watches.v1',operation_id:crypto.randomUUID(),expected_revision:revision,saved,alerts:[...choices]}});
  }
  const denied=(error instanceof ApiError && [401,403].includes(error.status)) || (read.error instanceof ApiError && [401,403].includes(read.error.status));
  const stale=error instanceof ApiError && error.status===409;
  return <PageFrame><PageHeader title={c.title} lead={c.intro} count={!denied && read.data?`${c.total}: ${formatNumber(read.data.total,locale)}`:undefined} actions={<Button disabled={sending} onClick={()=>void read.refetch()}>{c.refresh}</Button>}/><PageBody>
    {denied?<State kind="error" title={c.denied} body={c.deniedBody}><ButtonLink href={`/${locale}/account`}>{c.account}</ButtonLink></State>:<>
      <Input label={c.reference} value={reference} onValueChange={setReference} disabled={!!pending || sending}/>
      <Choices value={alerts} onChange={setAlerts} disabled={!!pending || sending} c={c}/>
      <Button disabled={!reference.trim() || !!pending || sending || reference.length>128} onClick={()=>void change(reference.trim(),0,true,alerts)}>{c.save}</Button>
      {pending && <State kind="loading" title={c.pending} body={c.pendingBody}><p className="bt-text">{c.operation}: <bdi>{pending.command.operation_id}</bdi></p>{!sending && <Button onClick={()=>void send(pending)}>{c.retry}</Button>}</State>}
      {(error || read.isError) && <State kind="error" title={stale?c.stale:c.error} body={stale?c.staleBody:c.errorBody}><Button disabled={sending} onClick={()=>pending?void send(pending):void read.refetch()}>{c.retry}</Button></State>}
      {read.isPending && <><State kind="loading" title={c.loading} body={c.loadingBody}/><RowSkeleton/></>}
      {read.data && <AnswerArrival view="saved-watches"><p className="bt-text" role="status">{read.isFetching?c.loading:''}</p>
        {read.data.total===0 && <State title={c.empty} body={c.emptyBody}/>}
        {read.data.items.map(watch=><WatchRow key={`${watch.watch_id}:${watch.revision}`} watch={watch} busy={!!pending || sending} change={(...args)=>void change(...args)} c={c} locale={locale}/>)}
        <Button disabled={offset===0 || !!pending} onClick={()=>setOffset(Math.max(0,offset-20))}>{c.previous}</Button>
        <Button disabled={offset+20>=read.data.total || !!pending} onClick={()=>setOffset(offset+20)}>{c.next}</Button>
      </AnswerArrival>}
    </>}
  </PageBody></PageFrame>;
}
export function ComposedSavedPage() {
  const session=useSession(),state=useSessionState(),locale=useLocale(),c=copy[locale];
  if(session) return <SavedView key={session.access_fingerprint} access={session.access_fingerprint}/>;
  return <PageFrame><PageHeader title={c.title}/><PageBody><State kind={state==='restoring'?'loading':'empty'} title={state==='restoring'?c.loading:c.signIn} body={state==='restoring'?c.loadingBody:c.signInBody}><ButtonLink href={`/${locale}/account`}>{c.account}</ButtonLink></State></PageBody></PageFrame>;
}

// Mount the private view only after shared route composition is registered.
export default function SavedPage() {
  const locale=useLocale(),c=copy[locale];
  return <PageFrame><PageHeader title={c.title}/><PageBody><State kind="error" title={c.error} body={c.compositionPending}><ButtonLink href={`/${locale}/account`}>{c.account}</ButtonLink></State></PageBody></PageFrame>;
}

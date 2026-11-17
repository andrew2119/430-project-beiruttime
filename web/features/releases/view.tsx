'use client';
import { useEffect, useRef, useState } from 'react';
import type { Command } from '@contracts/contracts-orders/releases';
import { Button, ButtonLink, Card, Input, RowSkeleton, State, formatAmount } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { ApiError } from '@/lib/api/client';
import { COPY } from './copy';
import { commandOf, dollars, pending, uuid, type Memory } from './model';
import { operationRead, releaseRead, submit, recover } from './api';

/** Mounted by the canonical shell once its route/read registration is supplied. */
export function ReleaseDesk({actor,organization,fingerprint}: {actor:string;organization:string|null;fingerprint:string}) {
  const locale = useLocale(), t = COPY[locale];
  const [draft,setDraft] = useState(''), [order,setOrder] = useState('');
  const [localMemory,setMemory] = useState<Memory|null>(null), [busy,setBusy] = useState(false), [error,setError] = useState<unknown>(null);
  const flight = useRef(false), alive = useRef(true), frozen = useRef<Memory|null>(null);
  useEffect(()=>{alive.current = true;const revoke=()=>{alive.current=false;frozen.current=null;setMemory(null);setOrder('');setDraft('');};window.addEventListener('bt:access-change',revoke);return()=>{alive.current=false;window.removeEventListener('bt:access-change',revoke);};},[]);
  const query = usePageRead(order ? releaseRead(order,organization,fingerprint) : null);
  const answer = query.data;
  const existingId = answer?.snapshot.active_release_operation_id;
  const restored = usePageRead(existingId ? operationRead(existingId,actor,organization,order,fingerprint) : null);
  const resumed:Memory|null = restored.data ? {command:commandOf(restored.data),result:restored.data} : null;
  const memory = localMemory ?? resumed;
  const money = (amount:number)=>formatAmount(dollars(amount),locale,t.currency,'—');
  const date = (value:string)=>new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut',numberingSystem:locale === 'ar' ? 'arab' : 'latn'}).format(new Date(value));
  async function act() {
    if (!alive.current || flight.current || (existingId && !memory) || (!memory && (!answer || query.isFetching || query.isError || answer.missing.length))) return;
    flight.current = true;setBusy(true);setError(null);
    if (!frozen.current && resumed) frozen.current = resumed;
    if (!frozen.current && answer) {
      const s = answer.snapshot;
      const command:Command = {schema_version:'orders.releases.v1',operation_id:crypto.randomUUID(),actor_id:actor,organization_id:organization,
        subject_id:s.subject_id,watch_id:s.watch_id,expected_revision:s.revision,quote_id:s.quote_id,quote_revision:s.quote_revision,
        policy_revision:s.policy_revision,recipient_id:s.recipient_id,recipient_revision:s.recipient_revision};
      frozen.current = {command,result:null};setMemory(frozen.current);
    }
    const retained = frozen.current;
    if (!retained) {flight.current=false;setBusy(false);return;}
    try {
      const result = retained.result ? await recover(retained.command,fingerprint) : await submit(retained.command,fingerprint);
      if (!alive.current) return;
      frozen.current = {command:retained.command,result};setMemory(frozen.current);
    } catch (failure) {if (alive.current) setError(failure);}
    finally {flight.current=false;if (alive.current) setBusy(false);}
  }
  const deniedAccess = [error,query.error,restored.error].some(failure=>failure instanceof ApiError && (failure.status === 401 || failure.status === 403));
  const state = memory?.result?.state;
  if (deniedAccess) return <PageFrame><PageHeader title={t.title}/><PageBody>
    <State kind="error" title={t.denied} body={t.deniedBody}>
      <Button onClick={()=>{frozen.current=null;setMemory(null);setOrder('');setDraft('');setError(null);}}>{t.refresh}</Button>
      <ButtonLink href={'/'+locale+'/inbox'}>{t.support}</ButtonLink>
    </State>
  </PageBody></PageFrame>;
  return <PageFrame><PageHeader title={t.title} lead={t.lead} notice={<p className="bt-caption">{t.simulated}</p>}/><PageBody>
    <form onSubmit={event=>{event.preventDefault();if (uuid.test(draft) && !memory && !busy) {setOrder(draft);setError(null);}}}>
      <Input label={t.order} value={draft} onValueChange={setDraft} disabled={!!memory || busy} autoComplete="off"/>
      <Button type="submit" disabled={!uuid.test(draft) || !!memory || busy}>{t.open}</Button>
    </form>
    {!order ? <State title={t.empty} body={t.emptyBody}/> : !answer && query.isPending ? <div role="status" aria-label={t.loading}><RowSkeleton/></div> : null}
    {query.isError && <State kind="error" title={t.unavailable} body={t.unavailableBody}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State>}
    {answer && <AnswerArrival view="releases"><Card><dl>
      <dt>{t.order}</dt><dd><bdi>{answer.snapshot.subject_id}</bdi></dd>
      <dt>{t.gross}</dt><dd>{money(answer.snapshot.principal_minor)}</dd>
      <dt>{t.fee}</dt><dd>{money(answer.snapshot.business_fee_minor)}</dd>
      <dt>{t.net}</dt><dd>{money(answer.snapshot.principal_minor-answer.snapshot.business_fee_minor)}</dd>
      <dt>{t.closes}</dt><dd>{answer.closes_at ? <time dateTime={answer.closes_at}>{date(answer.closes_at)}</time> : t.noDate}</dd>
    </dl>
      {answer.missing.length ? <ul>{answer.missing.map(reason=><li key={reason}>{t.reasons[reason]}</li>)}</ul> : <p>{t.ready}</p>}
      <Button variant="outline" busy={query.isFetching} onClick={()=>void query.refetch()}>{t.refresh}</Button>
      {!memory && !existingId && <Button busy={busy} disabled={query.isFetching || query.isError || answer.missing.length > 0} onClick={()=>void act()}>{t.release}</Button>}
    </Card></AnswerArrival>}
    {existingId && !memory && <State kind={restored.isError ? 'error' : 'loading'} title={restored.isError ? t.unavailable : t.loading} body={t.pendingBody}>
      <p className="bt-text"><bdi>{existingId}</bdi></p>
      <Button onClick={()=>void restored.refetch()}>{t.retry}</Button>
    </State>}
    {memory && <Card><p className="bt-caption">{t.reference}</p><p className="bt-text"><bdi>{memory.command.operation_id}</bdi></p>
      <State kind={state === 'denied' ? 'error' : state === 'paid_out' ? 'empty' : 'loading'}
        title={state === 'paid_out' ? t.paid_out : state === 'denied' ? t.denied : t.pending}
        body={state === 'paid_out' ? t.paidBody : state === 'denied' ? t.deniedBody : t.pendingBody}/>
      {memory.result?.missing.map(reason=><p key={reason}>{t.reasons[reason]}</p>)}
      {memory.result?.net_minor != null && <dl><dt>{t.gross}</dt><dd>{money(memory.result.gross_minor!)}</dd><dt>{t.fee}</dt><dd>{money(memory.result.fee_minor!)}</dd><dt>{t.net}</dt><dd>{money(memory.result.net_minor)}</dd></dl>}
      {memory.result?.responsible_operator_id && <p>{t.assigned}: <bdi>{memory.result.responsible_operator_id}</bdi></p>}
      {memory.result && <p>{t.nextAction}: {t.actions[memory.result.next_action]}</p>}
      {memory.result && <p>{t.review} <time dateTime={memory.result.next_review_at}>{date(memory.result.next_review_at)}</time></p>}
      {pending(memory) && <Button busy={busy} disabled={deniedAccess} onClick={()=>void act()}>{t.recover}</Button>}
      {state === 'denied' && <Button onClick={()=>{frozen.current=null;setMemory(null);setError(null);void query.refetch();}}>{t.refresh}</Button>}
    </Card>}
    {error != null && <State kind="error" title={deniedAccess ? t.denied : t.unavailable} body={deniedAccess ? t.deniedBody : t.unavailableBody}/>}
    <ButtonLink href={'/'+locale+'/inbox'} variant="outline">{t.support}</ButtonLink>
  </PageBody></PageFrame>;
}

/** No duplicate provider or shell is installed while route composition is absent. */
export default function PayoutsUnavailable() {
  const locale = useLocale(), t = COPY[locale], session = useSession(), status = useSessionState();
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    {status === 'restoring' ? <div role="status" aria-label={t.loading}><RowSkeleton/></div> :
      <State kind="error" title={t.unavailable} body={t.unavailableBody}>
        <Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button>
        {!session && <ButtonLink href={'/'+locale+'/account'}>{t.signIn}</ButtonLink>}
        <ButtonLink href={'/'+locale+'/inbox'} variant="outline">{t.support}</ButtonLink>
      </State>}
  </PageBody></PageFrame>;
}

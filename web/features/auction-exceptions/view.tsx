'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, ButtonLink, Input, Segmented, Skeleton, State, Textarea } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession } from '@/features/identity/session';
import type { Action, Command, Context, Receipt } from '@contracts/contracts-trust/auction-exceptions/current';
import { copy } from './copy';
import { boundReceipt, initialDraft, newRequest, prepare, rejected, validReason } from './model';
import './view.css';

export { SubmissionRejected } from './model';
export type Connection = {
  context: Context;
  submit: (command: Command, signal: AbortSignal) => Promise<Receipt>;
};
export default function AuctionExceptions({connection, access = 'unavailable'}: {
  connection?: Connection; access?: 'ready' | 'loading' | 'denied' | 'empty' | 'unavailable';
}) {
  const session = useSession();
  const allowed = !!session && access === 'ready' && !!connection;
  const [retainedScope, setRetainedScope] = useState<string | null>(null);
  const scope = !session || access === 'denied' || access === 'empty' ? null : connection
    ? JSON.stringify([connection.context.actor_id, connection.context.organization_id,
      connection.context.subject_id, connection.context.watch_id,
      connection.context.assignment_revision, connection.context.policy_revision])
    : retainedScope;
  if (scope !== retainedScope) setRetainedScope(scope);
  return <PrivateView key={`${session?.access_fingerprint ?? 'signed-out'}:${scope}`} connection={allowed ? connection : undefined} access={!session ? 'denied' : access === 'ready' ? 'unavailable' : access}/>;
}
function PrivateView({connection, access}: {connection?:Connection; access:'loading'|'denied'|'empty'|'unavailable'}) {
  const locale = useLocale();
  const t = copy[locale];
  const [draft, setDraft] = useState(initialDraft);
  const [busy, setBusy] = useState(false);
  const live = useRef(true);
  const active = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { live.current = true; return () => {live.current = false; controller.current?.abort();}; }, []);
  const locked = busy || !!draft.command;
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!validReason(draft.reason) || !connection || active.current || draft.receipt?.state === 'acknowledged' || draft.receipt?.state === 'denied' || draft.rejection) return;
    const next = prepare(draft, connection.context, crypto.randomUUID());
    setDraft(next); setBusy(true); active.current = true;
    const abort = new AbortController(); controller.current = abort;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const deadline = new Promise<never>((_, reject) => { timer = setTimeout(() => {abort.abort(); reject(new Error('pending'));}, 5000); });
      const receipt = await Promise.race([connection.submit(next.command!, abort.signal), deadline]);
      if (live.current && boundReceipt(next.command!, receipt)) setDraft({...next, receipt});
    } catch (error) { if (live.current) setDraft(rejected(next, error)); }
    finally {clearTimeout(timer); active.current = false; if (live.current) setBusy(false);}
  }
  const state = draft.rejection ?? draft.receipt?.state ?? (draft.command ? 'pending' : null);
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody><div className="bt-auction-exceptions">
    {!connection ? <State kind={access === 'loading' ? 'loading' : access === 'empty' ? 'empty' : 'error'} title={t[access]} body={t[`${access}Body`]}>
      {access === 'loading' ? <Skeleton size="card"/> : <ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink>}
    </State> : <form onSubmit={submit} className="bt-auction-exception-form">
      <Segmented label={t.action} value={draft.action} locale={locale} disabled={locked}
        options={(['cancel','retract','remove_bid','seller_end'] as Action[]).map(value => ({value,label:t[value]}))}
        onValueChange={value => setDraft({...draft,action:value as Action})}/>
      {(draft.action === 'retract' || draft.action === 'remove_bid') && <Input label={t.target} value={draft.target} required disabled={locked} onValueChange={value => setDraft({...draft,target:value.slice(0,128)})}/>}
      <Textarea label={t.reason} value={draft.reason} required disabled={locked} onValueChange={value => setDraft({...draft,reason:value})}/>
      <Button type="submit" disabled={!validReason(draft.reason) || busy || state === 'acknowledged' || state === 'denied' || state === 'error'}>{draft.command ? t.retry : t.submit}</Button>
      {(state === 'denied' || state === 'error') && <Button type="button" onClick={() => setDraft(newRequest(draft))}>{t.newRequest}</Button>}
      {state && <State kind={state === 'denied' || state === 'error' ? 'error' : state === 'pending' ? 'loading' : 'empty'} title={t[state]} body={t[`${state}Body`]}>
        <dl><dt>{t.reference}</dt><dd><bdi>{draft.command?.operation_id}</bdi></dd>
          {draft.receipt?.next_actor && <><dt>{t.owner}</dt><dd><bdi>{draft.receipt.next_actor}</bdi></dd></>}
          {draft.receipt?.next_review_at && <><dt>{t.review}</dt><dd><bdi>{draft.receipt.next_review_at}</bdi></dd></>}
        </dl><ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink>
      </State>}
    </form>}
  </div></PageBody></PageFrame>;
}

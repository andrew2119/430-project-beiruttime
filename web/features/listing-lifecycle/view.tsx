'use client';
import { useEffect, useRef, useState } from 'react';
import { BidiReference, Button, ButtonLink, Card, Input, Label, Select, State } from '@beirut-time/ui';
import { PageHeader, PageLayout as PageFrame } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { refreshSession, useSession, useSessionState } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { Action, Command, Receipt } from '@contracts/contracts-catalog/listing-lifecycle/v1';
import { copy } from './copy';
import { useRouter } from 'next/navigation';
import { retainLocaleNavigation } from './locale';
import { blank, commandFor, type Fields } from './form';
import { lookup, send } from './client';
import './styles.css';

export default function LifecyclePage() {
  const session = useSession(), sessionState = useSessionState(), locale = useLocale(), t = copy[locale], router = useRouter();
  useEffect(() => retainLocaleNavigation(document, window, () => router.refresh()), [router]);
  return <PageFrame><PageHeader title={t.title} count={t.intro}/>{session
    ? <LifecycleForm key={session.access_fingerprint} actor={session.principal.actor.subject_id} organization={session.principal.actor.organization_id}/>
    : sessionState === 'restoring'
      ? <State kind="loading" title={t.title} body={t.sessionLoading}/>
      : sessionState === 'unavailable'
        ? <State kind="error" title={t.title} body={t.sessionUnavailable}>
          <Button type="button" onClick={() => void refreshSession().catch(() => {})}>{t.sessionRetry}</Button>
        </State>
        : <State kind="empty" title={t.title} body={t.signIn}>
          <ButtonLink href={`/${locale}/account`}>{t.signInAction}</ButtonLink>
        </State>}</PageFrame>;
}
export function LifecycleForm({actor, organization}: {actor: string; organization: string | null}) {
  const locale = useLocale(), t = copy[locale];
  const [accessDenied, setAccessDenied] = useState(false);
  const [fields, setFields] = useState<Fields>(blank), [kind, setKind] = useState<Action>('pause');
  const [receipt, setReceipt] = useState<Receipt | null>(null), [problem, setProblem] = useState<'invalid' | 'unavailable' | 'denied' | null>(null);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<Command | null>(null);
  const alive = useRef(true), flight = useRef(false), revoked = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function perform() {
    if (flight.current || revoked.current) return;
    let command = pending;
    if (!command) {
      try { command = commandFor(fields, kind, actor, organization, crypto.randomUUID()); }
      catch { setProblem('invalid'); return; }
    }
    flight.current = true; setBusy(true); setProblem(null); setPending(command);
    try {
      let answer: Receipt;
      if (pending) {
        try { answer = await lookup(command); }
        catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
          answer = await send(command);
        }
        if (answer.state === 'pending') answer = await send(command);
      } else answer = await send(command);
      if (alive.current) setReceipt(answer);
    } catch (error) {
      if (alive.current) {
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          revoked.current = true;
          setFields(blank); setKind('pause'); setPending(null); setReceipt(null); setProblem(null);
          setAccessDenied(true);
        } else setProblem('unavailable');
      }
    } finally { flight.current = false; if (alive.current) setBusy(false); }
  }
  if (accessDenied) return <State kind="error" title={t.title} body={t.accessDenied}>
    <ButtonLink href={`/${locale}/account`}>{t.signInAction}</ButtonLink>
  </State>;
  const locked = busy || !!pending;
  const terminal = receipt?.state === 'succeeded' || receipt?.state === 'denied';
  return <Card><form className="l12-form" onSubmit={event => { event.preventDefault(); void perform(); }}>
    <Label htmlFor="l12-action">{t.title}</Label>
    <Select id="l12-action" value={kind} disabled={locked} onValueChange={value => setKind(value as Action)} options={(['pause', 'renew', 'relist'] as const).map(value => ({value, label: t[value]}))}/>
    {(Object.keys(blank) as (keyof Fields)[]).filter(key => kind !== 'pause' || ['listing', 'watch', 'revision', 'proof'].includes(key)).map(key => <div key={key}>
      <Label htmlFor={`l12-${key}`}>{t[key]}</Label>
      <Input id={`l12-${key}`} value={fields[key]} required disabled={locked} maxLength={key === 'listing' || key === 'watch' ? 36 : 128}
        inputMode={key === 'revision' || key === 'quoteRevision' ? 'numeric' : 'text'}
        onChange={event => setFields(current => ({...current, [key]: event.target.value}))}/>
    </div>)}
    {pending && <p>{t.operation}: <BidiReference>{pending.operation_id}</BidiReference></p>}
    {(busy || problem || receipt) && <div role="status"><State kind={busy ? 'loading' : problem ? 'error' : receipt?.state === 'denied' ? 'error' : 'empty'} title={t.title} body={busy ? t.loading : problem ? t[problem] : t[receipt!.state]}/></div>}
    {receipt?.state === 'pending' && <div><p>{t.nextAction}</p><p>{t.support}: <BidiReference>{receipt.responsible_operator_id}</BidiReference></p><p>{t.review}: <BidiReference>{receipt.next_review_at}</BidiReference></p><p>{t.escalation}: <BidiReference>{receipt.escalate_at}</BidiReference></p></div>}
    {!terminal && <Button type="submit" disabled={busy}>{pending ? t.retry : t.submit}</Button>}
    {terminal && <Button type="button" onClick={() => { setPending(null); setReceipt(null); setProblem(null); }}>{t.new}</Button>}
  </form></Card>;
}

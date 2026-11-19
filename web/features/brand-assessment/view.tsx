'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import { Button, Input, Textarea, State, Select } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { useSession, useSessionState } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import type { Current, Command, Kind, Feasibility } from '../../../packages/contracts-service/brand-assessment/v1';
import { assessmentRead, submit, lookupOperation } from './api';
import { words } from './copy';
import './styles.css';

export function reconcileAssessment(result: Current | null, current: Current | undefined) {
  if (!result || !current) return result ?? current;
  const sameBinding = result.subject_id === current.subject_id
    && result.organization_id === current.organization_id
    && result.actor_id === current.actor_id && result.watch_id === (current.current_watch_id ?? current.watch_id)
    && result.request_revision === (current.current_request_revision ?? current.request_revision)
    && result.capability_revision === (current.current_capability_revision ?? current.capability_revision);
  return sameBinding && result.revision > current.revision ? result : current;
}

export function AssessmentForm() {
  const locale = useLocale(), t = words[locale];
  const [draft, setDraft] = useState({ request: '', parts: '', limitations: '', basis: '', reason: '', replacement: '' });
  const [subject, setSubject] = useState('');
  const [feasibility, setFeasibility] = useState<Feasibility>('manual');
  const read = usePageRead(subject ? assessmentRead(subject) : null);
  const [result, setResult] = useState<Current | null>(null);
  const [operation, setOperation] = useState<Command | null>(null);
  const [busy, setBusy] = useState(false);
  const flight = useRef(false);
  const revoked = useRef(false);
  const [status, setStatus] = useState<'idle' | 'saved' | 'pending' | 'denied' | 'stale' | 'unavailable' | 'invalid'>('idle');
  const current = reconcileAssessment(result, read.data);
  const scope = current?.current_scope ?? read.data?.current_scope;
  async function send(command: Command) {
    if (flight.current || revoked.current) return;
    flight.current = true;
    setBusy(true); setOperation(command); setStatus('pending');
    try {
      const answer = await submit(command);
      if (revoked.current) return;
      setResult(answer);
      setStatus(answer.pending_reason ? 'pending' : 'saved');
    } catch (error) {
      if (revoked.current) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        revoked.current = true;
        setResult(null); setOperation(null); setSubject('');
        setDraft({ request: '', parts: '', limitations: '', basis: '', reason: '', replacement: '' });
        setFeasibility('manual');
      }
      setStatus(error instanceof ApiError && [401, 403].includes(error.status) ? 'denied' : error instanceof ApiError && error.status === 409 ? 'stale' : error instanceof ApiError && error.status === 422 ? 'invalid' : 'unavailable');
    } finally { flight.current = false; setBusy(false); }
  }
  async function recoverOperation() {
    if (!current?.operation_id || flight.current || revoked.current) return;
    flight.current = true;
    setBusy(true);
    try {
      const answer = await lookupOperation(current.subject_id, current.operation_id);
      if (revoked.current) return;
      setResult(answer);
      setStatus(answer.pending_reason ? 'pending' : 'saved');
      void read.refetch();
    } catch (error) {
      if (revoked.current) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        revoked.current = true;
        setResult(null); setOperation(null); setSubject('');
        setDraft({ request: '', parts: '', limitations: '', basis: '', reason: '', replacement: '' });
        setFeasibility('manual'); setStatus('denied');
      } else setStatus('unavailable');
    } finally { flight.current = false; setBusy(false); }
  }
  function act(kind: Kind) {
    if (!current || busy || status === 'pending' || status === 'unavailable') return;
    const parts = draft.parts.split('\n').map(part => part.trim()).filter(Boolean);
    if (draft.limitations.length > 4000 || draft.basis.length > 2000 || draft.reason.length > 2000 || draft.replacement.length > 100 || parts.length > 50 || parts.some(part => part.length > 300) || (kind === 'assess' && (!draft.limitations.trim() || !draft.basis.trim())) || (kind === 'correct' && !draft.reason.trim()) || (kind === 'reassign' && !draft.replacement.trim())) { setStatus('invalid'); return; }
    const command: Command = {
      schema_version: 'brand-assessment.v1', operation_id: crypto.randomUUID(), subject_id: subject,
      actor_id: current.actor_id, organization_id: current.organization_id, watch_id: current.current_watch_id ?? current.watch_id,
      expected_revision: current.revision, request_revision: current.current_request_revision ?? current.request_revision,
      assignment_revision: current.assignment_revision, capability_revision: current.current_capability_revision ?? current.capability_revision,
      kind, feasibility, replacement_id: draft.replacement || null,
      parts, limitations: draft.limitations,
      lead_time_basis: draft.basis, reason: draft.reason,
    };
    void send(command);
  }
  const blocked = busy || ['pending', 'unavailable', 'denied', 'stale'].includes(status) || !!current?.pending_reason;
  const readDenied = read.error instanceof ApiError && [401, 403].includes(read.error.status);
  useEffect(() => {
    if (!readDenied) return;
    revoked.current = true;
    // Revoke the mounted private form before any later refresh can reveal it.
    const reset = () => {
      setResult(null); setOperation(null); setSubject(''); setStatus('denied');
      setDraft({ request: '', parts: '', limitations: '', basis: '', reason: '', replacement: '' });
      setFeasibility('manual');
    };
    reset();
  }, [readDenied]);
  if (status === 'denied' || readDenied) return <PageFrame><PageHeader title={t.title}/><PageBody><State kind="error" title={t.denied} body={t.deniedBody}/></PageBody></PageFrame>;
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    <Input label={t.request} value={draft.request} onValueChange={request => setDraft({ ...draft, request })}/>
    <Button disabled={busy || status === 'pending' || status === 'unavailable' || !draft.request.trim() || draft.request.length > 100} onClick={() => { if (subject !== draft.request.trim()) setDraft({ request: draft.request.trim(), parts: '', limitations: '', basis: '', reason: '', replacement: '' }); setSubject(draft.request.trim()); setResult(null); setStatus('idle'); setOperation(null); }}>{t.open}</Button>
    {!subject && <State title={t.empty} body={t.emptyBody}/>}
    {read.isLoading && <PageLoading label={t.loading}/>}
    {read.isError && <State kind="error" title={readDenied ? t.denied : t.unavailable} body={readDenied ? t.deniedBody : t.recovery}><Button onClick={() => void read.refetch()}>{t.retry}</Button></State>}
    {current && !read.isError && <>
      <p>{t.status}: {t[current.state as keyof typeof t] ?? t.missing}</p>
      {current.next_review_at && <p>{t.review}: <bdi>{current.next_review_at}</bdi></p>}
      {scope && <dl className="bt-assessment-scope"><dt>{t.base}</dt><dd><bdi>{scope.base_id}</bdi></dd><dt>{t.caliber}</dt><dd><bdi>{scope.caliber_id}</bdi></dd>{scope.option_snapshots.map(option => <Fragment key={option.dimension}><dt>{t[option.dimension as keyof typeof t] ?? t.missing}</dt><dd><bdi>{option.option_id}</bdi></dd></Fragment>)}</dl>}
      <p className="bt-text">{t.next}: <bdi>{current.responsible_operator_id ?? current.next_actor}</bdi></p>
      {current.next_action && <p>{t.nextAction}: {current.next_action === 'recover_catalog_receipt' ? t.recoverCatalog : t.assignmentPending}</p>}
      {current.escalation_at && <p>{t.escalation}: <bdi>{current.escalation_at}</bdi></p>}
      {current.pending_reason && current.operation_id && <State title={t.pending} body={t.pendingBody}>
        <p className="bt-text">{t.operation}: <bdi>{current.operation_id}</bdi></p>
        <Button disabled={busy} onClick={() => void recoverOperation()}>{t.retry}</Button>
      </State>}
      <SavedAssessment current={current}/>
      <Select label={t.feasibility} value={feasibility} onValueChange={value => setFeasibility(value as Feasibility)}
        options={(['feasible', 'incompatible', 'parts_unavailable', 'manual'] as const).map(value => ({ value, label: t[value] }))}
        messages={{ placeholder: t.feasibility, filter: t.filter, emptyTitle: t.noOptions, emptyBody: t.noOptions, close: t.close, loading: t.optionLoading, errorTitle: t.optionError, errorBody: t.optionBody, retry: t.retry }}/>
      {(['parts', 'limitations', 'basis', 'reason'] as const).map(key => <Textarea key={key} label={t[key]} value={draft[key]} onValueChange={value => setDraft({ ...draft, [key]: value })}/>)}
      <Input label={t.replacement} value={draft.replacement} onValueChange={replacement => setDraft({ ...draft, replacement })}/>
      {(['claim', 'assess', 'correct', 'release', 'reassign'] as const).map(kind => <Button key={kind} disabled={blocked} onClick={() => act(kind)}>{t[kind]}</Button>)}
    </>}
    {operation && <p className="bt-text">{t.operation}: <bdi>{operation.operation_id}</bdi></p>}
    {status !== 'idle' && <State kind={status === 'stale' ? 'error' : 'empty'} title={t[status]} body={status === 'saved' ? t.savedBody : status === 'pending' ? t.pendingBody : status === 'stale' ? t.staleBody : status === 'invalid' ? t.invalidBody : t.recovery}>
      {(status === 'pending' || status === 'unavailable') && operation && <Button disabled={busy} onClick={() => void send(operation)}>{t.retry}</Button>}
      {(status === 'stale' || status === 'saved') && <Button onClick={() => { setResult(null); setStatus('idle'); void read.refetch(); }}>{t.reload}</Button>}
    </State>}
  </PageBody></PageFrame>;
}

export function AssessmentView() {
  useSession();
  const session = useSessionState(), access = useAccessContext(), t = words[useLocale()];
  if (session === 'restoring') return <PageLoading label={t.loading}/>;
  if (session !== 'authenticated') return <PageFrame><PageHeader title={t.title}/><PageBody><State title={t.denied} body={t.deniedBody}/></PageBody></PageFrame>;
  return <AssessmentForm key={access.fingerprint}/>;
}

export function SavedAssessment({ current }: { current: Current }) {
  const t = words[useLocale()];
  if (!current.assessment_id) return null;
  return <section className="bt-assessment-scope" aria-label={t.saved}><h2>{t.saved}</h2><dl>
    <dt>{t.assessment}</dt><dd><bdi>{current.assessment_id}</bdi> · {current.assessment_revision}</dd>
    <dt>{t.assessor}</dt><dd><bdi>{current.assessor_id}</bdi></dd>
    <dt>{t.feasibility}</dt><dd>{current.feasibility ? t[current.feasibility] : t.missing}</dd>
    <dt>{t.parts}</dt><dd>{current.parts?.length ? current.parts.map((part, index) => <p key={index}><bdi>{part}</bdi></p>) : t.noParts}</dd>
    <dt>{t.limitations}</dt><dd><bdi>{current.limitations || t.missing}</bdi></dd>
    <dt>{t.basis}</dt><dd><bdi>{current.lead_time_basis || t.missing}</bdi></dd>
  </dl></section>;
}

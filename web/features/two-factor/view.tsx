'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button, ButtonLink, Card, Input, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame as PageLayout, PageHeader } from '@/shell/foundation/page';
import { useRouter } from 'next/navigation';
import { useLocale } from '@/shell/locale-context';
import { useSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import type { TwoFactorResult } from '@contracts/contracts-identity/two-factor/current';
import { COPY } from './copy';
import { statusRead, submitFactor, type FactorCommand } from './transport';

export default function SecurityView({connected = false}: {connected?: boolean} = {}) {
  const session = useSession(), locale = useLocale(), t = COPY[locale], router = useRouter();
  return <PageLayout><PageHeader title={t.title} lead={t.lead}/><PageBody>
    {!connected ? <State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>router.refresh()}>{t.retry}</Button></State> : session ? <SecurityForm key={session.access_fingerprint} fingerprint={session.access_fingerprint}/> :
      <State title={t.title} body={t.signin}><ButtonLink href={`/${locale}/account`}>{t.signin}</ButtonLink></State>}
  </PageBody></PageLayout>;
}

function SecurityForm({fingerprint}: {fingerprint: string}) {
  const locale = useLocale(), t = COPY[locale];
  const status = usePageRead(statusRead(fingerprint));
  const [password, setPassword] = useState(''), [code, setCode] = useState('');
  const [result, setResult] = useState<TwoFactorResult | null>(null);
  const [message, setMessage] = useState<keyof typeof COPY.en | null>(null);
  const [busy, setBusy] = useState(false);
  const [denied, setDenied] = useState(false);
  const [pending, setPending] = useState<FactorCommand | null>(null);
  const flight = useRef(false);
  // Unmount fences late results; the mounted form survives locale changes.
  const generation = useRef(0);
  useEffect(()=>()=>{ generation.current++; }, []);
  const accessDenied = status.error instanceof ApiError && [401, 403].includes(status.error.status);
  useEffect(()=>{
    if (accessDenied) generation.current++;
  }, [accessDenied]);
  if (accessDenied && !denied) {
    setResult(null); setPassword(''); setCode(''); setPending(null);
    setMessage(null); setBusy(false); setDenied(true);
  }
  const state = result?.state ?? status.data?.state;
  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (denied || accessDenied || flight.current || !status.data || (!pending && (state === 'pending' || state === 'enabled'))) return;
    const command = pending ?? {
      schema_version: 1, operation_id: crypto.randomUUID(), expected_revision: result?.revision ?? status.data.revision,
      kind: state === 'enrolling' && result?.secret ? 'confirm' : 'enroll',
      ...(state === 'enrolling' && result?.secret ? {proof: code} : {current_password: password}),
    } satisfies FactorCommand;
    setPending(command); flight.current = true;
    const token = ++generation.current;
    setBusy(true); setMessage(null);
    try {
      const answer = await submitFactor(command, fingerprint);
      if (token !== generation.current) return;
      if (answer.state === 'pending') {
        setMessage('pending');
      } else {
        setResult(answer); setPending(null); setPassword(''); setCode('');
      }
    } catch (error) {
      if (token !== generation.current) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        generation.current++;
        setResult(null); setPassword(''); setCode(''); setPending(null);
        setMessage(null); setBusy(false); setDenied(true);
      } else if (error instanceof ApiError && [409, 422, 429].includes(error.status)) {
        if (error.status !== 429) setPending(null);
        setMessage(error.status === 409 ? 'stale' : error.status === 422 ? 'invalid' : error.status === 429 ? 'limited' : 'denied');
      } else setMessage('pending');
    } finally { flight.current = false; if (token === generation.current) setBusy(false); }
  }
  if (denied || accessDenied) return <State kind="error" title={t.title} body={t.denied}/>;
  return <div className="bt-page-example-stack">
    {!status.data ? <State kind={status.isError ? 'error' : 'loading'} title={t.title} body={status.isError ? t.unavailable : t.loading}>
      {status.isError && <Button onClick={()=>void status.refetch()}>{t.retry}</Button>}
    </State> : <Card>
      {message && <p role="alert">{t[message]}</p>}
      {state === 'pending' ? <State title={t.recovery} body={t.pendingReset}/> : state === 'enabled' ? <>
        <State title={t.enabled} body={result?.recovery_codes ? t.codes : t.lead}/>
        {result?.recovery_codes && <><ul>{result.recovery_codes.map(value=><li key={value}><bdi dir="ltr">{value}</bdi></li>)}</ul>
          <Button onClick={()=>setResult({...result, recovery_codes: undefined})}>{t.done}</Button></>}
      </> : <form onSubmit={event=>void send(event)}>
        <p>{result?.secret ? t.enrolling : state === 'enrolling' ? t.resume : t.empty}</p>
        {result?.secret ? <><Input label={t.secret} value={result.secret} readOnly/>
          <Input label={t.confirmCode} value={code} onValueChange={setCode} inputMode="numeric" autoComplete="one-time-code" required disabled={busy || !!pending}/></> :
          <Input label={t.password} value={password} onValueChange={setPassword} type="password" autoComplete="current-password" required disabled={busy || !!pending}/>}
        <Button type="submit" busy={busy}>{pending ? t.retry : result?.secret ? t.confirm : t.enroll}</Button>
      </form>}
      <Button variant="outline" disabled={busy || !!pending} onClick={()=>{setResult(null); setMessage(null); void status.refetch();}}>{t.refresh}</Button>
    </Card>}
    <State title={t.recovery} body={t.recoveryBody}><p>{t.supportUnavailable}</p></State>
  </div>;
}

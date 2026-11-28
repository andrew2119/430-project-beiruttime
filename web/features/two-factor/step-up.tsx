'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button, Input, State } from '@beirut-time/ui/foundation';
import type { SensitiveAction } from '@contracts/contracts-identity/two-factor/current';
import { useLocale } from '@/shell/locale-context';
import { useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { COPY } from './copy';
import { submitFactor, type FactorCommand } from './transport';

export type ProofScope = {
  action: SensitiveAction; record_id: string; record_revision: number;
  organization_id: string | null; factor_revision: number;
};
type Props = {scope: ProofScope; onProof: (proof: {proof_id: string; expires_at: string; revision: number})=>void};
export function SensitiveProofForm(props: Props) {
  const session = useSession(), locale = useLocale(), t = COPY[locale];
  // A changed action or access scope discards private inputs. Locale is not identity.
  const identity = JSON.stringify([session?.access_fingerprint, props.scope]);
  return session ? <ProofForm key={identity} scope={props.scope} onProof={props.onProof} fingerprint={session.access_fingerprint}/> : <State title={t.prove} body={t.signin}/>;
}
function ProofForm({scope, onProof, fingerprint}: Props & {fingerprint: string}) {
  const locale = useLocale(), t = COPY[locale];
  const [code, setCode] = useState(''), [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<FactorCommand | null>(null);
  const [message, setMessage] = useState<keyof typeof COPY.en | null>(null);
  const flight = useRef(false), live = useRef(true);
  const [denied, setDenied] = useState(false);
  useEffect(()=>{live.current = true; return ()=>{live.current = false;};}, []);
  async function send(event: FormEvent) {
    event.preventDefault();
    if (denied || flight.current || message === 'verified') return;
    const command: FactorCommand = pending ?? {
      schema_version: 1, operation_id: crypto.randomUUID(), kind: 'prove',
      expected_revision: scope.factor_revision, proof: code, action: scope.action,
      record_id: scope.record_id, record_revision: scope.record_revision, organization_id: scope.organization_id,
    };
    flight.current = true; setBusy(true); setPending(command); setMessage(null);
    try {
      const result = await submitFactor(command, fingerprint);
      if (!live.current) return;
      if (result.state === 'proved' && result.proof_id && result.expires_at) {
        setCode(''); setPending(null); setMessage('verified');
        onProof({proof_id: result.proof_id, expires_at: result.expires_at, revision: result.revision});
      } else setMessage('pending');
    } catch (error) {
      if (!live.current) return;
      if (error instanceof ApiError && [401,403].includes(error.status)) {
        live.current = false;
        setCode(''); setPending(null); setMessage(null); setBusy(false); setDenied(true);
      } else if (error instanceof ApiError && [409,422,429].includes(error.status)) {
        if (error.status !== 429) setPending(null);
        setMessage(error.status === 409 ? 'stale' : error.status === 422 ? 'invalid' : error.status === 429 ? 'limited' : 'denied');
      } else setMessage('pending');
    } finally {flight.current = false; if (live.current) setBusy(false);}
  }
  if (denied) return <State kind="error" title={t.prove} body={t.denied}/>;
  return <form onSubmit={event=>void send(event)}>
    <Input label={t.code} value={code} onValueChange={setCode} autoComplete="one-time-code" required disabled={busy || !!pending || message === 'verified'}/>
    {message && <p role="status">{t[message]}</p>}
    <Button type="submit" busy={busy} disabled={message === 'verified'}>{pending ? t.retry : t.prove}</Button>
  </form>;
}

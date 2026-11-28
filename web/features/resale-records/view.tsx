'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, ButtonLink, State } from '@beirut-time/ui/foundation';
import { PageHeader, PageFrame } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { acceptsResult, beginTransfer, type TransferBoundary, type TransferCommand, type TransferState } from './model';
import en from './en.json';
import ar from './ar.json';

export default function ResaleRecords({ accessKey = '', candidate, boundary }: {
  accessKey?: string; candidate?: Omit<TransferCommand, 'operation_id'>; boundary?: TransferBoundary;
}) {
  return <Workspace key={accessKey} candidate={candidate} boundary={boundary} />;
}
function Workspace({ candidate, boundary }: { candidate?: Omit<TransferCommand, 'operation_id'>; boundary?: TransferBoundary }) {
  const locale = useLocale(), t = locale === 'ar' ? ar : en;
  const [state, setState] = useState<TransferState>(boundary ? 'empty' : 'unavailable');
  const [busy, setBusy] = useState(false);
  const [reference, setReference] = useState('');
  const operation = useRef<TransferCommand | null>(null);
  const controller = useRef<AbortController | null>(null);
  const revoked = useRef(false);
  useEffect(() => {
    revoked.current = false;
    const clear = () => {
      revoked.current = true; controller.current?.abort(); operation.current = null;
      setReference(''); setState('denied'); setBusy(false);
    };
    window.addEventListener('bt:access-change', clear);
    return () => { revoked.current = true; controller.current?.abort(); window.removeEventListener('bt:access-change', clear); };
  }, []);
  async function transfer() {
    if (busy || revoked.current || !boundary || !candidate) return;
    operation.current ??= beginTransfer(candidate, crypto.randomUUID());
    const command = operation.current;
    setReference(command.operation_id); setBusy(true); setState('pending');
    const request = new AbortController(); controller.current = request;
    const timer = window.setTimeout(() => request.abort(), 5000);
    try {
      const result = await boundary.transfer(command, request.signal);
      if (!revoked.current) setState(acceptsResult(command, result) ? result.state : 'pending');
    } catch { if (!revoked.current) setState('pending'); }
    finally { window.clearTimeout(timer); if (!revoked.current) setBusy(false); }
  }
  const canTransfer = !!candidate && !!boundary && (state === 'empty' || state === 'pending');
  return <PageFrame>
    <PageHeader title={t.title} />
    <p>{t.intro}</p><p>{t.qualification}</p>
    <State kind={busy ? 'loading' : state === 'transferred' ? 'empty' : state === 'empty' ? 'empty' : 'error'} title={t.title} body={t[state]}>
      {reference && <p>{t.reference}: <bdi>{reference}</bdi></p>}
      {canTransfer && <Button disabled={busy} onClick={() => void transfer()}>{state === 'pending' ? t.retry : t.submit}</Button>}
      <ButtonLink href={`/${locale}/seller`}>{t.back}</ButtonLink>
    </State>
  </PageFrame>;
}

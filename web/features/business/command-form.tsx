'use client';
import { useEffect, useRef, useState, type ReactNode, type Ref, type FormEventHandler } from 'react';
import { Button, State } from '@beirut-time/ui/foundation';
import type { BusinessResult } from '@contracts/contracts-identity/businesses/workspace_v2';
import { ApiError } from '@/lib/api/client';
import { BusinessOperation } from './operation-v2';
import { Feedback, useAction, useCopy } from './components';

export function knownRejection(error:unknown) {
  return error instanceof ApiError && [400,403,409,413,415,422].includes(error.status);
}

export function accessDenied(error: unknown) {
  return error instanceof ApiError && [401, 403].includes(error.status);
}

export type PendingChange = (pending: boolean, operationId: string, operation?: BusinessOperation) => void;

export function usePendingCommands(ownsOperations = true) {
  const [operations, setOperations] = useState<ReadonlySet<string>>(new Set());
  const [recovery] = useState(new Map<string, BusinessOperation>());
  useEffect(() => () => {
    if (ownsOperations) { recovery.forEach(operation => operation.dispose()); recovery.clear(); }
  }, [recovery, ownsOperations]);
  const onPending: PendingChange = (pending, operationId, operation) => setOperations(previous => {
    if (pending && operation) recovery.set(operationId, operation);
    if (!pending) recovery.delete(operationId);
    const next = new Set(previous);
    if (pending) next.add(operationId); else next.delete(operationId);
    return next;
  });
  return { busy: operations.size > 0, onPending, recovery };
}

/** Keep the mounted command's source facts until its immutable request resolves.
 * Temporary failures and newer revisions cannot replace an unresolved form.
 * Denial and access changes clear private facts immediately. */
export function useCommandSnapshot<T>(value: T, pending: boolean, scope: string | null, denied = false) {
  const permittedValue = denied ? undefined : value;
  const [snapshot, setSnapshot] = useState({ scope, value: permittedValue });
  if (snapshot.scope !== scope || (denied && snapshot.value !== undefined) || (!pending && snapshot.value !== permittedValue)) {
    setSnapshot({ scope, value: permittedValue });
  }
  return denied ? undefined : pending && snapshot.scope === scope ? snapshot.value : value;
}

export function CommandForm({ children, submit, onComplete, onPending, disabled=false, formRef, onChange }: {
  children: ReactNode;
  formRef?: Ref<HTMLFormElement>;
  onChange?: FormEventHandler<HTMLFormElement>;
  submit: (data: FormData, operation: BusinessOperation) => Promise<BusinessResult>;
  onComplete: () => void;
  onPending?: PendingChange;
  disabled?: boolean;
}) {
  const t = useCopy(), action = useAction();
  const retry = useRef<(() => Promise<BusinessResult>) | null>(null);
  const operation = useRef<BusinessOperation | null>(null);
  const resolved = useRef(false);
  const [started, setStarted] = useState(false);
  const [reference, setReference] = useState('');
  const [rejected, setRejected] = useState(false);
  const [result, setResult] = useState<BusinessResult | null>(null);
  useEffect(() => () => { if (resolved.current) operation.current?.dispose(); }, []);
  const blocked = action.pending || (disabled && (rejected || result?.operation_state === 'committed'));
  const isBlocked = () => action.pending || (disabled && resolved.current);
  const run = (invoke: () => Promise<BusinessResult>) => {
    if (isBlocked()) return;
    void action.run(async () => {
    resolved.current = false;
    setRejected(false);
    setResult(null);
    onPending?.(true, operation.current!.id, operation.current!);
    try {
      const response = await invoke();
      setResult(response);
      if (response.operation_state === 'committed') {resolved.current = true; onPending?.(false, operation.current!.id); onComplete();}
    } catch (error) {
      if (knownRejection(error) && !accessDenied(error)) {resolved.current = true; setRejected(true);onPending?.(false, operation.current!.id);}
      throw error;
    }
  }, false);
  };
  return <div>
    <form ref={formRef} onChange={onChange} className="business-form" onSubmit={event => {
      event.preventDefault();
      if (started || action.pending || disabled) return;
      const data = new FormData(event.currentTarget);
      operation.current ??= new BusinessOperation();
      const current = operation.current;
      setReference(current.id);
      setStarted(true);
      onPending?.(true, operation.current!.id, operation.current!);
      retry.current = () => submit(data, current);
      current.retainSubmission(retry.current);
      run(retry.current);
    }}>
      <fieldset disabled={started || action.pending || disabled} className="business-command-fields">{children}</fieldset>
      <Button type="submit" disabled={started || disabled} busy={action.pending}>{t.save}</Button>
    </form>
    {started && <>
      <p>{t.actionReference}: <bdi dir="ltr">{reference}</bdi></p>
      <State kind={rejected ? "error" : result?.operation_state === "committed" ? "empty" : "loading"} title={rejected ? t.checkFields : result?.operation_state === "committed" ? t[result.state] : t.pending} body={rejected ? t.reviewChanges : t.operationHelp} />
      {result?.next_actor && <p>{t.responsible}: <bdi>{result.next_actor}</bdi></p>}
      {result?.next_review_at && <p>{t.followUp}: <bdi>{result.next_review_at}</bdi></p>}
      <Button disabled={blocked} onClick={() => run(() => operation.current!.recover())}>{t.recoverAction}</Button>
      <Button disabled={blocked} onClick={() => run(() => retry.current!())}>{t.retry}</Button>
      {(rejected || (result && result.operation_state === 'committed')) && <Button disabled={blocked} onClick={() => {
        if (isBlocked() || !resolved.current) return;
        onPending?.(false, operation.current!.id); operation.current?.dispose(); operation.current = null; setStarted(false); setResult(null); setRejected(false); retry.current = null; onComplete();
      }}>{t.newAction}</Button>}
    </>}
    <Feedback error={action.error} />
  </div>;
}

/** Recovery contains action references only; denied records stay unmounted. */
export function PendingRecovery({ recovery, onPending, refresh }: {
  recovery: ReadonlyMap<string, BusinessOperation>; onPending: PendingChange; refresh: () => void;
}) {
  const t = useCopy(), action = useAction();
  return <>{Array.from(recovery, ([id, operation]) => <div key={id}>
    <p>{t.actionReference}: <bdi dir="ltr">{id}</bdi></p>
    <Button disabled={action.pending} onClick={() => void action.run(async () => {
      const result = await operation.recover();
      if (result.operation_state === 'committed') { onPending(false, id); operation.dispose(); refresh(); }
    }, false)}>{t.recoverAction}</Button>
    <Button disabled={action.pending} onClick={() => void action.run(async () => {
      try {
        const result = await operation.replay();
        if (result.operation_state === 'committed') { onPending(false, id); operation.dispose(); refresh(); }
      } catch (error) {
        if (knownRejection(error) && !accessDenied(error)) { onPending(false, id); operation.dispose(); refresh(); }
        throw error;
      }
    }, false)}>{t.retry}</Button>
  </div>)}<Feedback error={action.error} /></>;
}

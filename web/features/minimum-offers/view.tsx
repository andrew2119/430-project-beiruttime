'use client';
import { useCallback, useReducer, useRef, useState } from 'react';
import { Button, Card, Input, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import type { Command, Result, Rule } from '../../../packages/contracts-pricing/minimum-offers/v1';
import { dollarCents, dollars, settle, formReducer, localizedForm, type Operation } from './model';

export type Current = Rule & { binding: Omit<Command, 'operation_id' | 'minimum_minor' | 'expected_revision'> };
export type Gateway = { save: (command: Command, signal: AbortSignal) => Promise<Result>; reload: () => void };
export type ScreenProps = {
  scopeKey: string; current?: Current; gateway?: Gateway;
  state: 'ready' | 'loading' | 'denied' | 'unavailable';
};

/** Only access-scope changes replace this key; reloads keep the same form. */
export default function MinimumOffers(props: ScreenProps) {
  return <PrivateForm key={props.scopeKey} scopeKey={props.scopeKey} current={props.current} gateway={props.gateway} state={props.state}/>;
}
function PrivateForm({current, gateway, state}: ScreenProps) {
  const locale = useLocale();
  const [draft, dispatch] = useReducer(formReducer, {amount: null, operation: null});
  const { text: t } = localizedForm(draft, locale);
  const { amount, operation } = draft;
  const setAmount = (value: string) => dispatch({type: 'amount', value});
  const setOperation = (value: Operation | null) => dispatch({type: 'operation', value});
  const [invalid, setInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  // Ref cleanup synchronously fences late completions on access-scope replacement.
  const root = useCallback((node: HTMLDivElement | null) => {
    if (!node) { generation.current++; active.current?.abort(); }
  }, []);
  const phase = operation?.phase;
  const locked = busy || phase === 'pending' || phase === 'stale' || phase === 'denied';
  const available = state === 'ready' && phase !== 'denied' && !!current && !!gateway;
  async function submit(remove = false) {
    if (!available || inFlight.current || phase === 'stale') return;
    const cents = remove ? null : dollarCents(amount ?? dollars(current.minimum_minor));
    if (phase !== 'pending' && !remove && cents === null) { setInvalid(true); return; }
    const command = phase === 'pending' && operation ? operation.command : {
      ...current.binding, expected_revision: phase === 'saved' && operation ? operation.command.expected_revision + 1 : current.revision,
      operation_id: crypto.randomUUID(), minimum_minor: cents,
    };
    const pending: Operation = { command, phase: 'pending' };
    setOperation(pending); setBusy(true); inFlight.current = true;
    const token = generation.current;
    const controller = new AbortController(); active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 2000);
    try {
      const result = await Promise.race([
        gateway.save(command, controller.signal),
        new Promise<Result>((_resolve, reject) => controller.signal.addEventListener('abort', () => reject(new Error('pending')), {once: true})),
      ]);
      if (token === generation.current) {
        const next = settle(pending, result);
        setOperation(next);
        if (next.phase === 'saved') setAmount(dollars(command.minimum_minor));
      }
    } catch {
      // An uncertain response retains the exact immutable command for retry.
    } finally {
      clearTimeout(timeout);
      if (token === generation.current) { setBusy(false); inFlight.current = false; }
    }
  }
  const outcome = state === 'ready' ? phase : state;
  const status = outcome === 'loading' || outcome === 'denied' || outcome === 'unavailable' || outcome === 'pending' || outcome === 'stale' || outcome === 'saved' ? outcome : null;
  return <div ref={root}><PageFrame>
    <PageHeader title={t.title} lead={t.intro}/>
    <PageBody><Card>
      {status && <State title={t[status]} body={t[`${status}Body`]} kind={status === 'loading' || status === 'pending' ? 'loading' : status === 'saved' ? 'empty' : 'error'}/>}
      {available && <form onSubmit={event => { event.preventDefault(); void submit(); }}>
        {current.minimum_minor === null && !operation && <State title={t.empty} body={t.emptyBody}/>}
        <Input id="private-offer-minimum" label={t.amount} inputMode="decimal" error={invalid ? t.invalid : undefined}
          value={amount ?? dollars(current.minimum_minor)} disabled={locked}
          onValueChange={value => { if (value.length <= 17) setAmount(value); setInvalid(false); }}/>
        <Button type="submit" disabled={locked}>{t.save}</Button>
        <Button type="button" variant="outline" disabled={locked} onClick={() => void submit(true)}>{t.remove}</Button>
        {phase === 'pending' && <Button type="button" disabled={busy} onClick={() => void submit()}>{t.retry}</Button>}
      </form>}
      {gateway && state !== 'loading' && (phase !== 'pending' || state === 'unavailable') && <Button type="button" variant="outline" onClick={() => {
        if (phase !== 'pending') {
          dispatch({type: 'reset'});
          setInvalid(false);
        }
        gateway.reload();
      }}>{t.reload}</Button>}
    </Card></PageBody>
  </PageFrame></div>;
}

'use client';
import { useEffect, useId, useState } from 'react';
import { usePageRead } from '@/lib/page-speed/read';
import { movementsRead, movementRead, selectionRead } from '../service-directory/reads';
import { Button, Input, Card, State, Select, formatNumber } from '@beirut-time/ui/foundation';
import { ApiError } from '@/lib/api/client';
import { useSession } from '@/features/identity/session';
import { SignInAction } from '../service-directory/auth-action';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { movementPath, useJsonCommand, useCommandMutation } from '../service-directory/api';
import type { Configuration, Movement, MovementSelection } from '@contracts/contracts-service/directory';
import en from './en.json';
import ar from './ar.json';
import { MovementOffering } from './offering';
import { formatMinor } from './money';
import { privateReadDenied } from '../service-directory/private-read';
import { selectMessages } from '../service-directory/select-messages';

function initialConfiguration(option?: Movement): Configuration {
  return { case: option?.cases[0] ?? '', dial: option?.dials[0] ?? '', hands: option?.hands[0] ?? '', functions: option?.functions ?? [] };
}

export default function MovementOption({ brandId, sample, onLockChange }: { brandId: string; sample: boolean; onLockChange?:(locked:boolean)=>void }) {
  useSession();
  const locale = useLocale();
  const t = locale === 'ar' ? ar : en;
  const headingId = useId();
  const access = useAccessContext();
  const signedIn = access.roles.includes('buyer');
  const command = useJsonCommand();
  const [staffLocked,setStaffLocked]=useState(false);
  const [optionId, setOptionId] = useState('');
  const [draft, setConfiguration] = useState<Configuration | null>(null);
  const [draftRevision, setDraftRevision] = useState<number | null>(null);
  const [functionsText, setFunctionsText] = useState<string | null>(null);
  const [cursors,setCursors]=useState<(string|null)[]>([null]);
  const options = usePageRead(movementsRead(brandId,cursors.at(-1)??null));
  const saved = usePageRead(signedIn && access.fingerprint ? selectionRead(access.fingerprint,brandId):null);
  const [accessDenied, setAccessDenied] = useState(false);
  const [hideResult, setHideResult] = useState(false);
  const denied = privateReadDenied(saved.error);
  if (denied && !accessDenied) {
    setAccessDenied(true);
    setHideResult(true);
    setOptionId('');
    setConfiguration(null);
    setDraftRevision(null);
    setFunctionsText(null);
  } else if (accessDenied && !denied && saved.isSuccess && !saved.isFetching) {
    setAccessDenied(false);
  }
  const privateBlocked = denied || accessDenied || !signedIn;
  const stored = privateBlocked ? null : saved.data?.selection;
  const published = options.data?.items ?? [];
  const pinnedId=optionId||stored?.option_id;
  const specific = usePageRead(pinnedId && !published.some(item=>item.id===pinnedId) ? movementRead(pinnedId):null);
  const movements = specific.data && specific.data.item.brand_id === brandId && !published.some(item => item.id === specific.data.item.id)
    ? [...published, specific.data.item] : published;
  const selected = movements.find(item => item.id === (optionId || stored?.option_id)) ?? (pinnedId?undefined:movements[0]);
  const configuration = draft ?? (stored && stored.option_id === selected?.id ? stored.configuration : initialConfiguration(selected));
  const optionRevision = draftRevision ?? (stored?.option_id === selected?.id ? stored?.option_revision : selected?.revision);
  const draftStale = Boolean(selected && optionRevision !== selected.revision);
  const mutation = useCommandMutation({
    mutationFn: () => command<MovementSelection>(`${movementPath}/selections`, {
      brand_id: brandId,
      option_id: selected?.id,
      option_revision: optionRevision,
      expected_revision: saved.data?.selection_revision ?? stored?.revision ?? 0,
      configuration: {
        ...configuration,
        functions: functionsText === null ? configuration.functions : functionsText.split(/[,،]/).map(value => value.trim()).filter(Boolean),
      },
    }),
    onSuccess: () => {
      setHideResult(false);
      void saved.refetch();
      setConfiguration(null);
      setDraftRevision(null);
      setFunctionsText(null);
    },
  });
  useEffect(()=>{onLockChange?.(staffLocked||mutation.isPending||mutation.needsRecovery);return()=>onLockChange?.(false);},[staffLocked,mutation.isPending,mutation.needsRecovery,onLockChange]);
  function chooseOption(id: string) {
    if (staffLocked || mutation.isPending || mutation.needsRecovery) return;
    const option = movements.find(item => item.id === id);
    if (!option) return;
    setOptionId(id);
    setConfiguration(initialConfiguration(option));
    setDraftRevision(option.revision);
    setFunctionsText(null);
    mutation.reset();
  }
  const result = privateBlocked || hideResult ? null : mutation.data ?? (!draft && functionsText === null ? stored : null);
  const outdated = result && selected && (result.option_id !== selected.id || result.option_revision !== selected.revision);
  const currentStoredOption = movements.find(item => item.id === stored?.option_id);
  const snapshotOutdated = stored && options.isSuccess && !specific.isFetching
    && (!currentStoredOption || stored.option_revision !== currentStoredOption.revision);
  const restoring = signedIn && (saved.isPending || specific.isFetching);
  const reload = () => {
    void options.refetch();
    if (signedIn) void saved.refetch();
    if (stored) void specific.refetch();
  };

  return <Card className="movement-panel"><section aria-labelledby={headingId}>
    <p className="eyebrow">{t.option}</p>
    <h2 id={headingId}>{t.title}</h2>
    <p>{t.intro}</p>
    {sample && <p className="directory-demo">{t.sample}</p>}
    <MovementOffering onLockChange={setStaffLocked} brandId={brandId} selected={selected} onSaved={()=>void options.refetch()}/>
    {stored && <div className="movement-snapshot" role="group" aria-label={t.restored}>
      <p className="eyebrow">{t.restored}</p>
      <dl>
        <div><dt>{t.savedOption}</dt><dd><bdi>{stored.option_id} · v{stored.option_revision}</bdi></dd></div>
        <div><dt>{t.impact}</dt><dd><bdi>{formatMinor(stored.quote_impact.minor, stored.quote_impact.currency, locale)}</bdi></dd></div>
        {(['case', 'dial', 'hands'] as const).map(field => <div key={field}><dt>{t[field]}</dt><dd><bdi>{stored.configuration[field]}</bdi></dd></div>)}
        <div><dt>{t.functions}</dt><dd><bdi>{stored.configuration.functions.join(', ') || '—'}</bdi></dd></div>
      </dl>
      {snapshotOutdated && <p role="status">{t.stale}</p>}
      <p>{t[stored.status]}</p>
    </div>}
    {!privateBlocked&&saved.data?.archived&&<p role="status">{t.archived}</p>}
    {!privateBlocked&&!selected&&pinnedId&&movements.length>0&&<Select label={t.replacement} value={null} onValueChange={chooseOption} disabled={staffLocked||restoring||mutation.isPending||mutation.needsRecovery} messages={selectMessages(locale)} options={movements.map(item=>({value:item.id,label:locale==='ar'?item.label_ar:item.label_en}))}/>}
    {!selected&&options.data?.next_after&&<Button type="button" disabled={staffLocked||mutation.isPending||mutation.needsRecovery} onClick={()=>setCursors(value=>[...value,options.data?.next_after??null])}>{t.more}</Button>}
    {privateBlocked && signedIn ? <State kind="error" title={t.title} body={t.authDenied}><Button onClick={()=>void saved.refetch()}>{t.retry}</Button></State> : options.isPending && !options.data ? <State kind="loading" title={t.title} body={t.loading}/> : options.isError && !options.data ? <div role="alert">
      <p>{t.error}</p><Button variant="outline" onClick={reload}>{t.retry}</Button>
    </div> : !selected ? <State title={t.title} body={pinnedId?t.stale:t.empty}><Button onClick={reload}>{t.retry}</Button></State> : <form onSubmit={event => { event.preventDefault(); if (!draftStale || mutation.needsRecovery) mutation.mutate(); }}>
      <Select name="movement-option" label={t.option} value={selected.id} onValueChange={chooseOption} disabled={staffLocked||restoring||mutation.isPending||mutation.needsRecovery} messages={selectMessages(locale)} options={movements.map(item=>({value:item.id,label:locale==='ar'?item.label_ar:item.label_en}))}/>
      <p className="bt-text">{t.total} · {formatNumber(options.data?.total??0,locale)}</p>
      {cursors.length>1&&<Button type="button" variant="outline" disabled={staffLocked||mutation.isPending||mutation.needsRecovery} onClick={()=>{setOptionId(selected.id);setCursors(value=>value.slice(0,-1));}}>{t.previous}</Button>}
      {options.data?.next_after&&<Button type="button" variant="outline" disabled={options.isFetching||staffLocked||mutation.isPending||mutation.needsRecovery} onClick={()=>{setOptionId(selected.id);setCursors(value=>[...value,options.data?.next_after??null]);}}>{t.more}</Button>}
      <div className="movement-facts">
        <span>{t.caliber}<br /><strong><bdi>{selected.caliber}</bdi></strong></span>
        <span>{t.impact}<br /><strong><bdi>{formatMinor(selected.quote_minor, selected.currency, locale)}</bdi></strong></span>
      </div>
      <p className="directory-muted">{t.units}</p>
      <div className="movement-fields">
        {(['case', 'dial', 'hands'] as const).map(field => <Input key={field} label={t[field]} required value={configuration[field]} disabled={staffLocked||restoring||mutation.isPending||mutation.needsRecovery} onValueChange={value => {
            setOptionId(selected.id);setDraftRevision(optionRevision ?? selected.revision);setConfiguration({ ...configuration, [field]: value }); mutation.reset();
          }} />)}
      </div>
      <Input label={t.functions} value={functionsText ?? configuration.functions.join(', ')} disabled={staffLocked||restoring||mutation.isPending||mutation.needsRecovery} onValueChange={value => {setOptionId(selected.id);setDraftRevision(optionRevision ?? selected.revision);setFunctionsText(value);mutation.reset();}} />
      {draftStale && <div role="alert"><p>{t.reviewChanged}</p><Button type="button" disabled={staffLocked||restoring||mutation.isPending||mutation.needsRecovery} onClick={()=>{setDraftRevision(selected.revision);mutation.reset();}}>{t.reviewCurrent}</Button></div>}
      {result && <p className="notice" role="status">{outdated ? t.stale : t[result.status]}</p>}
      {mutation.isError && <p role="alert">{mutation.error instanceof ApiError && mutation.error.code === 'stale_revision' ? t.stale : t.saveError}</p>}
      {(saved.isError || specific.isError) && <div role="alert"><p>{t.saveError}</p><Button variant="outline" type="button" onClick={reload}>{t.retry}</Button></div>}
      {signedIn
        ? <Button type="submit" aria-busy={mutation.isPending} disabled={staffLocked || mutation.isPending || restoring || saved.isError || (draftStale && !mutation.needsRecovery)}>{mutation.isPending ? t.saving : mutation.needsRecovery?t.retryOriginal:t.save}</Button>
        : <SignInAction next={`/services?purpose=customization&business=${brandId}`} label={t.signin}/>}
    </form>}
    {options.isError&&options.data&&<State kind="error" title={t.title} body={t.error}><Button onClick={reload}>{t.retry}</Button></State>}
  </section></Card>;
}

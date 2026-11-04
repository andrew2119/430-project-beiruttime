'use client';
import { useId, useState } from 'react';
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, BidiReference, Input } from '@beirut-time/ui';
import { request, ApiError } from '@/lib/api/client';
import { useSession } from '@/features/identity/session';
import { SignInAction } from '../service-directory/auth-action';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { movementPath, privateRequest, useJsonCommand } from '../service-directory/api';
import type { Configuration, Movement, MovementSelection } from '@contracts/contracts-service/directory';
import en from './en.json';
import ar from './ar.json';
import { formatMinor } from './money';

type OptionsPage = { items: Movement[]; next_after: string | null };
function initialConfiguration(option?: Movement): Configuration {
  return { case: option?.cases[0] ?? '', dial: option?.dials[0] ?? '', hands: option?.hands[0] ?? '', functions: option?.functions ?? [] };
}

export default function MovementOption({ brandId, sample }: { brandId: string; sample: boolean }) {
  useSession();
  const locale = useLocale();
  const t = locale === 'ar' ? ar : en;
  const headingId = useId();
  const access = useAccessContext();
  const signedIn = access.roles.includes('buyer');
  const queryClient = useQueryClient();
  const command = useJsonCommand();
  const [optionId, setOptionId] = useState('');
  const [draft, setConfiguration] = useState<Configuration | null>(null);
  const [functionsText, setFunctionsText] = useState<string | null>(null);
  const options = useInfiniteQuery({
    queryKey: ['movement-options', brandId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<OptionsPage>(`${movementPath}?brand_id=${brandId}${pageParam ? `&after=${pageParam}` : ''}`, { signal }),
    getNextPageParam: page => page.next_after ?? undefined,
    retry: false,
  });
  const savedKey = ['movement-selection', access.fingerprint, brandId];
  const saved = useQuery({
    queryKey: savedKey,
    queryFn: ({ signal }) => privateRequest<{ selection: MovementSelection | null }>(`${movementPath}/selections/current?brand_id=${brandId}`, { signal }),
    enabled: signedIn,
    retry: false,
  });
  const stored = saved.data?.selection;
  const published = options.data?.pages.flatMap(page => page.items) ?? [];
  // A restored choice may be beyond the first page; never silently replace its caliber.
  const specific = useQuery({
    queryKey: ['movement-option', stored?.option_id],
    queryFn: ({ signal }) => request<{ item: Movement }>(`${movementPath}/${stored?.option_id}`, { signal }),
    enabled: Boolean(stored && !published.some(item => item.id === stored.option_id)),
    retry: false,
  });
  const movements = specific.data && specific.data.item.brand_id === brandId && !published.some(item => item.id === specific.data.item.id)
    ? [...published, specific.data.item] : published;
  const selected = movements.find(item => item.id === (optionId || stored?.option_id)) ?? movements[0];
  const configuration = draft ?? (stored && stored.option_id === selected?.id ? stored.configuration : initialConfiguration(selected));
  const mutation = useMutation({
    mutationFn: () => command<MovementSelection>(`${movementPath}/selections`, {
      brand_id: brandId,
      option_id: selected?.id,
      option_revision: selected?.revision,
      expected_revision: stored?.revision ?? 0,
      configuration: {
        ...configuration,
        functions: functionsText === null ? configuration.functions : functionsText.split(/[,،]/).map(value => value.trim()).filter(Boolean),
      },
    }),
    onSuccess: result => {
      queryClient.setQueryData(savedKey, { selection: result });
      setConfiguration(null);
      setFunctionsText(null);
    },
  });
  function chooseOption(id: string) {
    const option = movements.find(item => item.id === id);
    if (!option) return;
    setOptionId(id);
    setConfiguration(initialConfiguration(option));
    setFunctionsText(null);
    mutation.reset();
  }
  const result = mutation.data ?? (!draft && functionsText === null ? stored : null);
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

  return <section className="movement-panel" aria-labelledby={headingId}>
    <p className="eyebrow">{t.option}</p>
    <h2 id={headingId}>{t.title}</h2>
    <p>{t.intro}</p>
    {sample && <p className="directory-demo">{t.sample}</p>}
    {stored && <div className="movement-snapshot" role="group" aria-label={t.restored}>
      <p className="eyebrow">{t.restored}</p>
      <dl>
        <div><dt>{t.savedOption}</dt><dd><BidiReference>{stored.option_id} · v{stored.option_revision}</BidiReference></dd></div>
        <div><dt>{t.impact}</dt><dd><BidiReference>{formatMinor(stored.quote_impact.minor, stored.quote_impact.currency, locale, t.minorUnits)}</BidiReference></dd></div>
        {(['case', 'dial', 'hands'] as const).map(field => <div key={field}><dt>{t[field]}</dt><dd><BidiReference>{stored.configuration[field]}</BidiReference></dd></div>)}
        <div><dt>{t.functions}</dt><dd><BidiReference>{stored.configuration.functions.join(', ') || '—'}</BidiReference></dd></div>
      </dl>
      {snapshotOutdated && <p role="status">{t.stale}</p>}
      <p>{stored.status === 'manual_review' ? t.manual : t.saved}</p>
    </div>}
    {options.isPending ? <p role="status">{t.loading}</p> : options.isError ? <div role="alert">
      <p>{t.error}</p><Button className="button-secondary" onClick={reload}>{t.retry}</Button>
    </div> : !selected ? <p>{t.empty}</p> : <form onSubmit={event => { event.preventDefault(); mutation.mutate(); }}>
      <label>{t.option}
        <select value={selected.id} onChange={event => chooseOption(event.target.value)} disabled={restoring}>
          {movements.map(item => <option key={item.id} value={item.id}>{locale === 'ar' ? item.label_ar : item.label_en}</option>)}
        </select>
      </label>
      {options.hasNextPage && <Button type="button" className="button-secondary" disabled={options.isFetchingNextPage} onClick={() => void options.fetchNextPage()}>{t.more}</Button>}
      <div className="movement-facts">
        <span>{t.caliber}<br /><strong><BidiReference>{selected.caliber}</BidiReference></strong></span>
        <span>{t.impact}<br /><strong><BidiReference>{formatMinor(selected.quote_minor, selected.currency, locale, t.minorUnits)}</BidiReference></strong></span>
      </div>
      <p className="directory-muted">{t.units}</p>
      <div className="movement-fields">
        {(['case', 'dial', 'hands'] as const).map(field => <label key={field}>{t[field]}
          <Input dir="ltr" required maxLength={80} value={configuration[field]} disabled={restoring} onChange={event => {
            setConfiguration({ ...configuration, [field]: event.target.value }); mutation.reset();
          }} />
        </label>)}
      </div>
      <label>{t.functions}
        <Input dir="ltr" maxLength={1600} value={functionsText ?? configuration.functions.join(', ')} disabled={restoring} onChange={event => {
          setFunctionsText(event.target.value); mutation.reset();
        }} />
      </label>
      {result && <p className="notice" role="status">{outdated ? t.stale : result.status === 'manual_review' ? t.manual : t.saved}</p>}
      {mutation.isError && <p role="alert">{mutation.error instanceof ApiError && mutation.error.code === 'stale_revision' ? t.stale : t.saveError}</p>}
      {(saved.isError || specific.isError) && <div role="alert"><p>{t.saveError}</p><Button className="button-secondary" type="button" onClick={reload}>{t.retry}</Button></div>}
      {signedIn
        ? <Button aria-busy={mutation.isPending} disabled={mutation.isPending || restoring || saved.isError}>{mutation.isPending ? t.saving : t.save}</Button>
        : <SignInAction next={`/services?purpose=customization&business=${brandId}`} label={t.signin}/>}
    </form>}
  </section>;
}

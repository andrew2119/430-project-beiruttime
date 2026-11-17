'use client';
import { useState, type ReactNode } from 'react';
import { Button, Input, State, Skeleton, formatAmount, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageBody, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { usePageRead } from '@/lib/page-speed/read';
import type { Column, Facts, Selection } from '@contracts/contracts-catalog/comparison';
import { comparisonRead } from './read';
import { addSelection, compareBody, minorDecimal } from './state';
import { messages } from './messages';
import './styles.css';

export function FactsView({ facts }: { facts: Facts }) {
  const locale = useLocale(), t = messages[locale];
  const money = (value: number | null) => value === null ? t.missing : formatAmount(minorDecimal(value), locale, locale === 'ar' ? 'دولار أمريكي' : 'USD', t.missing);
  const row = (label: string, content: ReactNode) => <div className="comparison-row"><dt>{label}</dt><dd>{content}</dd></div>;
  return <><h2 className="bt-heading">{facts.title[locale]}</h2>{facts.demo && <p className="bt-text">{t.demo}</p>}<dl>
    {row(t.specification, <>{facts.brand[locale]} · {facts.model[locale]}<br/><bdi>{facts.reference || t.missing}</bdi> · {formatNumber(facts.year, locale, { useGrouping: false }, t.missing)}</>)}
    {row(t.condition, <>{facts.condition[locale]}{facts.component_wear.map((wear, index) => <p key={index}>{wear[locale]}</p>)}</>)}
    {row(t.seller, t[facts.seller_type])}
    {row(t.documents, <>{facts.included.map(item => <p key={item}>{t[item]}</p>)}{!facts.included.includes('papers') && <p>{t.noDocuments}</p>}</>)}
    {row(t.modification, facts.modified ? facts.modifications.map((item, index) => <div key={index}><p>{item.component[locale]}</p><p>{t.provenance}: {item.provenance[locale]}</p><p>{t.modifier}: {item.modifier[locale]}</p><p>{t.warranty}: {item.warranty_issuer[locale]}</p></div>) : t.unmodified)}
    {row(t.authentication, t[facts.authentication])}
    {row(t.price, <>{money(facts.price_minor)}<p>{t[facts.price_basis]}</p></>)}
    {row(t.fee, money(facts.buyer_fee_minor))}{row(t.total, money(facts.total_minor))}
  </dl><p className="bt-text">{t.economics}</p></>;
}

export function ComparisonColumn({ column, busy, onRemove, onRetry, onReview }: {
  column: Column; busy: boolean; onRemove: () => void; onRetry: () => void; onReview: () => void;
}) {
  const locale = useLocale(), t = messages[locale];
  return <article className="bt-card comparison-column" aria-label={column.watch_id}>
    <div className="comparison-actions"><bdi>{column.watch_id}</bdi><Button variant="ghost" onClick={onRemove} aria-label={`${t.remove}: ${column.watch_id}`}>{t.remove}</Button></div>
    {busy ? <State kind="loading" title={t.loading} body={t.refresh}><Skeleton size="card"/></State> : column.state === 'available' && column.facts ? <FactsView facts={column.facts}/> : <State headingLevel={3} kind={column.state === 'pending' ? 'loading' : column.state === 'denied' ? 'error' : 'empty'} title={t[column.state]} body={t[`${column.state}Body` as 'unavailableBody']}>
      <Button onClick={column.state === 'stale' ? onReview : onRetry}>{column.state === 'stale' ? t.review : t.retry}</Button>
    </State>}
  </article>;
}

export default function ComparisonView() {
  const locale = useLocale(), t = messages[locale];
  const [draft, setDraft] = useState(''), [invalid, setInvalid] = useState(false);
  const [selection, setSelection] = useState<{ items: Selection[]; operation: string }>({ items: [], operation: '' });
  const body = compareBody(selection.items);
  const query = usePageRead(selection.items.length ? comparisonRead(selection.operation, body) : null);
  const result = query.data;
  if (!query.isError && !query.isFetching && result?.operation_id === selection.operation) {
    const items = selection.items.map(item => {
      const column = result.columns.find(column => column.watch_id === item.watch_id);
      return item.expected_revision === null && column?.state === 'available' && column.revision !== null
        ? { ...item, expected_revision: column.revision } : item;
    });
    if (items.some((item, index) => item !== selection.items[index])) {
      setSelection({ items, operation: crypto.randomUUID() });
    }
  }
  function replace(items: Selection[]) { setSelection({ items, operation: crypto.randomUUID() }); }
  return <PageFrame><PageHeader title={t.title} lead={t.intro} tools={
    <form className="comparison-form" onSubmit={event => {
      event.preventDefault(); const items = addSelection(selection.items, draft.trim());
      if (!items) { setInvalid(true); return; } replace(items); setDraft(''); setInvalid(false);
    }}><div><Input id="comparison-reference" label={t.identifier} value={draft} onValueChange={value => setDraft(value.slice(0, 100))} error={invalid ? t.invalid : undefined}/></div><Button type="submit" disabled={selection.items.length >= 3}>{t.add}</Button>{selection.items.length > 0 && <Button type="button" disabled={query.isFetching} onClick={() => { void query.refetch(); }}>{t.retry}</Button>}</form>
  }/><PageBody>
    {selection.operation && <p className="bt-text comparison-reference">{t.operation}: <bdi>{selection.operation}</bdi></p>}
    {!selection.items.length ? <State title={t.empty} body={t.emptyBody}/> : <>{query.isError && <State kind="error" title={t.error} body={t.errorBody}><Button onClick={() => { void query.refetch(); }}>{t.retry}</Button></State>}<div className="comparison-grid" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
      {selection.items.map(item => <ComparisonColumn key={item.watch_id} busy={!query.isError && (query.isFetching || !query.data)} column={(!query.isError && query.data?.columns.find(column => column.watch_id === item.watch_id)) || { ...item, state: 'pending', revision: null, facts: null }} onRemove={() => replace(selection.items.filter(selected => selected.watch_id !== item.watch_id))} onRetry={() => { void query.refetch(); }} onReview={() => replace(selection.items.map(selected => selected.watch_id === item.watch_id ? { ...selected, expected_revision: null } : selected))}/>)}
    </div></>}
  </PageBody></PageFrame>;
}

'use client';
import { useState } from 'react';
import { usesFoundationShell } from '@/shell/foundation/path';
import { Button, Card, Input, State, formatAmount, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame as PageLayout, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { progressRead } from './read';
import en from './en.json';
import ar from './ar.json';
import './view.css';

export default function CareProgress() {
  const access = useAccessContext();
  const locale = useLocale(), t = locale === 'ar' ? ar : en;
  if (!usesFoundationShell('/care/progress')) {
    return <PageLayout><PageHeader title={t.title} lead={t.intro}/><PageBody>
      <State kind="error" title={t.title} body={access.fingerprint ? t.unavailable : t.denied}/>
    </PageBody></PageLayout>;
  }
  return <ProgressContent key={access.fingerprint ?? 'signed-out'} fingerprint={access.fingerprint}/>;
}
export function ProgressContent({fingerprint}:{fingerprint:string|null}) {
  const locale = useLocale(), t = locale === 'ar' ? ar : en;
  const [draft,setDraft] = useState(''), [subject,setSubject] = useState(''), [offset,setOffset] = useState(0), [invalid,setInvalid] = useState(false);
  const query = usePageRead(subject && fingerprint ? progressRead(subject,offset,fingerprint) : null);
  const data = query.isError ? undefined : query.data;
  const timestamp = (value:string) => new Intl.DateTimeFormat(locale === 'ar' ? 'ar-LB' : 'en-LB',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut',numberingSystem:locale === 'ar' ? 'arab' : 'latn'}).format(new Date(value));
  const error = query.error instanceof ApiError && [401,403,404].includes(query.error.status) ? t.denied : t.unavailable;
  return <PageLayout><PageHeader title={t.title} lead={t.intro} notice={<p>{t.zone}</p>}/><PageBody>
    <form className="care-progress-search" onSubmit={event=>{event.preventDefault();if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(draft.trim())) {setSubject(draft.trim());setOffset(0);setInvalid(false);} else {setInvalid(true);}}}>
      <Input id="progress-job" label={t.job} error={invalid ? t.invalid : undefined} value={draft} required autoComplete="off" onValueChange={value=>setDraft(value.slice(0,36))}/><Button type="submit">{t.open}</Button>
    </form>
    {!fingerprint ? <State kind="error" title={t.title} body={t.denied}/> : !subject ? <State title={t.title} body={t.pending}/> : query.isPending ? <State kind="loading" title={t.title} body={t.loading}/> : query.isError ? <State kind="error" title={t.title} body={error}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State> : data && <>
      {query.isFetching && <p role="status">{t.refreshing}</p>}
      <p>{t.total}: <span className="bt-number">{formatNumber(data.total,locale)}</span> · {t[data.state]} · {t.quality}: {t[data.quality]}</p>
      <Card><p>{t.responsible}: <bdi>{data.next_actor}</bdi></p><p>{t.follow_up}: {locale === 'ar' ? data.next_action_ar : data.next_action_en}</p><p>{t.review}: {timestamp(data.next_review_at)}</p>{data.review_overdue && <p role="status">{t.overdue}</p>}</Card>
      <Button onClick={()=>void query.refetch()} disabled={query.isFetching}>{t.retry}</Button>
      {data.total === 0 && <State title={t.title} body={t.empty}/>}
      <ul className="care-progress-lines">{data.items.map(line=><li key={line.line_id}><Card>
        <h2>{locale === 'ar' ? line.title_ar : line.title_en}</h2><p>{line.required ? t.required : t.optional} · {t[line.state]}</p>
        <p>{t.amount}: <span className="bt-number">{formatAmount(`${Math.floor(line.amount_minor/100)}.${String(line.amount_minor%100).padStart(2,'0')}`,locale,t.currency,t.missing)}</span></p>
        {!line.report ? <p>{t.noReport}</p> : <dl>
          <dt>{t.step}</dt><dd dir="auto">{locale === 'ar' ? line.report.step_ar : line.report.step_en}</dd>
          <dt>{t.actor}</dt><dd><bdi>{line.report.actor_id}</bdi></dd>
          <dt>{t.since}</dt><dd>{timestamp(line.report.since_at)}</dd>
          <dt>{t.parts}</dt><dd dir="auto">{(locale === 'ar' ? line.report.parts_ar : line.report.parts_en) || t.missing}</dd>
          <dt>{t.readings}</dt><dd dir="auto">{(locale === 'ar' ? line.report.readings_ar : line.report.readings_en) || t.missing}</dd>
          <dt>{t.estimate}</dt><dd>{line.report.estimate_start && line.report.estimate_end ? `${timestamp(line.report.estimate_start)} – ${timestamp(line.report.estimate_end)}` : t.missing}</dd>
          <dt>{t.basis}</dt><dd dir="auto">{(locale === 'ar' ? line.report.estimate_basis_ar : line.report.estimate_basis_en) || t.missing}</dd>
          <dt>{t.responsible}</dt><dd><bdi>{line.report.next_actor}</bdi></dd>
          <dt>{t.review}</dt><dd>{timestamp(line.report.next_review_at)}{line.overdue && <p role="status">{t.overdue}</p>}</dd>
          <dt>{t.follow_up}</dt><dd>{line.report.follow_up === 'review' ? t.review_action : t[line.report.follow_up]}</dd>
        </dl>}
      </Card></li>)}</ul>
      <nav aria-label={t.total}><Button disabled={offset === 0 || query.isFetching} onClick={()=>setOffset(value=>Math.max(0,value-50))}>{t.previous}</Button><Button disabled={data.next_offset === null || query.isFetching} onClick={()=>{if(data.next_offset !== null) setOffset(data.next_offset);}}>{t.next}</Button></nav>
    </>}
  </PageBody></PageLayout>;
}

'use client';
import { Button, Skeleton, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import type { PassportState } from '../../../packages/contracts-trust/passports/v1';
import en from './en.json';
import ar from './ar.json';

/** Composition supplies a verified public answer; language never initiates a read. */
export function PassportView({answer,retry}:{answer:PassportState;retry:()=>void}) {
  const locale = useLocale(), copy = locale === 'ar' ? ar : en;
  return <PageFrame><PageHeader title={copy.title} lead={copy.boundary}/><PageBody>
    {answer.state === 'verified' ? <section aria-label={copy.summary}>
      <p>{copy.historical}</p><dl>
        <dt>{copy.issuer}</dt><dd><bdi>{answer.document.summary.issuer_id}</bdi></dd>
        <dt>{copy.date}</dt><dd><time dateTime={answer.document.summary.inspected_at}>{new Intl.DateTimeFormat(locale, {dateStyle:'long',timeStyle:'short',timeZone:'UTC'}).format(new Date(answer.document.summary.inspected_at))} {copy.utc}</time></dd>
        <dt>{copy.scope}</dt><dd>{copy.inspection}</dd>
        <dt>{copy.reference}</dt><dd><bdi>{answer.document.summary.watch_reference}</bdi></dd>
      </dl><p>{copy.privacy}</p>
    </section> : answer.state === 'loading' ? <div role="status" aria-label={copy.loading} aria-busy="true"><Skeleton/><Skeleton/></div> :
      <State kind={answer.state === 'invalid' || answer.state === 'unavailable' ? 'error' : 'empty'} title={copy[answer.state]} body={copy[`${answer.state}Body`]}>
        {answer.operation_id && <p>{copy.operation} <bdi>{answer.operation_id}</bdi></p>}
        <Button type="button" onClick={retry}>{copy.retry}</Button>
      </State>}
  </PageBody></PageFrame>;
}

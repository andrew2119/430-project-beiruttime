'use client';
import { useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { Button, ButtonLink, Card, RowSkeleton, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { usesFoundationShell } from '@/shell/foundation/path';
import { useLocale } from '@/shell/locale-context';
import { signInHref, useSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { ApiError } from '@/lib/api/client';
import { timelineRead } from './read';
import { copy } from './copy';
import { money } from './money';
import './styles.css';

export default function OrderTimeline({id = null}: {id?: string | null}) {
  const session = useSession(), params = useSearchParams(), pathname = usePathname();
  const locale = useLocale(), t = copy[locale];
  const organization = params.get('organization_id');
  const destination = (id ? '/orders/'+encodeURIComponent(id) : '/orders') + (params.size ? '?'+params.toString() : '');
  if (!session || !usesFoundationShell(pathname)) return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody><State kind="error" title={session ? t.unavailable : t.denied} body={t.recovery}>
    {session ? <ButtonLink href={destination}>{t.retry}</ButtonLink> : <ButtonLink href={signInHref(destination,locale)}>{t.signIn}</ButtonLink>}
  </State></PageBody></PageFrame>;
  return <TimelineView key={JSON.stringify([session?.access_fingerprint ?? 'closed', organization, id])} id={id} organization={organization} active={!!session}/>;
}
function TimelineView({id, organization, active}: {id: string | null; organization: string | null; active: boolean}) {
  const locale = useLocale(), t = copy[locale];
  const [offset, setOffset] = useState(0);
  const read = usePageRead(active ? timelineRead(id, organization, offset) : null);
  const denied = !active || read.error instanceof ApiError && [401,403,404].includes(read.error.status);
  const data = !denied && !read.error ? read.data : undefined;
  const time = (value: string) => new Intl.DateTimeFormat(locale === 'ar' ? 'ar-LB-u-nu-arab' : 'en-US-u-nu-latn', {timeZone: 'Asia/Beirut', dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value));
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    {active && read.isPending && <Card><State kind="loading" title={t.loading} body={t.recovery}/><RowSkeleton/></Card>}
    {(denied || read.error) && <State kind="error" title={denied ? t.denied : t.unavailable} body={t.recovery}>{active ? <Button onClick={() => void read.refetch()}>{t.retry}</Button> : <ButtonLink href={signInHref(id ? '/orders/'+id : '/orders',locale)}>{t.signIn}</ButtonLink>}</State>}
    {data && <AnswerArrival view="l22-order-timeline"><div className="order-timeline">
      <Button disabled={read.isFetching} onClick={() => void read.refetch()}>{t.refresh}</Button>
      {'items' in data ? <>
        <p>{t.rows}: {formatNumber(data.total, locale)}</p>
        {!data.items.length && <State title={t.empty} body={t.emptyBody}/>}
        <ul>{data.items.map(row => <li key={row.order_id}><ButtonLink href={`/${locale}/orders/${encodeURIComponent(row.order_id)}${organization ? '?organization_id='+encodeURIComponent(organization) : ''}`}><bdi>{row.reference}</bdi></ButtonLink></li>)}</ul>
        <nav aria-label={t.rows}><Button disabled={offset === 0 || read.isFetching} onClick={() => setOffset(Math.max(0, offset - 20))}>{t.previous}</Button><Button disabled={offset + data.limit >= data.total || read.isFetching} onClick={() => setOffset(offset + 20)}>{t.next}</Button></nav>
      </> : <>
        <Card><h2>{t.reference}: <bdi>{data.reference}</bdi></h2><dl>
          <dt>{t.waiting}</dt><dd>{t[data.waiting.party]}</dd><dt>{t.since}</dt><dd><time dateTime={data.waiting.since}>{time(data.waiting.since)}</time></dd>
          <dt>{t.operator}</dt><dd><bdi>{data.waiting.operator_id}</bdi></dd><dt>{t.review}</dt><dd><time dateTime={data.waiting.next_review_at}>{time(data.waiting.next_review_at)}</time></dd>
        </dl><p>{t[data.waiting.action]}</p><p role="status">{t[data.waiting.follow_up]}</p></Card>
        <Card><dl>{(['principal_minor','buyer_fee_minor','business_fee_minor','total_minor'] as const).map((field,index) => <div key={field}><dt>{[t.principal,t.buyerFee,t.businessFee,t.total][index]}</dt><dd><bdi>{money(data.economics[field], locale)}</bdi></dd></div>)}</dl><p>{t.fees}</p></Card>
        {data.milestones.some(row => row.state === 'unavailable') && <State kind="error" title={t.unavailable} body={t.partial}/>}
        <Card><h2>{t.financial}</h2>{!data.financial.length && <p>{t.noFinancial}</p>}<ul>{data.financial.map(row => <li key={row.operation_id}><p>{t[row.kind]} · {t[row.state]}</p><bdi>{money(row.amount_minor, locale)}</bdi><p><bdi>{row.operation_id}</bdi></p><time dateTime={row.occurred_at}>{time(row.occurred_at)}</time></li>)}</ul></Card>
        <ol>{data.milestones.map(row => <li key={row.source}><Card><h2>{t[row.source]}</h2><p>{t[row.state]}</p>{row.occurred_at && <p>{t.time}: <time dateTime={row.occurred_at}>{time(row.occurred_at)}</time></p>}{row.amount_minor !== null && <p>{t.amount}: <bdi>{money(row.amount_minor, locale)}</bdi></p>}</Card></li>)}</ol>
      </>}
    </div></AnswerArrival>}
  </PageBody></PageFrame>;
}

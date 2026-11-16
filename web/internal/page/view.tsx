'use client';
import { useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { Button, Card, Input, RowSkeleton, Segmented, Skeleton, State, formatCount, formatNumber } from '@beirut-time/ui/foundation';
import type { Locale } from '@/lib/i18n';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { DestinationLink } from '@/shell/foundation/destination';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { usePageRead } from '@/lib/page-speed/read';
import { DATA_MODES, reviewMode } from '@/internal/components/model';
import { replacePageQuery } from '@/lib/page-speed/address';
import { TEXT } from '@/tests/fixtures/worst-case';
import { demoRead, demoRequest } from './reads';
import { PAGE_COPY } from './copy';
export function StartingPage({locale}: {locale:Locale}) {
  const path = usePathname(), search = useSearchParams(), request = demoRequest(search.get('data'),search.get('page'));
  const query = usePageRead(demoRead(request),{keep:true}), t = PAGE_COPY[locale], [draft,setDraft] = useState('');
  const answer = query.data;
  const href = (page:number,mode=request.mode)=>`/${locale}/internal/page?data=${mode}&page=${page}`;
  return <PageFrame><PageHeader title={request.mode === 'worst' ? TEXT.titleAtLimit : t.title} lead={t.lead} count={answer !== undefined ? formatCount(answer.total,locale,t.count,'—') : <Skeleton/>}
    actions={<Button variant="outline" busy={query.isFetching} onClick={()=>void query.refetch()}>{t.refresh}</Button>}
    tabs={<><DestinationLink href={`/${locale}/internal/page`} label={t.start} icon="home" active path={path} appearance="tab"/><DestinationLink href={`/${locale}/internal/components`} label={t.components} icon="settings" path={path} appearance="tab"/></>}
    notice={<p className="bt-caption">{t.demo}</p>}/><PageBody>
    <Input id="page-note" label={t.draft} hint={t.draftHint} value={draft} onValueChange={setDraft}/>
    <Segmented label={t.data} locale={locale} value={request.mode} onValueChange={value=>replacePageQuery({data:reviewMode(value),page:'0'})} options={DATA_MODES.map(mode=>({value:mode,label:t.modes[mode]}))}/>
    {answer !== undefined ? <AnswerArrival view="page-start"><div className="bt-page-example-stack">
      <p role={query.isError ? 'alert' : 'status'} className="bt-page-feedback bt-caption">{query.isError ? t.refreshError : query.isFetching ? t.refreshing : ''}</p>
      <div className="bt-page-tools" data-bt-glance=""><p className="bt-number" role="status">{t.page} {formatNumber(answer.page+1,locale)} {t.of} {formatNumber(answer.pages,locale)}</p><DestinationLink href={href(Math.max(0,answer.page-1))} label={t.previous} icon="search" path={path} disabled={answer.page === 0 || query.isPlaceholderData}/><DestinationLink href={href(Math.min(answer.pages-1,answer.page+1))} label={t.next} icon="search" path={path} disabled={answer.page+1 === answer.pages || query.isPlaceholderData}/></div>
      {answer.items.length ? <div className="bt-page-example-grid">{answer.items.map(item=><Card key={item.id}><h2 className="bt-heading">{item.title}</h2><p className="bt-text"><bdi dir="ltr">{item.reference}</bdi></p></Card>)}</div> : <State title={t.empty} body={t.emptyBody}/>}
    </div></AnswerArrival> : query.isError ? <State kind="error" title={t.error} body={t.errorBody}><Button variant="outline" onClick={()=>void query.refetch()}>{t.retry}</Button></State> : <div role="status" aria-label={t.loading} aria-busy="true"><RowSkeleton/><RowSkeleton/><RowSkeleton/></div>}
    <Card><h2 className="bt-heading">{t.speed}</h2><p className="bt-text">{t.owed}</p><ul className="bt-page-methods">{t.methods.map(method=><li key={method} className="bt-text">{method}</li>)}</ul></Card>
  </PageBody></PageFrame>;
}

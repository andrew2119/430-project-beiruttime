'use client';
import { useState } from 'react';
import { Button, ButtonLink, Card, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import type { SimilarQuery } from '@contracts/contracts-catalog/similar-watches';
import { similarRead } from './read';
import { messages } from './messages';

/** The caller keeps this component mounted across an in-place language change. */
export default function SimilarView({initialQuery}:{initialQuery:SimilarQuery}) {
  const locale=useLocale(),t=messages[locale];
  const [offset,setOffset]=useState(initialQuery.offset);
  const query={...initialQuery,offset};
  const result=usePageRead(similarRead(query));
  const answer=result.data;
  const state=result.isError?'unavailable':answer?.state;
  return <PageFrame><PageHeader title={t.title} lead={t.rules}/><PageBody>
    {result.isPending?<State kind="loading" title={t.loading} body={t.rules}/>:state&&state!=='ready'?<State kind={state==='empty'?'empty':'error'} title={t[state]} body={t[`${state}Body`]}>
      <Button onClick={()=>void result.refetch()}>{t.retry}</Button>
      <ButtonLink href={`/${locale}/watches/${encodeURIComponent(initialQuery.subject_id)}`}>{t.back}</ButtonLink>
      <ButtonLink href={`/${locale}/watches`}>{t.browse}</ButtonLink>
    </State>:answer?<AnswerArrival view="similar-watches"><p className="bt-text">{t.count}: {formatNumber(answer.total,locale)}</p>
      {result.isFetching&&<p role="status">{t.refresh}</p>}
      {answer.items.map(({watch,rule})=><Card key={watch.id}><h2 className="bt-heading"><bdi>{watch.title}</bdi></h2><p className="bt-text">{t[rule]}</p><p className="bt-text"><bdi>{watch.reference}</bdi></p><p className="bt-number">{watch.price_minor===null?t.missing:formatNumber(watch.price_minor/100,locale,{style:'currency',currency:'USD'})}</p>{watch.sample&&<p className="bt-text">{t.sample}</p>}<ButtonLink href={`/${locale}/watches/${encodeURIComponent(watch.id)}`}>{t.open}</ButtonLink></Card>)}
      <nav aria-label={t.title}>{offset>0&&<Button onClick={()=>setOffset(0)}>{t.first}</Button>}{answer.next_offset!==null&&<Button onClick={()=>setOffset(answer.next_offset!)}>{t.next}</Button>}</nav>
    </AnswerArrival>:null}
  </PageBody></PageFrame>;
}

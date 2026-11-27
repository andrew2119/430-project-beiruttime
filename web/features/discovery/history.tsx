'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { WatchDetail } from '@contracts/contracts-catalog/discovery';
import { Button, State } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { discoveryApi } from './api';
import en from './en.json';
import ar from './ar.json';

export function WatchHistory({watch}:{watch:WatchDetail}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [cursor,setCursor]=useState('');
  const revision=watch.history_revision;
  const query=useQuery({
    queryKey:['discovery','public','history',watch.id,watch.revision,revision,cursor],
    queryFn:({signal})=>discoveryApi.history(watch.id,cursor,watch.revision,revision!,signal),
    enabled:!!cursor&&revision!=null,retry:false,staleTime:0,
  });
  const history=cursor?query.data?.history:watch.history;
  const next=cursor?query.data?.next_cursor:watch.history_next_cursor;
  return <section aria-label={t.history}><h2>{t.history}</h2>
    {cursor&&query.isPending?<p role="status">{t.loading}</p>:cursor&&query.isError?<State title={t.unavailable} body={t.historyUnavailable}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State>:history==null?<p>{t.historyUnavailable}</p>:history.length?<ul>{history.map((item,index)=><li key={index}><time dateTime={item.occurred_at}>{new Intl.DateTimeFormat(locale,{dateStyle:'medium'}).format(new Date(item.occurred_at))}</time> · {locale==='ar'?item.summary_ar:item.summary_en}{item.user_note&&<p dir="auto">{item.user_note}</p>}</li>)}</ul>:<p>{t.noHistory}</p>}
    <nav className="discovery-pagination" aria-label={t.history}>
      {cursor&&<Button variant="outline" onClick={()=>setCursor('')}>{t.first}</Button>}
      {next&&revision!=null&&!(cursor&&(query.isPending||query.isError))&&<Button onClick={()=>setCursor(next)}>{t.next}</Button>}
    </nav>
  </section>;
}

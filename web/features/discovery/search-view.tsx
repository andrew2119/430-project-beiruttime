'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Button, ButtonLink, Input, Skeleton, BidiReference } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { hasRoute } from '@/registry-loader';
import { discoveryApi } from './api';
import { defaults, readSearch, writeSearch, searchRangeError, exactMoney, saleStateLabel, type SearchState } from './url-state';
import { PublicPhoto } from './photo';
import en from './en.json';
import ar from './ar.json';

export default function SearchView() {
  const locale=useLocale(), t=locale==='ar'?ar:en;
  const params=useSearchParams(), router=useRouter(), pathname=usePathname();
  const state=readSearch(params), key=writeSearch(state), invalid=searchRangeError(state);
  const [copied,setCopied]=useState('');
  const query=useQuery({queryKey:['discovery','public',key],queryFn:({signal})=>discoveryApi.search(state,signal),enabled:!invalid,retry:false,staleTime:0,refetchOnWindowFocus:true,refetchOnReconnect:true});
  const href=(next: SearchState)=>`${pathname}?${writeSearch(next)}`;
  async function copySearch(){try{const url=new URL(location.href);url.search=writeSearch(state);url.hash='';await navigator.clipboard.writeText(url.href);setCopied(t.copied);}catch{setCopied(t.copyFailed);}}
  return <div className="discovery-page">
    <header className="discovery-heading"><p className="eyebrow">{t.eyebrow}</p><h1>{t.title}</h1><p>{t.intro}</p></header>
    <form key={key} className="discovery-filter" aria-label={t.searchTitle} onSubmit={event=>{event.preventDefault();const data=new FormData(event.currentTarget);const next={...defaults};for(const field of Object.keys(defaults) as (keyof SearchState)[]) if(field!=='cursor') next[field]=String(data.get(field)??defaults[field]);router.push(href(next));}}>
      <div className="discovery-search-row"><label>{t.search}<Input name="q" type="search" maxLength={160} defaultValue={state.q} placeholder={t.searchPlaceholder}/></label><Button type="submit">{t.apply}</Button></div>
      <details open={!!(state.brand||state.model||state.location||state.min_minor||state.max_minor||state.sale_mode)}><summary>{t.filters}</summary><div className="discovery-filter-grid">
        {(['brand','model','location'] as const).map(field=><label key={field}>{t[field]}<Input name={field} defaultValue={state[field]} maxLength={field==='brand'?100:160}/></label>)}
        <label>{t.currency}<select name="currency" defaultValue={state.currency}><option value="USD">USD</option><option value="LBP">LBP</option></select></label>
        <label>{t.min}<Input name="min_minor" inputMode="numeric" defaultValue={state.min_minor} maxLength={16} aria-describedby="discovery-money-help"/></label>
        <label>{t.max}<Input name="max_minor" inputMode="numeric" defaultValue={state.max_minor} maxLength={16} aria-describedby="discovery-money-help"/></label>
        <p id="discovery-money-help" className="discovery-help discovery-full-row">{t.moneyHelp}</p>
      </div></details>
      <div className="discovery-sort-row"><label>{t.mode}<select name="sale_mode" defaultValue={state.sale_mode}><option value="">{t.anyMode}</option><option value="fixed">{t.fixed}</option><option value="auction">{t.auction}</option><option value="offer">{t.offer}</option></select></label><label>{t.sort}<select name="sort" defaultValue={state.sort}>{(['newest','ending_soon','price_asc','price_desc'] as const).map(sort=><option key={sort} value={sort}>{t[sort]}</option>)}</select></label><ButtonLink href={pathname} className="button-secondary">{t.reset}</ButtonLink></div>
    </form>
    <section aria-labelledby="discovery-results"><div className="discovery-results-head"><h2 id="discovery-results">{t.results}</h2><details className="discovery-save-search"><summary>{t.keepSearch}</summary><p>{t.saveHelp}</p><Button className="button-secondary" onClick={copySearch}>{t.copy}</Button><p role="status">{copied}</p></details></div>
      {invalid?<p className="notice" role="alert">{t.rangeError}</p>:query.isPending?<Skeleton label={t.loading}/>:query.isError?<div className="discovery-message" role="alert"><h3>{t.unavailable}</h3><p>{query.error instanceof ApiError&&query.error.code==='invalid_cursor'?t.invalidCursor:t.unavailableBody}</p><Button onClick={()=>void query.refetch()}>{t.retry}</Button>{state.cursor&&<ButtonLink href={href({...state,cursor:''})} className="button-secondary">{t.first}</ButtonLink>}</div>:!query.data?.items.length?<div className="discovery-message"><h3>{t.empty}</h3><p>{t.emptyBody}</p><ButtonLink href={pathname} className="button-secondary">{t.reset}</ButtonLink></div>:<>
        <div className="discovery-grid">{query.data.items.map(watch=><article className="discovery-watch-card" key={watch.id}>
          <Link className="discovery-card-link" href={`/${locale}/watches/${encodeURIComponent(watch.id)}`}><PublicPhoto key={watch.thumbnail?.id??'missing'} photo={watch.thumbnail} fallback={t.noPhoto}/><div className="discovery-card-copy"><div className="discovery-card-meta"><span>{watch.brand}</span><span>{watch.sale_mode==='auction'?t.auction:watch.sale_mode==='offer'?t.offer:t.fixed} · {saleStateLabel(watch.sale_state,t)}</span></div><h3>{watch.title}</h3><p><BidiReference>{watch.model}</BidiReference> · {watch.location}</p><small className="discovery-help">{t.listingPrice}</small><br/><strong>{watch.price?exactMoney(watch.price.amount,watch.price.currency,locale):t.listingPriceUnstated}</strong>{watch.demo&&<small className="discovery-demo">{t.demo}</small>}</div></Link>
        </article>)}</div>
        <nav className="discovery-pagination" aria-label={t.results}>{state.cursor&&<ButtonLink href={href({...state,cursor:''})} className="button-secondary">{t.first}</ButtonLink>}{query.data.next_cursor&&<ButtonLink href={href({...state,cursor:query.data.next_cursor})}>{t.next}</ButtonLink>}</nav>
      </>}
    </section>
    {hasRoute('/image-credits')&&<p className="discovery-help"><Link href={`/${locale}/image-credits`}>{t.imageCredits}</Link></p>}
  </div>;
}

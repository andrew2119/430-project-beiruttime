'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { AnimatedList, Button, ButtonLink, Input, Label, Skeleton, State, StatusBadge, BidiReference, Checkbox } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { hasRoute } from '@/registry-loader';
import { discoveryApi } from './api';
import { readSearch, writeSearch, searchRangeError, exactMoney, saleStateLabel, type SearchState } from './url-state';
import { Comparison, toggleComparison } from './compare';
import { PublicPhoto } from './photo';
import { Select, type SelectOption } from '@beirut-time/ui';
import en from './en.json';
import ar from './ar.json';

function FormSelect({ name, label, value, onChange, options }: { name: string; label: string; value: string; onChange: (value: string) => void; options: SelectOption[] }) {
  return <div className="discovery-field"><Label htmlFor={`discovery-${name}`}>{label}</Label><input type="hidden" name={name} value={value}/><Select id={`discovery-${name}`} value={value} onValueChange={onChange} options={options} searchable={false}/></div>;
}
export function GridSkeleton({ label }: { label: string }) {
  return <div className="discovery-grid" role="status" aria-label={label}>{Array.from({length:8},(_,i)=><div className="discovery-watch-card" key={i}><Skeleton className="discovery-card-image"/><div className="discovery-card-copy"><Skeleton className="h-4 w-4/5"/><Skeleton className="h-3 w-2/5"/></div></div>)}<span className="sr-only">{label}</span></div>;
}
export default function SearchView() {
  const cache=useQueryClient();
  const warm=(id:string)=>{void cache.prefetchQuery({queryKey:['discovery','public','watch',id],queryFn:({signal})=>discoveryApi.detail(id,signal),staleTime:10000});};
  const locale=useLocale(), t=locale==='ar'?ar:en;
  const params=useSearchParams(), router=useRouter(), pathname=usePathname();
  const state=readSearch(params), key=writeSearch(state), invalid=searchRangeError(state);
  const criteriaKey=writeSearch({...state,cursor:''});
  const [draftState,setDraftState]=useState(()=>({key:criteriaKey,value:state}));
  if(draftState.key!==criteriaKey)setDraftState({key:criteriaKey,value:state});
  const draft=draftState.key===criteriaKey?draftState.value:state;
  const edit=(field:keyof SearchState,value:string)=>setDraftState(current=>({...current,value:{...current.value,[field]:value}}));
  const [copied,setCopied]=useState('');
  const [comparison,setComparison]=useState<string[]>([]);
  const query=useQuery({queryKey:['discovery','public',key],queryFn:({signal})=>discoveryApi.search(state,signal),enabled:!invalid,retry:false,staleTime:0,refetchOnWindowFocus:true,refetchOnReconnect:true});
  const href=(next: SearchState)=>`${pathname}?${writeSearch(next)}`;
  async function copySearch(){try{const url=new URL(location.href);url.search=writeSearch(state);url.hash='';await navigator.clipboard.writeText(url.href);setCopied(t.copied);}catch{setCopied(t.copyFailed);}}
  return <PageLayout className="discovery-page">
    <form className="discovery-filter" aria-label={t.searchTitle} onSubmit={event=>{event.preventDefault();router.push(href({...draft,cursor:''}));}}>
      <PageHeader title={t.title} count={t.intro} lead={<span className="discovery-help">{t.eyebrow}</span>} tools={<div className="discovery-filter-content">
        <div className="discovery-search-row"><label className="discovery-search"><span className="sr-only">{t.search}</span><Search aria-hidden="true"/><Input name="q" type="search" maxLength={160} value={draft.q} onChange={event=>edit('q',event.target.value)} placeholder={t.searchPlaceholder}/></label><Button chonk size="sm" type="submit">{t.apply}</Button></div>
        <details open={!!(state.brand||state.model||state.location||state.min_price||state.max_price||state.sale_mode)}><summary className="ui-filter-link">{t.filters}</summary><div className="discovery-filter-grid">
          {(['brand','model','location'] as const).map(field=><div className="discovery-field" key={field}><Label htmlFor={`discovery-${field}`}>{t[field]}</Label><Input id={`discovery-${field}`} name={field} value={draft[field]} onChange={event=>edit(field,event.target.value)} maxLength={field==='brand'?100:160}/></div>)}
          <FormSelect name="currency" label={t.currency} value={draft.currency} onChange={value=>edit('currency',value)} options={[{value:'USD',label:'USD'}]}/>
          {(['min_price','max_price'] as const).map(field=><div className="discovery-field" key={field}><Label htmlFor={`discovery-${field}`}>{field==='min_price'?t.min:t.max}</Label><Input id={`discovery-${field}`} name={field} inputMode="decimal" value={draft[field]} onChange={event=>edit(field,event.target.value)} maxLength={16} aria-describedby="discovery-money-help"/></div>)}
          <p id="discovery-money-help" className="discovery-help discovery-full-row">{t.moneyHelp}</p>
        </div></details>
        <div className="discovery-sort-row"><FormSelect name="sale_mode" label={t.mode} value={draft.sale_mode} onChange={value=>edit('sale_mode',value)} options={[{value:'',label:t.anyMode},{value:'fixed',label:t.fixed},{value:'auction',label:t.auction},{value:'offer',label:t.offer}]}/><FormSelect name="sort" label={t.sort} value={draft.sort} onChange={value=>edit('sort',value)} options={(['newest','ending_soon','price_asc','price_desc'] as const).map(sort=>({value:sort,label:t[sort]}))}/><ButtonLink href={pathname} variant="outline" size="sm">{t.reset}</ButtonLink></div>
      </div>}/>
    </form>
    <section aria-labelledby="discovery-results"><div className="discovery-results-head"><h2 id="discovery-results">{t.results}</h2><p className="discovery-help" role="status">{!invalid&&!query.isPending&&!query.isError&&query.data?.total!=null?`${t.total}: ${new Intl.NumberFormat(locale).format(query.data.total)}`:t.totalUnavailable}</p><details className="discovery-save-search"><summary className="ui-filter-link">{t.keepSearch}</summary><p className="discovery-help">{t.saveHelp}</p><Button variant="outline" size="sm" onClick={copySearch}>{t.copy}</Button><p className="discovery-help" role="status">{copied}</p></details></div>
      {invalid?<p className="notice" role="alert">{t.rangeError}</p>:query.isPending?<GridSkeleton label={t.loading}/>:query.isError?<div role="alert"><State kind="error" title={query.error instanceof ApiError&&query.error.status===403?t.denied:t.unavailable} body={query.error instanceof ApiError&&query.error.status===403?t.deniedBody:query.error instanceof ApiError&&query.error.code==='invalid_cursor'?t.invalidCursor:t.unavailableBody}><Button chonk size="sm" onClick={()=>void query.refetch()}>{t.retry}</Button>{state.cursor&&<ButtonLink href={href({...state,cursor:''})} variant="outline" size="sm">{t.first}</ButtonLink>}</State></div>:!query.data?.items.length?<State title={t.empty} body={t.emptyBody}><ButtonLink href={pathname} variant="outline" size="sm">{t.reset}</ButtonLink></State>:<>
        <AnimatedList grid items={query.data.items} getKey={watch=>watch.id} className="discovery-grid">{watch=><article className="discovery-watch-card">
          <Link className="discovery-card-link" onPointerEnter={()=>warm(watch.id)} onFocus={()=>warm(watch.id)} href={`/${locale}/watches/${encodeURIComponent(watch.id)}`}><PublicPhoto key={watch.thumbnail?.id??'missing'} photo={watch.thumbnail} fallback={t.noPhoto}/><div className="discovery-card-copy"><div className="discovery-card-meta"><span>{watch.brand}</span><StatusBadge hue={watch.sale_mode==='auction'?'blue':'neutral'}>{watch.sale_mode==='auction'?t.auction:watch.sale_mode==='offer'?t.offer:t.fixed} · {saleStateLabel(watch.sale_state,t)}</StatusBadge></div><h3>{watch.title}</h3><p><BidiReference>{watch.model}</BidiReference> · {watch.location}</p><div><small className="discovery-help">{t.listingPrice}</small><strong className="discovery-card-price">{watch.price?exactMoney(watch.price.amount,watch.price.currency,locale):t.listingPriceUnstated}</strong></div>{watch.demo&&<small className="discovery-demo">{t.demo}</small>}</div></Link>
        <div className="discovery-card-copy"><Checkbox checked={comparison.includes(watch.id)} disabled={comparison.length>=3&&!comparison.includes(watch.id)} onChange={()=>setComparison(ids=>toggleComparison(ids,watch.id))}>{t.compare} · {watch.title}</Checkbox></div></article>}</AnimatedList>
        <nav className="discovery-pagination" aria-label={t.results}>{state.cursor&&<ButtonLink href={href({...state,cursor:''})} variant="outline" size="sm">{t.first}</ButtonLink>}{query.data.next_cursor&&<ButtonLink href={href({...state,cursor:query.data.next_cursor})} size="sm">{t.next}</ButtonLink>}</nav>
      </>}
    </section>
    <Comparison ids={comparison} remove={id=>setComparison(ids=>ids.filter(value=>value!==id))}/>
    {hasRoute('/image-credits')&&<p className="discovery-help"><Link className="discovery-text-link" href={`/${locale}/image-credits`}>{t.imageCredits}</Link></p>}
  </PageLayout>;
}

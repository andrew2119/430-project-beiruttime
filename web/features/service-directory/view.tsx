'use client';
import { useRef, useState } from 'react';
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, ButtonLink, Card } from '@beirut-time/ui';
import { useRouter, useSearchParams } from 'next/navigation';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { request, ApiError } from '@/lib/api/client';
import { useSession } from '@/features/identity/session';
import { SignInAction } from './auth-action';
import type { Business, Capability, Choice, Purpose } from '@contracts/contracts-service/directory';
import MovementOption from '../movement-option/view';
import { directoryPath, privateRequest, useJsonCommand } from './api';
import en from './en.json';
import ar from './ar.json';

type Page = {items:Business[];next_after:string|null};
export default function ServiceDirectory() {
  useSession();
  const access = useAccessContext();
  return <DirectoryContent key={access.fingerprint ?? 'public'}/>;
}
function DirectoryContent() {
  const detail = useRef<HTMLElement>(null);
  const router = useRouter();
  const locale = useLocale(); const t = locale==='ar'?ar:en; const params = useSearchParams();
  const purpose:Purpose = params.get('purpose')==='customization'?'customization':'servicing';
  const access = useAccessContext(); const signedIn = access.roles.includes('buyer');
  const [businessId,setBusinessId] = useState(params.get('business') ?? '');
  const [capability,setCapability] = useState<Capability|null>(null); const queryClient = useQueryClient();
  const directory = useInfiniteQuery({queryKey:['official-directory',purpose], initialPageParam:null as string|null, queryFn:({pageParam,signal})=>request<Page>(`${directoryPath}/businesses?purpose=${purpose}${pageParam?`&after=${pageParam}`:''}`,{signal}),getNextPageParam:page=>page.next_after??undefined,retry:false});
  const businesses = directory.data?.pages.flatMap(page=>page.items) ?? [];
  const command = useJsonCommand();
  const choiceKey = ['directory-choice',access.fingerprint];
  const saved = useQuery({queryKey:choiceKey,queryFn:({signal})=>privateRequest<{choice:Choice|null}>(`${directoryPath}/choices/current`,{signal}),enabled:signedIn,retry:false});
  const savedChoice = saved.data?.choice;
  const selectedId = businessId || savedChoice?.organization_id || '';
  const selectedDetail = useQuery({
    queryKey:['official-business',selectedId],
    queryFn:({signal})=>request<Business>(`${directoryPath}/businesses/${encodeURIComponent(selectedId)}`,{signal}),
    enabled:Boolean(/^[0-9a-f-]{36}$/i.test(selectedId) && !businesses.some(item=>item.organization_id===selectedId)),retry:false,
  });
  const selected = businesses.find(item=>item.organization_id===selectedId) ?? (selectedDetail.isError?undefined:selectedDetail.data);
  const savedBusiness = businesses.find(item=>item.organization_id===savedChoice?.organization_id)
    ?? (selected?.organization_id===savedChoice?.organization_id?selected:undefined);
  const capabilityOptions = selected?.capabilities.filter(item=>purpose==='customization'?item==='customization':item!=='customization') ?? [];
  const restoredCapability = savedChoice && savedChoice.organization_id===selected?.organization_id && savedChoice.purpose===purpose ? savedChoice.capability : null;
  const preferredCapability = capability ?? restoredCapability;
  const selectedCapability = preferredCapability && capabilityOptions.includes(preferredCapability)?preferredCapability:capabilityOptions[0];
  const mutation = useMutation({mutationFn:()=>command<Choice>(`${directoryPath}/choices`,{organization_id:selected?.organization_id,profile_revision:selected?.revision,capability:selectedCapability,purpose,expected_revision:saved.data?.choice?.revision??0}),onSuccess:choice=>queryClient.setQueryData(choiceKey,{choice})});
  const chooseBusiness = (id:string) => {
    setBusinessId(id);setCapability(null);mutation.reset();
    // Public context survives language/reload without persisting credentials or private drafts.
    const url = new URL(window.location.href);
    url.searchParams.set('business',id);
    router.replace(url.pathname+url.search,{scroll:false});
    requestAnimationFrame(()=>{detail.current?.focus({preventScroll:true});detail.current?.scrollIntoView({block:'nearest',behavior:'instant'});});
  };
  return <div className="directory-page">
    <header className="directory-heading"><p className="eyebrow">{t.eyebrow}</p><h1>{t.title}</h1><p>{t.intro}</p></header>
    <nav className="directory-tabs" aria-label={t.capability}>
      <ButtonLink className={purpose==='servicing'?'':'button-secondary'} href={`/${locale}/services`} aria-current={purpose==='servicing'?'page':undefined}>{t.servicing}</ButtonLink>
      <ButtonLink className={purpose==='customization'?'':'button-secondary'} href={`/${locale}/services?purpose=customization`} aria-current={purpose==='customization'?'page':undefined}>{t.customization}</ButtonLink>
    </nav>
    <p className="directory-notice">{t.notice}</p>
    {savedChoice && <p className="directory-restored"><span>{t.restored} · {t[savedChoice.capability]}</span>{savedBusiness&&<> · <bdi>{savedBusiness.display_name}</bdi></>}</p>}
    {selectedDetail.isError && <div className="notice" role="alert"><p>{t.unavailable}</p><Button className="button-secondary" onClick={()=>void selectedDetail.refetch()}>{t.retry}</Button></div>}
    {directory.isPending ? <div className="directory-loading" role="status">{t.loading}</div> : directory.isError ? <Card><p role="alert">{t.unavailable}</p><Button className="button-secondary" onClick={()=>void directory.refetch()}>{t.retry}</Button></Card> : <div className="directory-columns">
      <section aria-label={t.all} className="directory-list"><div className="directory-list-heading"><p>{t.businesses} · {new Intl.NumberFormat(locale==='ar'?'ar-LB':'en-LB').format(businesses.length)}</p><Button className="button-secondary" onClick={()=>void directory.refetch()}>{t.refresh}</Button></div>
        {businesses.length===0 && <Card><p>{t.empty}</p></Card>}
        {businesses.map(business=><Card key={business.organization_id} className={`directory-business ${selected?.organization_id===business.organization_id?'is-selected':''}`}>
          <div className="directory-business-type"><span className="directory-seal" aria-hidden="true">◇</span><p className="eyebrow">{t[business.kind]}</p></div>
          <h2>{business.display_name}</h2>{business.sample&&<p className="directory-demo">{t.sample}</p>}
          <p className="directory-muted">{locale==='ar'?business.scope_ar:business.scope_en}</p>
          <ul className="directory-capabilities">{business.capabilities.map(item=><li key={item}>{t[item]}</li>)}</ul>
          <Button className="button-secondary" aria-label={`${t.details}: ${business.display_name}`} aria-pressed={selected?.organization_id===business.organization_id} onClick={()=>chooseBusiness(business.organization_id)}>{t.details}<span aria-hidden="true" className="direction-arrow">→</span></Button>
        </Card>)}
        {directory.hasNextPage&&<Button className="button-secondary" disabled={directory.isFetchingNextPage} onClick={()=>void directory.fetchNextPage()}>{directory.isFetchingNextPage?'…':t.more}</Button>}
      </section>
      <aside ref={detail} tabIndex={-1} className="directory-detail" aria-label={t.scope}>{!selected?<Card className="directory-placeholder"><span aria-hidden="true">◷</span><h2>{t.select}</h2></Card>:<>
        <Card><p className="eyebrow">{t.scope}</p><h2>{selected.display_name}</h2><p>{locale==='ar'?selected.scope_ar:selected.scope_en}</p>
          <h3>{t.visit}</h3><p><bdi dir="auto">{selected.contact}</bdi></p><p>{locale==='ar'?selected.visit_ar:selected.visit_en}</p>
          <form onSubmit={event=>{event.preventDefault();mutation.mutate();}}><label>{t.capability}<select value={selectedCapability??''} onChange={event=>{setCapability(event.target.value as Capability);mutation.reset();}}>{capabilityOptions.map(item=><option key={item} value={item}>{t[item]}</option>)}</select></label>
            {mutation.isSuccess&&<p className="notice" role="status">{t.saved}</p>}
            {mutation.isError&&<p role="alert">{mutation.error instanceof ApiError&&mutation.error.code==='stale_revision'?t.stale:t.error}</p>}
            {saved.isError&&<p role="alert">{t.error}<Button type="button" className="button-secondary" onClick={()=>void saved.refetch()}>{t.retry}</Button></p>}
            {signedIn?<Button aria-busy={mutation.isPending} disabled={mutation.isPending||saved.isPending||saved.isError||!selectedCapability}>{mutation.isPending?t.saving:t.choose}</Button>:<SignInAction next={`/services?purpose=${purpose}&business=${selected.organization_id}`} label={t.signin}/>}
          </form>
        </Card>
        {selected.kind==='brand'&&selected.capabilities.includes('customization')&&<MovementOption key={`${selected.organization_id}:${access.fingerprint}`} brandId={selected.organization_id} sample={selected.sample}/>}
      </>}</aside>
    </div>}
  </div>;
}

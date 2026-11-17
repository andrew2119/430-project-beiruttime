'use client';
import { useRef, useState } from 'react';
import { DirectoryAvailability } from './availability';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { usePageRead } from '@/lib/page-speed/read';
import { directoryRead, businessRead, choiceRead } from './reads';
import { Building2, ArrowRight } from 'lucide-react';
import { Button, Card, State, Segmented, Select, StatusBadge, AnimatedList, formatNumber } from '@beirut-time/ui/foundation';
import { PageHeader, PageFrame, PageBody } from '@/shell/foundation/page';
import { privateReadDenied } from './private-read';
import { selectMessages } from './select-messages';
import { OfferingMaintenance } from './maintenance';
import { useRouter, useSearchParams } from 'next/navigation';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { ApiError } from '@/lib/api/client';
import { useSession } from '@/features/identity/session';
import { SignInAction } from './auth-action';
import type { Capability, Choice, Purpose } from '@contracts/contracts-service/directory';
import MovementOption from '../movement-option/view';
import { directoryPath, useJsonCommand, useCommandMutation } from './api';
import en from './en.json';
import ar from './ar.json';

export default function ServiceDirectory() {
  useSession();
  const access = useAccessContext();
  return <DirectoryAvailability><DirectoryContent key={access.fingerprint ?? 'public'}/></DirectoryAvailability>;
}
function DirectoryContent() {
  const detail = useRef<HTMLElement>(null);
  const router = useRouter();
  const locale = useLocale(); const t = locale==='ar'?ar:en; const params = useSearchParams();
  const purpose:Purpose = params.get('purpose')==='customization'?'customization':'servicing';
  const access = useAccessContext(); const signedIn = access.roles.includes('buyer');
  const [businessId,setBusinessId] = useState(params.get('business') ?? '');
  const [capability,setCapability] = useState<Capability|null>(null);
  const [profileLocked,setProfileLocked]=useState(false);
  const [movementLocked,setMovementLocked]=useState(false);
  const [cursors,setCursors]=useState<(string|null)[]>([null]);
  const directory = usePageRead(directoryRead(purpose,cursors.at(-1)??null));
  const businesses = directory.data?.items ?? [];
  const command = useJsonCommand();
  const saved = usePageRead(signedIn && access.fingerprint ? choiceRead(access.fingerprint):null);
  const [accessDenied,setAccessDenied] = useState(false);
  const [hideResult,setHideResult] = useState(false);
  const denied = privateReadDenied(saved.error);
  if (denied && !accessDenied) {
    setAccessDenied(true);
    setHideResult(true);
    setCapability(null);
  } else if (accessDenied && !denied && saved.isSuccess && !saved.isFetching) {
    setAccessDenied(false);
  }
  const privateBlocked = denied || accessDenied || !signedIn;
  const savedChoice = privateBlocked ? null : saved.data?.choice;
  if (!businessId && savedChoice) setBusinessId(savedChoice.organization_id);
  const selectedId = businessId || savedChoice?.organization_id || '';
  const selectedDetail = usePageRead(/^[0-9a-f-]{36}$/i.test(selectedId) ? businessRead(selectedId):null);
  const selected = businesses.find(item=>item.organization_id===selectedId) ?? (selectedDetail.isError?undefined:selectedDetail.data);
  const savedBusiness = businesses.find(item=>item.organization_id===savedChoice?.organization_id)
    ?? (selected?.organization_id===savedChoice?.organization_id?selected:undefined);
  const capabilityOptions = selected?.capabilities.filter(item=>purpose==='customization'?item==='customization':item!=='customization') ?? [];
  const restoredCapability = savedChoice && savedChoice.organization_id===selected?.organization_id && savedChoice.purpose===purpose ? savedChoice.capability : null;
  const preferredCapability = capability ?? restoredCapability;
  const selectedCapability = preferredCapability && capabilityOptions.includes(preferredCapability)?preferredCapability:capabilityOptions[0];
  const mutation = useCommandMutation({mutationFn:()=>command<Choice>(`${directoryPath}/choices`,{organization_id:selected?.organization_id,profile_revision:selected?.revision,capability:selectedCapability,purpose,expected_revision:saved.data?.choice?.revision??0}),onSuccess:()=>{setHideResult(false);void saved.refetch();}});
  const chooseBusiness = (id:string) => {
    setBusinessId(id);setCapability(null);mutation.reset();
    // Public context survives language/reload without persisting credentials or private drafts.
    const url = new URL(window.location.href);
    url.searchParams.set('business',id);
    router.replace(url.pathname+url.search,{scroll:false});
    requestAnimationFrame(()=>{detail.current?.focus({preventScroll:true});detail.current?.scrollIntoView({block:'nearest',behavior:'instant'});});
  };
  return <PageFrame>
    <PageHeader lead={t.eyebrow} title={t.title} count={t.intro} tabs={<Segmented disabled={profileLocked||movementLocked||mutation.isPending||mutation.needsRecovery} label={t.capability} value={purpose} locale={locale} onValueChange={value=>{const url=new URL(window.location.href);setCursors([null]);url.searchParams.set('purpose',value);router.replace(url.pathname+url.search,{scroll:false});}} options={[{value:'servicing',label:t.servicing},{value:'customization',label:t.customization}]}/> } notice={<p className="bt-text">{t.notice}</p>}/><PageBody>
    <OfferingMaintenance onLockChange={setProfileLocked}/>
    {privateBlocked && signedIn && <State kind="error" title={t.restored} body={t.authDenied}><Button onClick={()=>void saved.refetch()}>{t.retry}</Button></State>}
    {savedChoice && <p className="directory-restored"><span>{t.restored} · {t[savedChoice.capability]}</span>{savedBusiness&&<> · <bdi>{savedBusiness.display_name}</bdi></>}</p>}
    {selectedDetail.isError && <div className="notice" role="alert"><p>{t.unavailable}</p><Button variant="outline" onClick={()=>void selectedDetail.refetch()}>{t.retry}</Button></div>}
    <AnswerArrival view="service-directory"><div className="directory-columns">
      <section aria-label={t.all} className="directory-list"><div className="directory-list-heading"><p>{t.businesses} · {formatNumber(directory.data?.total??0,locale)}</p><Button variant="outline" onClick={()=>void directory.refetch()}>{t.refresh}</Button></div>
        {directory.isPending && !directory.data && <State kind="loading" title={t.title} body={t.loading}/>}
        {!directory.isPending && !directory.isError && businesses.length===0 && <State title={t.businesses} body={t.empty}/>}
        <AnimatedList scopeKey={`directory:${purpose}`} items={businesses} getKey={business=>business.organization_id}>{business=><Card className={`directory-business ${selected?.organization_id===business.organization_id?'is-selected':''}`}>
          <div className="directory-business-type"><span className="directory-seal" aria-hidden="true"><Building2/></span><p className="eyebrow">{t[business.kind]}</p></div>
          <h2>{business.display_name}</h2>{business.sample&&<p className="directory-demo">{t.sample}</p>}
          <p className="directory-muted">{locale==='ar'?business.scope_ar:business.scope_en}</p>
          <ul className="directory-capabilities">{business.capabilities.map(item=><li key={item}><StatusBadge tone="neutral">{t[item]}</StatusBadge></li>)}</ul>
          <Button variant="outline" aria-label={`${t.details}: ${business.display_name}`} aria-pressed={selected?.organization_id===business.organization_id} disabled={profileLocked||movementLocked||mutation.isPending||mutation.needsRecovery} onClick={()=>chooseBusiness(business.organization_id)}>{t.details}<ArrowRight aria-hidden="true" className="direction-arrow"/></Button>
        </Card>}</AnimatedList>
        {directory.isError&&<State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>void directory.refetch()}>{t.retry}</Button></State>}
        {cursors.length>1&&<Button variant="outline" disabled={profileLocked||movementLocked||mutation.isPending||mutation.needsRecovery} onClick={()=>setCursors(value=>value.slice(0,-1))}>{t.previous}</Button>}
        {directory.data?.next_after&&<Button variant="outline" disabled={directory.isFetching||profileLocked||movementLocked||mutation.isPending||mutation.needsRecovery} onClick={()=>setCursors(value=>[...value,directory.data?.next_after??null])}>{t.more}</Button>}
      </section>
      <aside ref={detail} tabIndex={-1} className="directory-detail" aria-label={t.scope}>{!selected?<State title={t.select} body={t.scope}/>:<>
        <Card><p className="eyebrow">{t.scope}</p><h2>{selected.display_name}</h2><p>{locale==='ar'?selected.scope_ar:selected.scope_en}</p>
          <h3>{t.visit}</h3><p><bdi dir="auto">{selected.contact}</bdi></p><p>{locale==='ar'?selected.visit_ar:selected.visit_en}</p>
          {privateBlocked && signedIn ? <State kind="error" title={t.restored} body={t.authDenied}><Button onClick={()=>void saved.refetch()}>{t.retry}</Button></State> : <form onSubmit={event=>{event.preventDefault();mutation.mutate();}}><Select disabled={profileLocked||movementLocked||mutation.isPending||mutation.needsRecovery} label={t.capability} messages={selectMessages(locale)} value={selectedCapability??null} onValueChange={value=>{setCapability(value as Capability);mutation.reset();}} options={capabilityOptions.map(item=>({value:item,label:t[item]}))}/>
            {!hideResult&&mutation.isSuccess&&<p className="notice" role="status">{t.saved}</p>}
            {mutation.isError&&<p role="alert">{mutation.error instanceof ApiError&&mutation.error.code==='stale_revision'?t.stale:t.error}</p>}
            {saved.isError&&<p role="alert">{t.error}<Button type="button" variant="outline" onClick={()=>void saved.refetch()}>{t.retry}</Button></p>}
            {signedIn?<Button type="submit" aria-busy={mutation.isPending} disabled={mutation.isPending||saved.isPending||saved.isError||!selectedCapability}>{mutation.isPending?t.saving:mutation.needsRecovery?t.retryOriginal:t.choose}</Button>:<SignInAction next={`/services?purpose=${purpose}&business=${selected.organization_id}`} label={t.signin}/>}
          </form>}
        </Card>
        {selected.kind==='brand'&&selected.capabilities.includes('customization')&&<MovementOption key={`${selected.organization_id}:${access.fingerprint}`} onLockChange={setMovementLocked} brandId={selected.organization_id} sample={selected.sample}/>}
      </>}</aside>
    </div></AnswerArrival>
  </PageBody></PageFrame>;
}

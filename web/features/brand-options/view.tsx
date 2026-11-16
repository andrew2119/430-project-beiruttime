'use client';
import { PageHeader, PageLayout } from '@/shell/page-header';
import Image from 'next/image';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, Input, Segmented, Radio, Skeleton, AnimatedList } from '@beirut-time/ui';
import type { Configuration, Kind, Option, SelectionWrite } from '@contracts/contracts-catalog/options';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState, refreshSession, signInHref } from '@/features/identity/session';
import { hasRoute } from '@/registry-loader';
import { optionsApi } from './api';
import { matchesAcknowledgedSelection } from './model';
import { readPrivatePng } from './images';
import { fencePrivateState } from './access-lease';
import { previewPalette } from './preview';
import en from './en.json';
import ar from './ar.json';

const kinds: Kind[] = ['color','material','dial','sophistication'];
type Copy = typeof en;
function errorCopy(error: unknown, t: Copy) {
  if (!(error instanceof ApiError)) return t.genericError;
  if (error.status === 401) return t.signIn;
  if (error.status === 403 || error.status === 404) return t.denied;
  if (error.code.startsWith('stale_') || error.code === 'idempotency_conflict') return t.stale;
  if (error.status >= 500) return t.unavailable;
  if (error.code.includes('reference')) return t.referenceError;
  if (error.status === 409 || error.status === 422) return t.invalid;
  return t.genericError;
}

type InitialState = {initialBrand?:string;initialConfiguration?:string;initialBase?:string;initialCaliber?:string};
export default function BrandOptions(initial: InitialState) {
  const session = useSession();
  const fingerprint=session?.access_fingerprint??null;
  const sessionState=useSessionState();
  // The SDK owns restoration and retry status; do not mirror its external store in local state.
  // Remount all local private state at the same synchronous identity boundary as query state.
  return <Configurator key={fingerprint ?? 'public'} fingerprint={fingerprint}
    identityPending={!session&&sessionState==='restoring'} identityError={!session&&sessionState==='unavailable'}
    retryIdentity={()=>void refreshSession().catch(()=>{/* SDK publishes unavailable for explicit retry. */})} {...initial} />;
}

type IdentityState = {fingerprint:string|null;identityPending:boolean;identityError:boolean;retryIdentity:()=>void};
function Configurator({fingerprint,identityPending,identityError,retryIdentity,initialBrand='',initialConfiguration='',initialBase='',initialCaliber=''}: InitialState & IdentityState) {
  const locale = useLocale(), t = locale === 'ar' ? ar : en, queryClient = useQueryClient();
  const [draftBrand,setBrand] = useState(initialBrand), [draftBase,setBase] = useState(initialBase), [draftCaliber,setCaliber] = useState(initialCaliber);
  const [kind,setKind] = useState<Kind>('color'), [chosen,setChosen] = useState('');
  const [configurationId,setConfigurationId] = useState(initialConfiguration);
  const [pending,setPending] = useState(false);
  const [failure,setFailure] = useState<unknown>(null), [message,setMessage] = useState('');
  const [operation,setOperation] = useState<{signature:string;key:string;kind:Kind;body:SelectionWrite}|null>(null);
  const alive = useRef(true);
  const inFlight = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadOperation = useRef<{signature:string;key:string}|null>(null);
  useLayoutEffect(() => fencePrivateState(alive,window), []);
  const configurationQuery = useQuery({queryKey:['brand-options','configuration',fingerprint,configurationId],queryFn:({signal})=>optionsApi.configuration(configurationId,signal),enabled:!!fingerprint&&!!configurationId&&!pending});
  // One canonical snapshot drives bindings, references and summary, including after uncertain writes.
  const ack = fingerprint ? configurationQuery.data??null : null;
  const brand=ack?.brand_id??draftBrand,base=ack?.base_model??draftBase,caliber=ack?.caliber??draftCaliber;
  const references=ack?.reference_ids??[];
  const reconciled=!!ack&&!!operation&&failure instanceof ApiError&&failure.status>=500&&matchesAcknowledgedSelection(ack,operation.kind,operation.body);
  const brandQuery = useInfiniteQuery({queryKey:['brand-options','brands'],initialPageParam:null as string|null,
    queryFn:({signal,pageParam})=>optionsApi.brands(signal,pageParam),getNextPageParam:last=>last.next_after??undefined});
  const listedBrands=brandQuery.data?.pages.flatMap(page=>page.items)??[];
  const selectedBrand=listedBrands.some(item=>item.organization_id===brand)?null:brand;
  const catalogQuery = useQuery({queryKey:['brand-options','catalog',brand],queryFn:({signal})=>optionsApi.catalog(brand,signal),enabled:!!brand});
  const savedQuery = useQuery({queryKey:['brand-options','saved',fingerprint],queryFn:({signal})=>optionsApi.configurations(signal),enabled:!!fingerprint});
  const items = catalogQuery.data?.items ?? [];
  const bases = [...new Set(items.flatMap(o=>o.base_models))];
  const calibers = [...new Set(items.filter(o=>o.base_models.includes(base)).flatMap(o=>o.calibers))];
  const supported = items.filter(o=>o.kind===kind&&o.base_models.includes(base)&&o.calibers.includes(caliber));
  const selected = supported.find(o=>o.id===chosen);
  const palette=previewPalette(ack,selected);
  const busy = pending;
  function updateUrl(id:string, brandId:string) {
    const url = new URL(window.location.href);
    if(id) url.searchParams.set('configuration',id); else url.searchParams.delete('configuration');
    if(brandId) url.searchParams.set('brand',brandId); else url.searchParams.delete('brand');
    window.history.replaceState(window.history.state,'',url);
  }
  function updateBindings(nextBase:string,nextCaliber:string) {
    const url=new URL(window.location.href);
    if(nextBase)url.searchParams.set('base',nextBase);else url.searchParams.delete('base');
    if(nextCaliber)url.searchParams.set('caliber',nextCaliber);else url.searchParams.delete('caliber');
    window.history.replaceState(window.history.state,'',url);
  }
  function startNew() {
    setBrand(brand);setBase(base);setCaliber(caliber);
    setConfigurationId('');setChosen('');setMessage('');setFailure(null);setOperation(null);
    updateUrl('',brand);
  }
  async function save() {
    if (!selected || !fingerprint || inFlight.current) return;
    inFlight.current=true;setPending(true);setFailure(null);setMessage('');
    const id = configurationId || crypto.randomUUID();
    const body = {brand_id:brand,base_model:base,caliber,component:selected.component,option_id:selected.id,
      option_revision:selected.revision,expected_revision:ack?.revision??0,reference_ids:kind==='dial'?references:[]};
    const signature = JSON.stringify({id,kind,body});
    const intent=operation?.signature===signature?operation:{signature,key:crypto.randomUUID(),kind,body};
    setOperation(intent);
    // Keep the resource and operation IDs on timeout: a retry reconciles the original operation.
    setConfigurationId(id);updateUrl(id,brand);
    try {
      const result = await optionsApi.save(id,kind,body,intent.key);
      if (!alive.current) return;
      setMessage(t.saved);setOperation(null);
      queryClient.setQueryData(['brand-options','configuration',fingerprint,id],result);
      void queryClient.invalidateQueries({queryKey:['brand-options','saved',fingerprint]});
    } catch(error) {
      if(alive.current) {
        setFailure(error);
        // An uncertain write invalidates the canonical read in the event that caused it.
        if(error instanceof ApiError&&error.status>=500) void queryClient.invalidateQueries({queryKey:['brand-options','configuration',fingerprint,id]});
      }
    }
    finally { inFlight.current=false;if(alive.current)setPending(false); }
  }
  async function upload(file:File|undefined) {
    if(!file||!ack||inFlight.current) return;
    if(file.size>1048576||file.type!=='image/png') { setMessage(t.referenceError);return; }
    inFlight.current=true;setPending(true);setFailure(null);setMessage('');
    try {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())),byte=>byte.toString(16).padStart(2,'0')).join('');
      if (!alive.current) return;
      const signature=ack.id+':'+hash;
      if(uploadOperation.current?.signature!==signature)uploadOperation.current={signature,key:crypto.randomUUID()};
      const result=await optionsApi.upload(ack.id,file,uploadOperation.current.key);
      if(alive.current) {
        setMessage(t.referenceSaved);uploadOperation.current=null;
        queryClient.setQueryData<Configuration>(['brand-options','configuration',fingerprint,ack.id],prior=>prior?{...prior,reference_ids:[...new Set([...prior.reference_ids,result.id])]}:prior);
      }
    } catch(error) { if(alive.current)setFailure(error); }
    finally {inFlight.current=false;if(alive.current)setPending(false);if(fileInput.current)fileInput.current.value='';}
  }
  const activeError = (reconciled?null:failure) ?? configurationQuery.error ?? savedQuery.error;
  const returnQuery=new URLSearchParams();
  if(brand)returnQuery.set('brand',brand);
  if(base)returnQuery.set('base',base);
  if(caliber)returnQuery.set('caliber',caliber);
  if(configurationId)returnQuery.set('configuration',configurationId);
  return <PageLayout className="bo-page">
    <PageHeader lead={t.eyebrow} title={t.title} count={t.intro}/>
    <div className="bo-layout">
      <Card className="bo-workbench">
        <section className="bo-binding" aria-label={t.brand}>
          <label>{t.brand}<select name="brand" value={brand} disabled={busy||!!ack} onChange={e=>{setBrand(e.target.value);setBase('');setCaliber('');setChosen('');updateUrl('',e.target.value);updateBindings('','');}}>
            <option value="">{t.chooseBrand}</option>{selectedBrand&&catalogQuery.data&&<option value={selectedBrand}>{catalogQuery.data.brand.name[locale]}</option>}{listedBrands.map(b=><option value={b.organization_id} key={b.organization_id}>{b.name[locale]}</option>)}
          </select></label>
          <label>{t.base}<select dir="ltr" name="base_model" value={base} disabled={!brand||busy||!!ack} onChange={e=>{setBase(e.target.value);setCaliber('');setChosen('');updateBindings(e.target.value,'');}}>
            <option value="">{t.chooseBase}</option>{bases.map(b=><option key={b} value={b}>{b}</option>)}
          </select></label>
          <label>{t.caliber}<select dir="ltr" name="caliber" value={caliber} disabled={!base||busy||!!ack} onChange={e=>{setCaliber(e.target.value);setChosen('');updateBindings(base,e.target.value);}}>
            <option value="">{t.chooseCaliber}</option>{calibers.map(c=><option key={c} value={c}>{c}</option>)}
          </select></label>
        </section>
        {brandQuery.hasNextPage&&<Button variant="outline" disabled={brandQuery.isFetchingNextPage||busy} onClick={()=>void brandQuery.fetchNextPage()}>{brandQuery.isFetchingNextPage?t.loading:t.moreBrands}</Button>}
        {catalogQuery.data?.brand.sample&&<p className="notice">{t.sample}</p>}
        {(brandQuery.isLoading||catalogQuery.isLoading)&&<div role="status" className="bo-loading"><Skeleton/>{t.loading}</div>}
        {(brandQuery.error||catalogQuery.error)&&<div className="notice" role="alert"><p>{t.unavailable}</p><Button variant="outline" onClick={()=>{void brandQuery.refetch();void catalogQuery.refetch();}}>{t.retry}</Button></div>}
        {brandQuery.isSuccess&&!listedBrands.length&&!brandQuery.hasNextPage&&<p className="notice">{t.noBrands}</p>}
        <div className="bo-categories" inert={busy}><Segmented aria-label={t.chooseCategory} value={kind} onChange={value=>{setKind(value as Kind);setChosen('');setMessage('');}} options={kinds.map(value=>({value,label:t[value]}))}/></div>
        {!base||!caliber?<p className="bo-empty">{t.noSelection}</p>:<fieldset className="bo-options" disabled={busy}><legend className="sr-only">{t[kind]}</legend>
          {supported.length?<AnimatedList items={supported} getKey={option=>option.id}>{option=><div className="bo-option" data-selected={chosen===option.id} onClick={event=>{if(!busy&&option.available){setChosen(option.id);setMessage('');event.currentTarget.querySelector('input')?.focus();}}}>
            <Radio className="bo-option-title" name="brand-option" value={option.id} checked={chosen===option.id} disabled={!option.available} onChange={()=>{setChosen(option.id);setMessage('');}}>{option.label[locale]}</Radio>
            <p className="bo-option-meta">{t.component}: {t[option.component]} · {t.revision} <BidiReference>{option.revision}</BidiReference></p>
            <OptionDetails option={option} locale={locale} t={t}/>
            {!option.available&&<p className="notice">{t.invalid}</p>}
          </div>}</AnimatedList>:<p className="bo-empty">{t.empty}</p>}
        </fieldset>}
        {kind==='dial'&&<section className="bo-reference"><h2>{t.privateReference}</h2><p id="bo-reference-help">{t.referenceHelp}</p><Input name="private_dial_reference" ref={fileInput} type="file" accept="image/png" disabled={!ack||!fingerprint||busy||references.length>=3} aria-label={t.upload} aria-describedby="bo-reference-help" onChange={e=>{void upload(e.target.files?.[0]);}}/><p>{t.references}: <BidiReference>{references.length} / 3</BidiReference></p>{ack&&<div className="bo-private-images">{references.map(id=><PrivateReference key={id} configurationId={ack.id} referenceId={id} label={t.privateReference} failureLabel={t.referenceUnavailable} retryLabel={t.retry}/>)}</div>}</section>}
        {identityPending&&<p className="bo-feedback" role="status">{t.loadingSaved}</p>}
        {!!identityError&&<div className="notice" role="alert"><p>{t.identityUnavailable}</p><Button variant="outline" onClick={retryIdentity}>{t.retry}</Button></div>}
        {!fingerprint&&!identityPending&&!identityError&&<div className="bo-signin"><ButtonLink href={signInHref('/customize'+(returnQuery.size?'?'+returnQuery:''),locale)}>{t.signIn}</ButtonLink><p>{t.signInBody}</p></div>}
        <div className="bo-actions"><Button chonk disabled={!selected?.available||!fingerprint||busy} onClick={()=>void save()}>{busy?t.saving:t.save}<span aria-hidden="true">↗</span></Button>
          {(ack||configurationId)&&<Button variant="outline" disabled={busy} onClick={startNew}>{t.new}</Button>}</div>
        <div aria-live="polite" role="status" className="bo-feedback">{busy?t.pending:reconciled?t.saved:message}</div>
        {activeError&&<div role="alert" className="notice"><p>{errorCopy(activeError,t)}</p>{activeError instanceof ApiError&&activeError.requestId&&<BidiReference>{activeError.requestId}</BidiReference>}
          <Button variant="outline" disabled={busy} onClick={()=>{setFailure(null);void catalogQuery.refetch();void savedQuery.refetch();if(configurationId)void configurationQuery.refetch();}}>{t.refresh}</Button></div>}
      </Card>
      <aside className="bo-summary ui-card" aria-label={t.summary}>
        <figure className="bo-illustration"><svg viewBox="0 0 320 340" role="img" aria-label={t.watchFace}><rect x="132" y="4" width="56" height="330" rx="14" fill={palette.strap} stroke="var(--primary-ink)"/><circle cx="160" cy="170" r="112" fill={palette.case} stroke={palette.bezel} strokeWidth="3"/><circle cx="160" cy="170" r="97" fill={palette.dial}/>{Array.from({length:12},(_,i)=><path key={i} d="M160 83v10" transform={`rotate(${i*30} 160 170)`} stroke={palette.markers} strokeWidth="2"/>)}<path d="M160 109v61l43 29" stroke={palette.hands} strokeWidth="4" fill="none"/><circle cx="160" cy="170" r="5" fill={palette.hands}/></svg><figcaption>{t.illustration}</figcaption></figure>
        <section><p className="eyebrow">{t.notApproved}</p><h2>{t.summary}</h2>{ack?<><p>{t.savedRevision} <BidiReference>{ack.revision}</BidiReference></p><dl className="bo-saved">{ack.selections.map(s=><div key={`${s.kind}-${s.component}`}><dt>{t[s.kind]} · {t[s.component]}</dt><dd>{s.definition.label[locale]} <small>{t.revision} <BidiReference>{s.option_revision}</BidiReference></small>{!s.current&&<p className="notice">{t.needsReview}</p>}</dd></div>)}</dl>{hasRoute('/custom-requests')&&<ButtonLink variant="outline" href={`/${locale}/custom-requests?configuration=${ack.id}&revision=${ack.revision}`}>{t.next}</ButtonLink>}</>:<p>{t.summaryEmpty}</p>}</section>
        {!!savedQuery.data?.items.length&&<label className="bo-resume">{t.resume}<select dir="ltr" name="saved_configuration" value={configurationId} disabled={busy} onChange={e=>{setBrand(brand);setBase(base);setCaliber(caliber);setConfigurationId(e.target.value);setChosen('');setFailure(null);setOperation(null);updateUrl(e.target.value,'');}}><option value="">—</option>{savedQuery.data.items.map(c=><option key={c.id} value={c.id}>{c.base_model} · {c.id.slice(0,8)} · {c.revision}</option>)}</select></label>}
      </aside>
    </div>
  </PageLayout>;
}

function PrivateReference({configurationId,referenceId,label,failureLabel,retryLabel}: {configurationId:string;referenceId:string;label:string;failureLabel:string;retryLabel:string}) {
  const session=useSession(),token=session?.access_token;
  const [attempt,setAttempt]=useState(0);
  const requestKey=JSON.stringify([session?.access_fingerprint,configurationId,referenceId,attempt]);
  const [result,setResult]=useState<{key:string;url:string;failed:boolean}|null>(null);
  const current=token&&result?.key===requestKey?result:null;
  useEffect(()=>{
    if(!token)return;
    const abort=new AbortController(),alive={current:true};
    const close=fencePrivateState(alive,window,()=>abort.abort());
    void optionsApi.reference(configurationId,referenceId,token,abort.signal)
      .then(blob=>readPrivatePng(blob,abort.signal))
      .then(url=>{if(!abort.signal.aborted)setResult({key:requestKey,url,failed:false});})
      .catch(()=>{if(!abort.signal.aborted)setResult({key:requestKey,url:'',failed:true});});
    return close;
  },[configurationId,referenceId,token,requestKey]);
  if(current?.failed)return <div><p role="status">{failureLabel}</p><Button variant="outline" onClick={()=>setAttempt(prior=>prior+1)}>{retryLabel}</Button></div>;
  // Memory-only private data must never enter the public image optimizer.
  return current?.url?<Image unoptimized src={current.url} alt={label} width={120} height={120} onError={()=>setResult({key:requestKey,url:'',failed:true})}/>:<Skeleton role="status" aria-label={label} aria-hidden={false}/>;
}

function OptionDetails({option,locale,t}: {option:Option;locale:'en'|'ar';t:Copy}) {
  if(option.kind==='color') return <div className="bo-color"><span className="bo-swatch" style={{backgroundColor:/^#[\da-f]{6}$/i.test(option.details.swatch)?option.details.swatch:undefined}} aria-hidden="true"/><p>{option.details.color[locale]} · {option.details.finish[locale]}{option.details.coating&&<> · {t.coating}: {option.details.coating[locale]}</>}</p></div>;
  if(option.kind==='material') return <dl className="bo-details"><div><dt>{t.material}</dt><dd>{option.details.material[locale]}</dd></div><div><dt>{t.grade}</dt><dd><BidiReference>{option.details.grade}</BidiReference></dd></div><div><dt>{t.construction}</dt><dd>{t[option.details.construction]}</dd></div>{option.details.substrate&&<div><dt>{t.substrate}</dt><dd>{option.details.substrate[locale]}</dd></div>}{option.details.thickness_micrometers!==null&&<div><dt>{t.thickness}</dt><dd><BidiReference>{option.details.thickness_micrometers}</BidiReference></dd></div>}</dl>;
  if(option.kind==='dial') return <dl className="bo-details"><div><dt>{t.dial}</dt><dd>{option.details.dial[locale]}</dd></div><div><dt>{t.hands}</dt><dd>{option.details.hands[locale]}</dd></div><div><dt>{t.markers}</dt><dd>{option.details.markers[locale]}</dd></div><div><dt>{t.provenance}</dt><dd>{t[option.details.provenance]}</dd></div><div><dt>{t.source}</dt><dd><BidiReference>{option.details.source_reference}</BidiReference></dd></div></dl>;
  return <div className="bo-package">{(['interventions','exclusions','required_tests'] as const).map(key=><div key={key}><h3>{key==='required_tests'?t.tests:t[key]}</h3><ul>{option.details[key].map((entry,index)=><li key={index}>{entry[locale]}</li>)}</ul></div>)}<p>{t.priceRef}: <BidiReference>{option.details.price_reference}</BidiReference></p><strong><BidiReference>{new Intl.NumberFormat(locale==='ar'?'ar-LB':'en-US',{style:'currency',currency:option.details.currency}).format(option.details.price_minor/(option.details.currency==='USD'?100:1))}</BidiReference></strong><p>{t.priceNote}</p></div>;
}

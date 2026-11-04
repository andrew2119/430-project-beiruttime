'use client';
import Link from 'next/link';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, Input } from '@beirut-time/ui';
import type { Configuration, Kind, Option, SelectionWrite } from '@contracts/contracts-catalog/options';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { useSession, refreshSession, signInHref } from '@/features/identity/session';
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
  const [identityError,setIdentityError]=useState<unknown>(null),[checking,setChecking]=useState(true),[attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let active=true;
    if(session){setChecking(false);setIdentityError(null);return;}
    setChecking(true);setIdentityError(null);
    // Joins the SDK's one restoration flight; no token is copied into a query or persistence.
    void refreshSession().then(()=>{if(active)setChecking(false);}).catch(error=>{
      if(active){setIdentityError(error);setChecking(false);}
    });
    return()=>{active=false;};
  },[fingerprint,attempt]);
  // CP F-16: remount all local private state at the same synchronous identity boundary as query state.
  return <Configurator key={fingerprint ?? 'public'} fingerprint={fingerprint} identityPending={!session&&checking} identityError={session?null:identityError} retryIdentity={()=>setAttempt(prior=>prior+1)} {...initial} />;
}

type IdentityState = {fingerprint:string|null;identityPending:boolean;identityError:unknown;retryIdentity:()=>void};
function Configurator({fingerprint,identityPending,identityError,retryIdentity,initialBrand='',initialConfiguration='',initialBase='',initialCaliber=''}: InitialState & IdentityState) {
  const locale = useLocale(), t = locale === 'ar' ? ar : en, queryClient = useQueryClient();
  const [brand,setBrand] = useState(initialBrand), [base,setBase] = useState(initialBase), [caliber,setCaliber] = useState(initialCaliber);
  const [kind,setKind] = useState<Kind>('color'), [chosen,setChosen] = useState('');
  const [configurationId,setConfigurationId] = useState(initialConfiguration);
  const [ack,setAck] = useState<Configuration|null>(null), [pending,setPending] = useState(false);
  const [failure,setFailure] = useState<unknown>(null), [message,setMessage] = useState('');
  const [references,setReferences] = useState<string[]>([]);
  const alive = useRef(true);
  const inFlight = useRef(false);
  const operation = useRef<{signature:string;key:string;kind:Kind;body:SelectionWrite}|null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadOperation = useRef<{signature:string;key:string}|null>(null);
  useLayoutEffect(() => fencePrivateState(alive,window), []);
  const brandQuery = useQuery({queryKey:['brand-options','brands'],queryFn:({signal})=>optionsApi.brands(signal)});
  const catalogQuery = useQuery({queryKey:['brand-options','catalog',brand],queryFn:({signal})=>optionsApi.catalog(brand,signal),enabled:!!brand});
  const savedQuery = useQuery({queryKey:['brand-options','saved',fingerprint],queryFn:({signal})=>optionsApi.configurations(signal),enabled:!!fingerprint});
  const configurationQuery = useQuery({queryKey:['brand-options','configuration',fingerprint,configurationId],queryFn:({signal})=>optionsApi.configuration(configurationId,signal),enabled:!!fingerprint&&!!configurationId&&!pending});
  useEffect(() => {
    const config = configurationQuery.data;
    if (!config) return;
    setAck(config); setBrand(config.brand_id); setBase(config.base_model); setCaliber(config.caliber);
    setReferences(config.reference_ids);
    const intent=operation.current;
    if(intent&&failure instanceof ApiError&&failure.status>=500&&matchesAcknowledgedSelection(config,intent.kind,intent.body)) {
      operation.current=null;setFailure(null);setMessage(t.saved);
    }
  }, [configurationQuery.data, failure, t.saved]);
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
    setConfigurationId('');setAck(null);setChosen('');setReferences([]);setMessage('');setFailure(null);operation.current=null;
    updateUrl('',brand);
  }
  async function save() {
    if (!selected || !fingerprint || inFlight.current) return;
    inFlight.current=true;setPending(true);setFailure(null);setMessage('');
    const id = configurationId || crypto.randomUUID();
    const body = {brand_id:brand,base_model:base,caliber,component:selected.component,option_id:selected.id,
      option_revision:selected.revision,expected_revision:ack?.revision??0,reference_ids:kind==='dial'?references:[]};
    const signature = JSON.stringify({id,kind,body});
    if (operation.current?.signature !== signature) operation.current={signature,key:crypto.randomUUID(),kind,body};
    // Keep the resource and operation IDs on timeout: a retry reconciles the original operation.
    setConfigurationId(id);updateUrl(id,brand);
    try {
      const result = await optionsApi.save(id,kind,body,operation.current.key);
      if (!alive.current) return;
      setAck(result);setMessage(t.saved);operation.current=null;
      queryClient.setQueryData(['brand-options','configuration',fingerprint,id],result);
      void queryClient.invalidateQueries({queryKey:['brand-options','saved',fingerprint]});
    } catch(error) { if(alive.current) setFailure(error); }
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
        setReferences(prior=>[...new Set([...prior,result.id])].slice(0,3));setMessage(t.referenceSaved);uploadOperation.current=null;
        queryClient.setQueryData<Configuration>(['brand-options','configuration',fingerprint,ack.id],prior=>prior?{...prior,reference_ids:[...new Set([...prior.reference_ids,result.id])]}:prior);
      }
    } catch(error) { if(alive.current)setFailure(error); }
    finally {inFlight.current=false;if(alive.current)setPending(false);if(fileInput.current)fileInput.current.value='';}
  }
  const activeError = failure ?? configurationQuery.error ?? savedQuery.error;
  const returnQuery=new URLSearchParams();
  if(brand)returnQuery.set('brand',brand);
  if(base)returnQuery.set('base',base);
  if(caliber)returnQuery.set('caliber',caliber);
  if(configurationId)returnQuery.set('configuration',configurationId);
  return <div className="bo-page">
    <header className="bo-heading"><p className="eyebrow">{t.eyebrow}</p><h1>{t.title}</h1><p>{t.intro}</p></header>
    <div className="bo-layout">
      <div className="bo-workbench">
        <section className="bo-binding" aria-label={t.brand}>
          <label>{t.brand}<select name="brand" value={brand} disabled={busy||!!ack} onChange={e=>{setBrand(e.target.value);setBase('');setCaliber('');setChosen('');updateUrl('',e.target.value);updateBindings('','');}}>
            <option value="">{t.chooseBrand}</option>{brandQuery.data?.items.map(b=><option value={b.organization_id} key={b.organization_id}>{b.name[locale]}</option>)}
          </select></label>
          <label>{t.base}<select dir="ltr" name="base_model" value={base} disabled={!brand||busy||!!ack} onChange={e=>{setBase(e.target.value);setCaliber('');setChosen('');updateBindings(e.target.value,'');}}>
            <option value="">{t.chooseBase}</option>{bases.map(b=><option key={b} value={b}>{b}</option>)}
          </select></label>
          <label>{t.caliber}<select dir="ltr" name="caliber" value={caliber} disabled={!base||busy||!!ack} onChange={e=>{setCaliber(e.target.value);setChosen('');updateBindings(base,e.target.value);}}>
            <option value="">{t.chooseCaliber}</option>{calibers.map(c=><option key={c} value={c}>{c}</option>)}
          </select></label>
        </section>
        {catalogQuery.data?.brand.sample&&<p className="notice">{t.sample}</p>}
        {(brandQuery.isLoading||catalogQuery.isLoading)&&<div role="status" className="bo-loading"><div className="skeleton"/>{t.loading}</div>}
        {(brandQuery.error||catalogQuery.error)&&<div className="notice" role="alert"><p>{t.unavailable}</p><Button className="button-secondary" onClick={()=>{void brandQuery.refetch();void catalogQuery.refetch();}}>{t.retry}</Button></div>}
        {brandQuery.isSuccess&&!brandQuery.data.items.length&&<p className="notice">{t.noBrands}</p>}
        <div className="bo-categories" role="group" aria-label={t.chooseCategory}>{kinds.map((value,index)=><button key={value} type="button" aria-pressed={kind===value} disabled={busy} onClick={()=>{setKind(value);setChosen('');setMessage('');}}><span aria-hidden="true">0{index+1}</span>{t[value]}</button>)}</div>
        {!base||!caliber?<p className="bo-empty">{t.noSelection}</p>:<fieldset className="bo-options" disabled={busy}><legend className="sr-only">{t[kind]}</legend>
          {supported.length?supported.map(option=><label className="bo-option" data-selected={chosen===option.id} key={option.id}>
            <div className="bo-option-title"><input type="radio" name="brand-option" value={option.id} checked={chosen===option.id} disabled={!option.available} onChange={()=>{setChosen(option.id);setMessage('');}}/><h2>{option.label[locale]}</h2></div>
            <p className="bo-option-meta">{t.component}: {t[option.component]} · {t.revision} <BidiReference>{option.revision}</BidiReference></p>
            <OptionDetails option={option} locale={locale} t={t}/>
            {!option.available&&<p className="notice">{t.invalid}</p>}
          </label>):<p className="bo-empty">{t.empty}</p>}
        </fieldset>}
        {kind==='dial'&&<section className="bo-reference"><h2>{t.privateReference}</h2><p id="bo-reference-help">{t.referenceHelp}</p><Input name="private_dial_reference" ref={fileInput} type="file" accept="image/png" disabled={!ack||!fingerprint||busy||references.length>=3} aria-label={t.upload} aria-describedby="bo-reference-help" onChange={e=>{void upload(e.target.files?.[0]);}}/><p>{t.references}: <BidiReference>{references.length} / 3</BidiReference></p>{ack&&<div className="bo-private-images">{references.map(id=><PrivateReference key={id} configurationId={ack.id} referenceId={id} label={t.privateReference} failureLabel={t.referenceUnavailable} retryLabel={t.retry}/>)}</div>}</section>}
        {identityPending&&<p className="bo-feedback" role="status">{t.loadingSaved}</p>}
        {!!identityError&&<div className="notice" role="alert"><p>{t.identityUnavailable}</p><Button className="button-secondary" onClick={retryIdentity}>{t.retry}</Button></div>}
        {!fingerprint&&!identityPending&&!identityError&&<div className="bo-signin"><Link className="button" href={signInHref('/customize'+(returnQuery.size?'?'+returnQuery:''),locale)}>{t.signIn}</Link><p>{t.signInBody}</p></div>}
        <div className="bo-actions"><Button disabled={!selected?.available||!fingerprint||busy} onClick={()=>void save()}>{busy?t.saving:t.save}<span aria-hidden="true">↗</span></Button>
          {(ack||configurationId)&&<Button className="button-secondary" disabled={busy} onClick={startNew}>{t.new}</Button>}</div>
        <div aria-live="polite" role="status" className="bo-feedback">{busy?t.pending:message}</div>
        {activeError&&<div role="alert" className="notice"><p>{errorCopy(activeError,t)}</p>{activeError instanceof ApiError&&activeError.requestId&&<BidiReference>{activeError.requestId}</BidiReference>}
          <Button className="button-secondary" disabled={busy} onClick={()=>{setFailure(null);void catalogQuery.refetch();void savedQuery.refetch();if(configurationId)void configurationQuery.refetch();}}>{t.refresh}</Button></div>}
      </div>
      <aside className="bo-summary" aria-label={t.summary}>
        <figure className="bo-illustration"><svg viewBox="0 0 320 340" role="img" aria-label={t.watchFace}><rect x="132" y="4" width="56" height="330" rx="14" fill={palette.strap} stroke="var(--accent)"/><circle cx="160" cy="170" r="112" fill={palette.case} stroke={palette.bezel} strokeWidth="3"/><circle cx="160" cy="170" r="97" fill={palette.dial}/>{Array.from({length:12},(_,i)=><path key={i} d="M160 83v10" transform={`rotate(${i*30} 160 170)`} stroke={palette.markers} strokeWidth="2"/>)}<path d="M160 109v61l43 29" stroke={palette.hands} strokeWidth="4" fill="none"/><circle cx="160" cy="170" r="5" fill={palette.hands}/></svg><figcaption>{t.illustration}</figcaption></figure>
        <section><p className="eyebrow">{t.notApproved}</p><h2>{t.summary}</h2>{ack?<><p>{t.savedRevision} <BidiReference>{ack.revision}</BidiReference></p><dl className="bo-saved">{ack.selections.map(s=><div key={`${s.kind}-${s.component}`}><dt>{t[s.kind]} · {t[s.component]}</dt><dd>{s.definition.label[locale]} <small>{t.revision} <BidiReference>{s.option_revision}</BidiReference></small>{!s.current&&<p className="notice">{t.needsReview}</p>}</dd></div>)}</dl>{hasRoute('/custom-requests')&&<Link className="button button-secondary" href={`/${locale}/custom-requests?configuration=${ack.id}&revision=${ack.revision}`}>{t.next}</Link>}</>:<p>{t.summaryEmpty}</p>}</section>
        {!!savedQuery.data?.items.length&&<label className="bo-resume">{t.resume}<select dir="ltr" name="saved_configuration" value={configurationId} disabled={busy} onChange={e=>{setAck(null);setConfigurationId(e.target.value);setChosen('');setFailure(null);updateUrl(e.target.value,'');}}><option value="">—</option>{savedQuery.data.items.map(c=><option key={c.id} value={c.id}>{c.base_model} · {c.id.slice(0,8)} · {c.revision}</option>)}</select></label>}
      </aside>
    </div>
  </div>;
}

function PrivateReference({configurationId,referenceId,label,failureLabel,retryLabel}: {configurationId:string;referenceId:string;label:string;failureLabel:string;retryLabel:string}) {
  const token=useSession()?.access_token;
  const [url,setUrl]=useState(''),[failed,setFailed]=useState(false),[attempt,setAttempt]=useState(0);
  useEffect(()=>{
    if(!token)return;
    const abort=new AbortController(),alive={current:true};
    const close=fencePrivateState(alive,window,()=>abort.abort());setFailed(false);setUrl('');
    void optionsApi.reference(configurationId,referenceId,token,abort.signal)
      .then(blob=>readPrivatePng(blob,abort.signal))
      .then(value=>{if(!abort.signal.aborted)setUrl(value);})
      .catch(()=>{if(!abort.signal.aborted)setFailed(true);});
    return close;
  },[configurationId,referenceId,token,attempt]);
  if(failed)return <div><p role="status">{failureLabel}</p><Button className="button-secondary" onClick={()=>setAttempt(prior=>prior+1)}>{retryLabel}</Button></div>;
  return url?<img src={url} alt={label} width={120} height={120} onError={()=>setFailed(true)}/>:<span className="skeleton" role="status" aria-label={label}/>;
}

function OptionDetails({option,locale,t}: {option:Option;locale:'en'|'ar';t:Copy}) {
  if(option.kind==='color') return <div className="bo-color"><span className="bo-swatch" style={{backgroundColor:/^#[\da-f]{6}$/i.test(option.details.swatch)?option.details.swatch:undefined}} aria-hidden="true"/><p>{option.details.color[locale]} · {option.details.finish[locale]}{option.details.coating&&<> · {t.coating}: {option.details.coating[locale]}</>}</p></div>;
  if(option.kind==='material') return <dl className="bo-details"><div><dt>{t.material}</dt><dd>{option.details.material[locale]}</dd></div><div><dt>{t.grade}</dt><dd><BidiReference>{option.details.grade}</BidiReference></dd></div><div><dt>{t.construction}</dt><dd>{t[option.details.construction]}</dd></div>{option.details.substrate&&<div><dt>{t.substrate}</dt><dd>{option.details.substrate[locale]}</dd></div>}{option.details.thickness_micrometers!==null&&<div><dt>{t.thickness}</dt><dd><BidiReference>{option.details.thickness_micrometers}</BidiReference></dd></div>}</dl>;
  if(option.kind==='dial') return <dl className="bo-details"><div><dt>{t.dial}</dt><dd>{option.details.dial[locale]}</dd></div><div><dt>{t.hands}</dt><dd>{option.details.hands[locale]}</dd></div><div><dt>{t.markers}</dt><dd>{option.details.markers[locale]}</dd></div><div><dt>{t.provenance}</dt><dd>{t[option.details.provenance]}</dd></div><div><dt>{t.source}</dt><dd><BidiReference>{option.details.source_reference}</BidiReference></dd></div></dl>;
  return <div className="bo-package">{(['interventions','exclusions','required_tests'] as const).map(key=><div key={key}><h3>{key==='required_tests'?t.tests:t[key]}</h3><ul>{option.details[key].map((entry,index)=><li key={index}>{entry[locale]}</li>)}</ul></div>)}<p>{t.priceRef}: <BidiReference>{option.details.price_reference}</BidiReference></p><strong><BidiReference>{new Intl.NumberFormat(locale==='ar'?'ar-LB':'en-US',{style:'currency',currency:option.details.currency}).format(option.details.price_minor/(option.details.currency==='USD'?100:1))}</BidiReference></strong><p>{t.priceNote}</p></div>;
}

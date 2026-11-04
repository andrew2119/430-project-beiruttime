'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, Input, State } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { useSession, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { DraftInput, RequestDraft } from '@contracts/contracts-catalog/request-drafts';
import { draftApi, type BusinessOption } from './api';
import { recall,remember,purge,draftMemoryEpoch,type DraftMemory } from './memory';
import en from './en.json';
import ar from './ar.json';
const blank:DraftInput={configuration_id:null,configuration_revision:null,brand_id:null,kind:'customization',watch_context:'undecided',watch_reference:'',scope_intent:'',notes:'',options:{}};
const dimensions=['color','material','movement','dial','sophistication'] as const;
function message(error:unknown,t:Record<string,string>){if(!(error instanceof ApiError))return t.error;return error.status===401?t.signInBody:error.status===403?t.forbidden:error.code==='stale_revision'?t.stale:error.status===422?t.invalid:t.error;}
function upstreamStatus(value:unknown){return value&&typeof value==='object'&&'status'in value?String(value.status):'unavailable';}
function optionItems(value:unknown,locale:'en'|'ar'):BusinessOption[]{
  if(!value||typeof value!=='object'||!('data'in value))return[];
  const data=value.data;if(!data||typeof data!=='object'||!('items'in data)||!Array.isArray(data.items))return[];
  return data.items.flatMap(item=>{if(!item||typeof item!=='object'||typeof item.id!=='string'||item.available===false)return[];const dimension=item.kind??item.dimension;const label=typeof item.label==='string'?item.label:item.label?.[locale];return dimensions.includes(dimension)&&typeof label==='string'?[{id:item.id,label,dimension}]:[];});
}
export default function RequestDrafts(){
  const locale=useLocale(),t=locale==='ar'?ar:en,session=useSession();
  useEffect(()=>{const clear=()=>purge();window.addEventListener('bt:access-change',clear);return()=>window.removeEventListener('bt:access-change',clear);},[]);
  const boundary=useQuery({queryKey:['l08-drafts',session?.access_fingerprint??'restore'],queryFn:({signal})=>draftApi.list(signal),retry:false});
  if(!session){
    const outage=boundary.error instanceof ApiError&&boundary.error.status>=500;
    return <State title={t.title} body={boundary.isPending?t.loading:outage?t.error:t.signInBody}>{outage?<Button onClick={()=>void boundary.refetch()}>{t.reload}</Button>:!boundary.isPending&&<ButtonLink href={signInHref('/custom-requests',locale)}>{t.signIn}</ButtonLink>}</State>;
  }
  return <Workspace key={session.access_fingerprint} owner={session.access_fingerprint}/>;
}
function replaceDraftReference(id:string|null){const url=new URL(window.location.href);if(id)url.searchParams.set('draft',id);else url.searchParams.delete('draft');url.searchParams.delete('configuration');url.searchParams.delete('revision');window.history.replaceState(window.history.state,'',url);}
function fromServer(owner:string,draft:RequestDraft):DraftMemory{return{owner,id:draft.id,revision:draft.revision,dirty:false,form:{configuration_id:draft.configuration_id??null,configuration_revision:draft.configuration_revision??null,brand_id:draft.brand_id,kind:draft.kind,watch_context:draft.watch_context,watch_reference:draft.watch_reference,scope_intent:draft.scope_intent,notes:draft.notes,options:draft.options}};}
function Workspace({owner}:{owner:string}){
  const locale=useLocale(),t:Record<string,string>=locale==='ar'?ar:en;
  const[memory]=useState(()=>recall(owner));
  const[restoreId,setRestoreId]=useState(()=>memory||typeof window==='undefined'?null:new URLSearchParams(window.location.search).get('draft'));
  const[configuration,setConfiguration]=useState(()=>{if(restoreId||typeof window==='undefined')return null;const params=new URLSearchParams(window.location.search),id=params.get('configuration'),revision=Number(params.get('revision'));return id&&Number.isSafeInteger(revision)&&revision>0?{id,revision}:null;});
  const source=useQuery({queryKey:['l08-draft-restore',owner,restoreId],queryFn:({signal})=>draftApi.get(restoreId!,signal),enabled:!memory&&!!restoreId,retry:false});
  const linked=useQuery({queryKey:['l08-draft-configuration',owner,configuration],queryFn:({signal})=>draftApi.configuration(configuration!.id,configuration!.revision,signal),enabled:!!configuration&&!memory?.pending,retry:false});
  if(!memory&&restoreId&&!source.data)return <State title={t.title} body={source.isPending?t.loading:message(source.error,t)}>{!source.isPending&&<><Button onClick={()=>void source.refetch()}>{t.reload}</Button><Button className="button-secondary" onClick={()=>{replaceDraftReference(null);setRestoreId(null);}}>{t.new}</Button></>}</State>;
  if(configuration&&!memory?.pending&&!linked.data)return <State title={t.title} body={linked.isPending?t.loading:message(linked.error,t)}>{!linked.isPending&&<><Button onClick={()=>void linked.refetch()}>{t.reload}</Button><Button className="button-secondary" onClick={()=>{replaceDraftReference(null);setConfiguration(null);}}>{t.new}</Button></>}</State>;
  const initial=linked.data&&!memory?.pending?{owner,id:memory?.id??null,revision:memory?.revision??0,dirty:true,form:{...(memory?.form??blank),kind:'customization' as const,brand_id:linked.data.brand_id,configuration_id:linked.data.configuration_id,configuration_revision:linked.data.configuration_revision,options:linked.data.options}}:memory??(source.data?fromServer(owner,source.data):null);
  return <Editor owner={owner} initial={initial}/>;
}
function Editor({owner,initial}:{owner:string;initial:DraftMemory|null}){
  const locale=useLocale(),t:Record<string,string>=locale==='ar'?ar:en,cache=useQueryClient();
  const[generation]=useState(draftMemoryEpoch);
  const[form,setForm]=useState<DraftInput>(initial?.form??{...blank,options:{}}),[id,setId]=useState<string|null>(initial?.id??null),[revision,setRevision]=useState(initial?.revision??0);
  const[error,setError]=useState<unknown>(null),[saved,setSaved]=useState(false),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(!!initial?.pending),[dirty,setDirty]=useState(initial?.dirty??false);
  const op=useRef(initial?.pending??null),alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{remember({owner,form,id,revision,dirty,pending:op.current},generation);},[owner,form,id,revision,dirty,uncertain,generation]);
  const drafts=useQuery({queryKey:['l08-drafts',owner],queryFn:({signal})=>draftApi.list(signal),retry:false});
  const catalogue=useInfiniteQuery({queryKey:['l08-draft-catalogue',owner,form.kind],initialPageParam:null as string|null,queryFn:({signal,pageParam})=>draftApi.catalogue(form.kind,pageParam,signal),getNextPageParam:last=>last.data?.next_after??undefined,retry:false});
  const readiness=useQuery({queryKey:['l08-draft-readiness',owner,id,revision],queryFn:({signal})=>draftApi.readiness(id!,signal),enabled:!!id,retry:false});
  function change<K extends keyof DraftInput>(key:K,value:DraftInput[K]){if(draftMemoryEpoch()!==generation)return;setForm(prior=>({...prior,[key]:value}));setSaved(false);setDirty(true);}
  function resume(draft:RequestDraft){if(draftMemoryEpoch()!==generation)return;setId(draft.id);setRevision(draft.revision);setForm(fromServer(owner,draft).form);setDirty(false);setSaved(false);setError(null);op.current=null;replaceDraftReference(draft.id);}
  async function reload(){if(!id||draftMemoryEpoch()!==generation)return;setBusy(true);try{const current=await draftApi.get(id);if(alive.current&&draftMemoryEpoch()===generation)resume(current);}catch(reason){if(alive.current&&draftMemoryEpoch()===generation)setError(reason);}finally{if(alive.current&&draftMemoryEpoch()===generation)setBusy(false);}}
  const persist=useCallback(async():Promise<RequestDraft|null>=>{
    if(draftMemoryEpoch()!==generation)return null;
    setBusy(true);setError(null);setSaved(false);
    op.current??={form:structuredClone(form),id,revision,key:crypto.randomUUID()};
    remember({owner,form,id,revision,dirty,pending:op.current},generation);
    try{
      const value=await draftApi.save(op.current.form,op.current.id,op.current.revision,op.current.key);
      if(!alive.current||draftMemoryEpoch()!==generation)return null;
      setId(value.draft.id);setRevision(value.draft.revision);setDirty(false);setSaved(true);setUncertain(false);op.current=null;
      replaceDraftReference(value.draft.id);remember(fromServer(owner,value.draft),generation);
      void cache.invalidateQueries({queryKey:['l08-drafts',owner]});return value.draft;
    }catch(reason){if(alive.current&&draftMemoryEpoch()===generation){setError(reason);const unknown=!(reason instanceof ApiError)||reason.status>=500;setUncertain(unknown);if(!unknown){op.current=null;remember({owner,form,id,revision,dirty,pending:null},generation);}}return null;}
    finally{if(alive.current&&draftMemoryEpoch()===generation)setBusy(false);}
  },[owner,form,id,revision,dirty,generation,cache]);
  useEffect(()=>{
    const switchLocale=(event:MouseEvent)=>{
      const anchor=event.target instanceof Element?event.target.closest<HTMLAnchorElement>('a.locale-control'):null;
      if(draftMemoryEpoch()!==generation||!anchor||(!dirty&&!uncertain)||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      const destination=new URL(anchor.href),language=/^\/(en|ar)(?:\/|$)/.exec(destination.pathname)?.[1];
      if(destination.origin!==window.location.origin||!language)return;
      event.preventDefault();event.stopPropagation();if(busy)return;
      // A locale link performs a full navigation: acknowledge private intent on the server first.
      // No notes, evidence, credentials or uncertain write is persisted in browser storage.
      void persist().then(current=>{if(current&&alive.current&&draftMemoryEpoch()===generation){destination.searchParams.set('draft',current.id);window.dispatchEvent(new Event('bt:before-locale-change'));document.cookie=`bt-locale=${language}; Path=/; Max-Age=31536000; SameSite=Lax`;window.location.assign(destination.href);}});
    };
    document.addEventListener('click',switchLocale,true);return()=>document.removeEventListener('click',switchLocale,true);
  },[dirty,uncertain,busy,persist,generation]);
  const businesses=[...new Map((catalogue.data?.pages.flatMap(page=>page.data?.items??[])??[]).map(business=>[business.id,business])).values()];
  const directoryUnavailable=!!catalogue.error||!catalogue.data?.pages.length||catalogue.data.pages.some(page=>page.status!=='available');
  const options=optionItems(readiness.data?.options,locale);
  const currentOptions=readiness.data?.draft.brand_id===form.brand_id;
  const boundReadiness=readiness.data?.draft.configuration_id===form.configuration_id?readiness.data?.configuration:undefined;
  return <div className="request-page"><header><p className="eyebrow">{t.eyebrow}</p><h1>{t.title}</h1><p>{t.intro}</p></header>
  <div className="request-grid"><div><Card><form className="request-form" method="post" autoComplete="off" onSubmit={event=>{event.preventDefault();void persist();}}>
    {id&&<p><BidiReference>{id}</BidiReference> · {t.revision} {revision.toLocaleString(locale)}</p>}
    {form.configuration_id&&<div className="request-notice"><strong>{t.configuration}</strong><p><BidiReference>{form.configuration_id}</BidiReference> · {t.revision} {form.configuration_revision?.toLocaleString(locale)}</p><p>{t.configurationHelp}</p>{boundReadiness?.status==='unavailable'&&<p role="status">{t.configurationUnavailable}</p>}{boundReadiness?.data?.selection_summary.some(selection=>!selection.current)&&<p role="status">{t.configurationChanged}</p>}<ButtonLink className="button-secondary" href={`/${locale}/customize?configuration=${encodeURIComponent(form.configuration_id)}`}>{t.openOptions}</ButtonLink><Button type="button" className="button-secondary" disabled={busy||uncertain} onClick={()=>{change('configuration_id',null);change('configuration_revision',null);change('options',{});}}>{t.detachConfiguration}</Button></div>}
    <label>{t.kind}<select name="kind" className="input" value={form.kind} disabled={busy||uncertain} onChange={e=>change('kind',e.target.value as DraftInput['kind'])}><option value="customization">{t.customization}</option><option value="service">{t.service}</option></select></label>
    <label>{t.brand}<select name="brand_id" className="input" value={form.brand_id??''} disabled={busy||uncertain||!!form.configuration_id} onChange={e=>{change('brand_id',e.target.value||null);change('options',{});}}><option value="">{t.chooseBrand}</option>{form.brand_id&&!businesses.some(b=>b.id===form.brand_id)&&<option value={form.brand_id}>{form.brand_id}</option>}{businesses.map(b=><option key={b.id} value={b.id}>{b.name}{b.sample_content?' — '+t.sample:''}</option>)}</select></label>
    {directoryUnavailable&&<div className="request-notice"><p>{t.brandUnavailable}</p><Button type="button" className="button-secondary" disabled={catalogue.isFetching} onClick={()=>void catalogue.refetch()}>{t.directoryReload}</Button></div>}
    {catalogue.hasNextPage&&<Button type="button" className="button-secondary" disabled={busy||uncertain||catalogue.isFetchingNextPage} onClick={()=>void catalogue.fetchNextPage()}>{t.moreBusinesses}</Button>}
    <label>{t.watchContext}<select name="watch_context" className="input" value={form.watch_context} disabled={busy||uncertain} onChange={e=>change('watch_context',e.target.value as DraftInput['watch_context'])}>{(['undecided','owned_watch','seller_base']as const).map(context=><option value={context} key={context}>{t[context]}</option>)}</select></label>
    <label>{t.watch}<Input name="watch_reference" value={form.watch_reference} maxLength={300} disabled={busy||uncertain} onChange={e=>change('watch_reference',e.target.value)}/></label>
    <label>{t.scope}<textarea name="scope_intent" className="input" value={form.scope_intent} maxLength={1000} disabled={busy||uncertain} onChange={e=>change('scope_intent',e.target.value)}/></label>
    <label>{t.notes}<textarea name="notes" className="input" value={form.notes} maxLength={4000} disabled={busy||uncertain} onChange={e=>change('notes',e.target.value)}/><small>{t.notesHelp}</small></label>
    <fieldset><legend>{t.options}</legend><p>{t.optionHelp}</p><div className="request-option-grid">{dimensions.map(dimension=><label key={dimension}>{t[dimension]}<select name={'option_'+dimension} className="input" value={form.options[dimension]??''} disabled={busy||uncertain||!!form.configuration_id||!currentOptions||!options.some(o=>o.dimension===dimension)} onChange={e=>change('options',{...form.options,[dimension]:e.target.value})}><option value="">{t.notSelected}</option>{form.options[dimension]&&!options.some(o=>o.id===form.options[dimension])&&<option value={form.options[dimension]}>{form.options[dimension]}</option>}{currentOptions&&options.filter(o=>o.dimension===dimension).map(o=><option key={o.id} value={o.id}>{typeof o.label==='string'?o.label:o.label[locale]}</option>)}</select></label>)}</div></fieldset>
    {!!error&&<div className="request-notice" role="alert"><p>{message(error,t)}</p>{error instanceof ApiError&&error.requestId&&<small className="request-support">{t.support}: <BidiReference>{error.requestId}</BidiReference></small>}</div>}
    {uncertain&&<p role="status">{t.uncertain}</p>}{saved&&<p role="status">{t.saved}</p>}
    <div className="request-tools"><Button type="submit" disabled={busy}>{busy?t.saving:uncertain?t.retry:t.save}</Button>{id&&!uncertain&&<Button type="button" className="button-secondary" disabled={busy} onClick={()=>void reload()}>{t.reload}</Button>}</div>
  </form></Card>
  <Card className="checkout-result"><h2>{t.readiness}</h2><p>{t.noProgress}</p><ul className="request-readiness">{(['quote','consent','work','quality','collection']as const).map(section=><li key={section}><strong>{t[section]}</strong><span>{t.unavailable} — {t.notAssessed}</span></li>)}</ul><h2>{t.technical}</h2><p>{upstreamStatus(readiness.data?.intake)==='available'?t.available:t.technicalUnavailable}</p>{readiness.isFetching&&<p role="status">{t.loading}</p>}<div className="request-tools"><ButtonLink className="button-secondary" href={`/${locale}/customize`}>{t.openOptions}</ButtonLink><ButtonLink className="button-secondary" href={`/${locale}/services`}>{t.openServices}</ButtonLink></div></Card></div>
  <aside><Card><h2>{t.resume}</h2><Button className="button-secondary" disabled={busy||uncertain} onClick={()=>{if(draftMemoryEpoch()!==generation)return;setId(null);setRevision(0);setForm({...blank,options:{}});setDirty(false);setSaved(false);setError(null);op.current=null;replaceDraftReference(null);}}>{t.new}</Button>{drafts.isPending&&<p role="status">{t.loading}</p>}{drafts.error&&<div role="alert"><p>{message(drafts.error,t)}</p><Button onClick={()=>void drafts.refetch()}>{t.reload}</Button></div>}{drafts.data?.items.length===0&&<p>{t.empty}</p>}<ul className="request-list">{drafts.data?.items.map(draft=><li key={draft.id}><Button className="button-secondary" disabled={busy||uncertain} onClick={()=>resume(draft)}>{draft.watch_reference||t[draft.kind]}</Button><small>{t.updated} <time dateTime={draft.updated_at}>{new Date(draft.updated_at).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time></small></li>)}</ul></Card></aside></div></div>;
}

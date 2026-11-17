'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, Input, State, Textarea, AnimatedList, Select, Segmented } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { useSession, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { DraftInput, RequestDraft } from '@contracts/contracts-catalog/request-drafts';
import { draftApi, type BusinessOption } from './api';
import { recall,remember,purge,draftMemoryEpoch,type DraftMemory } from './memory';
import en from './en.json';
import ar from './ar.json';
import Submission from './submission';
import { changeRequestLocale } from './locale';
import { privateAccessDenied, readPrivateDrafts } from './private-drafts';
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
  const locale=useLocale(),t=locale==='ar'?ar:en,session=useSession(),search=useSearchParams(),router=useRouter(),cache=useQueryClient();
  const [accessEpoch,setAccessEpoch]=useState(0),[denied,setDenied]=useState(false);
  const revoke=useCallback(()=>{purge();setDenied(true);},[]);
  const owner=session?.access_fingerprint;
  useEffect(()=>{if(denied&&owner){void cache.cancelQueries({predicate:query=>query.queryKey[1]===owner});cache.removeQueries({predicate:query=>query.queryKey[1]===owner});}},[denied,cache,owner]);
  useEffect(()=>{
    const change=(event:MouseEvent)=>changeRequestLocale(event,()=>router.refresh());
    document.addEventListener('click',change,true);
    return()=>document.removeEventListener('click',change,true);
  },[router]);
  useEffect(()=>{
    const clear=()=>{
      purge();
      const privateKeys=['l08-draft-boundary','l08-drafts','l08-draft-restore','l08-draft-configuration','l08-draft-readiness','customization-requests','customization-history','buyer-brand-decision'];
      const filters={predicate:(query:{queryKey:readonly unknown[]})=>privateKeys.includes(String(query.queryKey[0]))};
      void cache.cancelQueries(filters);cache.removeQueries(filters);
      setAccessEpoch(value=>value+1);setDenied(false);
    };
    window.addEventListener('bt:access-change',clear);return()=>window.removeEventListener('bt:access-change',clear);
  },[cache]);
  const boundary=useQuery({queryKey:['l08-draft-boundary'],enabled:!session,queryFn:({signal})=>draftApi.list(signal),retry:false});
  if(!session){
    const outage=boundary.error instanceof ApiError&&boundary.error.status>=500;
    return <PageLayout className="request-page"><PageHeader title={t.title} count={t.intro}/><State kind={boundary.isPending?'loading':outage?'error':'empty'} title={t.title} body={boundary.isPending?t.loading:outage?t.error:t.signInBody}>{outage?<Button onClick={()=>void boundary.refetch()}>{t.reload}</Button>:!boundary.isPending&&<ButtonLink href={signInHref('/custom-requests',locale)}>{t.signIn}</ButtonLink>}</State></PageLayout>;
  }
  if(denied)return <PageLayout className="request-page"><PageHeader title={t.title}/><State kind="error" title={t.title} body={t.forbidden}><Button onClick={()=>{replaceDraftReference(null);setAccessEpoch(value=>value+1);setDenied(false);}}>{t.reload}</Button></State></PageLayout>;
  const sourceId=search.get('configuration'),sourceRevision=search.get('revision');
  // Entry parameters seed the workspace; saving and language changes keep its identity.
  return <Workspace key={`${session.access_fingerprint}:${accessEpoch}`} owner={session.access_fingerprint} sourceId={sourceId} sourceRevision={sourceRevision} draftId={search.get('draft')} onDenied={revoke}/>;
}
function replaceDraftReference(id:string|null){const url=new URL(window.location.href);if(id)url.searchParams.set('draft',id);else url.searchParams.delete('draft');url.searchParams.delete('configuration');url.searchParams.delete('revision');window.history.replaceState(window.history.state,'',url);}
function fromServer(owner:string,draft:RequestDraft):DraftMemory{return{owner,id:draft.id,revision:draft.revision,submittedRequestId:draft.submitted_request_id??null,dirty:false,form:{configuration_id:draft.configuration_id??null,configuration_revision:draft.configuration_revision??null,brand_id:draft.brand_id,kind:draft.kind,watch_context:draft.watch_context,watch_reference:draft.watch_reference,scope_intent:draft.scope_intent,notes:draft.notes,options:draft.options}};}
type WorkspaceProps={owner:string;sourceId:string|null;sourceRevision:string|null;draftId:string|null;onDenied:()=>void};
function Workspace(props:WorkspaceProps){
  const signature=JSON.stringify([props.draftId,props.sourceId,props.sourceRevision]);
  const [navigation,setNavigation]=useState(()=>({active:0,signature,acknowledged:signature,entries:[{...props,memory:recall(props.owner)}]}));
  const active=useRef(navigation.active),generation=useRef(draftMemoryEpoch());
  useEffect(()=>{active.current=navigation.active;},[navigation.active]);
  if(signature!==navigation.signature){
    if(signature===navigation.acknowledged)setNavigation({...navigation,signature});
    else {
      const existing=navigation.entries.findIndex(entry=>JSON.stringify([entry.draftId,entry.sourceId,entry.sourceRevision])===signature);
      setNavigation({signature,acknowledged:signature,active:existing<0?navigation.entries.length:existing,entries:existing<0?[...navigation.entries,{...props,memory:null}]:navigation.entries});
    }
  }
  return <>{navigation.entries.map((entry,index)=><div key={index} hidden={index!==navigation.active}><RecordWorkspace {...entry} onDenied={props.onDenied} onOpenDraft={draft=>{
    if(draftMemoryEpoch()!==generation.current)return;
    replaceDraftReference(draft.id);
    setNavigation(previous=>{
      const existing=previous.entries.findIndex(value=>value.draftId===draft.id);
      const selected=existing<0?previous.entries.length:existing;
      active.current=selected;
      return {...previous,active:selected,acknowledged:JSON.stringify([draft.id,null,null]),entries:existing<0?[...previous.entries,{...props,draftId:draft.id,sourceId:null,sourceRevision:null,memory:fromServer(props.owner,draft)}]:previous.entries};
    });
  }} onReferenceChange={id=>{
    if(index===active.current){
      replaceDraftReference(id);
    }
    setNavigation(previous=>({...previous,acknowledged:index===active.current?JSON.stringify([id,null,null]):previous.acknowledged,entries:previous.entries.map((value,i)=>i===index?{...value,draftId:id,sourceId:null,sourceRevision:null}:value)}));
  }}/></div>)}</>;
}
function RecordWorkspace({owner,sourceId,sourceRevision,draftId,onDenied,memory:initialMemory,onReferenceChange,onOpenDraft}:WorkspaceProps&{memory:DraftMemory|null;onOpenDraft:(draft:RequestDraft)=>void;onReferenceChange:(id:string|null)=>void}){
  const locale=useLocale(),t:Record<string,string>=locale==='ar'?ar:en;
  const[memory]=useState(initialMemory);
  const[restoreId,setRestoreId]=useState(()=>memory?null:draftId);
  const[configuration,setConfiguration]=useState(()=>{if(restoreId)return null;const revision=Number(sourceRevision);return sourceId&&Number.isSafeInteger(revision)&&revision>0?{id:sourceId,revision}:null;});
  const source=useQuery({queryKey:['l08-draft-restore',owner,restoreId],queryFn:({signal})=>readPrivateDrafts(()=>draftApi.get(restoreId!,signal),onDenied),enabled:!memory&&!!restoreId,retry:false});
  const linked=useQuery({queryKey:['l08-draft-configuration',owner,configuration],queryFn:({signal})=>readPrivateDrafts(()=>draftApi.configuration(configuration!.id,configuration!.revision,signal),onDenied),enabled:!!configuration&&!memory?.pending,retry:false});
  if(!memory&&restoreId&&!source.data)return <PageLayout className="request-page"><PageHeader title={t.title} count={t.intro}/><State kind={source.isPending?'loading':'error'} title={t.title} body={source.isPending?t.loading:message(source.error,t)}>{!source.isPending&&<><Button onClick={()=>void source.refetch()}>{t.reload}</Button><Button variant="outline" onClick={()=>{onReferenceChange(null);setRestoreId(null);}}>{t.new}</Button></>}</State></PageLayout>;
  if(configuration&&!memory?.pending&&!linked.data)return <PageLayout className="request-page"><PageHeader title={t.title} count={t.intro}/><State kind={linked.isPending?'loading':'error'} title={t.title} body={linked.isPending?t.loading:message(linked.error,t)}>{!linked.isPending&&<><Button onClick={()=>void linked.refetch()}>{t.reload}</Button><Button variant="outline" onClick={()=>{onReferenceChange(null);setConfiguration(null);}}>{t.new}</Button></>}</State></PageLayout>;
  const editableMemory=memory?.submittedRequestId?null:memory;
  const initial=linked.data&&!memory?.pending?{owner,id:editableMemory?.id??null,revision:editableMemory?.revision??0,dirty:true,form:{...(editableMemory?.form??blank),kind:'customization' as const,brand_id:linked.data.brand_id,configuration_id:linked.data.configuration_id,configuration_revision:linked.data.configuration_revision,options:linked.data.options}}:memory??(source.data?fromServer(owner,source.data):null);
  return <Editor owner={owner} initial={initial} onDenied={onDenied} onReferenceChange={onReferenceChange} onOpenDraft={onOpenDraft}/>;
}
function Editor({owner,initial,onDenied,onReferenceChange,onOpenDraft}:{owner:string;initial:DraftMemory|null;onOpenDraft:(draft:RequestDraft)=>void;onDenied:()=>void;onReferenceChange:(id:string|null)=>void}){
  const locale=useLocale(),t:Record<string,string>=locale==='ar'?ar:en,cache=useQueryClient();
  const[generation]=useState(draftMemoryEpoch);
  const[form,setForm]=useState<DraftInput>(initial?.form??{...blank,options:{}}),[id,setId]=useState<string|null>(initial?.id??null),[revision,setRevision]=useState(initial?.revision??0);
  const[error,setError]=useState<unknown>(null),[saved,setSaved]=useState(false),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(!!initial?.pending),[dirty,setDirty]=useState(initial?.dirty??false);
  const[submissionPending,setSubmissionPending]=useState(false),[submittedRequestId,setSubmittedRequestId]=useState(initial?.submittedRequestId??null);
  const op=useRef(initial?.pending??null),alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{remember({owner,form,id,revision,submittedRequestId,dirty,pending:op.current},generation);},[owner,form,id,revision,submittedRequestId,dirty,uncertain,generation]);
  const drafts=useInfiniteQuery({queryKey:['l08-drafts',owner],initialPageParam:null as string|null,queryFn:({signal,pageParam})=>readPrivateDrafts(()=>draftApi.list(signal,pageParam),onDenied),getNextPageParam:last=>last.next_cursor??undefined,retry:false});
  const catalogue=useInfiniteQuery({queryKey:['l08-draft-catalogue',owner,form.kind],initialPageParam:null as string|null,queryFn:({signal,pageParam})=>draftApi.catalogue(form.kind,pageParam,signal),getNextPageParam:last=>last.data?.next_after??undefined,retry:false});
  const readiness=useQuery({queryKey:['l08-draft-readiness',owner,id,revision],queryFn:({signal})=>readPrivateDrafts(()=>draftApi.readiness(id!,signal),onDenied),enabled:!!id,retry:false});

  function change<K extends keyof DraftInput>(key:K,value:DraftInput[K]){if(draftMemoryEpoch()!==generation)return;setForm(prior=>({...prior,[key]:value}));setSaved(false);setDirty(true);}
  function resume(draft:RequestDraft){if(draftMemoryEpoch()!==generation)return;setId(draft.id);setRevision(draft.revision);setSubmittedRequestId(draft.submitted_request_id??null);setForm(fromServer(owner,draft).form);setDirty(false);setSaved(false);setError(null);op.current=null;onReferenceChange(draft.id);}
  async function reload(){if(!id||draftMemoryEpoch()!==generation)return;setBusy(true);try{const current=await readPrivateDrafts(()=>draftApi.get(id),onDenied);if(alive.current&&draftMemoryEpoch()===generation)resume(current);}catch(reason){if(alive.current&&draftMemoryEpoch()===generation)setError(reason);}finally{if(alive.current&&draftMemoryEpoch()===generation)setBusy(false);}}
  const persist=useCallback(async():Promise<RequestDraft|null>=>{
    if(draftMemoryEpoch()!==generation||submissionPending||submittedRequestId)return null;
    setBusy(true);setError(null);setSaved(false);
    op.current??={form:structuredClone(form),id,revision,key:crypto.randomUUID()};
    remember({owner,form,id,revision,dirty,pending:op.current},generation);
    try{
      const value=await draftApi.save(op.current.form,op.current.id,op.current.revision,op.current.key);
      if(!alive.current||draftMemoryEpoch()!==generation)return null;
      setId(value.draft.id);setRevision(value.draft.revision);setDirty(false);setSaved(true);setUncertain(false);op.current=null;
      onReferenceChange(value.draft.id);remember(fromServer(owner,value.draft),generation);
      void cache.invalidateQueries({queryKey:['l08-drafts',owner]});return value.draft;
    }catch(reason){if(privateAccessDenied(reason)&&alive.current&&draftMemoryEpoch()===generation){onDenied();return null;}if(alive.current&&draftMemoryEpoch()===generation){setError(reason);const unknown=!(reason instanceof ApiError)||reason.status>=500;setUncertain(unknown);if(!unknown){op.current=null;remember({owner,form,id,revision,dirty,pending:null},generation);}}return null;}
    finally{if(alive.current&&draftMemoryEpoch()===generation)setBusy(false);}
  },[owner,form,id,revision,dirty,generation,cache,submissionPending,submittedRequestId,onDenied,onReferenceChange]);
  const businesses=[...new Map((catalogue.data?.pages.flatMap(page=>page.data?.items??[])??[]).map(business=>[business.id,business])).values()];
  const directoryUnavailable=!!catalogue.error||!catalogue.data?.pages.length||catalogue.data.pages.some(page=>page.status!=='available');
  const options=optionItems(readiness.data?.options,locale);
  const currentOptions=readiness.data?.draft.brand_id===form.brand_id;
  const boundReadiness=readiness.data?.draft.configuration_id===form.configuration_id?readiness.data?.configuration:undefined;
  return <PageLayout className="request-page"><PageHeader lead={t.eyebrow} title={t.title} count={t.intro}/>
  <div className="request-grid"><div><Card><form className="request-form" method="post" autoComplete="off" onSubmit={event=>{event.preventDefault();void persist();}}><fieldset className="request-submission-fence" aria-label={t.title} disabled={busy||uncertain||submissionPending||!!submittedRequestId||!!readiness.data?.draft.submitted_request_id}>
    {id&&<p><BidiReference>{id}</BidiReference> · {t.revision} {revision.toLocaleString(locale)}</p>}
    {form.configuration_id&&<div className="request-notice"><strong>{t.configuration}</strong><p><BidiReference>{form.configuration_id}</BidiReference> · {t.revision} {form.configuration_revision?.toLocaleString(locale)}</p><p>{t.configurationHelp}</p>{boundReadiness?.status==='unavailable'&&<p role="status">{t.configurationUnavailable}</p>}{boundReadiness?.data?.selection_summary.some(selection=>!selection.current)&&<p role="status">{t.configurationChanged}</p>}<ButtonLink variant="outline" href={`/${locale}/customize?configuration=${encodeURIComponent(form.configuration_id)}`}>{t.openOptions}</ButtonLink><Button type="button" variant="outline" disabled={busy||uncertain} onClick={()=>{change('configuration_id',null);change('configuration_revision',null);change('options',{});}}>{t.detachConfiguration}</Button></div>}
    <div><span>{t.kind}</span><input type="hidden" name="kind" value={form.kind}/><Segmented aria-label={t.kind} value={form.kind} options={[{value:'customization',label:t.customization},{value:'service',label:t.service}]} onChange={value=>{if(!busy&&!uncertain)change('kind',value as DraftInput['kind']);}}/></div>
    <label>{t.brand}<input type="hidden" name="brand_id" value={form.brand_id??''}/><Select aria-label={t.brand} value={form.brand_id??''} disabled={busy||uncertain||!!form.configuration_id} options={[{value:'',label:t.chooseBrand},...(form.brand_id&&!businesses.some(b=>b.id===form.brand_id)?[{value:form.brand_id,label:form.brand_id}]:[]),...businesses.map(b=>({value:b.id,label:b.name+(b.sample_content?' — '+t.sample:'')}))]} onValueChange={value=>{change('brand_id',value||null);change('options',{});}}/></label>
    {directoryUnavailable&&<div className="request-notice"><p>{t.brandUnavailable}</p><Button type="button" variant="outline" disabled={catalogue.isFetching} onClick={()=>void catalogue.refetch()}>{t.directoryReload}</Button></div>}
    {catalogue.hasNextPage&&<Button type="button" variant="outline" disabled={busy||uncertain||catalogue.isFetchingNextPage} onClick={()=>void catalogue.fetchNextPage()}>{t.moreBusinesses}</Button>}
    <label>{t.watchContext}<input type="hidden" name="watch_context" value={form.watch_context}/><Select aria-label={t.watchContext} value={form.watch_context} disabled={busy||uncertain} options={(['undecided','owned_watch','seller_base']as const).map(context=>({value:context,label:t[context]}))} onValueChange={value=>{change('watch_context',value as DraftInput['watch_context']);change('watch_reference','');}}/></label>
    <label>{t.watch}<Input name="watch_reference" value={form.watch_reference} maxLength={300} disabled={busy||uncertain} onChange={e=>change('watch_reference',e.target.value)}/></label>
    {form.watch_context==='seller_base'&&<p role="note">{t.baseIntent}</p>}
    <label>{t.scope}<Textarea name="scope_intent" value={form.scope_intent} maxLength={1000} disabled={busy||uncertain} onChange={e=>change('scope_intent',e.target.value)}/></label>
    <label>{t.notes}<Textarea name="notes" value={form.notes} maxLength={4000} disabled={busy||uncertain} onChange={e=>change('notes',e.target.value)}/><small>{t.notesHelp}</small></label>
    <fieldset><legend>{t.options}</legend><p>{t.optionHelp}</p><div className="request-option-grid">{dimensions.map(dimension=><label key={dimension}>{t[dimension]}<input type="hidden" name={'option_'+dimension} value={form.options[dimension]??''}/><Select aria-label={t[dimension]} value={form.options[dimension]??''} disabled={busy||uncertain||!!form.configuration_id||!currentOptions||!options.some(o=>o.dimension===dimension)} options={[{value:'',label:t.notSelected},...(form.options[dimension]&&!options.some(o=>o.id===form.options[dimension])?[{value:form.options[dimension]!,label:form.options[dimension]!}]:[]),...(currentOptions?options.filter(o=>o.dimension===dimension).map(o=>({value:o.id,label:typeof o.label==='string'?o.label:o.label[locale]})):[])]} onValueChange={value=>change('options',{...form.options,[dimension]:value})}/></label>)}</div></fieldset>
    {!!error&&<div className="request-notice" role="alert"><p>{message(error,t)}</p>{error instanceof ApiError&&error.requestId&&<small className="request-support">{t.support}: <BidiReference>{error.requestId}</BidiReference></small>}</div>}
    {uncertain&&<p role="status">{t.uncertain}</p>}{saved&&<p role="status">{t.saved}</p>}
    </fieldset><div className="request-tools"><Button type="submit" chonk disabled={busy||submissionPending||!!submittedRequestId||!!readiness.data?.draft.submitted_request_id}>{busy?t.saving:uncertain?t.retry:t.save}</Button>{id&&!uncertain&&<Button type="button" variant="outline" disabled={busy||submissionPending} onClick={()=>void reload()}>{t.reload}</Button>}</div>
  </form></Card>
  {id&&form.kind==='customization'&&<Submission key={`${owner}:${id}`} draftId={id} revision={revision} configurationId={form.configuration_id??null} configurationRevision={form.configuration_revision??null} brand={form.brand_id} dirty={dirty||busy} onPendingChange={setSubmissionPending} onSubmitted={setSubmittedRequestId} onDenied={onDenied}/>}
  <Card className="checkout-result"><h2>{t.readiness}</h2><p>{t.noProgress}</p><ul className="request-readiness">{(['quote','consent','work','quality','collection']as const).map(section=><li key={section}><strong>{t[section]}</strong><span>{t.unavailable} — {t.notAssessed}</span></li>)}</ul><h2>{t.technical}</h2><p>{upstreamStatus(readiness.data?.intake)==='available'?t.available:t.technicalUnavailable}</p>{readiness.isFetching&&<p role="status">{t.loading}</p>}<div className="request-tools"><ButtonLink variant="outline" href={`/${locale}/customize`}>{t.openOptions}</ButtonLink><ButtonLink variant="outline" href={`/${locale}/services`}>{t.openServices}</ButtonLink></div></Card></div>
  <aside><Card><h2>{t.resume}</h2><Button variant="outline" disabled={busy||uncertain||submissionPending} onClick={()=>{if(draftMemoryEpoch()!==generation)return;setId(null);setRevision(0);setSubmittedRequestId(null);setForm({...blank,options:{}});setDirty(false);setSaved(false);setError(null);op.current=null;onReferenceChange(null);}}>{t.new}</Button>{drafts.isPending&&<p role="status">{t.loading}</p>}{drafts.error&&<div role="alert"><p>{message(drafts.error,t)}</p><Button onClick={()=>void drafts.refetch()}>{t.reload}</Button></div>}{drafts.data?.pages[0]?.total===0&&<p>{t.empty}</p>}<AnimatedList role="list" aria-label={t.resume} className="request-list" items={drafts.data?.pages.flatMap(page=>page.items)??[]} getKey={draft=>draft.id}>{draft=><div role="listitem" className="request-list-row"><Button variant="outline" disabled={busy||uncertain||submissionPending} onClick={()=>onOpenDraft(draft)}>{draft.watch_reference||t[draft.kind]}</Button><small>{t.updated} <time dateTime={draft.updated_at}>{new Date(draft.updated_at).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time></small></div>}</AnimatedList>{drafts.data&&<p>{t.totalDrafts}: {drafts.data.pages[0].total.toLocaleString(locale)}</p>}{drafts.hasNextPage&&<Button variant="outline" disabled={drafts.isFetchingNextPage} onClick={()=>void drafts.fetchNextPage()}>{t.moreDrafts}</Button>}</Card></aside></div></PageLayout>;
}

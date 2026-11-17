'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, ButtonLink, Input, Skeleton, State } from '@beirut-time/ui/foundation';
import type { Command, Context, Result } from '@contracts/contracts-trust/disputes/v1';
import { useSession, refreshSession } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import { PageFrame, PageBody, PageHeader } from '@/shell/foundation/page';
import { ApiError } from '@/lib/api/client';
import { copy } from './copy';
import { useDisputeResource, request, send, stage } from './api';
import { dollars, freshDraft } from './model';
import { DisputeFields } from './fields';

export default function DisputesScreen() {
 const session=useSession(),locale=useLocale(),t=copy[locale];
 const [ready,setReady]=useState(false),[unavailable,setUnavailable]=useState(false),[attempt,setAttempt]=useState(0);
 useEffect(()=>{if(!session){let active=true;refreshSession().then(()=>{if(active){setUnavailable(false);setReady(true);}},()=>{if(active){setUnavailable(true);setReady(true);}});return ()=>{active=false;};}},[session,attempt]);
 return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>{session?<PrivateAccess key={session.access_fingerprint} scope={session.access_fingerprint}/>:!ready?<Skeleton/>:unavailable?<State kind="error" title={t.title} body={t.unavailable}><Button type="button" onClick={()=>{setReady(false);setAttempt(value=>value+1);}}>{t.retry}</Button></State>:<State title={t.title} body={t.denied}><ButtonLink href={`/${locale}/account`}>{t.signIn}</ButtonLink></State>}</PageBody></PageFrame>;
}

function PrivateAccess({scope}:{scope:string}) {
 const t=copy[useLocale()];
 const [denied,setDenied]=useState(false),[operation,setOperation]=useState<string|null>(null);
 function deny(reference?:string) {setOperation(reference??null);setDenied(true);}
 return denied?<State kind="error" title={t.denied} body={t.denied}>
  {operation&&<p>{t.reference}: <bdi dir="ltr">{operation}</bdi></p>}
  <Button type="button" onClick={()=>setDenied(false)}>{t.refresh}</Button>
 </State>:<PrivateForm scope={scope} onDenied={deny}/>;
}

function PrivateForm({scope,onDenied}:{scope:string;onDenied:(reference?:string)=>void}) {
 const locale=useLocale(),t=copy[locale];
 const [subject,setSubject]=useState(''),[organization,setOrganization]=useState('');
 const [selected,setSelected]=useState<{subject:string;organization:string}|null>(null);
 const [draft,setDraft]=useState(freshDraft),[kind,setKind]=useState<Command['kind']>('open');
 const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const lifetime=useRef<AbortController|null>(null),active=useRef(false);
 const fileInput=useRef<HTMLInputElement|null>(null),operationReference=useRef<string|undefined>(undefined);
 const [fixed,setFixed]=useState<Command|null>(null);
 useEffect(()=>{const controller=new AbortController();lifetime.current=controller;return ()=>controller.abort();},[]);
 const query=useDisputeResource(scope,selected);
 useEffect(()=>{if(query.error instanceof ApiError&&(query.error.status===403||query.error.code==='denied'))onDenied(fixed?.operation_id??result?.operation_id);},[query.error,onDenied,fixed,result]);
 const context=query.isError?undefined:query.data;
 const current=context?.case&&(!result||context.case.revision>result.revision)?context.case:result??context?.case;
 const formatDate=(date:string)=>new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(date));
 const failure=(cause:unknown)=>cause instanceof ApiError&&['denied','stale','conflict','late','prerequisites','evidence','invalid'].includes(cause.code)?cause.code:cause instanceof Error&&cause.message==='evidence'?'evidence':'unavailable';
 async function act() {
  const signal=lifetime.current?.signal;
  if(active.current||!signal||signal.aborted||!selected||(!context&&!fixed))return;
  active.current=true;setBusy(true);setError('');
  try {
   let body=fixed;
   if(!body&&context) {
    const amount=kind==='refund'?dollars(draft.amount):0;
    if(amount===null||draft.reason.trim().length<3||!context.actions.includes(kind)) {setError('invalid');return;}
    body={schema_version:'disputes.v1',operation_id:crypto.randomUUID(),subject_id:selected.subject,organization_id:selected.organization||null,expected_revision:context.expected_revision,source_revision:context.source_revision,assignment_revision:context.assignment_revision,kind,reason:draft.reason,evidence:[],amount_minor:amount};
    setFixed(body);
   }
   if(!body)return;
   operationReference.current=body.operation_id;
   if(draft.file&&!body.evidence.length) {
    const evidence=await stage(scope,selected.subject,selected.organization,draft.file,body.operation_id,signal);
    body={...body,evidence:[evidence]};setFixed(body);
   }
   const answer=await send(scope,body,signal);
   if(signal.aborted)return;
   setResult(answer);
   if(!answer.state.endsWith('_pending')) {setFixed(null);setDraft(freshDraft());if(fileInput.current)fileInput.current.value='';void query.refetch();}
  } catch(cause) {if(!signal.aborted){if(cause instanceof ApiError&&(cause.status===403||cause.code==='denied')){onDenied(operationReference.current);return;}setError(failure(cause));if((cause instanceof ApiError&&[403,409,422].includes(cause.status))||(cause instanceof Error&&cause.message==='evidence'))setFixed(null);}}
  finally {active.current=false;if(!signal.aborted)setBusy(false);}
 }
 function refresh() {setResult(null);setFixed(null);setError('');void query.refetch();}
 async function resume() {
  if(!current||!selected||busy)return;
  const signal=lifetime.current?.signal;if(!signal)return;
  setBusy(true);setError('');
  try {const answer=await request<Result>(scope,`/operations/${current.operation_id}?subject_id=${encodeURIComponent(selected.subject)}${selected.organization?`&organization_id=${encodeURIComponent(selected.organization)}`:''}`,{signal});if(!signal.aborted){setResult(answer);void query.refetch();}}
  catch(cause){if(!signal.aborted){if(cause instanceof ApiError&&(cause.status===403||cause.code==='denied'))onDenied(current.operation_id);else setError(failure(cause));}}
  finally {if(!signal.aborted)setBusy(false);}
 }
 const locked=busy||!!fixed;
 return <div>
  <form onSubmit={event=>{event.preventDefault();setResult(null);setError('');setDraft(freshDraft());setSelected({subject,organization});}}>
   <Input id="dispute-subject" label={t.subject} required value={subject} disabled={locked} onValueChange={value=>setSubject(value.slice(0,128))}/>
   <Input id="dispute-organization" label={t.organization} value={organization} disabled={locked} onValueChange={value=>setOrganization(value.slice(0,128))}/>
   <Button type="submit" disabled={locked}>{t.load}</Button>
  </form>
  {selected&&query.isPending&&<Skeleton/>}
  {(error||query.isError)&&<State kind="error" body={t.unavailable} title={t[(error||failure(query.error)) as keyof Pick<typeof t,'denied'|'stale'|'conflict'|'late'|'prerequisites'|'evidence'|'invalid'|'unavailable'>]}/>}
  {!context&&fixed&&<><p>{t.reference}: <bdi>{fixed.operation_id}</bdi></p><Button type="button" disabled={busy} onClick={()=>void act()}>{t.retry}</Button></>}
  {context&&<>
   <p>{t.closing}: <bdi>{formatDate(context.closing_at)}</bdi></p>
   {current?<State title={t.states[current.state]} body={current.state.endsWith('_pending')?t.pending:t.fee}/>:<State title={t.empty} body={t.fee}/>}
   {context.case&&<PrivateNotes onDenied={()=>onDenied(fixed?.operation_id??current?.operation_id)} context={context} scope={scope} organization={selected?.organization??''}/>}
   {(fixed||current)&&<p>{t.reference}: <bdi dir="ltr">{fixed?.operation_id??current?.operation_id}</bdi></p>}
   <p>{t.fee}</p>
   <DisputeFields locale={locale} draft={{...draft,operation:fixed}} onDraft={setDraft} kind={kind} onKind={setKind} context={context} locked={locked} fileInput={fileInput} onSubmit={()=>void act()}/>
   {!fixed&&current?.state.endsWith('_pending')&&<Button type="button" disabled={busy} onClick={()=>void resume()}>{t.retry}</Button>}
   {fixed&&<Button type="button" disabled={busy} onClick={()=>void act()}>{t.retry}</Button>}
   {!fixed&&<Button type="button" disabled={busy} onClick={refresh}>{t.refresh}</Button>}
  </>}
  {query.isError&&!fixed&&<Button type="button" onClick={refresh}>{t.refresh}</Button>}
 </div>;
}
function PrivateNotes({context,scope,organization,onDenied}:{context:Context;scope:string;organization:string;onDenied:()=>void}) {
 const t=copy[useLocale()];
 const [error,setError]=useState(false),[busy,setBusy]=useState(false);
 const lifetime=useRef<AbortController|null>(null);
 useEffect(()=>{const controller=new AbortController();lifetime.current=controller;return ()=>controller.abort();},[]);
 async function download(reference:string,size:number,media:string) {
  const signal=lifetime.current?.signal;if(!signal||busy||!context.case)return;
  setBusy(true);setError(false);
  try {
   const response=await request<{content_base64:string;media_type:string}>(scope,`/evidence/${encodeURIComponent(context.case.subject_id)}/${encodeURIComponent(reference)}${organization?`?organization_id=${encodeURIComponent(organization)}`:''}`,{signal});
   if(signal.aborted)return;
   if(response.content_base64.length>6666670||response.media_type!==media)throw new Error('evidence');
   const bytes=Uint8Array.from(atob(response.content_base64),value=>value.charCodeAt(0));
   if(bytes.length!==size)throw new Error('evidence');
   const url=URL.createObjectURL(new Blob([bytes],{type:media}));
   const anchor=document.createElement('a');anchor.href=url;anchor.download='private-evidence';anchor.click();URL.revokeObjectURL(url);
  } catch(cause) {if(!signal.aborted){if(cause instanceof ApiError&&(cause.status===403||cause.code==='denied'))onDenied();else setError(true);}}
  finally {if(!signal.aborted)setBusy(false);}
 }
 const evidence=[...(context.case?.evidence??[]),...(context.case?.response?.evidence??[]),...(context.case?.decision?.evidence??[])];
 return <div>{error&&<State kind="error" title={t.evidence} body={t.unavailable}/>}<ul>{evidence.map(item=><li key={item.reference}><Button type="button" disabled={busy} onClick={()=>void download(item.reference,item.size,item.media_type)}>{t.download}</Button></li>)}</ul><p dir="auto">{context.case?.reason}</p>{context.case?.response&&<p dir="auto">{t.response}: {context.case.response.reason}</p>}{context.case?.decision&&<p dir="auto">{t.decision}: {context.case.decision.reason}</p>}</div>;
}

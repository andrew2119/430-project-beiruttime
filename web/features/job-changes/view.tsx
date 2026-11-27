'use client';
import { useEffect, useRef, useState } from 'react';
import { PageFrame, usePageRead } from './page-boundary';
import { useSearchParams } from 'next/navigation';
import { Button, ButtonLink, Card, State, BidiReference, Textarea } from '@beirut-time/ui';
import { PageHeader } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { ChangeReview, ChangeOperation, ChangeCommand } from '@contracts/contracts-catalog/job-changes/v1';
import en from './en.json';
import ar from './ar.json';
import { formatUsdMinor } from './money';

function validOperation(value: unknown): value is ChangeOperation {
 if (!value || typeof value !== 'object') return false;
 const row = value as Record<string, unknown>;
 const reference = (item: unknown) => typeof item === 'string' && /^[A-Za-z0-9_.:-]{1,100}$/.test(item);
 const revision = (item: unknown) => typeof item === 'number' && Number.isInteger(item) && item > 0 && item <= 2147483647;
 const utc = (item: unknown) => typeof item === 'string' && /(?:Z|\+00:00)$/.test(item) && Number.isFinite(Date.parse(item));
 return row.schema_version === 'job-changes.v1'
  && ['operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'next_actor', 'active_scope_id'].every(key => reference(row[key]))
  && revision(row.expected_revision) && revision(row.revision)
  && ['pending_hold', 'awaiting_reapproval', 'pending_resume', 'reapproved'].includes(row.state as string)
  && (row.pending_reason === null || reference(row.pending_reason))
  && utc(row.next_review_at) && row.execution_authority === false
  && Array.isArray(row.invalidated) && row.invalidated.length === 4
  && ['quote', 'eligibility', 'brand_decision', 'buyer_acceptance'].every(item => (row.invalidated as unknown[]).includes(item));
}

function validReview(value: ChangeReview): boolean {
 const change=value.change,approval=value.approval;
 const reference=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9_.:-]{1,100}$/.test(v);
 const revision=(v:unknown)=>typeof v==='number'&&Number.isInteger(v)&&v>0&&v<=2147483647;
 if(!change||change.schema_version!=='job-changes.v1'
  ||!['operation_id','subject_id','watch_id','actor_id','organization_id','responsible_operator_id','order_id','source_scope_id','proposed_scope_id','retained_quote_id'].every(key=>reference((change as unknown as Record<string,unknown>)[key]))
  ||!revision(change.expected_revision)||!revision(change.retained_quote_revision)
  ||!value.scope||!value.terms||![value.scope.en,value.scope.ar,value.terms.en,value.terms.ar].every(text=>typeof text==='string'&&text.trim().length>0))return false;
 if(approval===null)return true;
 return !!approval&&approval.operation_id===change.operation_id&&approval.scope_id===change.proposed_scope_id
  &&['operation_id','scope_id','assessment_id','quote_id','assessor_id','approver_id','quality_reviewer_id','eligibility_reviewer_id'].every(key=>reference((approval as unknown as Record<string,unknown>)[key]))
  &&['scope_revision','assessment_revision','quote_revision','consent_revision','eligibility_revision','policy_revision','approval_revision','acceptance_revision','payment_revision'].every(key=>revision((approval as unknown as Record<string,unknown>)[key]))
  &&approval.currency==='USD'&&Number.isSafeInteger(approval.total_minor)&&approval.total_minor>0
  &&Number.isSafeInteger(approval.business_fee_minor)&&approval.business_fee_minor===Number((BigInt(approval.total_minor)*5n+50n)/100n)
  &&Number.isFinite(Date.parse(approval.accepted_at));
}

export default function JobChanges(){
 const locale=useLocale(),t=locale==='ar'?ar:en,params=useSearchParams(),access=useAccessContext();
 const subject=params.get('subject_id')??'';
 const operation=params.get('operation_id')??'',organization=params.get('organization_id')??'';
 return <PageFrame><PageHeader title={t.title} count={t.intro}/>
 {operation&&organization&&access.fingerprint?<Current key={`${access.fingerprint}:${organization}:${operation}`} operation={operation} organization={organization}/>:subject&&organization&&access.fingerprint?<Review key={`${access.fingerprint}:${organization}:${subject}`} subject={subject} organization={organization}/>:<State title={t.title} body={t.empty}/>}
 </PageFrame>;
}
function Current({operation,organization}:{operation:string;organization:string}){
 const locale=useLocale(),t=locale==='ar'?ar:en,access=useAccessContext();
 const [busy,setBusy]=useState(false),[failed,setFailed]=useState(false),[accessDenied,setAccessDenied]=useState(false);
 const query=usePageRead({queryKey:['job-changes.v1',access.fingerprint,organization,operation],
 queryFn:({signal})=>authenticatedRequest<ChangeOperation>(`/api/web/v1/catalog/v1/job-change-operations/${encodeURIComponent(operation)}?organization_id=${encodeURIComponent(organization)}`,{signal,accessFingerprint:access.fingerprint??undefined}),retry:false});
 const denied=query.error instanceof ApiError&&[401,403,404].includes(query.error.status);
 const value=!query.error?query.data:undefined;
 const valid=validOperation(value)&&value.operation_id===operation&&value.organization_id===organization;
 async function reconcile(){
  setBusy(true);setFailed(false);
  try{await authenticatedRequest(`/api/web/v1/catalog/v1/job-change-operations/${encodeURIComponent(operation)}/resume?organization_id=${encodeURIComponent(organization)}`,{method:'POST',accessFingerprint:access.fingerprint??undefined});void query.refetch();}
  catch(error){setFailed(true);if(error instanceof ApiError&&[401,403,404].includes(error.status))setAccessDenied(true);}finally{setBusy(false);}
 }
 if(accessDenied)return <State kind="error" title={t.title} body={t.denied}/>;
 return <Card>
 {query.isPending?<State kind="loading" title={t.title} body={t.loading}/>:!valid?<State kind="error" title={t.title} body={denied?t.denied:t.unavailable}/>:<>
 <p role="status">{t[value.state]}</p>{(value.state==='pending_hold'||value.state==='pending_resume')&&<Button disabled={busy} onClick={()=>void reconcile()}>{t.retry}</Button>}<dl><dt>{t.reference}</dt><dd><BidiReference>{operation}</BidiReference></dd>
 <dt>{t.revision}</dt><dd>{value.revision.toLocaleString(locale)}</dd>
 <dt>{t.next}</dt><dd>{Number.isFinite(Date.parse(value.next_review_at))?new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(value.next_review_at)):'—'}</dd></dl><p>{t.private}</p>{value.state==='awaiting_reapproval'&&<Review subject={value.subject_id} organization={organization} operation={operation} onDone={()=>void query.refetch()}/>}
 </>}
 {failed&&<p role="alert">{t.unavailable}</p>}
 <Button disabled={query.isFetching} onClick={()=>void query.refetch()}>{t.retry}</Button>
 <ButtonLink href={`/${locale}/business/customizations`}>{t.open}</ButtonLink>
 </Card>;
}

export function Review({subject,organization,operation,onDone}:{subject:string;organization:string;operation?:string;onDone?:()=>void}){
 const locale=useLocale(),t=locale==='ar'?ar:en,access=useAccessContext();
 const [reason,setReason]=useState(''),[busy,setBusy]=useState(false),[failed,setFailed]=useState(false),[result,setResult]=useState<ChangeOperation|null>(null),[uncertain,setUncertain]=useState(false),[accessDenied,setAccessDenied]=useState(false);
 const pending=useRef<{url:string;body:string;change:ChangeCommand}|null>(null);
 const query=usePageRead({queryKey:['job-change-review.v1',access.fingerprint,organization,subject,operation],queryFn:({signal})=>authenticatedRequest<ChangeReview>(`/api/web/v1/catalog/v1/jobs/${encodeURIComponent(subject)}/change-review?organization_id=${encodeURIComponent(organization)}`,{signal,accessFingerprint:access.fingerprint??undefined}),retry:false});
 const review=!query.error?query.data:undefined;
 const valid=review&&validReview(review)&&review.change.subject_id===subject&&review.change.organization_id===organization&&(!operation||review.change.operation_id===operation);
 const readDenied=query.error instanceof ApiError&&[401,403,404].includes(query.error.status);
 useEffect(()=>{if(readDenied)pending.current=null;},[readDenied]);
 async function submit(){
  if(!pending.current){
   if(!valid||!review||operation&&!review.approval)return;
   pending.current={url:operation?`job-change-operations/${encodeURIComponent(operation)}/accept`:`jobs/${encodeURIComponent(subject)}/changes`,body:JSON.stringify(operation?review.approval:{...review.change,reason}),change:{...review.change}};
  }
  setBusy(true);setFailed(false);setUncertain(true);
  try{
   const command=pending.current;
   const response=await authenticatedRequest<ChangeOperation>(`/api/web/v1/catalog/v1/${command.url}?organization_id=${encodeURIComponent(organization)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:command.body,accessFingerprint:access.fingerprint??undefined});
   const change=command.change;
   if(!validOperation(response)
    || !(['operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision'] as const).every(key=>response[key]===change[key])
    || response.active_scope_id!==(response.state==='pending_hold'?change.source_scope_id:change.proposed_scope_id)){
    setFailed(true);return;
   }
   setResult(response);pending.current=null;setUncertain(false);onDone?.();
  }catch(error){setFailed(true);if(error instanceof ApiError&&error.status<500){pending.current=null;setUncertain(false);if([401,403,404].includes(error.status)){setAccessDenied(true);setReason('');setResult(null);}}}
  finally{setBusy(false);}
 }
 if(readDenied&&!accessDenied){
  setAccessDenied(true);setReason('');setResult(null);setUncertain(false);
 }
 if(accessDenied||readDenied)return <State kind="error" title={t.title} body={t.denied}/>;
 if(result)return <State title={t.title} body={t[result.state]}><BidiReference>{result.operation_id}</BidiReference><ButtonLink href={`/${locale}/business/job-changes?organization_id=${encodeURIComponent(organization)}&operation_id=${encodeURIComponent(result.operation_id)}`}>{t.retry}</ButtonLink></State>;
 return <section>
 {query.isPending?<State kind="loading" title={t.title} body={t.loading}/>:!valid?<State kind="error" title={t.title} body={query.error instanceof ApiError&&[401,403,404].includes(query.error.status)?t.denied:t.unavailable}/>:<>
 <p>{review.scope[locale]}</p><p>{review.terms[locale]}</p>
 {review.approval&&<p><BidiReference>{formatUsdMinor(review.approval.total_minor,locale)}</BidiReference></p>}
 {!operation&&<label>{t.reason}<Textarea value={reason} maxLength={1000} disabled={busy||uncertain} onChange={e=>setReason(e.target.value)}/></label>}
 <Button disabled={busy||(!uncertain&&(!operation&&reason.trim().length<3||!!operation&&!review.approval))} onClick={()=>void submit()}>{uncertain?t.retry:operation?t.accept:t.start}</Button>
 </>}
 {failed&&<p role="alert">{t.unavailable}</p>}
 {uncertain&&!valid&&<Button disabled={busy} onClick={()=>void submit()}>{t.retry}</Button>}
 <Button variant="outline" disabled={busy||query.isFetching} onClick={()=>void query.refetch()}>{t.retry}</Button>
 </section>;
}

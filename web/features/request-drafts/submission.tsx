'use client';
import { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, ButtonLink, Card, State, BidiReference, StatusBadge } from '@beirut-time/ui';
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { configurationApi } from '@/features/brand-options/configuration-review';
import { configurationField, configurationSelectionLabel } from '@/features/brand-options/configuration-copy';
import type { BrandRequest, Submit, Operation, Validation, RequestHistory } from '@contracts/contracts-catalog/request-drafts/v2';
import { privateAccessDenied, readPrivateDrafts } from './private-drafts';
import { readPrivateHistory, historyAccessDenied } from './private-history';
import en from './en.json';
import arCopy from './ar.json';
const dimensions=['color','material','dial','sophistication','movement'] as const;
const root='/api/web/v1/catalog/v1';
export default function Submission({draftId,revision,configurationId,configurationRevision,brand,dirty,onPendingChange,onSubmitted,onDenied}:{draftId:string;revision:number;configurationId:string|null;configurationRevision:number|null;brand:string|null;dirty:boolean;onPendingChange:(pending:boolean)=>void;onSubmitted:(requestId:string)=>void;onDenied:()=>void}){
 const locale=useLocale(),ar=locale==='ar',access=useAccessContext(),alive=useRef(true),cache=useQueryClient();
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 const[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState<unknown>(null),[receipt,setReceipt]=useState<{binding:string;value:Validation}|null>(null),[result,setResult]=useState<Operation|null>(null);
 const operation=useRef<{key:string;body:Submit}|null>(null);
 const movement=useQuery({queryKey:['movement-selection',access.fingerprint,brand],queryFn:({signal})=>configurationApi.movement(brand!,signal),enabled:!!brand,retry:false});
 const reviewBinding=JSON.stringify([access.fingerprint,draftId,revision,configurationId,configurationRevision,brand,movement.data?.selection?.id,movement.data?.selection?.revision]);
 const validation=receipt&&receipt.binding===reviewBinding&&!movement.error?receipt.value:null;
 const requests=useQuery({queryKey:['customization-requests',access.fingerprint,draftId,revision],queryFn:({signal})=>readPrivateDrafts(()=>authenticatedRequest<{items:BrandRequest[]}>(`${root}/customization-requests?draft_id=${encodeURIComponent(draftId)}`,{signal}),onDenied),enabled:!brand||movement.isFetched,retry:false});
 const submitted=requests.data?.items.find(item=>item.draft_id===draftId)??result?.request;
 useEffect(()=>{if(submitted?.id)onSubmitted(submitted.id);},[submitted?.id,onSubmitted]);
 const shownValidation=uncertain?receipt?.value??null:validation,dimensionCopy=ar?arCopy:en;
 const decision=useQuery({queryKey:['buyer-brand-decision',access.fingerprint,submitted?.id,submitted?.revision],queryFn:({signal})=>readPrivateDrafts(()=>authenticatedRequest<{status:string;execution_authority:false}>(`${root}/customization-requests/${submitted!.id}/decision`,{signal}),onDenied),enabled:!!submitted,retry:false});
 const t=ar?{title:'إرسال طلب إلى العلامة',body:'يحتفظ الإرسال بنسخة ثابتة من الأبعاد الخمسة والملاحظات الخاصة. التقييم اليدوي ليس موافقة على تنفيذ عمل أو دفع.',review:'مراجعة الأبعاد الحالية',submit:'إرسال النسخة المراجعة',retry:'تسوية نفس عملية الإرسال',save:'احفظ المسودة أولاً ثم راجع الاختيارات.',missing:'اختر واحفظ الأبعاد الأربعة والحركة أولاً.',done:'تم الإرسال للمراجعة',approved:'تمت الموافقة على النطاق؛ تفويض العمل مستقل',rejected:'تم رفض النطاق',decisionPending:'القرار بانتظار التأكيد',references:'المراجع الخاصة المرفقة',pending:'النتيجة غير مؤكدة. أعد نفس العملية، ولا تبدأ طلباً آخر.',error:'لم يُقبل الطلب. راجع الحقول أو حدّث النسخة الحالية.',open:'فتح الاختيارات',reload:'تحديث الطلبات',manual_assessment:'يتطلب تقييماً يدوياً',valid:'مدعوم للمراجعة',incompatible:'غير متوافق',parts_unavailable:'قطع غير متوفرة'}:{title:'Submit to the brand',body:'Submission retains an immutable copy of all five dimensions and private notes. Manual assessment is not approval to work or pay.',review:'Review current dimensions',submit:'Submit reviewed revision',retry:'Reconcile the same submission',save:'Save the draft first, then review current choices.',missing:'Choose and save the four dimensions and movement first.',done:'Submitted for assessment',approved:'Scope approved; work authorization is separate',rejected:'Scope rejected',decisionPending:'Decision pending confirmation',references:'Attached private references',pending:'Outcome is uncertain. Retry this same operation, not a new request.',error:'The request was not accepted. Review the fields or reload the current revision.',open:'Open choices',reload:'Refresh requests',manual_assessment:'Manual assessment required',valid:'Supported for review',incompatible:'Incompatible',parts_unavailable:'Parts unavailable'};
 async function review(){if(!configurationId||!configurationRevision||!movement.data?.selection)return;setBusy(true);setError(null);try{const value=await configurationApi.validate(configurationId,configurationRevision,movement.data.selection);if(alive.current)setReceipt({binding:reviewBinding,value});}catch(e){if(alive.current){if(privateAccessDenied(e))onDenied();else setError(e);}}finally{if(alive.current)setBusy(false);}}
 async function submit(){if(!operation.current){if(!configurationId||!configurationRevision||!movement.data?.selection||!validation)return;operation.current={key:crypto.randomUUID(),body:{draft_revision:revision,configuration_id:configurationId,configuration_revision:configurationRevision,movement_selection_id:movement.data.selection.id,movement_revision:movement.data.selection.revision,expected_digest:validation.digest}};}setUncertain(true);onPendingChange(true);setBusy(true);setError(null);try{const op=operation.current;const value=await authenticatedRequest<Operation>(`${root}/request-drafts/${draftId}/submit`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':op.key},body:JSON.stringify(op.body)});if(alive.current){setResult(value);operation.current=null;setUncertain(false);onPendingChange(false);void requests.refetch();void cache.invalidateQueries({queryKey:['l08-draft-readiness',access.fingerprint,draftId]});}}catch(e){if(alive.current){if(privateAccessDenied(e)){onDenied();return;}setError(e);if(e instanceof ApiError&&e.status<500){operation.current=null;setUncertain(false);onPendingChange(false);}}}finally{if(alive.current)setBusy(false);}}
 const fields=error instanceof ApiError?error.details.fields:null;
 return <Card className="request-form"><h2>{t.title}</h2><p>{t.body}</p>{submitted?<div role="status"><StatusBadge hue="blue">{t.done}</StatusBadge><p><BidiReference>{submitted.id}</BidiReference> · <BidiReference>{submitted.revision}</BidiReference></p>{uncertain&&<Button disabled={busy} onClick={()=>void submit()}>{t.retry}</Button>}<RequestHistoryView request={submitted} onDenied={onDenied}/><p><BidiReference>{submitted.configuration.base_model} · {submitted.configuration.caliber}</BidiReference></p>{decision.data&&['approved','rejected','pending'].includes(decision.data.status)&&<p>{decision.data.status==='approved'?t.approved:decision.data.status==='rejected'?t.rejected:t.decisionPending}</p>}</div>:<>
 {(dirty||!configurationId||!movement.data?.selection)&&<p>{dirty?t.save:movement.error?t.error:t.missing}</p>}
 <div className="request-tools"><Button variant="outline" disabled={busy||dirty||!configurationId||!movement.data?.selection||!!movement.error||!requests.data||!!requests.error||uncertain} onClick={()=>void review()}>{t.review}</Button><Button disabled={busy||(!uncertain&&(dirty||!requests.data||!!requests.error||!validation||!['valid','manual_assessment'].includes(validation.status)))} onClick={()=>void submit()}>{uncertain?t.retry:t.submit}</Button></div>
 {shownValidation&&<><p role="status">{t[shownValidation.status]}</p><dl className="request-option-grid request-snapshot">{dimensions.map(dimension=>{const entry=shownValidation.snapshot.selections[dimension];return entry?<div key={dimension}><dt>{dimensionCopy[dimension]}</dt><dd>{configurationSelectionLabel(entry.definition,locale)} · <BidiReference>{entry.option_revision}</BidiReference></dd></div>:null;})}</dl><p>{t.references}: <BidiReference>{shownValidation.snapshot.reference_ids.length}</BidiReference></p></>}
 {!!error&&<div role="alert"><p>{uncertain?t.pending:t.error}</p>{!!fields&&typeof fields==='object'&&<ul>{Object.entries(fields).map(([field,value])=><li key={field}>{configurationField(locale,field,value)}</li>)}</ul>}</div>}
 </>}
 <div className="request-tools"><ButtonLink variant="outline" href={`/${locale}/customize${configurationId?'?configuration='+encodeURIComponent(configurationId):''}`}>{t.open}</ButtonLink><Button variant="outline" onClick={()=>{void movement.refetch();void requests.refetch();}}>{t.reload}</Button></div>
 {requests.isPending&&<State kind="loading" title={t.title} body={t.reload}/>}{requests.error&&<State kind="error" title={t.title} body={ar?'تعذّر تأكيد الطلبات الحالية. حدّث الطلبات؛ لا ترسل طلباً جديداً.':'Current requests could not be confirmed. Refresh requests; do not submit a new request.'}/>}
 </Card>;
}

function RequestHistoryView({request,onDenied}:{request:BrandRequest;onDenied:()=>void}){
 const locale=useLocale(),t=locale==='ar'?arCopy:en,access=useAccessContext();
 const cache=useQueryClient();
 const queryKey=['customization-history',access.fingerprint,request.id,request.revision];
 const history=useInfiniteQuery({
  queryKey,
  initialPageParam:null as number|null,
  queryFn:({signal,pageParam})=>readPrivateDrafts(()=>readPrivateHistory(cache,queryKey,()=>authenticatedRequest<RequestHistory>(`${root}/customization-requests/${request.id}/revisions?limit=20${pageParam?'&before_revision='+pageParam:''}`,{signal})),onDenied),
  getNextPageParam:last=>last.next_cursor??undefined,retry:false,
 });
 const denied=historyAccessDenied(history.error);
 return <section aria-label={t.history}><h3>{t.history}</h3>
  {history.isPending&&<State kind="loading" title={t.history} body={t.loading}/>}
  {history.error&&<State kind="error" title={t.history} body={denied?t.historyDenied:t.historyUnavailable}><Button onClick={()=>void history.refetch()}>{t.reload}</Button></State>}
  {!denied&&history.data?.pages.flatMap(page=>page.items).map(item=><article key={item.revision} className="request-history-row">
   <h4>{t.revision} {item.revision.toLocaleString(locale)}</h4>
   <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time>
   <p>{t.reason}: <bdi>{item.reason==='Buyer submitted current configuration'?t.originalSubmission:item.reason}</bdi></p>
   <dl className="request-option-grid request-snapshot">{dimensions.map(dimension=>{
    const selection=item.configuration.selections[dimension];
    return <div key={dimension}><dt>{t[dimension]}</dt><dd>{configurationSelectionLabel(selection.definition,locale)} · <BidiReference>{selection.option_revision}</BidiReference></dd></div>;
   })}</dl>
  </article>)}
  {!denied&&history.hasNextPage&&<Button variant="outline" disabled={history.isFetchingNextPage} onClick={()=>void history.fetchNextPage()}>{t.moreHistory}</Button>}
 </section>;
}

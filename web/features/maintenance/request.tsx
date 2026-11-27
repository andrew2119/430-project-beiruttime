'use client';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Button, Card, Checkbox, Input, Label, Textarea, Select, Segmented, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { ApiError } from '@/lib/api/client';
import { useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
import type { MaintenanceContextV1, MaintenancePhotoV1, MaintenanceResultV1 } from '@contracts/contracts-service/maintenance/v1';
import { usePageRead } from '@/lib/page-speed/read';
import { call, Recovery, SupportLink, useCopy } from './common';
import MaintenanceSignIn from './sign-in';
import {OpeningConsent} from './opening-consent';
import {ScopedOperation,ScopedOperationResolution,useScopedOperationJournal,type OperationBinding,type OperationJournal} from './scoped-operation';
import { privateRecordUnavailable } from './private-read';
import { ContextReviewRequired, isMissingReceipt, matchesReceipt, receiptBinding, Submission, validPhotos, validResultReceipt, type ReceiptBinding } from './submission';
const contextRead=definePageRead({key:(scope:string,id:string,generation:string,brand='')=>['maintenance-context',scope,id,generation,brand],warm:'open-only',fresh:0,
  ask:(signal:AbortSignal,scope:string,id:string,_generation:string,brand='')=>call<MaintenanceContextV1>(scope,
    `maintenance/context/${encodeURIComponent(id)}${brand?`?brand_id=${encodeURIComponent(brand)}`:''}`,{signal})});
function encoded(file:File):Promise<string> {return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>typeof reader.result==='string'?resolve(reader.result.split(',')[1]):reject(new Error('invalid_file'));reader.onerror=()=>reject(new Error('invalid_file'));reader.readAsDataURL(file);});}
export default function MaintenanceRequest() {
  const session=useSession();const status=useSessionState();const {t}=useCopy();
  const operation=useScopedOperationJournal(session?.principal.actor?.subject_id);
  const [restoreError,setRestoreError]=useState<unknown>();
  const restore=()=>{setRestoreError(undefined);void refreshSession().catch(setRestoreError);};
  return <PageFrame><PageHeader title={t('maintenanceTitle')} lead={t('scopePolicy')}/><PageBody>{session?<WatchRequest key={session.access_fingerprint} scope={session.access_fingerprint} openingOperation={operation.binding} openingJournal={operation.journal}/>:status==='restoring'?<PageLoading label={t('loading')}/>:status==='unavailable'?<Recovery error={restoreError} retry={restore}/>:<State title={t('signIn')} body={t('signInBody')}><MaintenanceSignIn/></State>}</PageBody></PageFrame>;
}
function WatchRequest({scope,openingOperation,openingJournal}:{scope:string;openingOperation:OperationBinding|null;openingJournal:OperationJournal}) {
  const {t}=useCopy();const [watch,setWatch]=useState('');const [opened,setOpened]=useState('');
  const [accessError,setAccessError]=useState<unknown>();
  const watchLocked=useRef(false);
  const [switchBlocked,setSwitchBlocked]=useState(false);
  function lockWatch(locked:boolean) {
    watchLocked.current=locked;
    setSwitchBlocked(locked);
  }
  const [readGeneration,setReadGeneration]=useState('');
  const [brand,setBrand]=useState('');
  const brandList=usePageRead(opened&&!accessError?contextRead(scope,opened,readGeneration):null);
  const read=usePageRead(opened&&brand&&!accessError?contextRead(scope,opened,readGeneration,brand):null);
  const choices=brandList.data?.destinations.filter(item=>item.organization_id===item.brand_id)??[];
  const scoped=read.data && read.data.watch_id===opened && read.data.destinations.every(item=>item.brand_id===brand)
    ? read.data : undefined;
  const operation=useRef<ReceiptBinding[]>([]);
  const [recoveryReference,setRecoveryReference]=useState('');
  const [checking,setChecking]=useState(false);
  const [confirmed,setConfirmed]=useState<MaintenanceResultV1>();
  const [openingEpoch,setOpeningEpoch]=useState(0);
  const [openingResolution,setOpeningResolution]=useState<'recorded'|'closed'>();
  const trackOpening:OperationJournal={begin(binding){
    if(!openingJournal.begin(binding))return false;
    setOpeningResolution(undefined);return true;
  },resolve:openingJournal.resolve};
  const [recoveryError,setRecoveryError]=useState<unknown>();
  const lookupLife=useRef<AbortController|null>(null);
  useEffect(()=>()=>lookupLife.current?.abort(),[]);
  const denied=useCallback((error:unknown)=>{
    watchLocked.current=false;
    setSwitchBlocked(false);
    setReadGeneration(crypto.randomUUID());
    setOpened('');
    setBrand('');
    setWatch('');
    setAccessError(error);
    const reference=operation.current[0]?.operation_id??'';
    setRecoveryReference(reference);
  },[]);
  const deniedAnswer=read.error??brandList.error;
  const revoked=privateRecordUnavailable(deniedAnswer);
  useEffect(()=>{
    if(!opened||!revoked)return;
    let current=true;
    queueMicrotask(()=>{if(current)denied(deniedAnswer);});
    return ()=>{current=false;};
  },[opened,revoked,deniedAnswer,denied]);
  async function recover(close=false) {
    const binding=operation.current[0];
    if(!binding||lookupLife.current)return;
    const controller=new AbortController();
    lookupLife.current=controller;
    setChecking(true);
    setRecoveryError(undefined);
    setAccessError(undefined);
    try {
      const answer=await lookupReceipt(scope,binding,controller.signal,close);
      if(controller.signal.aborted)return;
      if('closed' in answer) {
        if(!close||answer.closed!==true||answer.operation_id!==binding.operation_id||
          answer.organization_id!==binding.organization_id)throw new Error('response_scope');
        operation.current=[];
        setRecoveryReference('');
        return;
      }
      if(controller.signal.aborted)return;
      if(!validResultReceipt(answer)||!operation.current.some(value=>matchesReceipt(answer,value)))throw new Error('response_scope');
      if(answer.state==='submitted'){
        operation.current=[];
        setRecoveryReference('');
        setConfirmed(answer);
      }
    } catch(error) {
      if(!controller.signal.aborted)setRecoveryError(error);
    } finally {
      lookupLife.current=null;
      if(!controller.signal.aborted)setChecking(false);
    }
  }
  const receiptMissing=isMissingReceipt(recoveryError);
  if(recoveryReference)return <Card>
    {!checking&&!!accessError&&<Recovery error={accessError} retry={()=>void recover()}/>}
    {receiptMissing&&<><p role="status">{t('receiptMissing')}</p><Button disabled={checking} onClick={()=>void recover(true)}>{t('closeUnconfirmed')}</Button></>}
    {!accessError&&!!recoveryError&&!receiptMissing&&<Recovery error={recoveryError} retry={()=>void recover()}/>}
    {!accessError&&(!recoveryError||receiptMissing)&&<Button disabled={checking} onClick={()=>void recover()}>{t(checking?'pending':'retry')}</Button>}
    <SupportLink/><p role="status">{t('retrySame')}</p><bdi>{recoveryReference}</bdi>
  </Card>;
  return <>{openingResolution&&<ScopedOperationResolution outcome={openingResolution}/>}
    {openingOperation&&<ScopedOperation key={openingOperation.operation_id} scope={scope} binding={openingOperation}
      onResolved={outcome=>{if(openingJournal.resolve(openingOperation)){setOpeningResolution(outcome);setOpeningEpoch(value=>value+1);}}}/>}
    <Card><form onSubmit={event=>{event.preventDefault();if(watchLocked.current)return;setConfirmed(undefined);setAccessError(undefined);if(watch===opened){void brandList.refetch();if(brand)void read.refetch();}else {setBrand('');setOpened(watch.toLowerCase());}}}><Input disabled={switchBlocked} label={t('watch')} value={watch} onValueChange={setWatch} required/><Button type="submit" disabled={switchBlocked}>{t('open')}</Button></form>{switchBlocked&&<p>{t('finishWatchRequest')}</p>}</Card>
    {confirmed&&<><p role="status">{t('requestSubmitted')}</p><SubmittedScope receipt={confirmed}/><ConfirmationStatus scope={scope} receipt={confirmed}/><OpeningConsent key={openingEpoch} scope={scope} receipt={confirmed} blocked={!!openingOperation} journal={trackOpening}/></>}
    {!!accessError&&<Recovery error={accessError} retry={()=>setAccessError(undefined)}/>}
    {opened&&<>{(brandList.isPending||!!brand&&read.isPending)&&<p role="status">{t('loading')}</p>}
      {!!brandList.error&&<Recovery error={brandList.error} retry={brandList.refetch}/>}
      {choices.length>0&&!revoked&&<Select label={t('brandReference')} value={brand} disabled={switchBlocked} onValueChange={setBrand}
        options={choices.map(item=>({value:item.brand_id,label:item.display_name}))} messages={{placeholder:t('chooseBrand'),filter:t('chooseBrand'),emptyTitle:t('emptyDestinations'),emptyBody:t('noCurrentDestinations'),close:t('close'),loading:t('loading'),errorTitle:t('unavailable'),errorBody:t('unavailableBody'),retry:t('retry')}}/>}
      {brandList.data&&!choices.length&&!brandList.error&&<State title={t('emptyDestinations')} body={t('noCurrentDestinations')}/>}
      {!!brand&&!!read.error&&<Recovery error={read.error} retry={read.refetch}/>}
      {!!brand&&!!read.data&&!scoped&&!revoked&&<Recovery error={new Error('unavailable')} retry={read.refetch}/>}
      {brand&&scoped&&!revoked&&<RequestForm key={`${opened}:${brand}`} scope={scope} context={scoped} contextUnavailable={!!read.error||!!brandList.error} refreshContext={()=>void read.refetch()} onDenied={denied} onWatchLockChange={lockWatch} openingBlocked={!!openingOperation} openingEpoch={openingEpoch} openingJournal={trackOpening} onOperationChange={bindings=>{operation.current=bindings;}} reviewContext={async()=>{const answer=await read.refetch();if(answer.error)throw answer.error;if(!answer.data||answer.data.watch_id!==opened||answer.data.destinations.some(item=>item.brand_id!==brand))throw new Error('unavailable');return answer.data;}}/>}</>}
  </>;

}
function ConfirmationStatus({scope,receipt}:{scope:string;receipt:MaintenanceResultV1}) {
  const {t}=useCopy();
  const [value,setValue]=useState<{state:'awaiting_confirmation'|'confirmed'|'rejected';reason?:string}>();
  const [failure,setFailure]=useState(false);
  const [busy,setBusy]=useState(false);
  const pending=useRef<AbortController|null>(null);
  useEffect(()=>()=>pending.current?.abort(),[]);
  async function read() {
    if (pending.current) return;
    const controller=new AbortController();
    pending.current=controller;setBusy(true);setFailure(false);setValue(undefined);
    try {
      const response=await call<{request_id:string;state:'awaiting_confirmation'|'confirmed'|'rejected';reason?:string}>(
        scope,`maintenance/requests/${encodeURIComponent(receipt.request_id)}/disposition`,{signal:controller.signal});
      if(response.request_id!==receipt.request_id||!['awaiting_confirmation','confirmed','rejected'].includes(response.state)
        ||(response.state==='rejected'&&(typeof response.reason!=='string'||!response.reason.trim()||response.reason.length>1000)))throw new Error('response_scope');
      if(!controller.signal.aborted)setValue(response);
    } catch {if(!controller.signal.aborted)setFailure(true);}
    finally {pending.current=null;if(!controller.signal.aborted)setBusy(false);}
  }
  return <section><Button busy={busy} onClick={()=>void read()}>{t('checkConfirmation')}</Button>
    {failure&&<p role="status">{t('unavailableBody')}</p>}
    {value&&<p role="status">{t(value.state)}{value.state==='rejected'&&<>: <bdi>{value.reason}</bdi></>}</p>}
  </section>;
}
function SubmittedScope({receipt,destinations=[]}:{
  receipt:MaintenanceResultV1;
  destinations?:MaintenanceContextV1['destinations'];
}) {
  const {t}=useCopy();
  const destination=destinations.find(item=>item.organization_id===receipt.organization_id&&item.brand_id===receipt.brand_id);
  return <dl>
    <dt>{t('organization')}</dt><dd><bdi>{destination?.display_name??receipt.organization_id}</bdi></dd>
    <dt>{t('brandReference')}</dt><dd><bdi>{receipt.brand_id}</bdi></dd>
    <dt>{t('scope')}</dt><dd>{t(receipt.intervention==='limited_maintenance'?'limited':'overhaul')}</dd>
  </dl>;
}
type ClosedRequest = {closed:true;operation_id:string;organization_id:string};
function lookupReceipt(scope:string,body:ReceiptBinding,signal:AbortSignal):Promise<MaintenanceResultV1>;
function lookupReceipt(scope:string,body:ReceiptBinding,signal:AbortSignal,close:boolean):Promise<MaintenanceResultV1|ClosedRequest>;
function lookupReceipt(scope:string,body:ReceiptBinding,signal:AbortSignal,close=false) {
  return call<MaintenanceResultV1|ClosedRequest>(scope,'maintenance/operations/'+encodeURIComponent(body.operation_id)+'?organization_id='+encodeURIComponent(body.organization_id),{signal,method:close?'DELETE':'GET'});
}
function RequestForm({scope,context:initialContext,contextUnavailable,refreshContext,onDenied,reviewContext,onWatchLockChange,onOperationChange,openingBlocked,openingEpoch,openingJournal}:{openingBlocked:boolean;openingEpoch:number;
  openingJournal:OperationJournal;scope:string;context:MaintenanceContextV1;contextUnavailable:boolean;refreshContext:()=>void;onDenied:(error:unknown)=>void;reviewContext:()=>Promise<MaintenanceContextV1>;onWatchLockChange?:(locked:boolean)=>void;onOperationChange?:(bindings:ReceiptBinding[])=>void}) {
  const {t,locale}=useCopy();const fileId=useId();
  const [adoptedContext,setContext]=useState<MaintenanceContextV1>(()=>initialContext);
  const observedContext=useRef(initialContext);
  const contextBeforeReview=useRef(initialContext);
  const [needsReview,setNeedsReview]=useState(false);
  const [reviewed,setReviewed]=useState<MaintenanceContextV1>();
  const [reviewing,setReviewing]=useState(false);
  const [reviewLimitReached,setReviewLimitReached]=useState(false);
  const [retainedBusiness,setRetainedBusiness]=useState('');
  const [priorReference,setPriorReference]=useState('');
  async function review() {
    if(reviewing||active.current)return;
    contextBeforeReview.current=initialContext;
    setReviewing(true);setError(undefined);setReviewed(undefined);
    try {const value=await reviewContext();if(life.current?.signal.aborted)return;setReviewed(value);}
    catch(failure) {if(life.current?.signal.aborted)return;if(privateRecordUnavailable(failure)){onDenied(failure);return;}setError(failure);}
    finally {if(!life.current?.signal.aborted)setReviewing(false);}
  }
  function adopt() {
    if(active.current||!reviewed||!canAdoptReviewed)return;
    if(!reviewedHasDestination)setBusiness('');
    observedContext.current=contextBeforeReview.current;
    setContext(reviewed);
    priorSubmission.current=retained.current??priorSubmission.current;
    setRetainedBusiness(priorSubmission.current?.body.organization_id??'');
    setPriorReference(priorSubmission.current?.body.operation_id??'');
    retained.current=null;
    setReference('');
    setResult(undefined);
    setError(undefined);
    setNeedsReview(false);
    setReviewed(undefined);
    setReceiptMissing(false);
    setReceiptError(undefined);
    setPermission(false);
  }
  const [symptoms,setSymptoms]=useState('');const [modifications,setModifications]=useState('');
  const [business,setBusiness]=useState('');const [choice,setChoice]=useState('limited_maintenance');const [permission,setPermission]=useState(false);const [safe,setSafe]=useState(false);
  const fileInput=useRef<HTMLInputElement>(null);
  const [files,setFiles]=useState<File[]>([]);const [invalid,setInvalid]=useState(false);
  const filesValid=validPhotos(files);
  const [pending,setPending]=useState(false);const [reference,setReference]=useState('');const [error,setError]=useState<unknown>();const [result,setResult]=useState<MaintenanceResultV1>();
  const priorSubmission=useRef<Submission|null>(null);
  const retained=useRef<Submission|null>(null);const life=useRef<AbortController|null>(null);const active=useRef(false);
  useEffect(()=>{life.current=new AbortController();return ()=>life.current?.abort();},[]);
  const [admissionAttempted,setAdmissionAttempted]=useState(false);
  const [receiptMissing,setReceiptMissing]=useState(false);
  const [receiptError,setReceiptError]=useState<unknown>();
  async function resolveOperation(close=false) {
    const submission=retained.current??priorSubmission.current;
    const signal=life.current?.signal;
    if(!submission||!signal||signal.aborted||active.current||reviewing)return;
    const binding=receiptBinding(submission.body);
    active.current=true;
    setPending(true);
    setError(undefined);
    setReceiptError(undefined);
    if(!close)setReceiptMissing(false);
    try {
      const answer=await lookupReceipt(scope,binding,signal,close);
      if(signal.aborted)return;
      if('closed' in answer) {
        if(!close||answer.closed!==true||answer.operation_id!==binding.operation_id||
          answer.organization_id!==binding.organization_id)throw new Error('response_scope');
        retained.current=null;
        priorSubmission.current=null;
        setReference('');
        setAdmissionAttempted(false);
        setRetainedBusiness('');
        setReviewLimitReached(false);
        setPriorReference('');
        setBusiness('');
        setPermission(false);
        setContext(reviewed??initialContext);
        observedContext.current=initialContext;
        setNeedsReview(false);
        setReviewed(undefined);
        setResult(undefined);
      } else {
        if(answer.state!=='submitted'||!validResultReceipt(answer)||
          !submission.bindings.some(value=>matchesReceipt(answer,receiptBinding(value))))throw new Error('response_scope');
        retained.current=null;
        priorSubmission.current=null;
        setResult(answer);
        setNeedsReview(false);
        setFiles([]);
      }
      setReceiptMissing(false);
      onOperationChange?.([]);
      onWatchLockChange?.(false);
    } catch(failure) {
      if(signal.aborted)return;
      if(failure instanceof ApiError&&[401,403].includes(failure.status)) {
        onDenied(failure);
      } else if(!close&&isMissingReceipt(failure)) {
        setReceiptMissing(true);
      } else {
        setReceiptError(failure);
      }
    } finally {
      active.current=false;
      if(!signal.aborted)setPending(false);
    }
  }
  // An empty draft has no destination scope to retain. Follow current eligibility
  // until the buyer selects a destination and can review its revisions.
  const followsCurrentContext=!business&&adoptedContext.destinations.length===0;
  const context=followsCurrentContext?initialContext:adoptedContext;
  const destinations=context.destinations.filter(item=>!retainedBusiness||item.organization_id===retainedBusiness);
  const destination=destinations.find(item=>item.organization_id===business);
  const reviewedHasDestination=reviewed?.destinations.some(item=>item.organization_id===business)??false;
  const canAdoptReviewed=!reviewLimitReached&&(reviewedHasDestination||
    (!reference&&!priorReference&&!!reviewed?.destinations.length));
  const [photoUploadFailed,setPhotoUploadFailed]=useState(false);
  function discardPhotos() {
    if(active.current||!retained.current||retained.current.requestAttempted||priorSubmission.current)return;
    retained.current=null;
    setReference('');
    setFiles([]);
    if(fileInput.current)fileInput.current.value='';
    setSafe(false);
    setInvalid(false);
    setError(undefined);
    setPhotoUploadFailed(false);
    onOperationChange?.([]);
    onWatchLockChange?.(false);
  }
  if(result?.state==='submitted')return <Card>
    <p role="status">{t('requestSubmitted')}</p>
    <SubmittedScope receipt={result} destinations={context.destinations}/><ConfirmationStatus scope={scope} receipt={result}/><OpeningConsent key={openingEpoch} scope={scope} receipt={result} blocked={openingBlocked} journal={openingJournal}/>
  </Card>;
  const locked=needsReview||pending||!!reference;
  async function submit() {
    const signal=life.current?.signal;if(!signal||signal.aborted||active.current||needsReview)return;
    const retrying=!!retained.current;
    if(!retrying) {
      const latestContext=observedContext.current===initialContext?context:initialContext;
      const latest=latestContext.destinations.find(item=>item.organization_id===business);
      if(!destination)return;
      if(latestContext.watch_revision!==context.watch_revision||!latest||
        latest.brand_id!==destination.brand_id||latest.capability_revision!==destination.capability_revision||
        latest.policy_revision!==destination.policy_revision||!latest.interventions.includes(choice as 'limited_maintenance'|'overhaul_assessment')) {
        setNeedsReview(true);
        return;
      }
    }
    if(!retrying&&(!filesValid||!symptoms.trim()||symptoms.length>2000||modifications.length>2000||!permission||(files.length>0&&!safe)||!destination?.interventions.includes(choice as 'limited_maintenance'|'overhaul_assessment'))){setInvalid(true);return;}
    onWatchLockChange?.(true);
    active.current=true;setPending(true);setError(undefined);setPhotoUploadFailed(false);
    try {
      if(!retained.current&&destination) {
        const body:import('@contracts/contracts-service/maintenance/v1').MaintenanceRequestV1={schema_version:'service.maintenance.v1',operation_id:priorSubmission.current?.body.operation_id??crypto.randomUUID(),actor_id:context.actor_id,subject_id:context.subject_id,watch_id:context.watch_id,watch_revision:context.watch_revision,organization_id:business,brand_id:destination.brand_id,capability_revision:destination.capability_revision,policy_revision:destination.policy_revision,expected_revision:0,intervention:choice as 'limited_maintenance'|'overhaul_assessment',reported_symptoms:symptoms,known_modifications:modifications,photo_refs:[],limited_assessment_permission:permission};
        retained.current=priorSubmission.current?priorSubmission.current.revise(body):new Submission(body,await Promise.all(files.map(async file=>({operation_id:crypto.randomUUID(),media_type:file.type,content_base64:await encoded(file)}))));
      }
      if(!retained.current)return;
      setReviewLimitReached(retained.current.reviewLimitReached===true);
      setReference(retained.current.body.operation_id);
      const answer=await retained.current.run({upload:async(photo,body,uploadSignal)=>{
        const payload:MaintenancePhotoV1={
          ...photo, request_operation_id:body.operation_id, watch_id:body.watch_id,
          organization_id:body.organization_id, brand_id:body.brand_id, intervention:body.intervention,
          watch_revision:body.watch_revision, capability_revision:body.capability_revision,
          policy_revision:body.policy_revision, safe_photo_declared:safe,
        };
        return call<unknown>(scope,'maintenance/photos',{
          method:'POST', signal:uploadSignal, headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload),
        });
      },lookup:(body,lookupSignal)=>lookupReceipt(scope,body,lookupSignal),submit:(body,submitSignal)=>{
        setAdmissionAttempted(true);
        onOperationChange?.(retained.current?.bindings.map(receiptBinding)??[receiptBinding(body)]);
        return call(scope,'maintenance/requests',{method:'POST',signal:submitSignal,headers:{'Content-Type':'application/json','Idempotency-Key':body.operation_id},body:JSON.stringify(body)});
      }},signal);
      if(!signal.aborted){if(answer.state==='denied'){if(!retrying&&!priorSubmission.current)onOperationChange?.([]);retained.current=null;life.current?.abort();onDenied(new ApiError(403,'denied',''));return;}setResult(answer);if(answer.state==='submitted'){onOperationChange?.([]);setFiles([]);onWatchLockChange?.(false);}if(answer.state==='stale')setNeedsReview(true);}
    } catch(failure) {if(!signal.aborted){if(failure instanceof ContextReviewRequired){setNeedsReview(true);return;}
      if(failure instanceof ApiError&&['destination_ineligible','stale_photo_scope'].includes(failure.code)&&retained.current&&!retained.current.requestAttempted&&!priorSubmission.current){
        // Only uploads were attempted. Keep the local files for the newly reviewed destination.
        retained.current=null;
        setReference('');
        setPermission(false);
        setNeedsReview(true);
        onWatchLockChange?.(false);
        return;
      }if(failure instanceof ApiError&&[401,403].includes(failure.status)){if(!retrying&&!priorSubmission.current)onOperationChange?.([]);retained.current=null;life.current?.abort();onDenied(failure);return;}if(!retrying&&!priorSubmission.current&&failure instanceof ApiError&&[400,422,428].includes(failure.status)){retained.current=null;setReference('');onOperationChange?.([]);}if(!retained.current&&!priorSubmission.current)onWatchLockChange?.(false);
        setPhotoUploadFailed(!!retained.current&&!retained.current.requestAttempted&&!priorSubmission.current);
        setError(failure);}} finally {active.current=false;if(!signal.aborted)setPending(false);}
  }
  const reviewReference=reference||priorReference;
  const canResolveReceipt=!!reviewReference&&(needsReview||admissionAttempted);
  const commitmentConflict = error instanceof ApiError && error.code === 'watch_committed';
  const photosUnavailable = error instanceof ApiError && error.code === 'photo_unavailable';
  const receiptActions=canResolveReceipt&&<>
    {!!receiptError&&<Recovery error={receiptError} retry={()=>void resolveOperation(receiptMissing)}/>}
    <Button disabled={pending||reviewing} onClick={()=>void resolveOperation()}>{t('checkRequestReceipt')}</Button>
    {(receiptMissing||!!receiptError)&&<SupportLink/>}
    {receiptMissing&&<><p role="status">{t('receiptMissing')}</p><Button disabled={pending||reviewing} onClick={()=>void resolveOperation(true)}>{t('closeUnconfirmed')}</Button></>}
  </>;
  const messages={placeholder:t('chooseOrganization'),filter:t('organization'),emptyTitle:t('empty'),emptyBody:t('emptyBody'),close:t('close'),loading:t('loading'),errorTitle:t('unavailable'),errorBody:t('unavailableBody'),retry:t('retry')};
  return <Card><form onSubmit={event=>{event.preventDefault();void submit();}}><fieldset disabled={locked}>
    <Select label={t('organization')} value={business} onValueChange={value=>{if(value!==business){if(followsCurrentContext){setContext(context);observedContext.current=initialContext;}setBusiness(value);setPermission(false);}}} options={destinations.map(item=>({value:item.organization_id,label:item.display_name}))} messages={messages}/>
    <Textarea label={t('symptoms')} required value={symptoms} onValueChange={setSymptoms}/><Textarea label={t('modifications')} value={modifications} onValueChange={setModifications}/>
    <Segmented label={t('scope')} value={choice} onValueChange={value=>{if(value!==choice){setChoice(value);setPermission(false);}}} options={[{value:'limited_maintenance',label:t('limited'),disabled:!destination?.interventions.includes('limited_maintenance')},{value:'overhaul_assessment',label:t('overhaul'),disabled:!destination?.interventions.includes('overhaul_assessment')}]}/>
    <Checkbox label={t('permission')} checked={permission} onCheckedChange={setPermission}/><Checkbox label={t('safePhoto')} checked={safe} onCheckedChange={setSafe}/>
    <Label htmlFor={fileId}>{t('privateFile')}</Label><input ref={fileInput} className="bt-input" id={fileId} type="file" disabled={!!retainedBusiness} multiple accept="image/jpeg,image/png,image/webp" onChange={event=>{const next=Array.from(event.target.files??[]);setFiles(next);setSafe(false);setInvalid(!validPhotos(next));}}/>
    {retainedBusiness&&<p>{t('retainedDestination')}</p>}<p>{t('filesLimit')}</p><p>{t('selectedFiles')}: {formatNumber(files.length,locale)}</p>{invalid&&<p role="alert">{t('invalid')}</p>}
    <Button type="submit" disabled={!destination||!permission||(files.length>0&&!safe)||!filesValid}>{t('submitRequest')}</Button></fieldset></form>
    {photoUploadFailed&&!pending&&<Button onClick={discardPhotos}>{t('discardPhotoAttempt')}</Button>}
    {initialContext.destinations.length===0&&!contextUnavailable&&<State title={t('emptyDestinations')} body={t('noCurrentDestinations')}><Button onClick={refreshContext}>{t('refreshDestinations')}</Button></State>}{commitmentConflict
      ? <State title={t('watchCommitted')} body={t('watchCommittedBody')}>
          <Button disabled={pending} onClick={()=>void submit()}>{t('retry')}</Button>
        </State>
      : photosUnavailable
      ? <State kind="error" title={t('photosUnavailable')} body={t('photosUnavailableBody')}>
          <Button disabled={pending} onClick={()=>void submit()}>{t('preparePhotosAgain')}</Button>
        </State>
      : !!error&&<Recovery error={error} retry={()=>void (needsReview?review():submit())}/>} {needsReview&&<section aria-live="polite"><p>{t(reviewLimitReached?'reviewLimitReached':reviewReference?'reviewContextBody':'reviewChangedScope')}</p><Button disabled={reviewing||pending} onClick={()=>void review()}>{t('reviewContext')}</Button>{reviewing&&<p role="status">{t('loading')}</p>}{reviewed&&<><p>{t('watchRevision')}: {formatNumber(reviewed.watch_revision,locale)}</p><ul>{reviewed.destinations.map(item=><li key={item.organization_id}>{item.display_name} · {t('capabilityRevision')}: {formatNumber(item.capability_revision,locale)} · {t('policyRevision')}: {formatNumber(item.policy_revision,locale)} · {item.interventions.map(value=>t(value==='limited_maintenance'?'limited':'overhaul')).join(' / ')}</li>)}</ul>{!reviewedHasDestination&&<State title={t('unavailable')} body={t(reviewReference?'destinationUnavailable':canAdoptReviewed?'chooseReplacement':'noCurrentDestinations')}/>}<Button disabled={pending||!canAdoptReviewed} onClick={adopt}>{t('adoptContext')}</Button></>}
      {receiptActions}
    </section>}{!needsReview&&receiptActions}<p role="status">{pending?t('pending'):result?.state==='denied'?t('deniedBody'):result?.state==='stale'?t('stale'):reference?t('retrySame'):''}</p>{reviewReference&&<bdi>{reviewReference}</bdi>}{result?.state==='pending'&&reference&&<Button disabled={pending} onClick={()=>void submit()}>{t('retry')}</Button>}</Card>;
}

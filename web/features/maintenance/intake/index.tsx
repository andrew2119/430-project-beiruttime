'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, Card, Input, Select, State, Textarea, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { refreshSession, useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { usePageRead } from '@/lib/page-speed/read';
import type { AssessmentCustodyV1, IntakeCommandV1, IntakeOperationCommandV1, IntakeOperationReceiptV1 } from '@contracts/contracts-service/intake/v1';
import { call, Recovery, useCopy, useWrite, type IntakeWriteLock } from '../common';
import { privateRecordUnavailable } from '../private-read';
import { isMissingReceipt, isReference } from '../submission';
import MaintenanceSignIn from '../sign-in';
import { useMountedIntakeRead, type IntakeRead } from './mounted-read';
import EvidencePanel from './evidence';
import {DiagnosisEditor} from './diagnosis-editor';
import {OpeningReview} from './opening-review';
import {ScopedOperation,ScopedOperationResolution,useScopedOperationJournal,type OperationBinding,type OperationJournal} from '../scoped-operation';
import { detailRead, intakeRead, type Detail } from './reads';

export default function IntakeBoundary({screen,mountedRead=false}: {screen: 'intake';mountedRead?:boolean}) {
  const session=useSession();const {t}=useCopy();
  const [error,setError]=useState<unknown>();const [ready,setReady]=useState(false);
  const operation=useScopedOperationJournal(session?.principal.actor?.subject_id);
  const restore=()=>{setReady(false);setError(undefined);refreshSession().then(()=>setReady(true),e=>{setReady(true);setError(e);});};
  useEffect(()=>{refreshSession().then(()=>setReady(true),e=>{setReady(true);setError(e);});},[]);
  if(session)return <Intake key={session.access_fingerprint} useRead={mountedRead?useMountedIntakeRead:usePageRead} scope={session.access_fingerprint} organizations={session.principal.organizations}
    assessmentOperation={operation.binding} assessmentJournal={operation.journal}/>;
  return <PageFrame><PageHeader title={t(screen)}/><PageBody>{!ready?<PageLoading label={t('loading')}/>:error?<Recovery error={error} retry={restore}/>:<State title={t('signIn')} body={t('signInBody')}><MaintenanceSignIn/></State>}</PageBody></PageFrame>;
}
type ReceiptKind = IntakeOperationReceiptV1["kind"];
type WriteBinding = {reference:string; recordId?:string;orderId:string;uncertain?:boolean;expectedRevision:number};
type IntakeLock = (kind:ReceiptKind, locked:boolean, reference?:string, recordId?:string, uncertain?:boolean, expectedRevision?:number,orderId?:string)=>void;

function Intake({scope,organizations,useRead=usePageRead,assessmentOperation,assessmentJournal}: {scope:string;organizations:string[];
  useRead?:IntakeRead;assessmentOperation:OperationBinding|null;assessmentJournal:OperationJournal}) {
  const {t,locale}=useCopy();const [organization,setOrganization]=useState(assessmentOperation?.organization??'');const [accessError,setAccessError]=useState<unknown>();
  const writes=useRef(new Map<ReceiptKind,WriteBinding>());
  const [pendingWrites,setPendingWrites]=useState(new Map<ReceiptKind,WriteBinding>());
  const [readGeneration,setReadGeneration]=useState('');
  const [assessmentResolution,setAssessmentResolution]=useState<'recorded'|'closed'>();
  const trackAssessment:OperationJournal={begin(binding){
    if(!assessmentJournal.begin(binding))return false;
    setAssessmentResolution(undefined);return true;
  },resolve:assessmentJournal.resolve};
  const navigationLocked=pendingWrites.size>0||!!assessmentOperation;
  const [receipt,setReceipt]=useState<IntakeOperationReceiptV1>();
  const [reopen,setReopen]=useState('');
  const [closedSave,setClosedSave]=useState<string>();
  const [closedEvidence,setClosedEvidence]=useState<string>();
  const [evidenceRefresh,setEvidenceRefresh]=useState<{recordId:string; reference:string}>();
  const resolvedRecord=useRef<string|null>(null);
  function lock(kind:ReceiptKind,locked:boolean,reference?:string,recordId?:string,uncertain?:boolean,expectedRevision?:number,orderId?:string) {
    if(locked) {
      if(!reference||!orderId||expectedRevision===undefined)return;
      writes.current.set(kind,{reference,recordId,orderId,expectedRevision,...(uncertain?{uncertain}:{})});
    } else writes.current.delete(kind);
    setPendingWrites(new Map(writes.current));
    if(writes.current.size===0&&resolvedRecord.current!==null) {
      setReopen(resolvedRecord.current);
      resolvedRecord.current=null;
      // Reload the acknowledged revision and discard the resolved command state.
      setReadGeneration(crypto.randomUUID());
      setAccessError(undefined);
    }
  }
  function denied(error:unknown) {
    setReadGeneration(crypto.randomUUID());
    setReceipt(undefined);
    setAccessError(error);
  }
  function resolveEvidence(kind:ReceiptKind,binding:WriteBinding) {
    if(kind!=='evidence'||accessError||!binding.recordId)return false;
    setEvidenceRefresh({recordId:binding.recordId,reference:binding.reference});
    lock(kind,false);
    return true;
  }
  const messages={placeholder:t('chooseOrganization'),filter:t('organization'),emptyTitle:t('empty'),emptyBody:t('emptyBody'),close:t('close'),loading:t('loading'),errorTitle:t('unavailable'),errorBody:t('unavailableBody'),retry:t('retry')};
  return <PageFrame><PageHeader title={t('intake')} lead={t('scopePolicy')}/><PageBody>
    <Select label={t('organization')} value={organization} disabled={navigationLocked} onValueChange={value=>{if(!writes.current.size){setReceipt(undefined);setReopen('');setOrganization(value);}}} options={organizations.map(id=>({value:id,label:id}))} messages={messages}/>
    {receipt&&<p role="status">{t(receipt.kind==='evidence'?'evidenceRecovered':'intakeRecovered')} {formatNumber(receipt.revision,locale)} · <bdi>{receipt.record_id}</bdi></p>}
    {Array.from(pendingWrites,([kind,binding])=>(accessError||binding.uncertain)&&
      <IntakeReceiptRecovery key={binding.reference} scope={scope} organization={organization} kind={kind} binding={binding} onDenied={denied} onClosed={()=>{
        if(!accessError) {
          if(kind==='save')setClosedSave(binding.reference);
          else setClosedEvidence(binding.reference);
          lock(kind,false);
          return;
        }
        resolvedRecord.current??=binding.recordId??'';
        if(accessError&&!resolvedRecord.current&&writes.current.size===1)setOrganization('');
        lock(kind,false);
      }} onRecovered={result=>{
        setReceipt(result);
        if(resolveEvidence(kind,binding))return;
        resolvedRecord.current=result.record_id;
        lock(kind,false);
      }}/>)}
    {assessmentResolution&&<ScopedOperationResolution outcome={assessmentResolution}/>}
    {assessmentOperation&&<ScopedOperation key={assessmentOperation.operation_id} scope={scope} binding={assessmentOperation}
      onResolved={outcome=>{if(!assessmentJournal.resolve(assessmentOperation))return;setAssessmentResolution(outcome);setReopen(assessmentOperation.kind==='diagnosis'?assessmentOperation.record:reopen);
        setReadGeneration(crypto.randomUUID());setAccessError(undefined);}}/>}
    {accessError?(pendingWrites.size===0&&!assessmentOperation&&<Recovery error={accessError} retry={()=>{setOrganization('');setReopen('');setAccessError(undefined);}}/>)
      :organization?<Records useRead={useRead} closedSave={closedSave} closedEvidence={closedEvidence} key={organization+readGeneration} initialId={reopen} evidenceRefresh={evidenceRefresh} readGeneration={readGeneration} scope={scope} organization={organization} onDenied={denied} lock={lock} assessmentOperation={assessmentOperation} assessmentJournal={trackAssessment} navigationLocked={navigationLocked} isLocked={()=>writes.current.size>0||!!assessmentOperation}/>:<State title={t('chooseOrganization')} body={t('readFirst')}/>}
  </PageBody></PageFrame>;
}

function IntakeReceiptRecovery({scope,organization,kind,binding,onRecovered,onClosed,onDenied}:{
  scope:string; organization:string; kind:ReceiptKind; binding:WriteBinding; onDenied:(error:unknown)=>void; onRecovered:(receipt:IntakeOperationReceiptV1)=>void; onClosed:()=>void;
}) {
  const {t}=useCopy();
  const [pending,setPending]=useState(false);
  const [error,setError]=useState<unknown>();
  const active=useRef<AbortController|null>(null);
  useEffect(()=>()=>active.current?.abort(),[]);
  async function recover(close=false) {
    if(active.current)return;
    const controller=new AbortController();
    active.current=controller;
    setPending(true);
    setError(undefined);
    try {
      const command: IntakeOperationCommandV1 = {
        action: close ? 'close' : 'lookup',
        operation_id: binding.reference,
      };
      const receipt=await call<IntakeOperationReceiptV1|{state:"closed";operation_id:string;organization_id:string}>(scope,
        `intake/records?organization_id=${encodeURIComponent(organization)}`,
        {signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
      if(controller.signal.aborted)return;
      if('state' in receipt) {
        if(!close||receipt.state!=='closed'||receipt.operation_id!==binding.reference||
          receipt.organization_id!==organization)throw new Error('response_scope');
        onClosed();
        return;
      }
      if(receipt.operation_id!==binding.reference||receipt.organization_id!==organization||receipt.kind!==kind||receipt.order_id!==binding.orderId
        ||!isReference(receipt.record_id)||(binding.recordId&&receipt.record_id!==binding.recordId)
        ||!Number.isSafeInteger(receipt.revision)||receipt.revision!==binding.expectedRevision)throw new Error('response_scope');
      onRecovered(receipt);
    } catch(failure) {
      if(!controller.signal.aborted) {
        setError(failure);
        if(failure instanceof ApiError&&[401,403].includes(failure.status))onDenied(failure);
      }
    } finally {
      active.current=null;
      if(!controller.signal.aborted)setPending(false);
    }
  }
  const missing=isMissingReceipt(error);
  return <Card><p role="status">{t(pending?'pending':missing?'intakeReceiptMissing':'retrySame')}</p><bdi>{binding.reference}</bdi>
    {!!error&&!missing?<Recovery error={error} retry={()=>void recover()}/>:<Button disabled={pending} onClick={()=>void recover()}>{t('checkIntakeReceipt')}</Button>}
    {missing&&<Button disabled={pending} onClick={()=>void recover(true)}>{t('closeUnconfirmed')}</Button>}
  </Card>;
}
function Records({useRead=usePageRead,closedSave,closedEvidence,initialId,readGeneration='',evidenceRefresh,scope,organization,onDenied,lock,assessmentOperation,assessmentJournal,navigationLocked=false,isLocked=()=>false}:{useRead?:IntakeRead;scope:string;organization:string;onDenied:(error:unknown)=>void;lock:IntakeLock;assessmentOperation:OperationBinding|null;assessmentJournal:OperationJournal;navigationLocked?:boolean;isLocked?:()=>boolean;closedSave?:string;closedEvidence?:string;readGeneration?:string;initialId?:string;evidenceRefresh?:{recordId:string;reference:string}}) {
  const {t,locale}=useCopy();const [offset,setOffset]=useState(0);const [id,setId]=useState(initialId||undefined);
  const rows=useRead(intakeRead(scope,organization,offset,readGeneration));
  const refetchRows=rows.refetch;
  useEffect(()=>{if(evidenceRefresh)void refetchRows();},[evidenceRefresh,refetchRows]);
  useEffect(()=>{if(rows.error instanceof ApiError&&[401,403].includes(rows.error.status))onDenied(rows.error);},[rows.error,onDenied]);
  const denied=rows.error instanceof ApiError&&[401,403].includes(rows.error.status);
  return <><Card><h2>{t('queue')}</h2><Button disabled={navigationLocked||!rows.data||denied} onClick={()=>{if(rows.data&&!denied&&!isLocked())setId('');}}>{t('newRecord')}</Button><Button onClick={()=>void rows.refetch()}>{t('refresh')}</Button>
    {rows.isPending&&(rows.data?<p role="status">{t('loading')}</p>:<PageLoading label={t('loading')}/>)}{!!rows.error&&<Recovery error={rows.error} retry={()=>void rows.refetch()}/>} {rows.data&&!denied&&<><p>{t('total')}: {formatNumber(rows.data!.total,locale)}</p>{rows.data!.items.length===0&&<State title={t('empty')} body={t('emptyBody')}/>}<ul>{rows.data!.items.map(row=><li key={row.id}><p><bdi>{row.order_id}</bdi> · {t(row.state==='received'?'historicalReceipt':row.state)}</p><Button disabled={navigationLocked} onClick={()=>{if(!isLocked())setId(row.id);}}>{t('open')}</Button></li>)}</ul><Button disabled={offset===0} onClick={()=>setOffset(n=>Math.max(0,n-50))}>{t('previousPage')}</Button><Button disabled={rows.data!.next_offset===null} onClick={()=>setOffset(rows.data!.next_offset!)}>{t('nextPage')}</Button></>}
    </Card>{id!==undefined&&!denied&&<Editor useRead={useRead} closedSave={closedSave} closedEvidence={closedEvidence} evidenceRefresh={evidenceRefresh?.recordId===id?evidenceRefresh.reference:undefined} readGeneration={readGeneration} lock={lock} onDenied={onDenied} assessmentOperation={assessmentOperation} assessmentJournal={assessmentJournal} key={id||'new'} scope={scope} organization={organization} id={id} saved={value=>{setId(value);void rows.refetch();}}/>}</>;
}
function Editor({useRead=usePageRead,closedSave,closedEvidence,readGeneration='',evidenceRefresh,scope,organization,id,saved,onDenied,lock,assessmentOperation,assessmentJournal}:{useRead?:IntakeRead;assessmentOperation:OperationBinding|null;assessmentJournal:OperationJournal;closedSave?:string;closedEvidence?:string;readGeneration?:string;evidenceRefresh?:string;lock:IntakeLock;scope:string;organization:string;id:string;onDenied:(error:unknown)=>void;saved:(id:string)=>void}) {
  const {t}=useCopy();const read=useRead(id?detailRead(scope,organization,id,readGeneration):null);
  const refetchDetail=read.refetch;
  useEffect(()=>{if(evidenceRefresh)void refetchDetail();},[evidenceRefresh,refetchDetail]);
  useEffect(()=>{if(privateRecordUnavailable(read.error))onDenied(read.error);},[read.error,onDenied]);
  if(privateRecordUnavailable(read.error))return <Recovery error={read.error} retry={()=>void read.refetch()}/>;
  if(id&&!read.data&&read.isPending)return <PageLoading label={t('loading')}/>;
  if(id&&!read.data&&read.error)return <Recovery error={read.error} retry={()=>void read.refetch()}/>;
  const checkingCustody=read.isFetching||read.isPaused;
  const current=read.data&&read.data.custody_receipt_id&&(checkingCustody||read.error)
    ? {...read.data,custody_verification:checkingCustody?'checking' as const:'unavailable' as const,
      diagnosis_allowed:false,assessment_allowed:false,current_assessment_custody:undefined,
      current_opening_acceptance:undefined,current_opening_fee_minor:undefined,receipt_revision_for_review:undefined,
      private_record:{...read.data.private_record,assessed_issue:''}}
    : read.data;
  return <>{id&&<Button onClick={()=>void read.refetch()}>{t('refresh')}</Button>}{id&&read.error&&<Recovery error={read.error} retry={()=>void read.refetch()}/>}<IntakeForm closedSave={closedSave} onLockChange={(locked,reference,uncertain,expectedRevision,orderId)=>lock('save',locked,reference,id||undefined,uncertain,expectedRevision,orderId)} onDenied={onDenied} scope={scope} organization={organization} data={id?current:undefined} refresh={()=>void read.refetch()} saved={value=>{if(id)read.refetch();saved(value);}}/>{id&&read.data&&<DiagnosisEditor scope={scope} organization={organization} caseId={id}
    intakeRevision={read.data.revision} available={current?.diagnosis_allowed===true} inherited={assessmentOperation} onDenied={onDenied} journal={assessmentJournal}/>}
    {id&&current?.state==='received'&&current.custody_receipt_id&&<OpeningReview key={`${current.order_id}:${current.custody_receipt_id}:${current.revision}`}
      scope={scope} organization={organization} orderId={current.order_id} receiptId={current.custody_receipt_id}
      blocked={!!assessmentOperation||current.custody_verification!=='current'} journal={assessmentJournal} onDenied={onDenied} onRecorded={()=>void read.refetch()}/>}
    {id&&read.data&&<EvidencePanel useRead={useRead} key={evidenceRefresh} closedReference={closedEvidence} readGeneration={readGeneration} onLockChange={(locked,reference,uncertain,expectedRevision)=>lock('evidence',locked,reference,id,uncertain,expectedRevision,read.data?.order_id)} onDenied={onDenied} scope={scope} organization={organization} id={id} revision={read.data.revision} readOnly={read.data.private_record.currency!=='USD'} changed={()=>void read.refetch()}/>}</>;
}
const fields=['serial','reference','movement','received_condition','accessories','reported_issue','assessed_issue'] as const;
const checks=['diagnostic_opening_permission','no_polish_acknowledged','fee_acknowledged'] as const;

function intakeValues(data:Detail):IntakeCommandV1 {
  return {...data.private_record,order_id:data.order_id,custody_receipt_id:data.custody_receipt_id};
}

function CustodyStatus({data,refresh}:{data:Detail;refresh?:()=>void}) {
  const {t}=useCopy();
  const verification=data.custody_verification;
  if(verification==='checking')return <p role="status">{t('checkingCustody')}</p>;
  if(verification==='current')return <p role="status">{t('received')}</p>;
  if(verification==='awaiting_intake')return <p role="status">{t('awaiting_intake')}</p>;
  return <State kind="error" title={t(verification==='unconfirmed'?'custodyUnconfirmed':'custodyUnavailable')}
    body={t(verification==='unconfirmed'?'custodyUnconfirmedBody':'custodyUnavailableBody')}>
    {verification==='unavailable'&&data.custody_receipt_id&&<p>{t('historicalReceipt')}</p>}
    <Button onClick={refresh}>{t('refreshCustody')}</Button>
  </State>;
}

function sameAssessmentCustody(reviewed:AssessmentCustodyV1,current?:AssessmentCustodyV1) {
  return !!current&&reviewed.watch_id===current.watch_id&&reviewed.watch_revision===current.watch_revision
    &&reviewed.receipt_id===current.receipt_id&&reviewed.receipt_revision===current.receipt_revision
    &&reviewed.incident_revision===current.incident_revision;
}

function IntakeForm({scope,organization,data,saved,onDenied,refresh,onLockChange,closedSave}:{closedSave?:string;onLockChange?:IntakeWriteLock;scope:string;organization:string;data?:Detail;refresh?:()=>void;onDenied:(error:unknown)=>void;saved:(id:string)=>void}) {
  const {t,locale}=useCopy();const command=useWrite(scope,onDenied,onLockChange,closedSave);
  const attemptedFinding=useRef('');
  const [baseline,setBaseline]=useState(()=>data?{revision:data.revision,values:intakeValues(data)}:undefined);
  const draftRevision=baseline?.revision;
  const legacy=data?.private_record.currency!==undefined&&data.private_record.currency!=='USD';
  const [form,setForm]=useState<IntakeCommandV1>(()=>data?intakeValues(data):{order_id:'',custody_receipt_id:null,serial:'',reference:'',movement:'',received_condition:'',accessories:'',reported_issue:'',assessed_issue:'',diagnostic_opening_permission:false,no_polish_acknowledged:false,fee_acknowledged:false,fee_minor:0,currency:'USD'});
  const needsReview=!!data&&data.revision>(draftRevision??0);
  const custodyUnverified=!!data?.custody_receipt_id&&data.custody_verification!=='current';
  const current=needsReview&&data?intakeValues(data):undefined;
  if(current&&custodyUnverified)current.assessed_issue='';
  const original=baseline?.values;
  const findingChanged=data?.custody_verification==='current'&&data.revision===draftRevision
    &&data.private_record.assessed_issue!==original?.assessed_issue;
  const reviewedCustody=form.reviewed_assessment_custody;
  const currentAssessmentCustody=data?.current_assessment_custody;
  const staleFinding=!!reviewedCustody&&!sameAssessmentCustody(reviewedCustody,currentAssessmentCustody);
  const withholdFinding=custodyUnverified||findingChanged||staleFinding;
  const currentFinding=custodyUnverified?'':data?.private_record.assessed_issue??'';
  const conflicts=current&&original?fields.filter(field=>
    (field!=='assessed_issue'||!withholdFinding)&&form[field]!==original[field]&&current[field]!==original[field]&&form[field]!==current[field]):[];
  function editField(field:typeof fields[number], value:string) {
    if(field==='assessed_issue') {
      if(custodyUnverified||data?.assessment_allowed!==true||!currentAssessmentCustody)return;
      if(findingChanged&&baseline) {
        setBaseline({...baseline,values:{...baseline.values,assessed_issue:currentFinding}});
      }
    }
    setForm(previous=>({...previous,[field]:value,
      ...(field==='assessed_issue'?{reviewed_assessment_custody:currentAssessmentCustody}:{})}));
  }
  function reconcile() {
    if(!data||!current||!original||command.locked)return;
    const merged={...current};
    for(const field of fields) {
      if(field==='assessed_issue'&&withholdFinding)continue;
      if(form[field]!==original[field]&&current[field]===original[field])merged[field]=form[field];
    }
    if(!withholdFinding&&merged.assessed_issue!==current.assessed_issue) {
      merged.reviewed_assessment_custody=reviewedCustody;
    }
    setForm(merged);
    setBaseline({revision:data.revision,values:current});
  }
  const [replacement,setReplacement]=useState<{revision:number; custody:AssessmentCustodyV1}>();
  const [reviewPending,setReviewPending]=useState(false);
  const [reviewError,setReviewError]=useState<unknown>();
  const reviewRequest=useRef<AbortController|null>(null);
  useEffect(()=>()=>reviewRequest.current?.abort(),[]);
  const replacementId=data?.custody_receipt_id&&form.custody_receipt_id!==data.custody_receipt_id
    ? form.custody_receipt_id : undefined;
  const receiptForReview=replacementId
    ? (replacement?.revision===data?.revision&&replacement?.custody.receipt_id===replacementId
        ? replacement.custody : undefined)
    : data?.receipt_revision_for_review;
  const acceptedReceipt=!!form.reviewed_receipt_revision&&
    sameAssessmentCustody(form.reviewed_receipt_revision,receiptForReview);
  const waitingForCustody=reviewPending||((!!replacementId||custodyUnverified)&&
    (data?.custody_verification==='checking'||!acceptedReceipt));
  function resetReceiptReview() {
    reviewRequest.current?.abort();
    setReviewPending(false);
    setReplacement(undefined);
    setReviewError(undefined);
  }
  async function checkReplacement() {
    if(!data||!isReference(replacementId)||command.locked||needsReview)return;
    resetReceiptReview();
    setForm(previous=>({...previous,reviewed_receipt_revision:undefined}));
    const active=new AbortController();
    reviewRequest.current=active;
    setReviewPending(true);
    const query=new URLSearchParams({organization_id:organization,review_receipt_id:replacementId});
    try {
      const answer=await call<{revision:number;receipt_revision_for_review:AssessmentCustodyV1}>(
        scope,`intake/records/${encodeURIComponent(data.id)}?${query}`,{signal:active.signal});
      if(active.signal.aborted)return;
      const custody=answer.receipt_revision_for_review;
      if(answer.revision!==data.revision||custody?.receipt_id!==replacementId||!isReference(custody.watch_id)||
        !Number.isSafeInteger(custody.receipt_revision)||custody.receipt_revision<1||
        !Number.isSafeInteger(custody.watch_revision)||custody.watch_revision<1||
        !Number.isSafeInteger(custody.incident_revision)||custody.incident_revision<0)throw new Error('response_scope');
      setReplacement({revision:answer.revision,custody});
    } catch(error) {
      if(!active.signal.aborted) {
        setReviewError(error);
        if(privateRecordUnavailable(error))onDenied(error);
      }
    } finally {
      if(!active.signal.aborted)setReviewPending(false);
    }
  }
  function reviewReceiptRevision() {
    if (receiptForReview && !reviewPending && !command.locked && !needsReview) {
      setForm(previous=>({...previous,reviewed_receipt_revision:receiptForReview}));
    }
  }
  async function save() {
    if(legacy||(!command.reference&&(needsReview||waitingForCustody||staleFinding)))return;
    if(!command.reference)attemptedFinding.current=withholdFinding?currentFinding:form.assessed_issue;
    const values={...form,assessed_issue:attemptedFinding.current,currency:'USD' as const};
    const result=await command.save<{id:string;revision:number}>((data?`intake/records/${data.id}`:'intake/records')+'?organization_id='+encodeURIComponent(organization),values,draftRevision);
    if(result){
      const savedValues={...values,reviewed_assessment_custody:undefined,reviewed_receipt_revision:undefined};
      setForm(savedValues);
      setBaseline({revision:result.revision,values:savedValues});
      saved(result.id);
    }
  }
  const offeredAcceptance=data?.current_opening_acceptance;
  const offeredFee=data?.current_opening_fee_minor;
  function recordOpeningAcceptance() {
    if(!offeredAcceptance||offeredFee===undefined||command.locked||needsReview)return;
    setForm({...form,opening_acceptance:offeredAcceptance,diagnostic_opening_permission:true,
      no_polish_acknowledged:true,fee_acknowledged:true,fee_minor:offeredFee});
  }
  function restoreOpeningAcceptance() {
    if(!original||command.locked||needsReview)return;
    setForm({...form,opening_acceptance:original.opening_acceptance,
      diagnostic_opening_permission:original.diagnostic_opening_permission,
      no_polish_acknowledged:original.no_polish_acknowledged,
      fee_acknowledged:original.fee_acknowledged,fee_minor:original.fee_minor});
  }
  if(legacy)return <Card><State title={t('unavailable')} body={t('legacyCurrency')}/><dl>{fields.map(field=><div key={field}><dt>{t(field)}</dt><dd>{field==='assessed_issue'&&withholdFinding?currentFinding:form[field]}</dd></div>)}</dl><p><bdi>{form.currency}</bdi></p></Card>;
  return <Card><h2>{t(data?'intake':'newRecord')}</h2>{data&&<><CustodyStatus data={data} refresh={refresh}/><p>{t(data.diagnosis_allowed?'diagnosisAllowed':'diagnosisNotAllowed')}</p></>}{data&&needsReview&&<section><p>{t('reviewRevision')}</p><dl>{fields.map(field=><div key={field}><dt>{t(field)}</dt><dd>{field==='assessed_issue'?currentFinding:data.private_record[field]}</dd></div>)}<div><dt>{t('custody_receipt_id')}</dt><dd><bdi>{data.custody_receipt_id??t('noReceipt')}</bdi></dd></div>{checks.map(field=><div key={field}><dt>{t(field)}</dt><dd>{t(data.private_record[field]?'yes':'no')}</dd></div>)}</dl><p>{t('recordedFeeDollars')}: {formatNumber(data.private_record.fee_minor/100,locale,{minimumFractionDigits:2,maximumFractionDigits:2})}</p>{conflicts.length>0&&<><p>{t('conflictingNotes')}</p><dl>{conflicts.map(field=><div key={field}><dt>{t(field)} · {t('myDraft')}</dt><dd>{form[field]}</dd></div>)}</dl></>}<Button disabled={command.locked} onClick={reconcile}>{t(conflicts.length?'reconcileConflicts':'reconcileIntake')}</Button></section>}<form autoComplete="off" onSubmit={e=>{e.preventDefault();void save();}}><fieldset disabled={command.locked||needsReview}>
    <Input label={t('order_id')} required readOnly={!!data} value={form.order_id} onValueChange={order_id=>setForm({...form,order_id})}/>
    <Input label={t('custody_receipt_id')} readOnly={!!data?.custody_receipt_id&&data.custody_verification!=='unconfirmed'} value={form.custody_receipt_id??''} onValueChange={value=>{resetReceiptReview();setForm({...form,custody_receipt_id:value.toLowerCase()||null,reviewed_receipt_revision:undefined});}}/><p>{t('custodyHint')}</p>
    {replacementId&&<Button type="button" disabled={reviewPending||!isReference(replacementId)} onClick={()=>void checkReplacement()}>{t('checkReplacementReceipt')}</Button>}
    {reviewPending&&<p role="status">{t('loading')}</p>}
    {!!reviewError&&<Recovery error={reviewError} retry={()=>void checkReplacement()}/>}
    {receiptForReview&&<section>
      <p>{t('newerReceiptRevision')} <bdi>{receiptForReview.receipt_id}</bdi> · {formatNumber(receiptForReview.receipt_revision,locale)}</p>
      <dl>
        <dt>{t('custodyWatch')}</dt><dd><bdi>{receiptForReview.watch_id}</bdi></dd>
        <dt>{t('custodyWatchRevision')}</dt><dd>{formatNumber(receiptForReview.watch_revision,locale)}</dd>
        <dt>{t('custodyIncidentRevision')}</dt><dd>{formatNumber(receiptForReview.incident_revision,locale)}</dd>
      </dl>
      <Button type="button" disabled={acceptedReceipt} onClick={reviewReceiptRevision}>{t('reviewReceiptRevision')}</Button>
      {acceptedReceipt&&<p role="status">{t('receiptRevisionPrepared')}</p>}
    </section>}
    {fields.map(field=><Textarea key={field} label={t(field)} readOnly={field==='assessed_issue'&&(custodyUnverified||data?.assessment_allowed!==true||!currentAssessmentCustody)} required={['serial','reference','movement','received_condition','reported_issue'].includes(field)} value={field==='assessed_issue'&&withholdFinding?currentFinding:form[field]} onValueChange={value=>editField(field,value)}/>)}
    {staleFinding&&<><p role="status">{t('assessmentCustodyChanged')}</p>
      <Button type="button" onClick={()=>setForm(previous=>({...previous,assessed_issue:currentFinding,
        reviewed_assessment_custody:undefined}))}>{t('discardAssessmentEdit')}</Button></>}
    {offeredAcceptance&&offeredFee!==undefined&&<section>
      <p>{t('openingAcceptanceReview')}</p>
      <dl>
        <dt>{t('openingQuote')}</dt><dd><bdi>{offeredAcceptance.quote_id}</bdi> · {formatNumber(offeredAcceptance.quote_revision,locale)}</dd>
        <dt>{t('openingTermsRevision')}</dt><dd>{formatNumber(offeredAcceptance.accepted_terms_revision,locale)}</dd>
        <dt>{t('openingConsentRevision')}</dt><dd>{formatNumber(offeredAcceptance.consent_revision,locale)}</dd>
        <dt>{t('feeDollars')}</dt><dd>{formatNumber(offeredFee/100,locale,{minimumFractionDigits:2,maximumFractionDigits:2})}</dd>
      </dl>
      <Button type="button" onClick={recordOpeningAcceptance}>{t('recordOpeningAcceptance')}</Button>
      {form.opening_acceptance===offeredAcceptance&&<p role="status">{t('openingAcceptancePrepared')}</p>}
    </section>}
    {original&&form.opening_acceptance!==original.opening_acceptance&&
      <Button type="button" onClick={restoreOpeningAcceptance}>{t('discardOpeningReview')}</Button>}
    <Button type="submit" disabled={waitingForCustody||staleFinding}>{t('saveIntake')}</Button></fieldset></form>{!!command.error&&<Recovery error={command.error} retry={()=>{if(command.error instanceof ApiError&&command.error.code==='stale_receipt_revision'&&!command.reference){
      resetReceiptReview();
      setForm(previous=>({...previous,reviewed_receipt_revision:undefined}));
      refresh?.();
    }else if(command.error instanceof ApiError&&command.error.code==='stale_assessment_custody'&&!command.reference)refresh?.();
    else void save();}}/>}<p role="status">{command.pending?t('pending'):command.saved?t('saved'):command.reference?t('retrySame'):''}</p>{command.reference&&<bdi>{command.reference}</bdi>}</Card>;
}

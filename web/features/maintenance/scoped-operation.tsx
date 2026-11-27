'use client';
import {useEffect,useRef,useState} from 'react';
import {Button,Card,State} from '@beirut-time/ui/foundation';
import {ApiError} from '@/lib/api/client';
import {useLocale} from '@/shell/locale-context';
import {call} from './common';

export type OperationBinding={kind:'preference'|'diagnosis'|'intake-ack';operation_id:string;owner:string;record:string;
  organization:string;expected_revision:number;source_revision:number};

export type OperationJournal={
  begin:(binding:OperationBinding)=>boolean;
  resolve:(binding:OperationBinding)=>boolean;
};

export function sameOperation(left:OperationBinding|undefined,right:OperationBinding) {
  return !!left&&left.operation_id===right.operation_id&&left.owner===right.owner&&left.kind===right.kind&&
    left.record===right.record&&left.organization===right.organization&&left.expected_revision===right.expected_revision&&
    left.source_revision===right.source_revision;
}

export function useScopedOperationJournal(owner:string|undefined) {
  const retained=useRef(new Map<string,OperationBinding>());
  const [,refresh]=useState(0);
  const journal:OperationJournal={
    begin(binding) {
      if (!owner||binding.owner!==owner) return false;
      const original=retained.current.get(owner);
      if (original) return sameOperation(original,binding);
      retained.current.set(owner,binding);refresh(value=>value+1);return true;
    },
    resolve(binding) {
      if (!owner||binding.owner!==owner||!sameOperation(retained.current.get(owner),binding)) return false;
      retained.current.delete(owner);refresh(value=>value+1);return true;
    },
  };
  return {binding:owner?retained.current.get(owner)??null:null,journal};
}

export function operationPath(binding:OperationBinding) {
  const record=encodeURIComponent(binding.record), operation=encodeURIComponent(binding.operation_id);
  const query=`?organization_id=${encodeURIComponent(binding.organization)}`;
  if(binding.kind==='diagnosis') return `service-cases/${record}/diagnosis/operations/${operation}${query}`;
  return `maintenance/requests/${record}/opening-consent/${binding.kind==='intake-ack'?'intake/':''}operations/${operation}${binding.kind==='intake-ack'?query:''}`;
}

export function originalOutcome(value:unknown,binding:OperationBinding) {
  if (!value||typeof value!=='object'||Array.isArray(value)) return null;
  const row=value as Record<string,unknown>,diagnosis=binding.kind==='diagnosis',buyer=binding.kind==='preference';
  if (row.operation_id!==binding.operation_id||row[diagnosis?'case_id':'request_id']!==binding.record||
      row[buyer?'buyer_id':'actor_id']!==binding.owner) return null;
  if(row.state==='closed'&&(buyer||row.organization_id===binding.organization)) return 'closed';
  if(row.organization_id!==binding.organization) return null;
  if (binding.kind==='intake-ack') return row.consent_revision===binding.expected_revision && row.request_revision===binding.source_revision
    && row.accepted_assessment_fee===true?'recorded':null;
  if(row.expected_revision!==binding.expected_revision||row.revision!==binding.expected_revision+1) return null;
  if(diagnosis) {
    const reviewed=row.reviewed_intake as {intake_revision?:number}|undefined;
    return row.state==='assessed'&&reviewed?.intake_revision===binding.source_revision?'recorded':null;
  }
  return row.request_revision===binding.source_revision && typeof row.opening_permitted==='boolean' && typeof row.no_polish==='boolean'?'recorded':null;
}

const copy={
  en:{pending:'Check the original action',intro:'Check this reference before starting another action. The current record may already have changed.',lookup:'Check original receipt',close:'Close this unrecorded attempt',missing:'No receipt was found. You can close this attempt before starting another.',unknown:'The original action could not be verified. Keep this reference and try again.',recorded:'The original action was recorded.',closed:'The original action was closed without a write.'},
  ar:{pending:'تحقّق من الإجراء الأصلي',intro:'تحقّق من هذا المرجع قبل بدء إجراء آخر. ربما تغيّر السجل الحالي بالفعل.',lookup:'تحقّق من الإيصال الأصلي',close:'أغلق هذه المحاولة غير المسجّلة',missing:'لم يُعثر على إيصال. يمكنك إغلاق هذه المحاولة قبل بدء محاولة أخرى.',unknown:'تعذّر التحقّق من الإجراء الأصلي. احتفظ بهذا المرجع وحاول مجددًا.',recorded:'تم تسجيل الإجراء الأصلي.',closed:'أُغلق الإجراء الأصلي دون تسجيل تغيير.'},
};

export function ScopedOperationResolution({outcome}:{outcome:'recorded'|'closed'}) {
  const t=copy[useLocale()];
  return <p role="status">{t[outcome]}</p>;
}

export function ScopedOperation({scope,binding,onResolved}:{scope:string;binding:OperationBinding;onResolved:(outcome:'recorded'|'closed')=>void}) {
  const t=copy[useLocale()];
  const [busy,setBusy]=useState(false),[state,setState]=useState<'missing'|'unknown'|'recorded'|'closed'>();
  const active=useRef<AbortController|null>(null);
  useEffect(()=>()=>active.current?.abort(),[]);
  async function recover(close=false) {
    if(active.current) return;
    const controller=new AbortController();active.current=controller;setBusy(true);
    try {
      const value=await call<unknown>(scope,operationPath(binding),{signal:controller.signal,method:close?'DELETE':'GET'});
      if(controller.signal.aborted)return;
      const outcome=originalOutcome(value,binding);
      if(!outcome||(!close&&outcome==='closed'))throw Error('operation_receipt_binding');
      setState(outcome);onResolved(outcome);
    } catch(error) {
      if(controller.signal.aborted)return;
      const missing=binding.kind==='preference'?'opening_operation_missing':binding.kind==='diagnosis'?'diagnosis_operation_missing':'opening_acknowledgement_missing';
      setState(error instanceof ApiError && error.status===404 && error.code===missing?'missing':'unknown');
    } finally {if(!controller.signal.aborted)setBusy(false);active.current=null;}
  }
  return <Card><State title={t.pending} body={state?t[state]:t.intro} kind={state==='unknown'?'error':'empty'}>
    <p><bdi>{binding.operation_id}</bdi></p>
    <Button busy={busy} onClick={()=>void recover()}>{t.lookup}</Button>
    {state==='missing'&&<Button disabled={busy} onClick={()=>void recover(true)}>{t.close}</Button>}
  </State></Card>;
}

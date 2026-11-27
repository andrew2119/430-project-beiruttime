'use client';
import {useEffect,useRef,useState} from 'react';
import {Button,Card,State,formatNumber} from '@beirut-time/ui/foundation';
import {useLocale} from '@/shell/locale-context';
import {useSession} from '@/features/identity/session';
import {ApiError} from '@/lib/api/client';
import {call} from '../common';
import {isReference} from '../submission';
import type {OperationBinding,OperationJournal} from '../scoped-operation';

type Binding={request_revision:number;consent_revision:number;assignment_revision:number;order_id:string;receipt_id:string;
  receipt_revision:number;fee_acceptance_operation_id:string;offer_id:string;offer_revision:number};
type Review={request_id:string;organization_id:string;actor_id:string;watch_id:string;received_at:string;opening_permitted:boolean;
  no_polish:boolean;acknowledged:boolean;binding:Binding;fee:{operation_id:string;request_id:string;request_revision:number;
    buyer_id:string;organization_id:string;offer_id:string;offer_revision:number;policy_revision:number;amount_minor:number;currency:'USD';state:'accepted';decided_at:string}};
type Command=Binding & {operation_id:string};
type Receipt=Command & {request_id:string;organization_id:string;actor_id:string;buyer_id:string;watch_id:string;
  customer_opening_permission:boolean;customer_no_polish_acknowledged:boolean;no_polish:boolean;accepted_assessment_fee:boolean;
  accepted_fee_minor:number;policy_revision:number;received_at:string};
const copy={
  en:{title:'Opening and fee acknowledgements',review:'Review current preferences and fee',opening:'Diagnostic opening',polish:'No-polish preference',yes:'Yes',no:'No',fee:'Accepted assessment fee',receipt:'Physical custody receipt',record:'Acknowledge against this receipt',done:'Acknowledgement recorded. Refresh the intake before opening.',unavailable:'The current preference, custody receipt or accepted fee could not be verified.',missing:'No confirmed maintenance assessment is assigned to you for this intake.',pending:'The result is not yet verified. Check the original action above.',separate:'This records what you reviewed. It does not charge the buyer or grant approval to polish.'},
  ar:{title:'إقرار الفتح والرسوم',review:'راجع التفضيلات والرسوم الحالية',opening:'الفتح للتشخيص',polish:'تفضيل عدم التلميع',yes:'نعم',no:'لا',fee:'رسوم التقييم المقبولة',receipt:'إيصال الاستلام الفعلي',record:'أقرّ بهذه البيانات مقابل إيصال الاستلام',done:'تم تسجيل الإقرار. حدّث سجل الاستلام قبل فتح الساعة.',unavailable:'تعذّر التحقق من التفضيل الحالي أو إيصال الاستلام أو الرسوم المقبولة.',missing:'لم يُسند إليك تقييم صيانة مؤكّد لهذا الاستلام.',pending:'لم تُتحقق النتيجة بعد. تحقّق من الإجراء الأصلي أعلاه.',separate:'يُسجّل هذا الإجراء ما راجعته. لا يخصم رسومًا ولا يمنح موافقة على التلميع.'},
};

export function OpeningReview({scope,organization,orderId,receiptId,blocked,journal,onDenied,onRecorded}:{
  scope:string;organization:string;orderId:string;receiptId:string;blocked:boolean;
  journal:OperationJournal;onDenied:(error:unknown)=>void;onRecorded:()=>void;
}) {
  const locale=useLocale(),t=copy[locale],session=useSession();
  const actor=session?.access_fingerprint===scope?session.principal.actor?.subject_id:undefined;
  const [review,setReview]=useState<Review>(),[busy,setBusy]=useState(false);
  const [status,setStatus]=useState<'unavailable'|'missing'|'pending'|'done'>();
  const active=useRef<AbortController|null>(null);
  useEffect(()=>()=>active.current?.abort(),[]);
  const query=new URLSearchParams({organization_id:organization});
  const canReview=!!actor&&!blocked;
  function valid(value:Review) {
    const {binding,fee}=value;
    return value.actor_id===actor&&value.organization_id===organization&&binding?.order_id===orderId&&binding.receipt_id===receiptId&&
      [value.request_id,value.watch_id,binding.fee_acceptance_operation_id,binding.offer_id,fee?.buyer_id].every(isReference)&&
      value.request_id===fee.request_id&&fee.organization_id===organization&&fee.state==='accepted'&&fee.currency==='USD'&&
      binding.request_revision===fee.request_revision&&binding.offer_id===fee.offer_id&&binding.offer_revision===fee.offer_revision&&
      binding.fee_acceptance_operation_id===fee.operation_id&&Number.isSafeInteger(fee.amount_minor)&&fee.amount_minor>=0&&
      [binding.request_revision,binding.consent_revision,binding.assignment_revision,binding.receipt_revision,binding.offer_revision,fee.policy_revision]
        .every(n=>Number.isSafeInteger(n)&&n>0)&&typeof value.opening_permitted==='boolean'&&typeof value.no_polish==='boolean'&&
      typeof value.acknowledged==='boolean'&&Number.isFinite(Date.parse(value.received_at));
  }
  function denied(error:unknown) {
    if(error instanceof ApiError&&[401,403].includes(error.status))onDenied(error);
  }
  async function load() {
    if(!canReview||active.current)return;
    const controller=new AbortController();active.current=controller;setBusy(true);setReview(undefined);setStatus(undefined);
    try {
      const value=await call<Review>(scope,`maintenance/opening-consent/intake/${encodeURIComponent(orderId)}?${query}`,{signal:controller.signal});
      if(controller.signal.aborted)return;
      if(!valid(value))throw Error('opening_review_binding');
      setReview(value);
      if(value.acknowledged)setStatus('done');
    } catch(error) {
      if(controller.signal.aborted)return;
      denied(error);
      setStatus(error instanceof ApiError&&error.status===404&&error.code==='opening_review_missing'?'missing':'unavailable');
    } finally {active.current=null;if(!controller.signal.aborted)setBusy(false);}
  }
  async function save() {
    if(!canReview||active.current||!review||!valid(review)||review.acknowledged)return;
    const command:Command={...review.binding,operation_id:crypto.randomUUID()};
    const binding:OperationBinding={kind:'intake-ack',operation_id:command.operation_id,owner:review.actor_id,record:review.request_id,
      organization,expected_revision:command.consent_revision,source_revision:command.request_revision};
    if(!journal.begin(binding))return;
    const controller=new AbortController();active.current=controller;setBusy(true);setStatus(undefined);
    try {
      const value=await call<Receipt>(scope,`maintenance/requests/${encodeURIComponent(review.request_id)}/opening-consent/intake?${query}`,
        {signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
      if(controller.signal.aborted)return;
      if(value.request_id!==review.request_id||value.watch_id!==review.watch_id||value.actor_id!==actor||value.organization_id!==organization||
        value.buyer_id!==review.fee.buyer_id||value.customer_opening_permission!==review.opening_permitted||
        value.customer_no_polish_acknowledged!==true||value.no_polish!==review.no_polish||value.accepted_assessment_fee!==true||
        value.accepted_fee_minor!==review.fee.amount_minor||value.policy_revision!==review.fee.policy_revision||
        Date.parse(value.received_at)!==Date.parse(review.received_at)||
        Object.entries(command).some(([key,expected])=>value[key as keyof Command]!==expected))throw Error('opening_acknowledgement_binding');
      if(journal.resolve(binding)){setReview(undefined);setStatus('done');onRecorded();}
    } catch(error) {if(!controller.signal.aborted){setReview(undefined);setStatus('pending');denied(error);}}
    finally {active.current=null;if(!controller.signal.aborted)setBusy(false);}
  }
  return <Card><h2>{t.title}</h2><p>{t.separate}</p>
    <Button busy={busy} disabled={!canReview} onClick={()=>void load()}>{t.review}</Button>
    {review&&valid(review)&&!blocked&&<><dl>
      <dt>{t.opening}</dt><dd>{review.opening_permitted?t.yes:t.no}</dd>
      <dt>{t.polish}</dt><dd>{review.no_polish?t.yes:t.no}</dd>
      <dt>{t.fee}</dt><dd><bdi>{formatNumber(review.fee.amount_minor/100,locale,{minimumFractionDigits:2,maximumFractionDigits:2})} USD</bdi></dd>
      <dt>{t.receipt}</dt><dd><bdi>{review.binding.receipt_id}</bdi></dd>
    </dl>{!review.acknowledged&&<Button disabled={busy} onClick={()=>void save()}>{t.record}</Button>}</>}
    {status==='done'?<p role="status">{t.done}</p>:status&&<State headingLevel={3} kind="error" title={t[status]} body={t.separate}/>}
  </Card>;
}

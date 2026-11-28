'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button, Card, Input, State, Textarea, Select } from '@beirut-time/ui/foundation';
import { PageFrame as PageLayout, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';

export type ReturnState = 'requested'|'permitted'|'declined'|'unresolved'|'received'|'refund_pending'|'refunded';
export type ReturnAnswer = { operation_id:string; subject_id:string; state:ReturnState; revision:number };
export class ReturnFailure extends Error { constructor(public code:'denied'|'stale_revision'|'invalid'|'unavailable'){super(code);} }
export type ReturnCommand = {operation_id:string; subject_id:string; reason:string; kind:'request'|'permit'|'decline'|'receive'; expected_revision:number; receipt_id:string};
export type ReturnProvider = { request:(command:ReturnCommand, signal:AbortSignal)=>Promise<ReturnAnswer>; current:(subject:string,signal:AbortSignal)=>Promise<ReturnAnswer|null> };
const states:ReturnState[]=['requested','permitted','declined','unresolved','received','refund_pending','refunded'];
const words = {
  en:{title:'Return a watch',lead:'Permission, physical receipt and simulated refund are separate steps. Collected fees are not refundable.',order:'Order reference',reason:'Return reason',send:'Request return review',retry:'Retry the same request',unavailable:'Returns unavailable',recovery:'Return review is unavailable. Contact support through your order. Keep this request open and try again.',pending:'Result pending',pendingBody:'Retry with the same reference. A request does not confirm permission or receipt.',invalid:'Enter an order reference and a reason within the stated limits.',requested:'Return requested',permitted:'Return permitted',declined:'Return declined',unresolved:'Intake unresolved: watch, receipt or accessories need review',received:'Watch physically received; refund review remains separate',refund_pending:'Simulated refund pending',refunded:'Simulated refund confirmed'},
  ar:{title:'إرجاع ساعة',lead:'الإذن والاستلام الفعلي والاسترداد التجريبي خطوات منفصلة. الرسوم المحصلة غير قابلة للاسترداد.',order:'مرجع الطلب',reason:'سبب الإرجاع',send:'طلب مراجعة الإرجاع',retry:'إعادة المحاولة بالطلب نفسه',unavailable:'الإرجاع غير متاح',recovery:'مراجعة الإرجاع غير متاحة. تواصل مع الدعم من خلال طلبك. أبقِ هذا الطلب مفتوحاً وحاول مجدداً.',pending:'النتيجة قيد الانتظار',pendingBody:'أعد المحاولة بالمرجع نفسه. الطلب لا يؤكد الإذن أو الاستلام.',invalid:'أدخل مرجع الطلب وسبباً ضمن الحدود المحددة.',requested:'تم طلب الإرجاع',permitted:'تم السماح بالإرجاع',declined:'تم رفض الإرجاع',unresolved:'الاستلام غير محسوم: الساعة أو الإيصال أو الملحقات تحتاج إلى مراجعة',received:'تم استلام الساعة فعلياً؛ مراجعة الاسترداد خطوة منفصلة',refund_pending:'الاسترداد التجريبي قيد الانتظار',refunded:'تم تأكيد الاسترداد التجريبي'}
};

/** Mounted beneath the existing locale provider; private drafts stay in memory. */
export default function Returns({provider}:{provider?:ReturnProvider}) {
  const locale=useLocale(),t=words[locale];
  const [kind,setKind]=useState<ReturnCommand['kind']>('request'),[receipt,setReceipt]=useState('');
  const [readError,setReadError]=useState(false),[failure,setFailure]=useState<ReturnFailure['code']|null>(null);
  const [order,setOrder]=useState(''),[reason,setReason]=useState('');
  const [answer,setAnswer]=useState<ReturnAnswer|null>(null),[pending,setPending]=useState(false),[busy,setBusy]=useState(false),[invalid,setInvalid]=useState(false);
  const operation=useRef<ReturnCommand|null>(null);
  const active=useRef<AbortController|null>(null),epoch=useRef(0);
  useEffect(()=>{
    const clear=()=>{epoch.current++;active.current?.abort();operation.current=null;setOrder('');setReason('');setKind('request');setReceipt('');setAnswer(null);setPending(false);setBusy(false);setReadError(false);setFailure(null);};
    window.addEventListener('bt:access-change',clear);
    return()=>{clear();window.removeEventListener('bt:access-change',clear);};
  },[]);
  function changeOrder(value:string){
    if(value===order||busy||pending)return;
    epoch.current++;active.current?.abort();operation.current=null;
    setOrder(value);setAnswer(null);setReceipt('');setFailure(null);setReadError(false);setInvalid(false);
  }
  async function submit(event:FormEvent){
    event.preventDefault();
    if(!provider||busy)return;
    if(!order.trim()||order.length>128||!reason.trim()||reason.length>1000){setInvalid(true);return;}
    operation.current??={operation_id:crypto.randomUUID(),subject_id:order,reason,kind,expected_revision:answer?.subject_id===order?answer.revision:0,receipt_id:receipt};
    const command=operation.current,generation=epoch.current;
    const controller=new AbortController();active.current=controller;
    let timeout:ReturnType<typeof setTimeout>;
    const deadline=new Promise<never>((_,reject)=>{timeout=setTimeout(()=>{controller.abort();reject(new Error('unavailable'));},5000);});
    setBusy(true);setPending(true);setInvalid(false);setFailure(null);
    try{
      const result=await Promise.race([provider.request(command,controller.signal),deadline]);
      if(generation!==epoch.current)return;
      if(result.subject_id!==command.subject_id||result.operation_id!==command.operation_id||!states.includes(result.state)||!Number.isSafeInteger(result.revision)||result.revision<1)throw new Error('invalid');
      setAnswer(result);setPending(false);operation.current=null;
    }catch(error){if(generation===epoch.current){if(error instanceof ReturnFailure&&error.code!=='unavailable'){setFailure(error.code);setPending(false);operation.current=null;if(error.code==='denied'){setAnswer(null);setOrder('');setReason('');setReceipt('');}}else setPending(true);}}
    finally{clearTimeout(timeout!);if(generation===epoch.current)setBusy(false);}
  }
  return <PageLayout><PageHeader title={t.title} lead={t.lead}/><Card>
    <form onSubmit={submit}>
      <Input label={t.order} value={order} onValueChange={changeOrder} disabled={busy||pending} required/>
      <Textarea label={t.reason} value={reason} onValueChange={setReason} disabled={busy||pending} required/>
      <Select messages={locale==='ar'?{placeholder:'اختر إجراءً',filter:'تصفية الإجراءات',emptyTitle:'لا توجد إجراءات',emptyBody:'غيّر التصفية وحاول مجدداً.',close:'إغلاق',loading:'جارٍ تحميل الإجراءات',errorTitle:'الإجراءات غير متاحة',errorBody:'حاول تحميل الإجراءات مجدداً.',retry:'إعادة المحاولة'}:{placeholder:'Choose an action',filter:'Filter actions',emptyTitle:'No actions',emptyBody:'Change the filter and try again.',close:'Close',loading:'Loading actions',errorTitle:'Actions unavailable',errorBody:'Try loading the actions again.',retry:'Retry'}} label={locale==='ar'?'الإجراء':'Action'} value={kind} onValueChange={value=>setKind(value as ReturnCommand['kind'])} disabled={busy||pending} options={(['request','permit','decline','receive'] as const).map((value,index)=>({value,label:(locale==='ar'?['طلب الإرجاع','السماح بالإرجاع','رفض الإرجاع','تسجيل الاستلام الفعلي']:['Request return','Permit return','Decline return','Record actual receipt'])[index]}))}/>
      {kind==='receive'&&<Input label={locale==='ar'?'مرجع إيصال الحيازة الفعلي':'Actual custody receipt reference'} value={receipt} onValueChange={setReceipt} disabled={busy||pending} required/>}
      <Button type="button" disabled={!provider||busy||pending} onClick={async()=>{if(!provider)return;const generation=epoch.current;const controller=new AbortController();active.current=controller;let timer:ReturnType<typeof setTimeout>;const deadline=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('unavailable'));},5000);});setBusy(true);try{const value=await Promise.race([provider.current(order,controller.signal),deadline]);if(generation===epoch.current){if(value&&(value.subject_id!==order||!states.includes(value.state)||!Number.isSafeInteger(value.revision)))throw new Error('invalid');setAnswer(value);setReadError(false);}}catch(error){if(generation===epoch.current){setReadError(true);setAnswer(null);if(error instanceof ReturnFailure&&error.code==='denied'){setOrder('');setReason('');setReceipt('');setFailure('denied');}}}finally{clearTimeout(timer!);if(generation===epoch.current)setBusy(false);}}}>{locale==='ar'?'تحديث الحالة الحالية':'Refresh current state'}</Button>
      <Button type="submit" disabled={!provider||busy}>{pending?t.retry:t.send}</Button>
    </form>
    {failure&&<State kind="error" title={locale==='ar'?'تعذر قبول الإجراء':'Action could not be accepted'} body={failure==='denied'?(locale==='ar'?'ليس لديك إذن حالي لهذا الطلب. تواصل مع المسؤول.':'You do not have current permission for this order. Contact the responsible operator.'):failure==='stale_revision'?(locale==='ar'?'تغير الطلب. حدّث الحالة وراجعها قبل المحاولة مجدداً.':'The order changed. Refresh and review its current state before retrying.'):t.invalid}/>}
    {readError&&<State kind="error" title={t.unavailable} body={t.recovery}/>}
    {invalid&&<State kind="error" title={t.invalid} body={t.recovery}/>}
    {!provider&&<State kind="error" title={t.unavailable} body={t.recovery}/>}
    {pending&&<State kind="loading" title={t.pending} body={t.pendingBody}/>}
    {answer?.subject_id===order&&<State title={t[answer.state]} body={t.lead}/>}
  </Card></PageLayout>;
}

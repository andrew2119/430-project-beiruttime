'use client';
import './reviews.css';
import { useState } from 'react';
import { Button, Input, Select, State, Textarea, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageHeader, PageFrame } from '@/shell/foundation/page';
import { useSession, refreshSession } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';

const copy = {
  en: {title:'Transaction reviews', intro:'One released purchase permits one rating and one seller reply.', subject:'Purchase reference', rating:'Rating', text:'Review or reply', reason:'Report or decision reason', action:'Action', create:'Write review', reply:'Seller reply', report:'Report review', decide:'Moderation decision', send:'Submit', pending:'Result pending. Retry the same action reference.', unavailable:'Reviews are unavailable. Retry when current access and purchase facts are available.', retry:'Retry', denied:'Permission denied. Reload your current access before continuing.', stale:'This record changed. Reload before submitting a new action.', saved:'Change confirmed.', visible:'Keep visible', hidden:'Hide after independent review', decision:'Decision', reference:'Action reference'},
  ar: {title:'مراجعات المعاملات', intro:'تتيح كل عملية شراء محررة تقييماً واحداً ورداً واحداً من البائع.', subject:'مرجع الشراء', rating:'التقييم', text:'المراجعة أو الرد', reason:'سبب البلاغ أو القرار', action:'الإجراء', create:'كتابة مراجعة', reply:'رد البائع', report:'الإبلاغ عن المراجعة', decide:'قرار الإشراف', send:'إرسال', pending:'النتيجة قيد الانتظار. أعد المحاولة بمرجع الإجراء نفسه.', unavailable:'المراجعات غير متاحة. أعد المحاولة عند توفر الصلاحيات الحالية وحقائق الشراء.', retry:'إعادة المحاولة', denied:'رُفض الإذن. أعد تحميل صلاحياتك الحالية قبل المتابعة.', stale:'تغيّر هذا السجل. أعد تحميله قبل إرسال إجراء جديد.', saved:'تم تأكيد التغيير.', visible:'إبقاء المراجعة ظاهرة', hidden:'إخفاؤها بعد مراجعة مستقلة', decision:'القرار', reference:'مرجع الإجراء'}
};
export type Draft = {subject:string; kind:string; rating:number; text:string; reason:string; visible:boolean};
export type Transport = (draft:Draft, operation:string) => Promise<'saved'|'denied'|'stale'|'pending'|'unavailable'>;
/** Access-bound transport is supplied only by the runtime composition. */
export default function ReviewsScreen({transport}:{transport?:Transport}) {
  const session=useSession();
  return <ReviewForm key={session?.access_fingerprint??'signed-out'} transport={session?transport:undefined}/>;
}
export function ReviewForm({transport}:{transport?:Transport}) {
  const locale=useLocale(); const t=copy[locale==='ar'?'ar':'en'];
  const [draft,setDraft]=useState<Draft>({subject:'',kind:'create',rating:5,text:'',reason:'',visible:true});
  const [state,setState]=useState<'saved'|'denied'|'stale'|'pending'|'unavailable'>('unavailable');
  const [busy,setBusy]=useState(false);
  const [operation,setOperation]=useState<string|null>(null);
  const messages={placeholder:locale==='ar'?'اختر':'Choose',filter:locale==='ar'?'بحث':'Search',emptyTitle:locale==='ar'?'لا توجد خيارات':'No options',emptyBody:locale==='ar'?'جرّب بحثاً آخر.':'Try another search.',close:locale==='ar'?'إغلاق':'Close',loading:locale==='ar'?'جارٍ التحميل':'Loading',errorTitle:t.unavailable,errorBody:t.retry,retry:t.retry};
  const locked=operation!==null;
  const change=(patch:Partial<Draft>)=>setDraft(old=>({...old,...patch}));
  async function submit() {
    if(busy)return;
    if(!transport){setState('unavailable');return;}
    const reference=operation??crypto.randomUUID();
    setOperation(reference);
    setBusy(true);setState('pending');
    try {setState(await transport(draft,reference));}
    catch {setState('pending');}
    finally {setBusy(false);}
  }
  return <PageFrame><PageHeader title={t.title} count={t.intro}/><PageBody><section className="transaction-reviews-content" dir={locale==='ar'?'rtl':'ltr'}>
    <form onSubmit={event=>{event.preventDefault();void submit();}}>
      <Input id="review-subject" label={t.subject} required value={draft.subject} disabled={locked} onValueChange={subject=>change({subject:subject.slice(0,128)})}/>
      <Select messages={messages} id="review-action" label={t.action} value={draft.kind} disabled={locked} onValueChange={kind=>change({kind})} options={(['create','reply','report','decide'] as const).map(value=>({value,label:t[value]}))}/>
      {draft.kind==='create'&&<><Select messages={messages} id="review-rating" label={t.rating} value={String(draft.rating)} disabled={locked} onValueChange={rating=>change({rating:Number(rating)})} options={[1,2,3,4,5].map(value=>({value:String(value),label:formatNumber(value,locale)}))}/></>}
      {(draft.kind==='create'||draft.kind==='reply')&&<><Textarea id="review-text" label={t.text} required disabled={locked} value={draft.text} onValueChange={text=>change({text:text.slice(0,2000)})}/></>}
      {(draft.kind==='report'||draft.kind==='decide')&&<><Textarea id="review-reason" label={t.reason} required disabled={locked} value={draft.reason} onValueChange={reason=>change({reason:reason.slice(0,1000)})}/></>}
      {draft.kind==='decide'&&<><Select messages={messages} id="review-decision" label={t.decision} disabled={locked} value={String(draft.visible)} onValueChange={value=>change({visible:value==='true'})} options={[{value:'true',label:t.visible},{value:'false',label:t.hidden}]}/></>}
      <Button type="submit" disabled={busy||state==='saved'||state==='denied'||state==='stale'} aria-busy={busy}>{locked?t.retry:t.send}</Button>
    </form>
    {(state==='denied'||state==='stale'||state==='saved')&&<Button type="button" onClick={async()=>{try {await refreshSession();setOperation(null);setState('unavailable');}catch {setState('unavailable');}}}>{t.retry}</Button>}
    <State kind={state==='denied'||state==='unavailable'?'error':undefined} title={t.title} body={t[state]} />
    {operation&&<p>{t.reference}: <bdi>{operation}</bdi></p>}
  </section></PageBody></PageFrame>;
}

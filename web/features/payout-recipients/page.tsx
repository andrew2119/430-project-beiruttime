'use client';
import {useEffect,useRef,useState} from 'react';
import {recipientRead,root,type Result,type RecipientScope} from './read';
import {Button,Card,Input,Label,Radio,SectionState} from '@beirut-time/ui';
import {PageHeader} from '@/shell/page-header';
import {PageFrame,usePageRead} from './page-boundary';
import {useLocale} from '@/shell/locale-context';
import {authenticatedRequest,refreshSession,signInHref,useSession,useSessionState} from '@/features/identity/session';

const copy={en:{title:'Payout recipient',description:'Synthetic references only. Pending transfers retain their original recipient.',reference:'Synthetic recipient reference',proof:'Current verification reference',save:'Verify and save',retry:'Resolve the same operation',unavailable:'Recipient service unavailable',next:'Try again. No change is confirmed.',pending:'Change pending',saved:'Recipient saved',denied:'Access or verification denied',invalid:'Correct the verification reference and try again',empty:'No recipient saved',loading:'Loading',method:'Recipient method',bank:'Synthetic bank',whish:'Synthetic Whish Money',omt:'Synthetic OMT Pay',signIn:'Sign in to manage your recipient',restore:'Session unavailable',restoreNext:'Retry restoring your session.',restoreRetry:'Retry session',load:'Reload current recipient'},ar:{title:'مستلم العائدات',description:'مراجع تجريبية فقط. تحتفظ التحويلات المعلقة بالمستلم الأصلي.',reference:'مرجع المستلم التجريبي',proof:'مرجع التحقق الحالي',save:'تحقق واحفظ',retry:'استعلم عن العملية نفسها',unavailable:'خدمة المستلم غير متاحة',next:'حاول مجدداً. لم يتم تأكيد أي تغيير.',pending:'التغيير معلق',saved:'تم حفظ المستلم',denied:'تم رفض الوصول أو التحقق',invalid:'صحح مرجع التحقق وحاول مجدداً',empty:'لا يوجد مستلم محفوظ',loading:'جار التحميل',method:'طريقة الاستلام',bank:'بنك تجريبي',whish:'ويش موني تجريبي',omt:'أو إم تي باي تجريبي',signIn:'سجّل الدخول لإدارة مستلم العائدات',restore:'الجلسة غير متاحة',restoreNext:'أعد محاولة استعادة جلستك.',restoreRetry:'أعد محاولة الجلسة',load:'أعد تحميل المستلم الحالي'}};
export default function RecipientPage(){
 const session=useSession();
 const sessionState=useSessionState();
 return <RecipientForm key={session?.access_fingerprint??'signed-out'} owner={session?.access_fingerprint} subject={session?.principal.actor.subject_id} organization={session?.principal.actor.organization_id??null} sessionState={sessionState}/>;
}
function RecipientForm({owner,subject,organization,sessionState}:{owner?:string;subject?:string;organization:string|null;sessionState:ReturnType<typeof useSessionState>}){
 const locale=useLocale(),t=copy[locale];
 const scope:RecipientScope|null=owner&&subject?{owner,subject,organization}:null;
 const {cache,read}=usePageRead(scope);
 const retained=scope?cache.getQueryData<Result>(read!.queryKey):undefined;
 const initial=retained?.state==='succeeded'?retained:null;
 const [reference,setReference]=useState(''),[proof,setProof]=useState(''),[method,setMethod]=useState('bank');
 const [current,setCurrent]=useState<Result|null>(initial),[state,setState]=useState<keyof typeof copy.en>(initial?(initial.revision?'saved':'empty'):'loading');
 const [busy,setBusy]=useState(false);
 const [operation,setOperation]=useState<{id:string;body:string}|null>(null);
 const active=useRef(true),inflight=useRef(false);
 useEffect(()=>{active.current=true;const clear=()=>{active.current=false;setReference('');setProof('');setCurrent(null);setOperation(null);setState('denied');};window.addEventListener('bt:access-change',clear);return()=>{clear();window.removeEventListener('bt:access-change',clear);};},[]);
 async function load(force=true){
  if(!scope||!active.current||inflight.current)return;
  inflight.current=true;setBusy(true);
  try{const result=await cache.fetchQuery({...read!,...(force?{staleTime:0}:{})});if(!active.current)return;
   if(result.schema_version!==1||!Number.isSafeInteger(result.revision))throw Error();
   if(result.state!=='succeeded'){
    if(result.state==='denied'){setCurrent(null);setReference('');setProof('');setMethod('bank');setOperation(null);setState('denied');}
    else setState('unavailable');
    return;
   }
   setCurrent(result);setState(result.revision?'saved':'empty');
  }catch{if(active.current)setState('unavailable');}finally{inflight.current=false;if(active.current)setBusy(false);}
 }
 useEffect(()=>{const timer=setTimeout(()=>void load(false),0);return()=>clearTimeout(timer); // Retained content stays visible while an older answer refreshes.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[owner,subject,organization]);
 async function submit(){
  if(!owner||!current||inflight.current||!active.current)return;
  const retry=operation!==null;
  const id=operation?.id??crypto.randomUUID();
  const op=operation??{id,body:JSON.stringify({schema_version:1,operation_id:id,subject_id:current.subject_id,organization_id:current.organization_id,expected_revision:current.revision,method,reference,proof_id:proof})};
  setOperation(op);inflight.current=true;setBusy(true);setState('pending');
  try{let result=await authenticatedRequest<Result>(retry?`${root}/operations/${op.id}`:root,{method:retry?'GET':'POST',accessFingerprint:owner,...(!retry?{headers:{'Content-Type':'application/json'},body:op.body}:{})});
   if(retry&&result.state==='pending'&&result.pending_reason==='operation_unknown'){
    result=await authenticatedRequest<Result>(root,{method:'POST',accessFingerprint:owner,headers:{'Content-Type':'application/json'},body:op.body});
   }
   if(!active.current)return;
   if(result.schema_version!==1||result.subject_id!==current.subject_id||result.organization_id!==current.organization_id)throw Error();
   if(result.state==='denied'&&result.operation_id===null&&(result.code==='invalid_request'||result.code==='request_too_large')){
    setOperation(null);setProof('');setState('invalid');return;
   }
   if(result.operation_id!==op.id)throw Error();
   if(result.state==='pending'){setState('pending');return;}
   if(result.state==='denied'){if(scope)cache.removeQueries({queryKey:recipientRead(scope).queryKey,exact:true});setOperation(null);setReference('');setProof('');setMethod('bank');setCurrent(null);setState('denied');return;}
   if(result.revision!==current.revision+1)throw Error();
   setOperation(null);setProof('');
   setCurrent(result);if(scope)cache.setQueryData(recipientRead(scope).queryKey,result);setState('saved');
  }catch{if(active.current)setState('pending');}finally{inflight.current=false;if(active.current)setBusy(false);}
 }
 if(!owner)return <PageFrame><PageHeader title={t.title} count={t.description}/><Card>
 <SectionState title={sessionState==='restoring'?t.loading:sessionState==='signed-out'?t.signIn:t.restore} body={sessionState==='unavailable'?t.restoreNext:undefined}/>
 {sessionState==='signed-out'?<a href={signInHref('/seller/payout-recipient',locale)}>{t.signIn}</a>:sessionState==='unavailable'?<Button type="button" onClick={()=>void refreshSession().catch(()=>{})}>{t.restoreRetry}</Button>:null}
 </Card></PageFrame>;
 return <PageFrame><PageHeader title={t.title} count={t.description}/><Card>
 <SectionState title={t[state]} body={state==='unavailable'?t.next:undefined}/>
 <Button type="button" disabled={busy||!owner||!!operation} onClick={()=>void load()}>{t.load}</Button>
 <form onSubmit={event=>{event.preventDefault();void submit();}}>
 <fieldset disabled={busy||!current||!!operation}>
 <legend>{t.method}</legend>
 {(['bank','whish','omt'] as const).map(value=><Radio key={value} name="recipient-method" value={value} checked={method===value} onChange={()=>setMethod(value)}>{t[value]}</Radio>)}
 <Label htmlFor="recipient-reference">{t.reference}</Label>
 <Input id="recipient-reference" value={reference} maxLength={74} pattern="synthetic_[a-zA-Z0-9_-]{1,64}" required autoComplete="off" onChange={event=>setReference(event.target.value)}/>
 <Label htmlFor="recipient-proof">{t.proof}</Label>
 <Input id="recipient-proof" type="password" value={proof} required autoComplete="off" onChange={event=>setProof(event.target.value)}/>
 </fieldset><Button type="submit" disabled={busy||!current||(!operation&&(!reference||!proof))}>{operation?t.retry:t.save}</Button>
 </form></Card></PageFrame>;
}

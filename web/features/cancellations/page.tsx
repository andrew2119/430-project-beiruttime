'use client';
import {useRef,useState} from 'react';
import {BidiReference,Button,ButtonLink,Card,Input,Label,LoadingRows,Notice,SectionState,Segmented,StatusBadge} from '@beirut-time/ui';
import {PageHeader,PageFrame,usePageRead} from './composition';
import {useCancellationLocale} from './locale';
import {authenticatedRequest,useSession,useSessionState,signInHref} from '@/features/identity/session';
import {ApiError} from '@/lib/api/client';
import en from './en.json';
import ar from './ar.json';
import {failureRecovery} from './recovery';
import {localizePath} from '@/shell/paths';

type Command={schema_version:1;operation_id:string;subject_id:string;watch_id:string;organization_id:string|null;expected_revision:number;action:'request';reason:string};
type Outcome={operation_id:string;subject_id:string;watch_id:string;state:'accepted'|'declined'|'pending'|'denied';pending_reason:string|null;refundable_minor:number;completed:boolean;next_review_at:string|null};
const endpoint='/api/web/v1/orders/v1/cancellations';
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export default function Cancellations(){
 const {locale,changeLocale}=useCancellationLocale();
 const t=locale==='ar'?ar:en,session=useSession(),state=useSessionState();
 return <div lang={locale} dir={locale==='ar'?'rtl':'ltr'}><PageFrame><PageHeader title={t.title} count={t.intro} tools={<Segmented value={locale} onChange={changeLocale} aria-label={t.language} options={[{value:'en',label:'English',plain:true},{value:'ar',label:'العربية',plain:true}]}/>}/>{session?<Workspace key={session.access_fingerprint} locale={locale}/>:<Card>{state==='restoring'?<LoadingRows label={t.loading}/>:<SectionState kind="locked" title={state==='unavailable'?t.unavailable:t.signIn}><ButtonLink href={signInHref('/cancellations',locale)}>{t.signIn}</ButtonLink></SectionState>}</Card>}</PageFrame></div>;
}
function Workspace({locale}:{locale:'en'|'ar'}){
 const t=locale==='ar'?ar:en,session=useSession()!;
 const[subject,setSubject]=useState(''),[watch,setWatch]=useState(''),[revision,setRevision]=useState(''),[organization,setOrganization]=useState(''),[reason,setReason]=useState('');
 const[operation,setOperation]=useState<Command|null>(null),[outcome,setOutcome]=useState<Outcome|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<'invalid'|'denied'|'unavailable'|null>(null);
 const[saved,setSaved]=useState(''),[previous,setPrevious]=useState(''),[lookupOnly,setLookupOnly]=useState(false);
 const[rejected,setRejected]=useState(false);
 const active=useRef(false);
 const unresolved=useRef(false);
 const read=usePageRead(session.access_fingerprint);
 async function send(resolve=false,restore=false){
  if(active.current)return;
  if(restore&&!uuid.test(saved)){setError('invalid');return;}
  if(!operation&&(!uuid.test(subject)||!uuid.test(watch)||(organization&&!uuid.test(organization))||!Number.isSafeInteger(Number(revision))||Number(revision)<1||(!restore&&!reason.trim()))){setError('invalid');return;}
  const command:Command=operation??{schema_version:1,operation_id:restore?saved:crypto.randomUUID(),subject_id:subject,watch_id:watch,organization_id:organization||null,expected_revision:Number(revision),action:'request',reason};
  if(restore)setLookupOnly(true);
  setOperation(command);setBusy(true);setError(null);active.current=true;
  const scope=command.organization_id?'&organization_id='+encodeURIComponent(command.organization_id):'';
  try{
   const result=resolve?await read<Outcome>(`${endpoint}/operations/${command.operation_id}?subject_id=${command.subject_id}${scope}`):await authenticatedRequest<Outcome>(`${endpoint}${command.organization_id?'?organization_id='+encodeURIComponent(command.organization_id):''}`,{method:'POST',cache:'no-store',accessFingerprint:session.access_fingerprint,headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
   if(result.operation_id!==command.operation_id||result.subject_id!==command.subject_id||result.watch_id!==command.watch_id||!['accepted','declined','pending','denied'].includes(result.state)||!Number.isSafeInteger(result.refundable_minor)||result.refundable_minor<0)throw new Error('invalid_result');
   unresolved.current=false;
   setOutcome(result);
  }catch(e){
   const recovery=failureRecovery(e instanceof ApiError?e.status:null,resolve,outcome,unresolved.current);
   if(recovery.error==='unavailable')unresolved.current=true;
   setOutcome(recovery.outcome);setError(recovery.error);
   if(recovery.rejected)setRejected(true);
  }finally{setBusy(false);active.current=false;}
 }
 return <><Card><Notice>{t.consequences}</Notice><p>{t.scope}</p><ButtonLink href={`${localizePath('/inbox',locale)}${operation?'?operation_id='+encodeURIComponent(operation.operation_id):''}`}>{t.support}</ButtonLink><form onSubmit={e=>{e.preventDefault();void send();}}>
 <Label htmlFor="cancel-subject">{t.subject}</Label><Input id="cancel-subject" value={subject} onChange={e=>setSubject(e.target.value)} required maxLength={36} disabled={!!operation}/>
 <Label htmlFor="cancel-watch">{t.watch}</Label><Input id="cancel-watch" value={watch} onChange={e=>setWatch(e.target.value)} required maxLength={36} disabled={!!operation}/>
 <Label htmlFor="cancel-organization">{t.organization}</Label><Input id="cancel-organization" value={organization} onChange={e=>setOrganization(e.target.value)} maxLength={36} disabled={!!operation}/>
 <Label htmlFor="cancel-revision">{t.revision}</Label><Input id="cancel-revision" inputMode="numeric" value={revision} onChange={e=>setRevision(e.target.value)} required disabled={!!operation}/>
 <Label htmlFor="cancel-reason">{t.reason}</Label><Input id="cancel-reason" value={reason} onChange={e=>setReason(e.target.value)} required maxLength={500} disabled={!!operation}/>
 <Button type="submit" disabled={busy||!!outcome||lookupOnly||rejected}>{busy?t.loading:operation?t.retry:t.request}</Button>
 </form>
 {!operation&&<><Label htmlFor="cancel-saved">{t.saved}</Label><Input id="cancel-saved" value={saved} onChange={e=>setSaved(e.target.value)} maxLength={36}/><Button disabled={busy||!saved} onClick={()=>void send(true,true)}>{t.restore}</Button></>}
 {(outcome?.state==='denied'||rejected)&&<Button disabled={busy} onClick={()=>{setPrevious(operation!.operation_id);setOperation(null);setOutcome(null);setLookupOnly(false);setRejected(false);setError(null);}}>{t.edit}</Button>}
 {previous&&<p>{t.previous}: <BidiReference>{previous}</BidiReference></p>}
 </Card>
 {error&&<Card><SectionState title={t[error]} kind="error"/></Card>}
 {operation&&<Card><p>{t.reference}: <BidiReference>{operation.operation_id}</BidiReference></p><Button disabled={busy} onClick={()=>void send(true)}>{t.reload}</Button></Card>}
 {outcome?<Card><StatusBadge>{t[outcome.state]}</StatusBadge><p>{outcome.pending_reason?(t[outcome.pending_reason as keyof typeof t]??t.unknown):t[outcome.completed?'completed':'held']}</p><p>{t.amount}: {new Intl.NumberFormat(locale,{style:'currency',currency:'USD'}).format(outcome.refundable_minor/100)}</p><p>{t[outcome.completed?'completed':'held']}</p>{outcome.next_review_at&&<p>{t.next}: <time dateTime={outcome.next_review_at}>{new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(outcome.next_review_at))}</time></p>}</Card>:!operation&&<Card><SectionState title={t.none}/></Card>}
 </>;
}

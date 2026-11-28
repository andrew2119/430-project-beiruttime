'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, ButtonLink, Card, Input, Textarea, State, RowSkeleton, formatNumber, Dialog, DialogContent } from '@beirut-time/ui/foundation';
import { PageHeader, PageFrame } from '@/shell/foundation/page';
import { request, ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest, useSession, signInHref } from '@/features/identity/session';
import { definePageRead } from '@/lib/page-speed/definition';
import { usePageRead } from '@/lib/page-speed/read';
import type { Command, ListingQuestions, Question, PrivateReview, Receipt } from '@contracts/contracts-comms/listing-questions';
import { copy } from './copy';
const base='/api/web/v1/communications/v1/listing-questions/';
const read=definePageRead({key:(listing:string,page:number,signedIn:boolean)=>['listing-questions.v1',listing,page,signedIn],ask:(signal,listing:string,page:number,signedIn:boolean)=>(signedIn?authenticatedRequest<ListingQuestions>:request<ListingQuestions>)(`${base}${encodeURIComponent(listing)}?page=${page}`,{signal}),warm:'open-only',fresh:0});
type Status='pending'|'held'|'done'|'denied'|'stale'|'unavailable';
const valid=(text:string)=>text.trim().length>0 && text.length<=2000;
export function Questions({listing,onPending,signedIn}:{listing:string;onPending:(value:boolean)=>void;signedIn:boolean}) {
 const locale=useLocale(),c=copy[locale==='ar'?'ar':'en'];
 const [page,setPage]=useState(0),[text,setText]=useState(''),[reason,setReason]=useState(''),[answer,setAnswer]=useState('');
 const [matches,setMatches]=useState<Question[]|null>(null),[checked,setChecked]=useState('');
 const [status,setStatus]=useState<Status|null>(null),[busy,setBusy]=useState(false),[pending,setPending]=useState<Command|null>(null);
 const [selected,setSelected]=useState<Question|null>(null),[receipt,setReceipt]=useState<Receipt|null>(null);
 const [reference,setReference]=useState(''),[review,setReview]=useState<PrivateReview|null>(null);
 const [retryRead,setRetryRead]=useState<'suggest'|'review'|null>(null);
 const [matchPage,setMatchPage]=useState(0),[matchTotal,setMatchTotal]=useState(0);
 const [reviewPages,setReviewPages]=useState({reports:0,appeals:0});
 const gate=useRef(false),data=usePageRead(useMemo(()=>listing?read(listing,page,signedIn):null,[listing,page,signedIn]));
 useEffect(()=>{onPending(busy||pending!==null);return ()=>onPending(false);},[busy,onPending,pending]);
 const url=base+encodeURIComponent(listing);
 async function suggest(targetPage=0){
  if(gate.current)return;gate.current=true;setBusy(true);
  try {const result=await request<{items:Question[];total:number;page:number}>(`${url}/suggest`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,page:targetPage})});setMatches(result.items);setMatchTotal(result.total);setMatchPage(result.page);setChecked(text);setStatus(null);setRetryRead(null);}
  catch(error){const denied=error instanceof ApiError && [401,403].includes(error.status);setStatus(denied?'denied':'unavailable');setMatchPage(targetPage);setRetryRead(denied?null:'suggest');}finally{gate.current=false;setBusy(false);}
 }
 async function openReview(reportsPage=0,appealsPage=0){
  if(gate.current)return;gate.current=true;setBusy(true);setReview(null);setSelected(null);setReviewPages({reports:reportsPage,appeals:appealsPage});
  try{const result=await authenticatedRequest<PrivateReview>(`${url}/review/${encodeURIComponent(reference)}?reports_page=${reportsPage}&appeals_page=${appealsPage}`);setReview(result);setSelected(result);setStatus(null);setRetryRead(null);}
  catch(error){const denied=error instanceof ApiError && [401,403].includes(error.status);setStatus(denied?'denied':'unavailable');setRetryRead(denied?null:'review');}finally{gate.current=false;setBusy(false);}
 }
 async function send(kind:Command['kind'],row?:Question){
  if(!data.data||gate.current)return;gate.current=true;setBusy(true);setStatus('pending');
  const body=pending??{operation_id:crypto.randomUUID(),kind,watch_id:data.data.watch_id,source_revision:data.data.source_revision,expected_revision:row?.revision??0,question_id:row?.id??crypto.randomUUID(),text:kind==='ask'?text:kind==='answer'?answer:reason};
  setPending(body);
  try{
   const retained=pending?await authenticatedRequest<Receipt|{state:'pending';operation_id:string}>(`${url}/operations/${encodeURIComponent(body.operation_id)}`):null;
   const result=retained&&retained.state!=='pending'?retained:await authenticatedRequest<Receipt>(`${url}/commands`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   setPending(null);setReceipt(result);setStatus(result.state==='held'?'held':'done');setSelected(null);setReview(null);
   if(kind==='ask'){setText('');setMatches(null);setChecked('');}
   void data.refetch();
  }catch(error){
   setSelected(null);
   if(error instanceof ApiError && [400,401,403,404,409,422].includes(error.status)){if(!pending)setPending(null);setStatus(error.status===409?'stale':'denied');void data.refetch();}
   else setStatus('pending');
  }finally{gate.current=false;setBusy(false);}
 }
 const privateAllowed=data.data?.can_moderate===true&&!data.isError&&(!review||data.data.assigned_question_ids.includes(review.id));
 if(review&&!privateAllowed){setReview(null);setSelected(null);setReason('');}
 const locked=busy||pending!==null;
 const accessDenied=data.error instanceof ApiError && [401,403].includes(data.error.status);
 return <>
  {data.isPending&&listing&&<><State kind="loading" title={c.loading} body={c.loading}/><RowSkeleton/></>}
  {data.isError&&<State kind="error" title={c.unavailable} body={c.recovery}><Button disabled={busy} onClick={()=>void data.refetch()}>{c.retry}</Button></State>}
  {data.data&&!accessDenied&&<>
   <p data-page-answer>{c.count}: {formatNumber(data.data.total,locale)}</p>
   {data.data.items.length===0&&<State title={c.empty} body={c.emptyBody}/>}
   {data.data.items.map(row=><Card key={row.id}><p dir="auto">{row.question}</p><p dir="auto">{row.answer??'—'}</p><p>{c.reference}: <bdi>{row.id}</bdi></p><Button disabled={locked||!signedIn} onClick={()=>{setSelected(row);setReview(null);setReason('');setAnswer('');}}>{c.actions}</Button></Card>)}
   <Button disabled={page===0||locked} onClick={()=>setPage(page-1)}>{c.back}</Button>
   <Button disabled={(page+1)*20>=data.data.total||locked} onClick={()=>setPage(page+1)}>{c.next}</Button>
   {signedIn&&<><Textarea label={c.question} value={text} disabled={locked} onValueChange={value=>{setText(value);setMatches(null);setChecked('');}}/>
   <Button disabled={locked||!valid(text)} onClick={()=>void suggest()}>{c.check}</Button>
   {matches&&<Card><h2>{c.suggest}</h2><p>{c.count}: {formatNumber(matchTotal,locale)}</p>{matches.length===0&&<p>{c.empty}</p>}{matches.map(row=><p key={row.id} dir="auto">{row.question} — {row.answer}</p>)}<Button disabled={locked||matchPage===0} onClick={()=>void suggest(matchPage-1)}>{c.back}</Button><Button disabled={locked||(matchPage+1)*20>=matchTotal} onClick={()=>void suggest(matchPage+1)}>{c.next}</Button></Card>}
   <Button disabled={locked||checked!==text||!valid(text)} onClick={()=>void send('ask')}>{c.send}</Button>
   {receipt&&<Card><p>{c.reference}: <bdi>{receipt.question_id}</bdi></p><p><bdi>{receipt.operation_id}</bdi></p>{receipt.state!=='published'&&<><Textarea label={c.reason} value={reason} onValueChange={setReason} disabled={locked}/><Button disabled={locked||!valid(reason)} onClick={()=>void send('appeal',{id:receipt.question_id,revision:receipt.revision,question:'',answer:null,seller:''})}>{c.appeal}</Button></>}</Card>}
   </>}
   {signedIn&&data.data.can_moderate&&<Card><Input label={c.reference} value={reference} onValueChange={setReference} disabled={locked}/><Button disabled={locked||!reference||reference.length>200} onClick={()=>void openReview()}>{c.review}</Button></Card>}
   <Dialog open={selected!==null} onOpenChange={open=>{if(!open){setSelected(null);setReview(null);}}}><DialogContent title={c.actions} closeLabel={c.close}>
    <p dir="auto">{selected?.question}</p><p dir="auto">{selected?.answer}</p><p>{c.reference}: <bdi>{selected?.id}</bdi></p>
    {review&&<>{(['reports','appeals'] as const).map(kind=><div key={kind}><p>{c[kind]}: {formatNumber(review[`${kind}_total`],locale)}</p><Button disabled={locked||review[`${kind}_page`]===0} onClick={()=>void openReview(kind==='reports'?review.reports_page-1:review.reports_page,kind==='appeals'?review.appeals_page-1:review.appeals_page)}>{c.back}</Button><Button disabled={locked||(review[`${kind}_page`]+1)*20>=review[`${kind}_total`]} onClick={()=>void openReview(kind==='reports'?review.reports_page+1:review.reports_page,kind==='appeals'?review.appeals_page+1:review.appeals_page)}>{c.next}</Button></div>)}{review.reports.map((r,i)=><p dir="auto" key={`report-${i}`}>{r.reason}</p>)}{review.appeals.map((r,i)=><p dir="auto" key={`appeal-${i}`}>{r.reason}</p>)}</>}
    {data.data.can_answer&&!review&&<><Textarea label={c.answer} value={answer} onValueChange={setAnswer} disabled={locked}/><Button disabled={locked||!valid(answer)} onClick={()=>selected&&void send('answer',selected)}>{c.answerSend}</Button></>}
    <Textarea label={c.reason} value={reason} onValueChange={setReason} disabled={locked}/>
    <Button disabled={locked||!valid(reason)} onClick={()=>selected&&void send(review?'hide':'report',selected)}>{review?c.hide:c.report}</Button>
   </DialogContent></Dialog>
  </>}
  {status&&<State kind={status==='pending'||status==='denied'||status==='stale'||status==='unavailable'?'error':'empty'} title={c[status]} body={status==='unavailable'?c.readRecovery:status==='pending'?c.recovery:c[status]}>{status==='unavailable'&&retryRead&&<Button disabled={locked} onClick={()=>void (retryRead==='suggest'?suggest(matchPage):openReview(reviewPages.reports,reviewPages.appeals))}>{c.retry}</Button>}{pending&&<><p><bdi>{pending.operation_id}</bdi></p><Button disabled={busy} onClick={()=>void send(pending.kind)}>{c.retry}</Button></>}</State>}
 </>;
}
export default function ListingQuestionsPage(){
 const locale=useLocale(),c=copy[locale==='ar'?'ar':'en'],session=useSession();
 const [draft,setDraft]=useState(''),[listing,setListing]=useState(''),[locked,setLocked]=useState(false);
 return <PageFrame><PageHeader title={c.title}/><Input label={c.listing} value={draft} onValueChange={setDraft} disabled={locked}/><Button disabled={locked||!draft.trim()||draft.length>200} onClick={()=>setListing(draft.trim())}>{c.open}</Button><Questions key={`${session?.access_fingerprint??'public'}:${listing}`} listing={listing} onPending={setLocked} signedIn={session!==null}/> {!session&&<State title={c.title} body={c.sign}><ButtonLink href={signInHref('/questions',locale)}>{c.signin}</ButtonLink></State>}</PageFrame>;
}

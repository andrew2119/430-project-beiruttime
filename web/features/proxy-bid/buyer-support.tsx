'use client';

import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {Button,ButtonLink,Card,RowSkeleton,State,Textarea} from '@beirut-time/ui/foundation';
import {PageFrame,PageHeader} from '@/shell/foundation/page';
import {useLocale} from '@/shell/locale-context';
import {usePageRead} from '@/lib/page-speed/read';
import {AnswerArrival} from '@/lib/page-speed/arrival';
import {ApiError} from '@/lib/api/client';
import {useBuyerSession,signInHref} from './session';
import {BuyerLanguageControl} from './buyer-language';
import {buyerDateFormatter} from './buyer-date';
import {checkSupport,deliverSupport,openSupport,prepareSupport,supportBody,supportRead} from './support-api';
import {noPendingSupport,parseSupportAttempt,pendingSupport,retainSupportAttempt,settleSupportAttempt,subscribePendingSupport} from './pending-support';

const copy={
  en:{title:'Auction support',intro:'Speak with support about this auction result.',back:'Back to my results',
    history:'Auction support history',historyIntro:'Read the previous conversation for this auction result.',
    historyMissing:'There is no support conversation for this result.',
    signIn:'Sign in to open your support conversation.',account:'Sign in',loading:'Checking the conversation',
    unavailable:'Support is temporarily unavailable',retry:'Try again',denied:'You do not have access to this conversation.',
    open:'Open support conversation',missing:'No support conversation is open for this result.',
    awaiting:'No support operator has been assigned yet',followUp:'We will follow up within 24 hours of the hold starting.',
    assigned:'A support operator is assigned',due:'Follow-up due',draft:'Message for support',send:'Send message',limit:'Use up to 2,000 characters.',
    pending:'The message is not yet confirmed. Retry the same request.',sent:'Message confirmed',
    pendingHistory:'The previous message is not yet confirmed.',checkAttempt:'Check previous message',
    notSent:'The previous message was not sent. This conversation has not been reopened.',
    stillPrepared:'The previous message is saved but has not been sent.',activeSupport:'Go to conversation to retry sending',
    checkUnavailable:'Message status is temporarily unavailable. Check the same message again.',
    recoveryUnavailable:'Message recovery is unavailable. No new message has been sent.',
    abandoned:'The original message was not sent. Enter it again if you still need help.',
    stale:'The conversation changed before this message was recorded. Review it and send again.',
    empty:'No messages yet',buyer:'You',support:'Support',older:'Older messages',latest:'Latest messages',
    changed:'This page of messages has changed. Return to the latest messages.'},
  ar:{title:'دعم المزادات',intro:'تواصل مع الدعم بشأن نتيجة هذا المزاد.',back:'العودة إلى نتائجي',
    history:'سجلّ دعم المزاد',historyIntro:'اقرأ المحادثة السابقة بشأن نتيجة هذا المزاد.',
    historyMissing:'لا توجد محادثة دعم لهذه النتيجة.',
    signIn:'سجّل الدخول لفتح محادثة الدعم الخاصة بك.',account:'تسجيل الدخول',loading:'جارٍ التحقق من المحادثة',
    unavailable:'الدعم غير متاح مؤقتًا',retry:'حاول مجددًا',denied:'ليس لديك إذن للوصول إلى هذه المحادثة.',
    open:'افتح محادثة الدعم',missing:'لا توجد محادثة دعم مفتوحة لهذه النتيجة.',
    awaiting:'لم يُعيَّن مسؤول دعم بعد',followUp:'سنتابع معك خلال ٢٤ ساعة من بدء التعليق.',
    assigned:'تم تعيين مسؤول دعم',due:'موعد المتابعة',draft:'رسالة إلى الدعم',send:'أرسل الرسالة',limit:'اكتب ما يصل إلى ٢٬٠٠٠ حرف.',
    pending:'لم يتم تأكيد الرسالة بعد. أعد محاولة الطلب نفسه.',sent:'تم تأكيد الرسالة',
    pendingHistory:'لم يتم تأكيد الرسالة السابقة بعد.',checkAttempt:'تحقّق من الرسالة السابقة',
    notSent:'لم تُرسل الرسالة السابقة. لم يُعَد فتح هذه المحادثة.',
    stillPrepared:'الرسالة السابقة محفوظة ولم تُرسل بعد.',activeSupport:'انتقل إلى المحادثة لإعادة محاولة الإرسال',
    checkUnavailable:'حالة الرسالة غير متاحة مؤقتًا. تحقّق من الرسالة نفسها مجددًا.',
    recoveryUnavailable:'لا يمكن استعادة الرسالة الآن. لم تُرسل أي رسالة جديدة.',
    abandoned:'لم تُرسل الرسالة الأصلية. اكتبها مجددًا إذا كنت لا تزال بحاجة إلى المساعدة.',
    stale:'تغيّرت المحادثة قبل تسجيل رسالتك. راجعها ثم أعد الإرسال.',
    empty:'لا توجد رسائل بعد',buyer:'أنت',support:'الدعم',older:'الرسائل الأقدم',latest:'أحدث الرسائل',
    changed:'تغيّرت هذه الصفحة من الرسائل. ارجع إلى أحدث الرسائل.'},
} as const;

export function BuyerSupport({auctionId,listingId,historyOnly=false}:{auctionId:string;listingId:string;historyOnly?:boolean}) {
  const locale=useLocale(),t=copy[locale], session=useBuyerSession();
  const permitted=session.state==='authenticated'&&session.signedIn&&!session.organizationId&&session.roles.includes('buyer');
  const next=`/buyer/auctions/${listingId}/support?auction=${auctionId}${historyOnly?'&view=history':''}`;
  return <PageFrame><PageHeader title={historyOnly?t.history:t.title} lead={historyOnly?t.historyIntro:t.intro}
    actions={<ButtonLink href={`/${locale}/buyer?view=won`}>{t.back}</ButtonLink>}/>
    <BuyerLanguageControl/>
    {!permitted&&!session.fingerprint&&<State title={session.state==='restoring'?t.loading:session.state==='unavailable'?t.unavailable:t.signIn} body={t.intro}>
      {session.state==='signed-out'&&<ButtonLink href={signInHref(next,locale)}>{t.account}</ButtonLink>}
    </State>}
    {session.fingerprint&&session.subjectId&&<Conversation key={`${session.fingerprint}:${auctionId}:${historyOnly}`} auction={auctionId}
      buyer={session.subjectId} access={session.fingerprint} permitted={permitted} historyOnly={historyOnly}
      activeHref={`/${locale}/buyer/auctions/${listingId}/support?auction=${auctionId}`}/>}
  </PageFrame>;
}

const notOpen=(error:unknown)=>error instanceof ApiError&&error.status===404&&error.code==='support_not_open';

function Conversation({auction,buyer,access,permitted,historyOnly,activeHref}:{auction:string;buyer:string;access:string;permitted:boolean;historyOnly:boolean;activeHref:string}) {
  const locale=useLocale(),t=copy[locale], dates=buyerDateFormatter(locale);
  const [cursor,setCursor]=useState<string|null>(null),[draft,setDraft]=useState('');
  const [status,setStatus]=useState<'idle'|'busy'|'openUnavailable'|'pending'|'sent'|'denied'|'stale'|'abandoned'|'recoveryUnavailable'|'stillPrepared'|'checkUnavailable'>('idle');
  const [authority,setAuthority]=useState({permitted,epoch:0});
  if(authority.permitted!==permitted) {
    setAuthority({permitted,epoch:authority.epoch+1});
    setStatus('idle');
  }
  const openKey=useRef<string|null>(null);
  const active=useRef<AbortController|null>(null);
  useEffect(()=>()=>{active.current?.abort();active.current=null;},[permitted]);
  const query=usePageRead(permitted&&authority.permitted?supportRead(auction,buyer,access,cursor,authority.epoch):null);
  const {refetch}=query;
  useEffect(()=>{
    if(!permitted) return;
    const timer=setInterval(()=>void refetch({cancelRefetch:false}),15000);
    return ()=>clearInterval(timer);
  },[permitted,refetch]);
  const current=permitted&&query.isFetchedAfterMount&&!query.isError?query.data:undefined;
  const unknownHold=Boolean(current&&current.hold_state!=='active'&&current.hold_state!=='resolved');
  const readOnly=historyOnly||current?.hold_state!=='active';
  const scoped=Boolean(!unknownHold&&current&&current.buyer_id===buyer&&current.auction_id===auction);
  const saved=useSyncExternalStore(subscribePendingSupport,()=>scoped?pendingSupport(buyer,auction):null,noPendingSupport);
  const retained=parseSupportAttempt(saved);
  const pending=retained&&retained.conversationId===current?.conversation_id?retained:null;
  const unavailable=scoped&&saved!==null&&!pending;
  const denied=query.error instanceof ApiError&&[401,403].includes(query.error.status);
  const currentLatestError=cursor===null&&query.isFetchedAfterMount&&query.isError;
  const unopened=!historyOnly&&currentLatestError&&notOpen(query.error);
  const noHistory=currentLatestError&&query.error instanceof ApiError&&query.error.status===404&&
    (query.error.code==='support_history_missing'||historyOnly&&query.error.code==='support_not_open');

  async function perform(open:boolean) {
    if(!permitted||active.current||status==='denied'||(open?!unopened:!scoped||!current||cursor!==null)) return;
    const stored=open?null:pendingSupport(buyer,auction);
    const existing=parseSupportAttempt(stored);
    if(stored!==null&&(!existing||existing.conversationId!==current?.conversation_id)) return;
    // History may recover a previously prepared action, never prepare or open one.
    if(!open&&readOnly&&(!existing||existing.key!==pending?.key)) return;
    const controller=new AbortController();
    active.current=controller;
    setStatus('busy');
    try {
      if(open) {
        openKey.current??=crypto.randomUUID();
        await openSupport(auction,buyer,access,openKey.current,controller.signal);
        if(controller.signal.aborted) return;
        openKey.current=null;
        await query.refetch();
        if(!controller.signal.aborted) setStatus('idle');
      } else {
        if(!current||(!existing&&!supportBody(draft))) {setStatus('idle');return;}
        const message=existing??{key:crypto.randomUUID(),conversationId:current.conversation_id};
        if(!existing&&!retainSupportAttempt(buyer,auction,message)) {setStatus('recoveryUnavailable');return;}
        const signal=controller.signal;
        const prepared=existing?null:await prepareSupport(auction,buyer,access,message.key,
          {conversation_id:message.conversationId,expected_revision:current.revision,body:draft},signal);
        if(signal.aborted) return;
        const receipt=readOnly?await checkSupport(auction,buyer,access,message.key,message.conversationId,signal):
          prepared&&prepared.state!=='prepared'?prepared:
            await deliverSupport(auction,buyer,access,message.key,message.conversationId,signal);
        if(signal.aborted) return;
        if(receipt.state==='prepared') {setStatus('stillPrepared');return;}
        settleSupportAttempt(buyer,auction,message);
        if(receipt.state==='accepted') {setDraft('');setStatus('sent');}
        else setStatus(receipt.state==='abandoned'?'abandoned':'stale');
        await query.refetch();
      }
    } catch(error) {
      if(controller.signal.aborted) return;
      setStatus(error instanceof ApiError&&[401,403].includes(error.status)?'denied':
        open?'openUnavailable':readOnly?'checkUnavailable':'pending');
    } finally {
      if(active.current===controller) active.current=null;
    }
  }

  async function retry() {
    const answer=await query.refetch();
    if((answer.isSuccess&&answer.data)||(cursor===null&&notOpen(answer.error))) setStatus('idle');
  }

  function latest() {
    setCursor(null);
    setAuthority(previous=>({...previous,epoch:previous.epoch+1}));
    if(status==='denied') setStatus('idle');
  }
  const latestAction=cursor!==null&&<Button variant="outline" onClick={latest}>{t.latest}</Button>;

  if(!permitted||denied||status==='denied') return <State kind="error" title={t.denied} body={t.intro}>
    {permitted&&<><Button onClick={()=>void retry()}>{t.retry}</Button>{latestAction}</>}
  </State>;
  if(noHistory) return <State kind="empty" title={t.historyMissing} body={t.historyIntro}/>;
  if(unopened) return <State title={status==='openUnavailable'?t.unavailable:t.missing} body={t.intro}>
    <Button busy={status==='busy'} onClick={()=>void perform(true)}>{status==='openUnavailable'?t.retry:t.open}</Button>
  </State>;
  if(query.isError||unknownHold) return <State kind="error" title={t.unavailable}
    body={cursor!==null&&query.error instanceof ApiError&&query.error.status===409?t.changed:t.intro}>
    <Button onClick={()=>void retry()}>{t.retry}</Button>{latestAction}
  </State>;
  if(!current) return <State kind="loading" title={t.loading} body={t.intro}><RowSkeleton/></State>;
  const waiting=current.assignment_state==='awaiting_operator';
  return <AnswerArrival view={`auction-support:${auction}`}><Card>
    {readOnly?<p>{t.historyIntro}</p>:<>
      <State title={waiting?t.awaiting:t.assigned} body={waiting?t.followUp:t.intro}/>
      <p>{t.due}: <time dateTime={current.follow_up_due_at}>{dates.format(new Date(current.follow_up_due_at))}</time></p>
    </>}
    {current.items.length===0?<State title={t.empty} body={t.intro}/>:<ol>{current.items.map(message=><li key={message.sequence}>
      <p>{t[message.author]} · <time dateTime={message.sent_at}>{dates.format(new Date(message.sent_at))}</time></p>
      <p className="buyer-reference" dir="auto">{message.body}</p>
    </li>)}</ol>}
    <div className="proxy-actions">
      {latestAction}
      {current.next_cursor&&<Button variant="outline" onClick={()=>setCursor(current.next_cursor)}>{t.older}</Button>}
    </div>
    {readOnly&&cursor===null&&<>
      {pending&&<>
        <p role="status">{status==='stillPrepared'?t.stillPrepared:status==='checkUnavailable'?t.checkUnavailable:t.pendingHistory}</p>
        <Button type="button" busy={status==='busy'} onClick={()=>void perform(false)}>{t.checkAttempt}</Button>
        {historyOnly&&current.hold_state==='active'&&status==='stillPrepared'&&
          <ButtonLink variant="outline" href={activeHref}>{t.activeSupport}</ButtonLink>}
      </>}
      {unavailable&&<p role="status">{t.recoveryUnavailable}</p>}
      {status==='sent'&&<p role="status">{t.sent}</p>}
      {(status==='stale'||status==='abandoned')&&<p role="status">{t.notSent}</p>}
    </>}
    {!readOnly&&cursor===null&&<form onSubmit={event=>{event.preventDefault();void perform(false);}}>
      <Textarea label={t.draft} hint={t.limit} value={draft} disabled={Boolean(pending)||unavailable||status==='busy'}
        onValueChange={value=>{setDraft(value);if(status==='sent')setStatus('idle');}}/>
      <Button type="submit" busy={status==='busy'} disabled={unavailable||(!pending&&!supportBody(draft))}>{pending?t.retry:t.send}</Button>
      {pending&&<p role="status">{t.pending}</p>}
      {(unavailable||status==='recoveryUnavailable')&&<p role="status">{t.recoveryUnavailable}</p>}
      {(status==='sent'||status==='stale'||status==='abandoned')&&<p role="status">{t[status]}</p>}
    </form>}
  </Card></AnswerArrival>;
}

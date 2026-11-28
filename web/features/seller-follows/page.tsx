'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, ButtonLink, Card, Input, RowSkeleton, State, Switch, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { usePageRead } from '@/lib/page-speed/read';
import { authenticatedRequest, useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { Session } from '@contracts/contracts-identity/accounts';
import type { Follow, FollowCommand, Receipt, NoticeCommand } from '@contracts/contracts-comms/seller-follows';
import { base, followingRead, noticesRead } from './reads';
import { copy } from './copy';

export function Following({session}:{session:Session}) {
  const locale=useLocale(),t=copy[locale],scope=session.access_fingerprint,router=useRouter();
  const [page,setPage]=useState(0),[noticePage,setNoticePage]=useState(0),[seller,setSeller]=useState(''),[alerts,setAlerts]=useState(false);
  const [pending,setPending]=useState<FollowCommand|NoticeCommand|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState<keyof typeof t|null>(null);
  const [accessDenied,setAccessDenied]=useState(false);
  const flight=useRef(false),revoked=useRef(false);
  const follows=usePageRead(followingRead(scope,page)),notices=usePageRead(noticesRead(scope,noticePage));
  const readDenied = [follows.error, notices.error].some(error=>error instanceof ApiError && [401,403].includes(error.status));
  if (readDenied && !accessDenied) {
    setAccessDenied(true);setPending(null);setSeller('');setAlerts(false);setMessage(null);
  }
  useEffect(()=>{if(readDenied)revoked.current=true;},[readDenied]);
  const denied = accessDenied || readDenied;
  const refresh=()=>{void follows.refetch();void notices.refetch();};
  function suppressDenied(error:unknown) {
    if (!(error instanceof ApiError) || ![401,403].includes(error.status)) return false;
    revoked.current=true;setAccessDenied(true);setPending(null);setSeller('');setAlerts(false);setMessage(null);
    refresh();
    return true;
  }
  async function send(command:FollowCommand|NoticeCommand) {
    if(denied||flight.current)return;
    flight.current=true;setBusy(true);setPending(command);setMessage('pending');
    try {
      await authenticatedRequest<Receipt>('notice_id' in command?`${base}/notices`:base,{method:'PUT',accessFingerprint:scope,headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
      if(revoked.current)return;
      setPending(null);setMessage('accepted');refresh();
    } catch(error) {
      if(revoked.current)return;
      if(suppressDenied(error)) return;
      if(error instanceof ApiError && [404,409,422].includes(error.status)) {setPending(null);setMessage(error.status===409?'conflict':'recover');}
      else setMessage('pending');
    } finally {flight.current=false;setBusy(false);}
  }
  async function change(row:Follow|undefined,following:boolean,enabled:boolean) {
    if(denied||pending||flight.current)return;
    const reference=row?.seller_id??seller.trim();
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(reference)){setMessage('invalid');return;}
    flight.current=true;setBusy(true);
    try {
      const current=row??await authenticatedRequest<Follow>(`${base}/sellers/${reference}`,{accessFingerprint:scope});
      if(revoked.current)return;
      const command:FollowCommand={schema_version:'seller-follows.v1',operation_id:crypto.randomUUID(),actor_id:session.principal.actor.subject_id,organization_id:null,seller_id:reference,expected_revision:current.revision,following,alerts_enabled:enabled};
      flight.current=false;await send(command);
    }catch(error) {if(!suppressDenied(error))setMessage('recover');}finally{flight.current=false;setBusy(false);}
  }
  async function open(id:string) {
    if(denied)return;
    try {const result=await authenticatedRequest<{url:string}>(`${base}/notices/${id}/destination`,{accessFingerprint:scope});
      if(revoked.current)return;
      if(!/^\/watches\/[0-9a-f-]{36}$/.test(result.url))throw new Error('unavailable');
      router.push(`/${locale}${result.url}`);
    }catch(error) {if(!suppressDenied(error))setMessage('unknown');}
  }
  if(denied) return <PageFrame><PageHeader title={t.title}/><PageBody><State title={t.denied} body={t.deniedBody}><Button onClick={refresh}>{t.refresh}</Button></State></PageBody></PageFrame>;
  return <PageFrame><PageHeader title={t.title} lead={t.lead} count={follows.data?`${t.total}: ${formatNumber(follows.data.total,locale)}`:undefined} actions={<Button variant="outline" onClick={refresh}>{t.refresh}</Button>}/><PageBody>
    <form onSubmit={event=>{event.preventDefault();void change(undefined,true,alerts);}}>
      <Input label={t.seller} value={seller} onValueChange={setSeller} disabled={busy||!!pending}/>
      <Switch label={t.alerts} checked={alerts} onCheckedChange={setAlerts} disabled={busy||!!pending}/>
      <Button type="submit" disabled={busy||!!pending}>{t.follow}</Button>
    </form>
    {message&&<p role="status" className="bt-text">{t[message]}</p>}
    {pending&&<Card><p className="bt-text"><bdi>{pending.operation_id}</bdi></p><Button busy={busy} onClick={()=>void send(pending)}>{t.retry}</Button></Card>}
    {(follows.isError||notices.isError)&&<p role="alert" className="bt-text">{t.recover}</p>}
    {follows.isPending?<div role="status" aria-label={t.loading}><RowSkeleton/></div>:follows.isError&&!follows.data?<State kind="error" title={t.unavailable} body={t.recover}/>:follows.data.items.length===0?<State title={t.empty} body={t.emptyBody}/>:follows.data.items.map(row=><Card key={row.seller_id}><p className="bt-text"><bdi>{row.seller_id}</bdi></p><Button disabled={busy||!!pending} variant="outline" onClick={()=>void change(row,false,false)}>{t.unfollow}</Button><Switch label={t.alerts} checked={row.alerts_enabled} disabled={busy||!!pending} onCheckedChange={enabled=>void change(row,true,enabled)}/></Card>)}
    <div className="bt-page-tools"><Button disabled={page===0} onClick={()=>setPage(page-1)}>{t.previous}</Button><Button disabled={!follows.data||(page+1)*50>=follows.data.total} onClick={()=>setPage(page+1)}>{t.next}</Button></div>
    <h2 className="bt-heading">{t.notices}</h2>
    {notices.isPending?<RowSkeleton/>:notices.isError&&!notices.data?<State kind="error" title={t.unavailable} body={t.recover}/>:notices.data.items.length===0?<State title={t.noticeEmpty} body={t.noticeBody}/>:notices.data.items.map(notice=><Card key={notice.id}><p className="bt-text">{t.notice} {notice.sample?t.sample:''}</p><p className="bt-text"><bdi>{notice.watch}</bdi></p><time dateTime={notice.occurred}>{new Date(notice.occurred).toLocaleString(locale==='ar'?'ar-LB-u-nu-arab':'en-GB-u-nu-latn',{timeZone:'Asia/Beirut'})}</time><p className="bt-text">{notice.read_at?t.readState:t.unread}</p><Button onClick={()=>void open(notice.id)}>{t.open}</Button>{(['read','clear'] as const).map(action=><Button key={action} disabled={busy||!!pending||(action==='read'&&!!notice.read_at)} onClick={()=>void send({schema_version:'seller-follows.v1',operation_id:crypto.randomUUID(),actor_id:session.principal.actor.subject_id,organization_id:null,notice_id:notice.id,expected_revision:notice.notice_revision,action})}>{t[action]}</Button>)}</Card>)}
    {notices.data&&<p className="bt-number">{formatNumber(notices.data.total,locale)}</p>}
    <div className="bt-page-tools"><Button disabled={noticePage===0} onClick={()=>setNoticePage(noticePage-1)}>{t.previous}</Button><Button disabled={!notices.data||(noticePage+1)*50>=notices.data.total} onClick={()=>setNoticePage(noticePage+1)}>{t.next}</Button></div>
  </PageBody></PageFrame>;
}
export default function FollowingPage() {
  const session=useSession(),locale=useLocale(),t=copy[locale];
  return session&&session.principal.actor.organization_id===null&&session.principal.roles.includes('buyer')?<Following key={session.access_fingerprint} session={session}/>:<PageFrame><PageHeader title={t.title}/><PageBody><State title={t.denied} body={t.deniedBody}><ButtonLink href={`/${locale}/account`}>{t.denied}</ButtonLink></State></PageBody></PageFrame>;
}

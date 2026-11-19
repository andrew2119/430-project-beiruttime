'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, ButtonLink, Card, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { PushCommand } from '@contracts/contracts-comms/browser-push';
import { copy } from './copy';
import { existingRegistration, installation, submit } from './client';
import { pushDeviceRead } from './read';
import { PendingOperation } from './pending';
import { initializeDevice } from './initialization';

async function bounded<T>(promise:Promise<T>):Promise<T> {
  let timer:ReturnType<typeof setTimeout>|undefined;
  try {return await Promise.race([promise,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error('pending')),5000);})]);}
  finally {clearTimeout(timer);}
}
function DeviceSettings({scope}:{scope:string}) {
  const locale=useLocale(), c=copy[locale], [device,setDevice]=useState<string|null>(null);
  const [attempt]=useState(()=>new PendingOperation(body=>submit(body,scope)));
  const [state,setState]=useState<'ready'|'pending'|'denied'|'unavailable'|'saved'>('ready');
  const [busy,setBusy]=useState(false), [pending,setPending]=useState<PushCommand|null>(null), alive=useRef(true);
  useEffect(()=>{alive.current=true;queueMicrotask(()=>{if(!alive.current)return;const result=initializeDevice(installation);setDevice(result.device);setState(result.state);});return()=>{alive.current=false;};},[]);
  const read=usePageRead(device?pushDeviceRead(device,scope):null);
  async function change(revoke=false) {
    if (!device || !read.data || busy) return;
    setBusy(true);
    let operation=pending;
    try {
      if (!operation) {
        let subscription:PushCommand['subscription']=null;
        if (!revoke) {
          if (!isSecureContext || !('Notification' in window) || !('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('unavailable');
          const permissionRequest=Notification.requestPermission();
          const registration=await bounded(existingRegistration());
          const config=await authenticatedRequest<{application_server_key:string}>('/api/web/v1/communications/v1/browser-push/config',{accessFingerprint:scope});
          if (!alive.current) return;
          const permission=await permissionRequest;
          if (!alive.current) return;
          if (permission!=='granted') {setState('denied');return;}
          const current=await bounded(registration.pushManager.getSubscription());
          const value=current??await bounded(registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:config.application_server_key}));
          if (!alive.current) return;
          const json=value.toJSON();
          if (!json.endpoint||!json.keys?.p256dh||!json.keys.auth) throw new Error('unavailable');
          subscription={endpoint:json.endpoint,p256dh:json.keys.p256dh,auth:json.keys.auth};
        }
        operation={schema_version:'browser-push.v1',operation_id:crypto.randomUUID(),device_id:device,expected_revision:read.data.revision,action:revoke?'revoke':read.data.revision?'rebind':'opt_in',permission:revoke?'default':'granted',subscription};
        setPending(operation);
      }
      setState('pending');
      await attempt.run(operation);
      if (!alive.current) return;
      setPending(null);
      setState('saved');
      await read.refetch();
    } catch(error) {
      if (!alive.current) return;
      if (error instanceof ApiError && [400,401,403,409,422].includes(error.status)) {
        attempt.clear();setPending(null);setState(error.status===403?'denied':'unavailable');void read.refetch();
      } else setState(operation?'pending':'unavailable');
    } finally {if(alive.current)setBusy(false);}
  }
  function refresh() {
    if (!device) {
      const result=initializeDevice(installation);
      setDevice(result.device);setState(result.state);
    } else void read.refetch();
  }
  const unavailable=state==='unavailable'||read.isError;
  const waiting=!unavailable&&(!device||read.isPending);
  const title=unavailable?c.unavailable:read.data?c[read.data.state]:c.loading;
  return <Card>
    <State title={title} body={read.isError?c.unavailable:c[state]} kind={state==='pending'?'loading':state==='unavailable'||read.isError?'error':waiting?'loading':'empty'}>
      {!!device&&!waiting&&!read.isError&&<>
        <Button disabled={busy||!!pending||read.data?.state==='active'} onClick={()=>void change()}>{c.enable}</Button>
        <Button variant="outline" disabled={busy||!!pending||read.data?.state!=='active'} onClick={()=>void change(true)}>{c.revoke}</Button>
      </>}
      {pending&&<Button disabled={busy} onClick={()=>void change()}>{c.retry}</Button>}
      {(read.isError||state==='unavailable')&&<Button disabled={busy} onClick={refresh}>{c.refresh}</Button>}
      <ButtonLink href={`/${locale}/inbox`} variant="outline">{c.inbox}</ButtonLink>
    </State>
  </Card>;
}
export default function NotificationDevices() {
  const locale=useLocale(),c=copy[locale],session=useSession(),status=useSessionState();
  return <PageFrame><PageHeader title={c.title} lead={c.intro}/><PageBody>
    {session?<DeviceSettings key={session.access_fingerprint} scope={session.access_fingerprint}/>:<State title={status==='restoring'?c.loading:c.signin} body={status==='unavailable'?c.unavailable:c.ready} kind={status==='restoring'?'loading':'empty'}><ButtonLink href={`/${locale}/account`}>{c.signinaction}</ButtonLink></State>}
  </PageBody></PageFrame>;
}

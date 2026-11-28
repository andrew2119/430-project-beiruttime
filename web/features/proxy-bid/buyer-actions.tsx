'use client';
import {useState} from 'react';
import {Button,ButtonLink,Card,Input} from '@beirut-time/ui/foundation';
import {usePageRead} from '@/lib/page-speed/read';
import {inboxRead} from './inbox-read';
import {useLocale} from '@/shell/locale-context';
import en from './en.json';
import ar from './ar.json';

export function BuyerActions({fingerprint,authorizationEpoch}:{fingerprint:string;authorizationEpoch?:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [watch,setWatch]=useState('');
  const notices=usePageRead(inboxRead(fingerprint,null,authorizationEpoch));
  const unread=notices.isFetchedAfterMount!==false&&!notices.isError&&(notices.data?.unread_count??0)>0;
  return <Card>
    <div className="proxy-actions">
      <ButtonLink variant="outline" href={`/${locale}/inbox`}>
        {unread&&<span className="buyer-unread-dot" aria-label={t.unreadNotices}>●</span>}{t.supportInbox}
      </ButtonLink>
    </div>
    <form action={`/${locale}/checkout`} method="get">
      <Input label={t.watchReference} name="watch_id" value={watch} onValueChange={setWatch} required/>
      <input type="hidden" name="watch" value={watch.trim()}/>
      <Button type="submit" disabled={!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(watch.trim())}>{t.reviewWatch}</Button>
    </form>
  </Card>;
}

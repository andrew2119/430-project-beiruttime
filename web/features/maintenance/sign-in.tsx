'use client';
import { useRef, useState } from 'react';
import { Button, Input } from '@beirut-time/ui/foundation';
import { beginSession } from '@/features/identity/session';
import { useCopy } from './common';

export default function MaintenanceSignIn() {
  const {t}=useCopy();
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [pending,setPending]=useState(false);
  const [failed,setFailed]=useState(false);
  const operation=useRef<{body:string;key:string}|undefined>(undefined);
  const active=useRef(false);
  async function submit() {
    if(active.current)return;
    const body=JSON.stringify({email,password});
    if(operation.current?.body!==body)operation.current={body,key:crypto.randomUUID()};
    active.current=true;setPending(true);setFailed(false);
    try {
      await beginSession('login',body,operation.current.key);
      setPassword('');operation.current=undefined;
    } catch {setFailed(true);}
    finally {active.current=false;setPending(false);}
  }
  return <form onSubmit={event=>{event.preventDefault();void submit();}}>
    <fieldset disabled={pending}>
      <Input label={t('email')} type="email" autoComplete="username" required value={email} onValueChange={setEmail}/>
      <Input label={t('password')} type="password" autoComplete="current-password" required value={password} onValueChange={setPassword}/>
      <Button type="submit">{t(pending?'pending':'continueRequest')}</Button>
    </fieldset>
    {failed&&<p role="alert">{t('signInFailed')}</p>}
  </form>;
}

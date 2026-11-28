'use client';
import { useEffect, useRef, useState } from 'react';
import { PageHeader, PageFrame, PageBody } from '@/shell/foundation/page';
import './rebuilt.css';
import { useRouter } from 'next/navigation';
import { Button, ButtonLink, Card, Input, Segmented } from '@beirut-time/ui/foundation';
import { request, ApiError } from '@/lib/api/client';
import { beginSession, accountApi, refreshSession, safeReturnPath, signOut, useSession, useSessionState } from './session';
import { ErrorNotice, useIdentityCopy } from './shared';

type Mode = 'signin' | 'register' | 'recovery' | 'reset';
export default function AccountView({ initialMode = 'signin' }: { initialMode?: Mode }) {
  const session = useSession();
  const sessionState = useSessionState();
  const {locale} = useIdentityCopy();
  const router = useRouter();
  const [revokeFailed,setRevokeFailed] = useState(false);
  const [revoking,setRevoking] = useState(false);
  async function revoke() {
    setRevoking(true);
    try {await signOut();setRevokeFailed(false);}
    catch {setRevokeFailed(true);}
    finally {setRevoking(false);}
  }
  function authenticated() {
    const next = safeReturnPath(new URL(window.location.href).searchParams.get('next'));
    if(next !== '/account') router.push(`/${locale}${next}`);
  }
  const access = JSON.stringify([session?.account.id, session?.access_fingerprint, sessionState]);
  return <AccountContent key={access} initialMode={initialMode} session={session} sessionState={sessionState} revokeFailed={revokeFailed} revoking={revoking} revoke={revoke} authenticated={authenticated}/>;
}

function AccountContent({initialMode, session, sessionState, revokeFailed, revoking, revoke, authenticated}: {initialMode:Mode; session:ReturnType<typeof useSession>; sessionState:ReturnType<typeof useSessionState>; revokeFailed:boolean; revoking:boolean; revoke:()=>Promise<void>; authenticated:()=>void}) {
  const { locale, t } = useIdentityCopy();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<''|'recoverySent'|'passwordChanged'>('');
  const operation = useRef<{ body: string; key: string; endpoint: string; authorization?: string } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [unresolved, setUnresolved] = useState(false);
  useEffect(()=>()=>{ operation.current=null; },[]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending || unresolved) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const values: Record<string, string> = {};
    for (const [key,value] of data) if (typeof value === 'string') values[key] = value;
    if (values.password && (values.password.length > 128 || (mode !== 'signin' && values.password.length < 12))) { setError(new Error()); return; }
    const endpoint = mode === 'signin' ? 'login' : mode;
    if (mode === 'reset' && !values.token) values.token = window.location.hash.slice(1);
    if(mode==='recovery') values.locale=locale;
    if (!operation.current) operation.current = { body: JSON.stringify(values), key: crypto.randomUUID(), endpoint };
    await send(form);
  }
  async function send(form?: HTMLFormElement) {
    const saved = operation.current;
    if (!saved || pending) return;
    const {body,key,endpoint,authorization} = saved;
    setPending(true); setError(null); setMessage('');
    try {
      if (endpoint === 'login' || endpoint === 'register') {await beginSession(endpoint, body, key);authenticated();}
      else if(endpoint==='password' && unresolved) {
        try {await request(`${accountApi}/password`, {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key,Authorization:authorization!},body});}
        catch (failure) {
          if(failure instanceof ApiError && failure.code==='invalid_credentials') throw failure;
          await request(`${accountApi}/reset`, {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({...JSON.parse(body),action:'password_receipt',authorization})});}
      }
      else await request(`${accountApi}/${endpoint}`, { method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key,...(authorization?{Authorization:authorization}:{})},body });
      if(operation.current !== saved) return;
      form?.reset(); operation.current = null;setUnresolved(false);
      if (endpoint === 'recovery') setMessage('recoverySent');
      else if (endpoint === 'reset' || endpoint === 'password') { setMode('signin'); setMessage('passwordChanged'); window.history.replaceState(null,'',window.location.pathname); if(endpoint==='password') await signOut().catch(()=>undefined); }
      else {
        requestAnimationFrame(()=>heading.current?.focus());
      }
    } catch (failure) {
      if(operation.current !== saved) return;
      if(failure instanceof ApiError && failure.status>=400 && failure.status<500 && ![408,429].includes(failure.status)
          && (endpoint!=='password' || failure.code==='invalid_credentials' || !unresolved && failure.status!==401)) {operation.current=null;setUnresolved(false);} else setUnresolved(true);
      setError(failure);
    }
    finally { setPending(false); }
  }
  async function logout() {
    operation.current=null;setUnresolved(false);
    setPending(true); setError(null); setMode('signin');
    await revoke();
    setPending(false);
  }
  async function password(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending || unresolved) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const nextPassword = String(data.get('new_password') ?? '');
    if (nextPassword.length < 12 || nextPassword.length > 128) { setError(new Error()); return; }
    let fresh;
    try {fresh=await refreshSession();if(!fresh) throw new Error();} catch(failure) {setError(failure);return;}
    if (!operation.current) operation.current = {endpoint:'password',key:crypto.randomUUID(),
      authorization:`Bearer ${fresh.access_token}`,
      body:JSON.stringify({current_password:data.get('current_password'),new_password:data.get('new_password')})};
    await send(form);
  }

  return <PageFrame><noscript><p className="identity-demo">{t.javascriptRequired}</p></noscript><PageHeader lead={t.eyebrow} title={session ? t.welcome : t.title} count={t.intro}/>
    <PageBody><div className="account-grid"><div className="account-stack">
      <Card><h2 ref={heading} tabIndex={-1}>{session ? t.profile : t[mode]}</h2><div className="account-stack">
        {sessionState === 'restoring' && <p role="status">{t.loading}</p>}
        {sessionState === 'unavailable' && <div className="account-feedback" role="alert"><p>{t.unavailable}</p><Button variant="outline" onClick={()=>void refreshSession().catch(setError)}>{t.retry}</Button></div>}
        {session ? <div className="account-stack"><p>{session.account.display_name}</p><p><bdi>{session.account.email}</bdi></p><div className="account-actions"><ButtonLink href={`/${locale}/seller/verification`}>{t.apply}</ButtonLink><ButtonLink variant="outline" href={`/${locale}/consent`}>{t.consent}</ButtonLink></div><Button variant="outline" disabled={pending || revoking} onClick={logout}>{t.signout}</Button></div> : <>
          <div className="identity-tabs" inert={pending}><Segmented locale={locale} disabled={pending} value={mode} label={t.profile} options={(['signin','register','recovery'] as const).map(value=>({value,label:t[value]}))} onValueChange={value=>{setMode(value as Mode);setError(null);setMessage('');}}/></div>
          <form key={mode} method="post" onSubmit={submit} className="account-form" aria-busy={pending}>
            {mode==='register' && <Input label={t.name} name="display_name" autoComplete="name" required/>}
            {mode!=='reset' && <Input label={t.email} name="email" type="email" autoComplete="email" required/>}
            {mode==='reset' && <Input label={t.token} name="token" type="password" autoComplete="off"/>}
            {mode!=='recovery' && <Input label={mode==='reset'?t.newPassword:t.password} name="password" type="password" autoComplete={mode==='signin'?'current-password':'new-password'} hint={t.passwordHint} required/>}
            <Button type="submit" disabled={pending}>{pending?t.working:t.submit}</Button>
          </form>
        </>}
        <ErrorNotice error={error}/>{unresolved&&<Button disabled={pending} onClick={()=>void send()}>{t.retry}</Button>}{message&&<p className="account-feedback" role="status">{t[message]}</p>}
        {revokeFailed&&<div className="account-feedback" role="alert"><p>{t.logoutFailed}</p><Button disabled={pending || revoking} onClick={logout}>{t.signout}</Button></div>}
      </div></Card>
      {session&&<Card><h2>{t.security}</h2><form method="post" onSubmit={password} className="account-form"><input type="hidden" autoComplete="username" value={session.account.email} readOnly/><Input label={t.currentPassword} type="password" name="current_password" autoComplete="current-password" required/><Input label={t.newPassword} type="password" name="new_password" autoComplete="new-password" hint={t.passwordHint} required/><Button type="submit" disabled={pending}>{pending?t.working:t.changePassword}</Button></form></Card>}
    </div><aside className="account-stack"><Card><p className="eyebrow">{t.privacy}</p><h2>{t.privateSelling}</h2><p>{t.privateIntro}</p><p>{t.privacyBody}</p></Card><div className="identity-demo">{t.demo}</div></aside></div>
  </PageBody></PageFrame>;
}

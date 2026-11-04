'use client';
import { useEffect, useRef, useState } from 'react';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { AuthCard, AutoHeight } from '@beirut-time/ui';
import { useRouter } from 'next/navigation';
import { Button, ButtonLink, Card, Input, BidiReference, Segmented } from '@beirut-time/ui';
import { request } from '@/lib/api/client';
import { beginSession, accountApi, authenticatedRequest, refreshSession, safeReturnPath, signOut, useSession, useSessionState } from './session';
import { ErrorNotice, useIdentityCopy } from './shared';

type Mode = 'signin' | 'register' | 'recovery' | 'reset';
export default function AccountView({ initialMode = 'signin' }: { initialMode?: Mode }) {
  const { locale, t } = useIdentityCopy();
  const session = useSession();
  const sessionState = useSessionState();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState('');
  const [revokeFailed, setRevokeFailed] = useState(false);
  const operation = useRef<{ body: string; key: string } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(()=>{ operation.current=null; },[session?.access_fingerprint]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const values: Record<string, string> = {};
    for (const [key,value] of data) if (typeof value === 'string') values[key] = value;
    const endpoint = mode === 'signin' ? 'login' : mode;
    if (mode === 'reset' && !values.token) values.token = decodeURIComponent(window.location.hash.slice(1));
    const body = JSON.stringify(values);
    if (operation.current?.body !== body) operation.current = { body, key: crypto.randomUUID() };
    setPending(true); setError(null); setMessage('');
    try {
      if (endpoint === 'login' || endpoint === 'register') await beginSession(endpoint, body, operation.current.key);
      else await request(`${accountApi}/${endpoint}`, { method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':operation.current.key},body });
      form.reset(); operation.current = null;
      if (mode === 'recovery') setMessage(t.recoverySent);
      else if (mode === 'reset') { setMode('signin'); setMessage(t.passwordChanged); window.history.replaceState(null,'',window.location.pathname); }
      else {
        const next = safeReturnPath(new URL(window.location.href).searchParams.get('next'));
        if (next !== '/account') router.push(`/${locale}${next}`);
        else requestAnimationFrame(()=>heading.current?.focus());
      }
    } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }
  async function logout() {
    setPending(true); setError(null); setMode('signin');
    try { await signOut(); setRevokeFailed(false); }
    catch { setRevokeFailed(true); }
    finally { setPending(false); }
  }
  async function password(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setPending(true); setError(null);
    try {
      await authenticatedRequest(`${accountApi}/password`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({current_password:data.get('current_password'),new_password:data.get('new_password')}) });
      form.reset(); setMode('signin'); setMessage(t.passwordChanged);
      // The acknowledged password mutation already revoked every lineage; cleanup cannot undo it.
      await signOut().catch(()=>undefined);
    } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }
  return <PageLayout className="identity-page"><noscript><p className="identity-demo">{t.javascriptRequired}</p></noscript><PageHeader lead={t.eyebrow} title={session ? t.welcome : t.title} count={t.intro}/>
    <div className="identity-grid"><div className="identity-stack">
      <AuthCard authenticated={!!session} headingRef={heading} title={session ? t.profile : t[mode]}><div className="identity-stack">
        {sessionState === 'restoring' && <p role="status">{t.loading}</p>}
        {sessionState === 'unavailable' && <div className="identity-feedback" role="alert"><p>{t.unavailable}</p><Button variant="outline" onClick={()=>void refreshSession().catch(setError)}>{t.retry}</Button></div>}
        {session ? <div className="identity-stack"><p>{session.account.display_name}</p><p><BidiReference>{session.account.email}</BidiReference></p><div className="identity-actions"><ButtonLink href={`/${locale}/seller/verification`}>{t.apply}</ButtonLink><ButtonLink variant="outline" href={`/${locale}/consent`}>{t.consent}</ButtonLink></div><Button variant="outline" disabled={pending} onClick={logout}>{t.signout}</Button></div> : <>
          <div className="identity-tabs" inert={pending}><Segmented compact value={mode} aria-label={t.profile} options={(['signin','register','recovery'] as const).map(value=>({value,label:t[value]}))} onChange={value=>{setMode(value as Mode);setError(null);setMessage('');operation.current=null;}}/></div>
          <AutoHeight><form key={mode} method="post" onSubmit={submit} className="identity-form" aria-busy={pending}>
            {mode==='register' && <label>{t.name}<Input name="display_name" autoComplete="name" required maxLength={100}/></label>}
            {mode!=='reset' && <label>{t.email}<Input name="email" type="email" dir="ltr" autoComplete="email" required maxLength={254}/></label>}
            {mode==='reset' && <label>{t.token}<Input name="token" type="password" autoComplete="off" maxLength={200}/></label>}
            {mode!=='recovery' && <label>{mode==='reset'?t.newPassword:t.password}<Input name="password" type="password" autoComplete={mode==='signin'?'current-password':'new-password'} required minLength={mode==='signin'?1:12} maxLength={128}/>{mode!=='signin'&&<small>{t.passwordHint}</small>}</label>}
            <Button chonk disabled={pending}>{pending?t.working:t.submit}</Button>
          </form></AutoHeight><p className="identity-muted">{t.google}</p>
        </>}
        <ErrorNotice error={error}/>{message&&<p className="identity-feedback" role="status">{message}</p>}
        {revokeFailed&&<div className="identity-feedback" role="alert"><p>{t.logoutFailed}</p><Button disabled={pending} onClick={logout}>{t.signout}</Button></div>}
      </div></AuthCard>
      {session&&<Card><h2>{t.security}</h2><form method="post" onSubmit={password} className="identity-form"><input type="hidden" autoComplete="username" value={session.account.email} readOnly/><label>{t.currentPassword}<Input type="password" name="current_password" autoComplete="current-password" required maxLength={128}/></label><label>{t.newPassword}<Input type="password" name="new_password" autoComplete="new-password" minLength={12} maxLength={128} required/><small>{t.passwordHint}</small></label><Button disabled={pending}>{pending?t.working:t.changePassword}</Button></form></Card>}
    </div><aside className="identity-stack"><Card><p className="eyebrow">{t.privacy}</p><h2>{t.privateSelling}</h2><p>{t.privateIntro}</p><p>{t.privacyBody}</p></Card><div className="identity-demo">{t.demo}</div></aside></div>
  </PageLayout>;
}

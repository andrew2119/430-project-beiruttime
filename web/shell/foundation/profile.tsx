'use client';
import { useState } from 'react';
import { Avatar, Button, State, toast } from '@beirut-time/ui/foundation';
import { refreshSession, signOut, useSession, useSessionState } from '@/features/identity/session';
import type { Locale } from '@/lib/i18n';
import { ShellInstall } from './install';
import { LocaleControl } from './locale-control';
import { ThemeSwitch } from '@/shell/theme-switch';
import { DestinationLink } from './destination';
import { SHELL_COPY } from './copy';
export function ShellProfile({locale,path}: {locale:Locale;path:string}) {
  const session = useSession(), state = useSessionState(), t = SHELL_COPY[locale];
  const [pending,setPending] = useState(false), [revokeFailed,setRevokeFailed] = useState(false);
  const display = session?.account.display_name;
  const name = display?.trim() ? display : session ? t.account : state === 'restoring' ? t.restoring : t.visitor;
  return <div className="bt-shell-profile"><LocaleControl locale={locale}/><div className="bt-profile-identity"><Avatar name={name} label={name}/><p className="bt-text">{name}</p><ThemeSwitch lightLabel={t.light} darkLabel={t.dark}/></div>
    <DestinationLink href={`/${locale}/account`} label={session ? t.account : t.signIn} icon="account" path={path}/><DestinationLink href={`/${locale}/settings`} label={t.settings} icon="settings" path={path}/>
    <ShellInstall locale={locale}/>
    {state === 'unavailable' && <State kind="error" headingLevel={3} title={t.unavailable} body={t.retry}><Button variant="outline" onClick={()=>void refreshSession().catch(()=>toast.error(t.unavailable))}>{t.retry}</Button></State>}
    {(session || revokeFailed || pending) && <Button variant="ghost" busy={pending} onClick={async()=>{setPending(true);try {await signOut();setRevokeFailed(false);} catch {setRevokeFailed(true);toast.error(t.signOutError);} finally {setPending(false);}}}>{t.signOut}</Button>}
  </div>;
}

'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { Settings, SunMoon, UserCircle, LogOut } from 'lucide-react';
import { Button, toast } from '@beirut-time/ui';
import { signOut, useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { useTheme } from './theme-provider';
import { PwaInstall } from './pwa';
import { messages, type Locale } from '@/lib/i18n';
export function ProfileBlock({ locale }: { locale: Locale }) {
  const session=useSession(), state=useSessionState(), path=usePathname();
  const {theme,cycleTheme}=useTheme();
  const [pending,setPending]=useState(false);
  const [revokeFailed,setRevokeFailed]=useState(false);
  const ar=locale==='ar', t=messages(locale);
  const name=session?.account.display_name ?? (state==='restoring'?(ar?'جارٍ التحميل':'Loading'):state==='unavailable'?(ar?'تعذر الاتصال':'Connection unavailable'):(ar?'زائر':'Guest'));
  const role=session?.principal.roles[0];
  const roles:Record<string,string>=ar?{buyer:'مشتري',private_seller:'بائع خاص',dealer:'تاجر',brand:'علامة تجارية',operator:'مشغّل'}:{buyer:'Buyer',private_seller:'Private seller',dealer:'Dealer',brand:'Brand',operator:'Operator'};
  return <div className="pg-sidebar-foot">
    <div className="pg-profile-row"><span className="pg-profile-avatar" aria-hidden="true">{session?name.trim().split(/\s+/).map(n=>n[0]).slice(0,2).join('').toUpperCase():<UserCircle/>}</span><div className="pg-profile-copy"><div className="pg-profile-name">{name}</div><div className="pg-profile-role">{role?roles[role]??role:(ar?'تصفح السوق':'Browse the marketplace')}</div></div><Link href={`/${locale}/settings`} aria-label={ar?'الإعدادات':'Settings'} title={ar?'الإعدادات':'Settings'} aria-current={path.endsWith('/settings')?'page':undefined} className={`ui-btn ui-btn-ghost ui-btn-icon pg-profile-control proto-settings-btn`}><Settings aria-hidden="true"/></Link><Button size="icon" variant="ghost" className="pg-profile-control" onClick={cycleTheme} aria-label={theme==='light'?t.dark:t.light} title={theme==='light'?t.dark:t.light}><SunMoon aria-hidden="true"/></Button></div>
    <Link className="pg-nav-item pg-profile-link" href={`/${locale}/account`} aria-current={path.endsWith('/account')?'page':undefined}><UserCircle aria-hidden="true"/>{session?(ar?'الحساب':'Account'):(ar?'تسجيل الدخول':'Sign in')}</Link>
    {state==='unavailable' && <Button variant="ghost" size="sm" onClick={()=>void refreshSession().catch(()=>toast.error(ar?'تعذر استعادة الجلسة. حاول مجددًا.':'Could not restore the session. Try again.'))}>{ar?'إعادة المحاولة':'Try again'}</Button>}
    <PwaInstall t={t}/>
    {(session || revokeFailed) && <Button variant="ghost" className="pg-nav-item pg-profile-link" disabled={pending} onClick={async()=>{setPending(true);try{await signOut();setRevokeFailed(false);}catch{setRevokeFailed(true);toast.error(ar?'تعذر تأكيد تسجيل الخروج. أعد المحاولة.':'Could not confirm sign out. Please retry.');}finally{setPending(false);}}}><LogOut aria-hidden="true"/>{ar?'تسجيل الخروج':'Sign out'}</Button>}
  </div>;
}

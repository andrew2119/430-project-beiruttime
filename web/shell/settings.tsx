'use client';

import { useEffect, useState } from 'react';
import { Avatar, ButtonLink, Card, Segmented, Skeleton, State } from '@beirut-time/ui/foundation';
import { useSession, useSessionState } from '@/features/identity/session';
import { useTheme } from './theme-provider';
import { useLocale, useLocaleChange } from './locale-context';
import { PageFrame, PageHeader, PageBody, HeaderTabs } from '@/shell/foundation/page';
import { usePageTitle } from './foundation/page-title';
import { AnswerArrival } from '@/lib/page-speed/arrival';

export function SettingsPage() {
  const locale = useLocale(), ar = locale === 'ar', changeLocale = useLocaleChange();
  const session = useSession(), sessionState = useSessionState();
  const { theme, cycleTheme } = useTheme();
  usePageTitle(ar ? 'الإعدادات' : 'Settings', locale);
  const [section, setSection] = useState('profile');
  useEffect(() => {
    const tray = document.getElementById('main-content');
    if (!tray) return;
    const spy = () => {
      const line = tray.getBoundingClientRect().top + tray.clientHeight * .3;
      const active = ['profile','language','appearance'].filter(id => (document.getElementById(`settings-${id}`)?.getBoundingClientRect().top ?? Infinity) <= line).pop();
      if (active) setSection(active);
    };
    tray.addEventListener('scroll', spy, {passive:true});
    return () => tray.removeEventListener('scroll', spy);
  }, []);
  const profile = ar ? 'الملف الشخصي' : 'Profile';
  const language = ar ? 'اللغة' : 'Language';
  const appearance = ar ? 'المظهر' : 'Appearance';
  const sections = [{id:'profile',label:profile},{id:'language',label:language},{id:'appearance',label:appearance}];
  const sectionLinks = () => sections.map(item => <ButtonLink key={item.id} variant="ghost" href={`#settings-${item.id}`} aria-current={section === item.id ? 'location' : undefined}
    onClick={event => {if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;event.preventDefault();setSection(item.id);document.getElementById(`settings-${item.id}`)?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});}}>{item.label}</ButtonLink>);
  const sectionLabel = ar ? 'أقسام الإعدادات' : 'Settings sections';
  return <div className="bt-settings-page"><PageFrame>
    <PageHeader title={ar ? 'الإعدادات' : 'Settings'} lead={ar ? 'الملف الشخصي واللغة ومظهر بيروت تايم.' : 'Your profile, language and Beirut Time’s appearance.'}
      tabs={<div className="bt-settings-tabs"><HeaderTabs items={sections} value={section} label={sectionLabel} nav onChange={id => {
        setSection(id);
        document.getElementById(`settings-${id}`)?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
      }}/></div>}
      actions={<ButtonLink prefetch variant="outline" href={`/${locale}`}>{ar ? 'العودة إلى لوحة التحكم' : 'Back to dashboard'}</ButtonLink>}/>
    <PageBody><AnswerArrival view="settings"><div className="bt-settings-layout">
      <aside className="bt-settings-index"><Card><nav aria-label={sectionLabel}>{sectionLinks()}</nav><p className="bt-text">{ar ? 'تُحفظ تفضيلات المظهر واللغة في هذا المتصفح.' : 'Appearance and language are kept in this browser.'}</p></Card></aside>
      <div className="bt-page-example-stack">
      <section id="settings-profile"><Card><h2 className="bt-heading">{profile}</h2>
        {sessionState === 'restoring' ? <Skeleton size="title"/> : session ? <><Avatar name={session.account.display_name} label={profile}/><p className="bt-text">{session.account.display_name}</p><p className="bt-text"><bdi dir="ltr">{session.account.email}</bdi></p></> :
          <State kind={sessionState === 'unavailable' ? 'error' : 'empty'} headingLevel={3}
            title={sessionState === 'unavailable' ? (ar ? 'تعذر استعادة جلستك.' : 'Your session could not be restored.') : (ar ? 'تصفح كزائر' : 'Browse as a guest')}
            body={ar ? 'افتح الحساب لتسجيل الدخول أو إعادة المحاولة.' : 'Open Account to sign in or try again.'}/>}
        <ButtonLink prefetch variant="outline" href={`/${locale}/account`}>{session ? (ar ? 'إدارة الحساب' : 'Manage account') : (ar ? 'تسجيل الدخول' : 'Sign in')}</ButtonLink>
      </Card></section>
      <section id="settings-language"><Card><h2 className="bt-heading">{language}</h2>
        <Segmented label={language} value={locale} locale={locale} onValueChange={next => {if (next === 'en' || next === 'ar') changeLocale(next);}}
          options={[{value:'en',label:<span lang="en">English</span>},{value:'ar',label:<span lang="ar">العربية</span>}]}/>
        <p className="bt-text">{ar ? 'تتغير اللغة هنا مع الاحتفاظ بمدخلاتك واختياراتك دون إرسالها.' : 'Language changes here while keeping your inputs and selections without submitting them.'}</p>
      </Card></section>
      <section id="settings-appearance"><Card><h2 className="bt-heading">{appearance}</h2>
        <Segmented className="bt-settings-themes" label={appearance} value={theme} locale={locale} onValueChange={next => {if (next !== theme) cycleTheme();}}
          options={(['light','dark'] as const).map(mode => ({value:mode,label:<><span className="bt-settings-shot" data-theme={mode} aria-hidden="true"><span className="bt-settings-shot-rail"><i data-on/><i/><i/></span><span className="bt-settings-shot-tray"><span className="bt-settings-shot-card"><b/><i/><i data-short/></span><span className="bt-settings-shot-bar"><em/><i/></span></span></span><span className="bt-settings-theme-label">{mode === 'light' ? (ar ? 'فاتح' : 'Light') : (ar ? 'داكن' : 'Dark')}</span></>}))}/>
        <p className="bt-text">{ar ? 'تُحفظ تفضيلات المظهر واللغة في هذا المتصفح.' : 'Appearance and language are kept in this browser.'}</p>
      </Card></section>
    </div></div></AnswerArrival></PageBody>
  </PageFrame></div>;
}

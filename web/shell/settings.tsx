'use client';

import Link from 'next/link';
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, Languages, Palette, UserCircle } from 'lucide-react';
import { ButtonLink, Card, HeaderTabs, Segmented, SegmentedGroup, SegmentedItem, Skeleton } from '@beirut-time/ui';
import { useSession, useSessionState } from '@/features/identity/session';
import { useTheme } from './theme-provider';
import { useLocale,useChangeLocale } from './locale-context';
import { PageHeader, PageLayout } from './page-header';

function SettingsCard({ id, title, subtitle, icon: Icon, children }: {
  id: string; title: string; subtitle: string; icon: typeof UserCircle; children: ReactNode;
}) {
  return <Card id={id} className="proto-set-card pg-card">
    <header className="proto-set-card-head">
      <span className="proto-set-icon"><Icon aria-hidden="true"/></span>
      <div><h2 className="proto-set-h">{title}</h2><p className="proto-set-card-sub">{subtitle}</p></div>
    </header>
    <div className="proto-set-block">{children}</div>
  </Card>;
}

export function SettingsPage() {
  const locale=useLocale(),ar=locale==='ar',changeLocale=useChangeLocale();
  const session = useSession(), sessionState = useSessionState();
  const { theme, cycleTheme } = useTheme();
  const themeOptions = useRef<HTMLDivElement>(null);
  const focusAfterThemeChange = useRef(false);
  useLayoutEffect(() => {
    if (!focusAfterThemeChange.current) return;
    focusAfterThemeChange.current = false;
    themeOptions.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
  }, [theme]);
  const [section, setSection] = useState('profile');
  const [wide, setWide] = useState(true);
  useLayoutEffect(() => {
    const page = document.querySelector<HTMLElement>('.proto-set-page');
    if (!page) return;
    const measure = () => {
      const style = getComputedStyle(page);
      const content = page.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      setWide(content >= 56 * (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16));
    };
    measure();
    const observer = new ResizeObserver(measure); observer.observe(page);
    return () => observer.disconnect();
  }, []);
  const sections = [
    { id: 'profile', label: ar ? 'الملف الشخصي' : 'Profile', icon: UserCircle },
    { id: 'language', label: ar ? 'اللغة' : 'Language', icon: Languages },
    { id: 'appearance', label: ar ? 'المظهر' : 'Appearance', icon: Palette },
  ];
  const sectionLabel = ar ? 'أقسام الإعدادات' : 'Settings sections';
  const jump = (id: string) => {
    setSection(id);
    document.getElementById(`settings-${id}`)?.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  };
  useEffect(() => {
    const tray = document.querySelector('main.pg-tray');
    if (!tray) return;
    const spy = () => {
      const line = tray.getBoundingClientRect().top + tray.clientHeight * .3;
      const active = ['profile', 'language', 'appearance'].filter(id => (document.getElementById(`settings-${id}`)?.getBoundingClientRect().top ?? Infinity) <= line).pop();
      if (active) setSection(active);
    };
    tray.addEventListener('scroll', spy, { passive: true });
    return () => tray.removeEventListener('scroll', spy);
  }, []);
  const chooseLanguage = (next: string) => {
    if(next!==locale&&(next==='en'||next==='ar'))changeLocale(next);
  };

  return <PageLayout className="proto-set-page">
    <div className="proto-set-header">
      <PageHeader title={ar ? 'الإعدادات' : 'Settings'}
        lead={<Link className="hx-back" href={`/${locale}`}><ArrowLeft className="direction-arrow" aria-hidden="true"/>{ar ? 'العودة إلى لوحة التحكم' : 'Back to dashboard'}</Link>}
        count={ar ? 'الملف الشخصي واللغة ومظهر بيروت تايم.' : 'Your profile, language and Beirut Time’s appearance.'}
        nav={!wide ? <HeaderTabs items={sections} value={section} onChange={jump} label={sectionLabel} nav/> : undefined}/>
    </div>
    <div className="proto-set-layout">
      <aside className="proto-set-index pg-card">
        <SegmentedGroup activeKey={section} className="proto-set-index-nav" aria-label={sectionLabel}>
          {sections.map(s => <SegmentedItem key={s.id} active={s.id === section} aria-current={s.id === section ? 'location' : undefined} onClick={() => jump(s.id)} plain>
            <s.icon className="proto-set-nav-icon" aria-hidden="true"/>{s.label}
          </SegmentedItem>)}
        </SegmentedGroup>
        <div className="proto-set-index-foot"><p className="proto-set-desc">{ar ? 'تُحفظ تفضيلات المظهر واللغة في هذا المتصفح.' : 'Appearance and language are kept in this browser.'}</p></div>
      </aside>
      <div className="proto-set-stack">
        <SettingsCard id="settings-profile" title={sections[0].label} subtitle={ar ? 'حسابك وأمانه.' : 'Your account and security.'} icon={UserCircle}>
          {sessionState === 'restoring' ? <Skeleton className="h-16 w-full"/> : session ?
            <div className="bt-settings-profile"><span className="pg-profile-avatar" aria-hidden="true">{session.account.display_name.slice(0, 2).toUpperCase()}</span><div><h3 className="proto-set-h">{session.account.display_name}</h3><p className="proto-set-desc"><bdi dir="ltr">{session.account.email}</bdi></p></div></div> :
            <p className="proto-set-desc">{sessionState === 'unavailable' ? (ar ? 'تعذر استعادة جلستك. افتح الحساب لإعادة المحاولة.' : 'Your session could not be restored. Open Account to try again.') : (ar ? 'تصفح السوق كزائر، أو سجّل الدخول لإدارة حسابك.' : 'Browse as a guest, or sign in to manage your account.')}</p>}
          <ButtonLink variant="outline" href={`/${locale}/account`} className="mt-4">{session ? (ar ? 'إدارة الحساب' : 'Manage account') : (ar ? 'تسجيل الدخول' : 'Sign in')}</ButtonLink>
        </SettingsCard>
        <SettingsCard id="settings-language" title={sections[1].label} subtitle={ar ? 'لغة التطبيق في هذا المتصفح.' : 'The app’s language in this browser.'} icon={Languages}>
          <Segmented aria-label={sections[1].label} value={locale} onChange={chooseLanguage} options={[
            { value: 'en', label: <span lang="en">English</span>, plain: true },
            { value: 'ar', label: <span lang="ar">العربية</span>, plain: true },
          ]}/>
          <p className="proto-set-footnote">{ar ? 'تُعرض العربية من اليمين إلى اليسار.' : 'Arabic reads right to left.'}</p>
        </SettingsCard>
        <SettingsCard id="settings-appearance" title={sections[2].label} subtitle={ar ? 'مظهر بيروت تايم في هذا المتصفح.' : 'How Beirut Time looks in this browser.'} icon={Palette}>
          <div ref={themeOptions} role="radiogroup" aria-label={ar ? 'نمط الألوان' : 'Colour mode'} className="proto-set-themes bt-two-themes">
            {(['light', 'dark'] as const).map(mode => {
              const selected = theme === mode;
              const label = mode === 'light' ? (ar ? 'فاتح' : 'Light') : (ar ? 'داكن' : 'Dark');
              return <button key={mode} type="button" role="radio" aria-checked={selected} tabIndex={selected ? 0 : -1} className="proto-set-theme"
                onClick={() => { if (!selected) cycleTheme(); }}
                onKeyDown={event => {
                  if (['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
                    event.preventDefault();
                    // View Transition updates are asynchronous: move focus after React commits.
                    focusAfterThemeChange.current = true;
                    cycleTheme();
                  }
                }}>
                <span className="proto-set-shot" data-theme={mode} aria-hidden="true"><span className="proto-set-shot-rail"><i data-on/><i/><i/></span><span className="proto-set-shot-tray"><span className="proto-set-shot-card"><b/><i/><i data-short/></span><span className="proto-set-shot-bar"><em/><i/></span></span></span>
                <span className="proto-set-theme-foot"><span className="proto-set-radio" aria-hidden="true"/><span className="proto-set-row-title">{label}</span></span>
              </button>;
            })}
          </div>
          <p className="proto-set-footnote">{ar ? 'يُحفظ اختيارك في هذا المتصفح.' : 'Your choice is kept in this browser.'}</p>
        </SettingsCard>
      </div>
    </div>
  </PageLayout>;
}

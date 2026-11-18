'use client';
import { LocaleControl } from './foundation/locale-control';
import { ThemeSwitch } from './theme-switch';
import { messages, type Locale, type Messages } from '@/lib/i18n';
import { useLocale } from './locale-context';
export function Preferences(props: {locale:Locale;theme:'light'|'dark';t:Messages}) {
  const locale = useLocale(props.locale), t = messages(locale);
  return <div className="preferences"><LocaleControl locale={locale}/><ThemeSwitch lightLabel={t.light} darkLabel={t.dark}/></div>;
}

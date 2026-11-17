'use client';
import type { Locale } from '@beirut-time/i18n';
import { Button } from '@beirut-time/ui/foundation';
import { useLocale, useLocaleChange } from '../locale-context';

export function LocaleControl({locale: fallback = 'en'}: {locale?: Locale}) {
  const locale = useLocale(fallback), changeLocale = useLocaleChange();
  const other = locale === 'en' ? 'ar' : 'en';
  return <Button className="bt-locale-control" variant="ghost" onClick={() => changeLocale(other)}>
    <span lang={other}>{other === 'ar' ? 'العربية' : 'English'}</span>
  </Button>;
}

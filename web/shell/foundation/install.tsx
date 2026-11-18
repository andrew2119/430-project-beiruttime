'use client';

import { useState } from 'react';
import { Button, Popover, PopoverTrigger, PopoverContent } from '@beirut-time/ui/foundation';
import { useInstallPrompt } from '../install-prompt-provider';
import { messages, type Locale } from '@/lib/i18n';

export function ShellInstall({locale}: {locale: Locale}) {
  const {canInstall, promptInstall, isStandalone, isIOS} = useInstallPrompt();
  const [open, setOpen] = useState(false), t = messages(locale);
  if (isStandalone || !canInstall && !isIOS) return null;
  if (canInstall) return <Button variant="ghost" onClick={() => void promptInstall()}>{t.install}</Button>;
  return <Popover open={open} onOpenChange={setOpen}><PopoverTrigger label={t.install}>{t.install}</PopoverTrigger>
    <PopoverContent label={t.install} closeLabel={locale === 'ar' ? 'إغلاق' : 'Close'}><p className="bt-text">{t.iosInstall}</p></PopoverContent>
  </Popover>;
}

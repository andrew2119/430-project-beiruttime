'use client';
import type { ReactNode } from 'react';
import type { Locale } from '@beirut-time/i18n';
import { LocaleProvider } from '../locale-context';
import { InstallPromptProvider } from '../install-prompt-provider';

/** The shell owns the single memory-only read scope below this preference layer. */
export function FoundationProviders({locale, children}: {locale: Locale; children: ReactNode}) {
  return <LocaleProvider locale={locale}><InstallPromptProvider>{children}</InstallPromptProvider></LocaleProvider>;
}

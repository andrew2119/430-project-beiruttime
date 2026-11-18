'use client';
import type { ReactNode } from 'react';
import type { Locale } from '@beirut-time/i18n';
import { FoundationProviders } from './foundation/providers';
export function Providers({locale,children}: {locale:Locale;children:ReactNode}) {
  return <FoundationProviders locale={locale}>{children}</FoundationProviders>;
}

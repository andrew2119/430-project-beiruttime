'use client';
import type { ReactNode } from 'react';
import { ButtonLink, State } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { usesFoundationShell } from '@/shell/foundation/path';
import { useLocale } from '@/shell/locale-context';
import en from './en.json';
import ar from './ar.json';
/** The shared shell owns the single read provider and route adoption. */
export function DirectoryAvailability({children}:{children:ReactNode}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  if(usesFoundationShell('/services'))return children;
  return <PageFrame><PageHeader title={t.title} lead={t.eyebrow}/><PageBody><State kind="error" title={t.updateUnavailable} body={t.updateRecovery}><ButtonLink href={`/${locale}/services`}>{t.retry}</ButtonLink></State></PageBody></PageFrame>;
}

'use client';
import { useEffect } from 'react';
import type { Locale } from '@beirut-time/i18n';

export function usePageTitle(title: string, locale: Locale) {
  useEffect(() => {document.title = `${title} · ${locale === 'ar' ? 'بيروت تايم' : 'Beirut Time'}`;}, [title, locale]);
}

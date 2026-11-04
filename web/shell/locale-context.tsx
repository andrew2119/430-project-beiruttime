'use client';
import { createContext, useContext } from 'react';
import type { Locale } from '@beirut-time/i18n';
export const LocaleContext = createContext<Locale>('en');
export const useLocale = () => useContext(LocaleContext);

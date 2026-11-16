'use client';
import { createContext, useContext } from 'react';
import type { Locale } from '@beirut-time/i18n';
export const LocaleContext = createContext<Locale|undefined>(undefined);
export const useLocale = (fallback:Locale='en') => useContext(LocaleContext)??fallback;
export const LocaleActionsContext = createContext<(locale:Locale)=>void>(()=>{});
export const useChangeLocale = () => useContext(LocaleActionsContext);

'use client';
import { Toaster } from '@beirut-time/ui';
import { useTheme } from './theme-provider';
export function AppToaster({ locale }: { locale: 'en' | 'ar' }) { const { theme }=useTheme(); return <Toaster theme={theme} dir={locale==='ar'?'rtl':'ltr'}/>; }

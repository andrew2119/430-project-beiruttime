import Link from 'next/link';
import type { Locale } from '@/lib/i18n';
export function Brand({ locale, label }: { locale: Locale; label: string }) {
  return <Link href={`/${locale}`} className="pg-brand"><svg className="bt-brand-mark" viewBox="0 0 43 32" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M17 7V2h9v5M17 25v5h9v-5"/><circle cx="21.5" cy="16" r="10"/><path d="M21.5 10v6l4 2M32 14h2v4h-2"/></svg><span>{label}</span></Link>;
}

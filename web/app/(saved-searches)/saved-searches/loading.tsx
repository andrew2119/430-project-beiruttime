'use client';
import { PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { en, ar } from '@/features/saved-searches/copy';

export default function Loading() {
  const locale = useLocale();
  return <PageLoading label={(locale === 'ar' ? ar : en).loading}/>;
}

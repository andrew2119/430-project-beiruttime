'use client';

import { Button, Card, State } from '@beirut-time/ui/foundation';
import type { BrandJobReceipt } from '@contracts/contracts-orders/brand-jobs';

const copy = {
  en: {
    authorized: 'Job authorized', denied: 'Access denied', stale: 'Scope has changed',
    pending: 'Authorization pending', unavailable: 'Authorization unavailable',
    loading: 'Checking current authorization', empty: 'No authorization yet',
    body: 'Approval alone does not start work. Current accepted scope, held payment, watch allocation and qualified assignment are required.',
    reconcile: 'Keep this action reference and ask the responsible operator to reconcile the result. Do not start work from this receipt.',
    recovery: 'Current authorization is unavailable. Retry with the same action reference.',
    retry: 'Check the same action again', reference: 'Action reference',
  },
  ar: {
    authorized: 'تم تفويض العمل', denied: 'الوصول مرفوض', stale: 'تغيّر نطاق العمل',
    pending: 'تفويض العمل قيد الانتظار', unavailable: 'تفويض العمل غير متاح',
    loading: 'جارٍ التحقق من التفويض الحالي', empty: 'لا يوجد تفويض بعد',
    body: 'الموافقة وحدها لا تبدأ العمل. يلزم نطاق مقبول حالي ودفع محتجز وتخصيص الساعة وتعيين شخص مؤهل.',
    reconcile: 'احتفظ بمرجع الإجراء واطلب من المسؤول مطابقة النتيجة. لا تبدأ العمل اعتماداً على هذا الإيصال.',
    recovery: 'التفويض الحالي غير متاح. أعد المحاولة بمرجع الإجراء نفسه.',
    retry: 'التحقق من الإجراء نفسه مجدداً', reference: 'مرجع الإجراء',
  },
};

/** Parent clears private receipts when current identity or access changes. */
export function BrandJobStatus({ locale, receipt, loading, unavailable, operationId, onRetry }: {
  locale: 'en' | 'ar'; receipt: BrandJobReceipt | null; loading: boolean;
  unavailable: boolean; operationId: string; onRetry: (operationId: string) => void;
}) {
  const t = copy[locale];
  const state = loading ? 'loading' : unavailable ? 'unavailable' : receipt?.state;
  return <Card><State title={state ? t[state] : t.empty}
    body={state === 'unavailable' ? t.recovery : receipt ? t.reconcile : t.body}
    kind={loading || state === 'pending' ? 'loading' : state === 'denied' || state === 'unavailable' ? 'error' : 'empty'}>
    {operationId && <><p>{t.reference}: <bdi>{operationId}</bdi></p>
      <Button disabled={loading} onClick={() => onRetry(operationId)}>{t.retry}</Button></>}
  </State></Card>;
}

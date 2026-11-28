'use client';

import { useEffect, useState } from 'react';
import { Button, State } from '@beirut-time/ui/foundation';
import type { Locale } from '@beirut-time/i18n';

/** One registration uses the existing public-only worker and notification seam. */
export function ShellUpdates({locale}: {locale: Locale}) {
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production' || !('serviceWorker' in navigator)) return;
    let disposed = false, remove: (() => void) | undefined;
    navigator.serviceWorker.register('/sw.js', {updateViaCache:'none'}).then(registration => {
      if (disposed) return;
      const inspect = () => {if (registration.waiting && navigator.serviceWorker.controller) setWaiting(registration.waiting);};
      const found = () => {
        const installing = registration.installing;
        installing?.addEventListener('statechange', inspect);
        const previous = remove;
        remove = () => {previous?.(); installing?.removeEventListener('statechange', inspect);};
      };
      registration.addEventListener('updatefound', found);
      remove = () => registration.removeEventListener('updatefound', found);
      inspect(); found();
    }).catch(() => {});
    return () => {disposed = true; remove?.();};
  }, []);
  if (!waiting) return null;
  const ar = locale === 'ar';
  return <State kind="empty" headingLevel={2} title={ar ? 'يتوفر تحديث' : 'An update is available'}
    body={ar ? 'أكمل عملك قبل إعادة التحميل. لن تُحفظ المدخلات غير المرسلة تلقائيًا.' : 'Finish your work before reloading. Unsent inputs will not be saved automatically.'}>
    <Button variant="outline" onClick={() => {
      navigator.serviceWorker.addEventListener('controllerchange', () => window.location.reload(), {once:true});
      waiting.postMessage('SKIP_WAITING');
    }}>{ar ? 'تحديث وإعادة تحميل' : 'Update and reload'}</Button>
  </State>;
}

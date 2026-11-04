'use client';
import { useEffect, useState, useSyncExternalStore } from 'react';
import type { Messages } from '@/lib/i18n';
import { Button } from './primitives';
type InstallEvent = Event & { prompt(): Promise<void>; userChoice: Promise<{ outcome: string }> };
const subscribe = (callback: () => void) => { window.addEventListener('online', callback); window.addEventListener('offline', callback); return () => { window.removeEventListener('online', callback); window.removeEventListener('offline', callback); }; };
export function Pwa({ t }: { t: Messages }) {
  const online = useSyncExternalStore(subscribe, () => navigator.onLine !== false, () => true);
  const [install, setInstall] = useState<InstallEvent | null>(null);
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  useEffect(() => {
    const prompt = (event: Event) => { event.preventDefault(); setInstall(event as InstallEvent); };
    const installed = () => setInstall(null);
    window.addEventListener('beforeinstallprompt', prompt);
    window.addEventListener('appinstalled', installed);
    let disposed = false;
    let interval: ReturnType<typeof setInterval> | undefined;
    if (process.env.NODE_ENV === 'production' && 'serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).then(registration => {
        if (disposed) return;
        const inspect = () => { if (registration.waiting && navigator.serviceWorker.controller) setWaiting(registration.waiting); };
        inspect();
        registration.addEventListener('updatefound', () => registration.installing?.addEventListener('statechange', inspect));
        interval = setInterval(() => { if (document.visibilityState === 'visible') void registration.update().catch(() => {}); }, 3600000);
      }).catch(() => {});
    }
    return () => { disposed = true; if (interval) clearInterval(interval); window.removeEventListener('beforeinstallprompt', prompt); window.removeEventListener('appinstalled', installed); };
  }, []);
  function update() {
    if (!waiting) return;
    let reloaded = false;
    const reload = () => { if (!reloaded) { reloaded = true; location.reload(); } };
    navigator.serviceWorker.addEventListener('controllerchange', reload, { once: true });
    waiting.postMessage('SKIP_WAITING');
    // User consented; a busy superseded worker must not strand this update.
    setTimeout(() => { if (!reloaded) void navigator.serviceWorker.getRegistration().then(r => r?.unregister()).finally(reload); }, 4000);
  }
  return <div className="pwa-controls">
    {!online && <p role="status" className="notice">{t.offline}</p>}
    {install ? <Button className="button-secondary" onClick={async () => { await install.prompt(); await install.userChoice; setInstall(null); }}>{t.install}</Button> : <small>{t.iosInstall}</small>}
    {waiting && <div className="notice" role="status"><p>{t.update}</p><Button onClick={update}>{t.updateAction}</Button></div>}
  </div>;
}

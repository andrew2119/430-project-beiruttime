/* CP F-55/F-56: public assets only. Never cache HTML, API, RSC or credentials. */
const CACHE = 'bt-public-v2';
const LIMIT = 160;
// CP's self-contained offline face intentionally uses a platform font: no network required.
const OFFLINE_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    <meta name="theme-color" content="#8B1A1A">
    <title>Offline · Beirut Time</title>
    <style>
      :root { color-scheme: light; }
      * { box-sizing: border-box; }
      body {
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
        padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
        background: oklch(95.8% 0.015 90.2);
        color: oklch(37.6% 0.022 64.3);
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      main {
        display: flex;
        width: min(100%, 24rem);
        flex-direction: column;
        align-items: center;
        padding: 40px 32px 32px;
        border-radius: 16px;
        background: oklch(99.1% 0.01 87.5);
        box-shadow: 0 0 0 1px oklch(0% 0 0 / 8%), 0 2px 4px oklch(0% 0 0 / 4%), 0 6px 12px -3px oklch(0% 0 0 / 6%);
        text-align: center;
      }
      .icon {
        display: grid;
        width: 56px;
        height: 56px;
        margin-bottom: 16px;
        place-items: center;
        border-radius: 16px;
        background: oklch(92.4% 0.019 83.1);
        color: oklch(53.9% 0.039 71.2);
      }
      h1 { margin: 0; font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.2; }
      p { margin: 8px 0 0; color: oklch(53.9% 0.039 71.2); font-size: 0.8125rem; line-height: 1.5; }
      form { align-self: stretch; margin-top: 24px; }
      button {
        width: 100%;
        min-height: 44px;
        padding: 0 20px;
        border: 0;
        border-radius: 10px;
        background: #8B1A1A;
        color: #f5f1e6;
        font: inherit;
        font-size: 0.875rem;
        font-weight: 700;
        cursor: pointer;
      }
      button:focus-visible { outline: 2px solid #8B1A1A; outline-offset: 2px; }
    </style>
  </head>
  <body>
    <main role="status">
      <div class="icon" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h.01"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/><path d="M5 12.859a10 10 0 0 1 5.17-2.69"/><path d="M19 12.859a10 10 0 0 0-2.007-1.523"/><path d="M2 8.82a15 15 0 0 1 4.177-2.643"/><path d="M22 8.82a15 15 0 0 0-11.288-3.764"/><path d="m2 2 20 20"/></svg>
      </div>
      <h1>You're offline</h1>
      <p>Purchases and bids have not been confirmed.</p>
      <p lang="ar" dir="rtl">أنت غير متصل. لم يتم تأكيد المشتريات والمزايدات.</p>
      <form method="get" action="">
        <button type="submit">Try again · حاول مجدداً</button>
      </form>
    </main>
  </body>
</html>`;
self.addEventListener('install', () => {}); // No unsolicited skipWaiting.
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const name of await caches.keys()) if (name.startsWith('bt-public-') && name !== CACHE) await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
  if (event.data === 'PURGE_PUBLIC_CACHE') event.waitUntil(caches.delete(CACHE).then(() => event.ports[0]?.postMessage('purged')));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => new Response(OFFLINE_HTML, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } })));
    return;
  }
  if (!url.pathname.startsWith('/_next/static/') && !/^\/icons\/bt-[\w-]+\.png$/.test(url.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(request);
    if (hit) return hit;
    const response = await fetch(request);
    if (response.ok && response.type === 'basic') {
      const copy = response.clone();
      void cache.put(request, copy).then(async () => {
        const keys = await cache.keys();
        for (const key of keys.slice(0, Math.max(0, keys.length - LIMIT))) await cache.delete(key);
      }).catch(() => {});
    }
    return response;
  })());
});

/* CP F-55/F-56: public assets only. Never cache HTML, API, RSC or credentials. */
const CACHE = 'bt-public-v1';
const LIMIT = 160;
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
    event.respondWith(fetch(request).catch(() => new Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Beirut Time · Offline</title><body style="font:18px system-ui;padding:32px;max-width:480px;margin:auto"><h1>Beirut Time</h1><p>You are offline. Purchases and bids have not been confirmed.</p><p lang="ar" dir="rtl">أنت غير متصل. لم يتم تأكيد المشتريات والمزايدات.</p><a href="/" style="display:inline-block;padding:16px">Try again · حاول مجدداً</a></body></html>', { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } })));
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

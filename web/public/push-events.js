/* Imported by the existing worker; never register this file as a root worker. */
self.addEventListener('push', event => {
  let data;
  try { data = event.data?.json(); } catch { return; }
  if (data?.schema_version !== 'browser-push.v1' || data.kind !== 'notice') return;
  event.waitUntil(self.registration.showNotification('Beirut Time · بيروت تايم', {
    body: 'A notice is available in your inbox. يوجد إشعار في صندوق الوارد.',
    tag: 'bt-inbox', renotify: false,
    data: { destination: '/inbox' }
  }));
});
self.addEventListener('notificationclick', event => {
  if (event.notification.tag !== 'bt-inbox') return;
  event.notification.close();
  // The inbox authenticates again and checks each record when opened.
  event.waitUntil(self.clients.openWindow(new URL('/inbox', self.location.origin).href));
});

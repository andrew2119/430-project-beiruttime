import type { MessagePhotos, PhotoPage, PhotoResult, PhotoScope } from '@contracts/contracts-comms/message-photos';
/** Composition provides authenticated, access-fenced transport for both response modes. */
export type PhotoTransport = <T>(path: string, options: RequestInit, format: 'json' | 'blob') => Promise<T>;
export function photoProvider(scope: PhotoScope, transport: PhotoTransport): MessagePhotos {
  const base = '/api/web/v1/communications/v1/message-photos';
  const path = (suffix: string, extra: Record<string, string> = {}) => `${base}${suffix}?${new URLSearchParams({
    business: scope.business, thread: scope.thread, watch: scope.watch, expected_revision: String(scope.revision), ...extra,
  })}`;
  const options = (signal: AbortSignal): RequestInit => ({ signal, cache: 'no-store', credentials: 'same-origin' });
  return {
    upload: (file, operation, signal) => transport<PhotoResult>(path('/uploads', { operation, purpose: 'watch_detail', declaration: 'true' }), {
      ...options(signal), method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' },
    }, 'json'),
    attach: (photo, operation, signal) => transport<PhotoResult>(path('/attachments'), {
      ...options(signal), method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo, operation, purpose: 'watch_detail', declaration: true }),
    }, 'json'),
    list: (offset, signal) => transport<PhotoPage>(path('', { offset: String(offset), limit: '20' }), options(signal), 'json'),
    operation: (operation, signal) => transport<PhotoResult>(path(`/operations/${encodeURIComponent(operation)}`), options(signal), 'json'),
    bytes: (photo, signal) => transport<Blob>(path(`/${encodeURIComponent(photo)}/bytes`), options(signal), 'blob'),
  };
}

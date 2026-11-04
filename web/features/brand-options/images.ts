import { ApiError } from '@/lib/api/client';

// Shell CSP permits data: PNGs, not blob: URLs. This result is private, memory-only UI state.
export async function readPrivatePng(blob: Blob, signal: AbortSignal): Promise<string> {
  signal.throwIfAborted();
  if (blob.type !== 'image/png' || blob.size > 1048576) throw new ApiError(422, 'unsafe_reference', '');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    let settled = false;
    const finish = (action: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', cancel);
      reader.onload = null; reader.onerror = null; reader.onabort = null;
      action();
    };
    const cancel = () => {
      finish(() => reject(signal.reason ?? new DOMException('Aborted', 'AbortError')));
      if (reader.readyState === FileReader.LOADING) reader.abort();
    };
    reader.onload = () => {
      const value = reader.result;
      if (typeof value === 'string' && value.startsWith('data:image/png;base64,')) finish(() => resolve(value));
      else finish(() => reject(new ApiError(503, 'reference_unavailable', '')));
    };
    reader.onerror = () => finish(() => reject(new ApiError(503, 'reference_unavailable', '')));
    reader.onabort = cancel;
    signal.addEventListener('abort', cancel, {once:true});
    try { reader.readAsDataURL(blob); }
    catch { finish(() => reject(new ApiError(503, 'reference_unavailable', ''))); }
  });
}

import type { MessagePhotos, PhotoResult } from '@contracts/contracts-comms/message-photos';
/** One mounted draft owns both references, including an uncertain upload response. */
export class PhotoAction {
  readonly upload: string;
  readonly attach: string;
  photo?: string;
  constructor(reference: () => string) { this.upload = reference(); this.attach = reference(); }
  async run(provider: MessagePhotos, file: File, signal: AbortSignal): Promise<PhotoResult> {
    signal.throwIfAborted();
    if (!this.photo) {
      const result = await withSignal(provider.upload(file, this.upload, signal), signal);
      if (signal.aborted || result.state !== 'uploaded' || !result.photo) return result;
      this.photo = result.photo;
    }
    signal.throwIfAborted();
    return withSignal(provider.attach(this.photo, this.attach, signal), signal);
  }
}

/** Stop waiting at the request deadline even if a provider cannot cancel its work. */
export function withSignal<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(signal.reason ?? new Error('unavailable'));
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
    work.then(value => { if (!signal.aborted) resolve(value); }, reject)
      .finally(() => signal.removeEventListener('abort', abort));
  });
}

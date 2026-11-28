import {ApiError} from '@/lib/api/client';

export type ConfirmMissingQuote = (quoteId: string, access: string, signal: AbortSignal) => Promise<boolean>;

/** The Pricing and gateway 404 codes overlap. Confirm absence through Pricing's own read. */
export async function confirmMissingQuote(quoteId: string, token: string, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return false;
  try {
    const response = await fetch(`/api/web/v1/pricing/v1/quotes/${encodeURIComponent(quoteId)}`, {
      headers: {Accept: 'application/json', Authorization: 'Bearer ' + token},
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.any([signal, AbortSignal.timeout(1500)]),
    });
    if (response.status !== 404) {
      void response.body?.cancel().catch(() => {});
      if (response.status === 401 || response.status === 403) {
        throw new ApiError(response.status, 'quote_read_denied', '');
      }
      return false;
    }
    const {error} = await response.json();
    return !signal.aborted && error?.code === 'not_found' && error.message === 'Quote not found.';
  } catch (error) {
    if (error instanceof ApiError) throw error;
    return false;
  }
}

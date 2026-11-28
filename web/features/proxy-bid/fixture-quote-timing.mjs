const PREVIEW_LIFETIME_MS = 15 * 60 * 1000;

export function quotePreviewTiming(serverTime) {
  const created = Date.parse(serverTime);
  return {
    created_at: new Date(created).toISOString(),
    expires_at: new Date(created + PREVIEW_LIFETIME_MS).toISOString(),
  };
}

export function quotePreviewExpired(quote, serverTime) {
  return Date.parse(serverTime) >= Date.parse(quote.expires_at);
}

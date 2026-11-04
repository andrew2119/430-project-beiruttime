import { requestBlob, ApiError } from "@/lib/api/client";
import {
  authenticatedRequest,
  refreshSession,
} from "@/features/identity/session";
import type {
  Listing,
  WatchFacts,
  Media,
  Page,
  FeeQuote,
  SellerWorkspace,
} from "@contracts/contracts-catalog/listings/v1";
import type {Session} from '@contracts/contracts-identity/accounts';
const base = "/api/web/v1/catalog/v1/seller/listings";
function headers(revision?: number, operation?: string) {
  return {
    ...(revision ? { "If-Match": String(revision) } : {}),
    ...(operation ? { "Idempotency-Key": operation } : {}),
  };
}
export function scopedHref(path: string, organization: string | null) {
  return organization
    ? path +
        (path.includes("?") ? "&" : "?") +
        "organization_id=" +
        encodeURIComponent(organization)
    : path;
}
function scope(path: string) {
  const organization =
    typeof window === "undefined"
      ? null
      : new URLSearchParams(window.location.search).get("organization_id");
  return scopedHref(path, organization);
}
function request<T>(path: string, options: RequestInit = {}) {
  return authenticatedRequest<T>(scope(path), options);
}
async function authorizedBlob(path: string,current:Session|null) {
  // Identity owns credential rotation/lineage. File bytes stay only in the
  // requesting feature's short-lived memory; no credentials/evidence persistence.
  let session = current??await refreshSession();
  if (!session) throw new ApiError(401, "unauthorized", "");
  try {
    return await requestBlob(scope(path), {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    session = await refreshSession();
    if (!session) throw new ApiError(401, "unauthorized", "");
    return requestBlob(scope(path), {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
  }
}
export const listingApi = {
  list: (cursor?: string) =>
    request<Page>(
      base + (cursor ? "?before=" + encodeURIComponent(cursor) : ""),
      { headers: headers() },
    ),
  read: (id: string) =>
    request<Listing>(`${base}/${id}`, { headers: headers() }),
  create: (operation: string) =>
    request<Listing>(base, {
      method: "POST",
      headers: {
        ...headers(undefined, operation),
        "Content-Type": "application/json",
      },
      body: "{}",
    }),
  save: (row: Listing, facts: WatchFacts, operation: string) =>
    request<Listing>(`${base}/${row.id}`, {
      method: "PUT",
      headers: {
        ...headers(row.revision, operation),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ facts }),
    }),
  media: (id: string) =>
    request<{ items: Media[] }>(`${base}/${id}/media`, { headers: headers() }),
  upload: (row: Listing, file: File, kind: Media["kind"], operation: string) =>
    request<{ asset_id: string; listing: Listing }>(
      `${base}/${row.id}/media?kind=${kind}&public_safe=true`,
      {
        method: "POST",
        headers: {
          ...headers(row.revision, operation),
          "Content-Type": "application/octet-stream",
        },
        body: file,
      },
    ),
  file: (id: string, asset: string,session:Session|null) =>
    authorizedBlob(`${base}/${id}/media/${asset}`,session),
  remove: (row: Listing, asset: string, operation: string) =>
    request<Listing>(`${base}/${row.id}/media/${asset}`, {
      method: "DELETE",
      headers: headers(row.revision, operation),
    }),
  gallery: (
    row: Listing,
    photo_ids: string[],
    cover_id: string,
    operation: string,
  ) =>
    request<Listing>(`${base}/${row.id}/gallery`, {
      method: "PUT",
      headers: {
        ...headers(row.revision, operation),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ photo_ids, cover_id }),
    }),
  quote: (row: Listing, operation: string) =>
    request<FeeQuote>("/api/web/v1/pricing/v1/quotes", {
      method: "POST",
      headers: {
        ...headers(undefined, operation),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        listing_id: row.id,
        listing_revision: row.revision,
        price_minor: row.facts.price_minor,
        currency: row.facts.currency,
      }),
    }),
  publish: (row: Listing, quote: FeeQuote, operation: string) =>
    request<Listing>(`${base}/${row.id}/publish`, {
      method: "POST",
      headers: {
        ...headers(row.revision, operation),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        fee_quote_id: quote.id,
        rules_version: quote.rules_version,
      }),
    }),
  workspace: () =>
    request<SellerWorkspace>("/api/web/v1/communications/v1/seller/workspace", {
      headers: headers(),
    }),
};

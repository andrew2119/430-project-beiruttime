import { request } from '@/lib/api/client';
import type { AuctionRead, HistoryPage, SearchPage, WatchDetail } from '@contracts/contracts-catalog/discovery';
import { requestSearch, type SearchState } from './url-state';
const base='/api/web/v1/catalog/v1/discovery/watches';
export const discoveryApi = {
  search: (state: SearchState, signal?: AbortSignal) => request<SearchPage>(`${base}?${requestSearch(state)}`,{signal}),
  sellerListings: (id: string, cursor: string, signal?: AbortSignal) => request<SearchPage>(`${base}?${new URLSearchParams({seller_id:id,cursor})}`,{signal}),
  detail: (id: string, signal?: AbortSignal) => request<WatchDetail>(`${base}/${encodeURIComponent(id)}`,{signal}),
  history: (id: string, cursor: string, listingRevision: number, revision: number, signal?: AbortSignal) => request<HistoryPage>(`${base}/${encodeURIComponent(id)}/history?${new URLSearchParams({cursor,listing_revision:String(listingRevision),revision:String(revision)})}`,{signal}),
  auction: (id: string, signal?: AbortSignal) => request<AuctionRead>(`${base}/${encodeURIComponent(id)}/auction`,{signal}),
};

import { request } from '@/lib/api/client';
import type { AuctionRead, SearchPage, WatchDetail } from '@contracts/contracts-catalog/discovery';
import { normalizeDigits } from '@beirut-time/i18n';
import { writeSearch, type SearchState } from './url-state';
const base='/api/web/v1/catalog/v1/discovery/watches';
export const discoveryApi = {
  search: (state: SearchState, signal?: AbortSignal) => request<SearchPage>(`${base}?${writeSearch({...state,min_minor:normalizeDigits(state.min_minor),max_minor:normalizeDigits(state.max_minor)})}`,{signal}),
  detail: (id: string, signal?: AbortSignal) => request<WatchDetail>(`${base}/${encodeURIComponent(id)}`,{signal}),
  auction: (id: string, signal?: AbortSignal) => request<AuctionRead>(`${base}/${encodeURIComponent(id)}/auction`,{signal}),
};

export type Money = { amount: string; currency: 'USD' };
export type Photo = { id: string; url: string; alt: string; alt_ar?: string | null; credit?: string | null };
export type WatchSummary = {
  id: string; revision: number; title: string; brand: string; model: string;
  location: string; price: Money | null; sale_mode: 'fixed' | 'auction' | 'offer';
  sale_state: 'available' | 'not_started' | 'reserved' | 'sold' | 'ended' | 'unavailable';
  thumbnail: Photo | null; published_at: string; ends_at: string | null; demo: boolean;
};
export type WatchDetail = WatchSummary & {
  history_next_cursor?: string | null;
  history_revision?: number | null;
  no_documents?: boolean | null;
  history?: HistoryEntry[] | null;
  reference?: string | null; year?: number | null;
  component_wear?: Partial<Record<'case'|'dial'|'crystal'|'bracelet'|'movement',string>>;
  description: string; condition: string; included_items: string[];
  modified: boolean; modified_parts: string[]; photos: Photo[]; media_state?: 'available'|'unavailable';
  seller: { id?: string | null; city?: string | null; display_name: string; kind: 'private' | 'dealer' | 'brand'; completed_sales: number | null; joined_at: string | null; review_distribution?: number[] | null };
  assurance: { kind: 'private_inspection' | 'official_business'; status: 'pending' | 'passed' | 'failed' | 'inconclusive' | 'onboarded' | 'unavailable' };
};
export type SearchPage = { total?: number | null; items: WatchSummary[]; next_cursor: string | null; server_time: string };
export type PublicBid = { sequence: number; bidder_label: string; amount: Money; accepted_at: string };
export type AuctionSnapshot = {
  auction_id: string; listing_id: string; revision: number; last_sequence: number;
  current_price: Money; opening_price?: Money | null; server_time: string; starts_at?: string | null; ends_at: string; end_version: number;
  status: 'scheduled' | 'open' | 'ended' | 'cancelled'; bids: PublicBid[];
  history_truncated: boolean;
};
export type AuctionRead = { state: 'available'; snapshot: AuctionSnapshot } | { state: 'not_started' | 'unavailable'; snapshot: null };

export type PublicSellerFactsV1 = {
  schema_version: 'catalog-public-facts.v1'; seller_id: string; organization_id: string | null;
  watch_id: string; listing_revision: number; revision: number; city: string | null;
  released_sales: number; joined_at: string; review_distribution: [number,number,number,number,number];
  history_next_cursor: string | null;
  history: HistoryEntry[]; inspection: 'passed'|'failed'|'inconclusive'|null;
};
export type PublicSearchTotalV1 = {
  schema_version: 'catalog-public-total.v1'; criteria: string; total: number; revision: number; as_of: string;
};

export type HistoryPage = { history: HistoryEntry[]; next_cursor: string | null; revision: number; listing_revision: number };

export type HistoryEntry = { occurred_at: string; summary_en: string; summary_ar: string; user_note?: string | null };

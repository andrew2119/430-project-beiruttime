export type Money = { amount: string; currency: 'USD' | 'LBP' };
export type Photo = { id: string; url: string; alt: string; alt_ar?: string | null; credit?: string | null };
export type WatchSummary = {
  id: string; revision: number; title: string; brand: string; model: string;
  location: string; price: Money | null; sale_mode: 'fixed' | 'auction' | 'offer';
  sale_state: 'available' | 'not_started' | 'reserved' | 'sold' | 'ended' | 'unavailable';
  thumbnail: Photo | null; published_at: string; ends_at: string | null; demo: boolean;
};
export type WatchDetail = WatchSummary & {
  reference?: string | null; year?: number | null;
  component_wear?: Partial<Record<'case'|'dial'|'crystal'|'bracelet'|'movement',string>>;
  description: string; condition: string; included_items: string[];
  modified: boolean; modified_parts: string[]; photos: Photo[]; media_state?: 'available'|'unavailable';
  seller: { display_name: string; kind: 'private' | 'dealer' | 'brand'; completed_sales: number | null; joined_at: string | null };
  assurance: { kind: 'private_inspection' | 'official_business'; status: 'pending' | 'passed' | 'failed' | 'inconclusive' | 'onboarded' | 'unavailable' };
};
export type SearchPage = { items: WatchSummary[]; next_cursor: string | null; server_time: string };
export type PublicBid = { sequence: number; bidder_label: string; amount: Money; accepted_at: string };
export type AuctionSnapshot = {
  auction_id: string; listing_id: string; revision: number; last_sequence: number;
  current_price: Money; server_time: string; starts_at?: string | null; ends_at: string; end_version: number;
  status: 'scheduled' | 'open' | 'ended' | 'cancelled'; bids: PublicBid[];
  history_truncated: boolean;
};
export type AuctionRead = { state: 'available'; snapshot: AuctionSnapshot } | { state: 'not_started' | 'unavailable'; snapshot: null };

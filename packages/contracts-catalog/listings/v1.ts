export type Modification = {
  component: string;
  provenance: "genuine" | "aftermarket" | "reworked" | "unknown";
  modifier: string;
  warranty_issuer: string;
  notes: string;
};
export type WatchFacts = {
  brand: string;
  model: string;
  reference: string;
  year: number | null;
  condition: string;
  component_wear: Partial<
    Record<"case" | "dial" | "crystal" | "bracelet" | "movement", string>
  >;
  location: string;
  included: ("box" | "papers" | "links")[];
  no_documents: boolean;
  modified: boolean | null;
  modifications: Modification[];
  ownership_confirmed: boolean;
  sale_mode: "fixed_price" | "auction" | "offer";
  currency: "USD";
  price_minor: number | null;
};
export type Listing = {
  id: string;
  revision: number;
  status: "draft" | "publication_pending" | "published";
  seller_type: "private" | "dealer" | "brand";
  seller_label: string;
  physical_watch_id: string;
  is_demo: boolean;
  is_hidden: boolean;
  facts: WatchFacts;
  photo_ids: string[];
  cover_id: string | null;
  published_at: string | null;
  updated_at: string;
  rules_version: string | null;
  fee_snapshot: Record<string, unknown> | null;
};
export type Media = {
  id: string;
  kind: "public_photo" | "private_document";
  mime: string;
  width: number | null;
  height: number | null;
  credit: Record<string, unknown> | null;
};
export type Page = {
  items: Listing[];
  next_cursor: string | null;
  counts: Record<Listing["status"], number>;
};
export type FeeQuote = {
  price_minor?: number;
  currency?: "USD";
  id: string;
  owner_id: string;
  subject_id: string;
  subject_revision: number;
  schedule_id: "usd-v2";
  purpose: "purchase";
  source: "sample";
  sample: true;
  seller_commission_minor: number;
  buyer_fee_minor: number;
  expires_at: string;
};
export type Section<T> =
  | { status: "available"; data: T }
  | { status: "unavailable" };
export type WorkspaceAuction = {
  id: string;
  listing_id: string;
  current_minor: number;
  currency: "USD" | "LBP";
  accepted_sequence: number;
  status: "live" | "scheduled" | "ended";
};
export type WorkspaceSale = {
  id: string;
  watch_id: string;
  state: "awaiting_payment" | "payment_unknown" | "expired_fenced";
  revision: number;
  deadline: string;
};
export type SellerWorkspace = {
  listings: Section<Page>;
  bids: Section<{ items: WorkspaceAuction[] }>;
  sales: Section<{ items: WorkspaceSale[] }>;
  payout: { status: string; reason: string };
};

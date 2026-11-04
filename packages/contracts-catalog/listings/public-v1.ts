import type { WatchFacts } from "./v1";
export type RegistrationProof = {
  watch_id: string;
  listing_id: string;
  sale_mode: "fixed" | "auction" | "seller_base";
  revision: number;
};
/** Same-service Catalog read seam. Visibility-filtered; not an availability claim. */
export type CatalogPublicListingV1 = {
  id: string;
  seller_id: string;
  organization_id: string | null;
  seller_type: "private" | "dealer" | "brand";
  seller_label: string;
  physical_watch_id: string;
  revision: number;
  status: "published";
  facts: WatchFacts;
  photo_ids: string[];
  cover_id: string;
  is_demo: boolean;
  registration: RegistrationProof;
  rules_version: string;
  published_at: string;
};
export type PublicPhotoCredit = {
  title: string;
  author: string;
  author_url: string;
  source_url: string;
  license: string;
  license_url: string;
  changes: string;
  credit: string;
  alt_en: string;
  alt_ar: string;
  share_alike_required: boolean;
};

export type Text = { en: string; ar: string };
export type Selection = { watch_id: string; expected_revision: number | null };
export type CompareRequest = { schema_version: 'comparison.v1'; selections: Selection[] };
export type Facts = {
  title: Text; brand: Text; model: Text; reference: string | null; year: number | null;
  condition: Text; component_wear: Text[]; included: ('box'|'papers'|'links')[];
  seller_type: 'private'|'dealer'|'brand'; modified: boolean;
  modifications: { component: Text; provenance: Text; modifier: Text; warranty_issuer: Text }[];
  authentication: 'not_inspected'|'pending'|'passed'|'failed'|'inconclusive'|'unavailable';
  price_minor: number | null; buyer_fee_minor: number | null; total_minor: number | null;
  currency: 'USD'; price_basis: 'fixed'|'auction'|'offer'|'unavailable'; economics_revision: string | null; demo: boolean;
};
export type Column = { watch_id: string; expected_revision: number | null; state: 'available'|'unavailable'|'pending'|'denied'|'stale'; revision: number | null; facts: Facts | null };
export type Comparison = { schema_version: 'comparison.v1'; operation_id: string; server_time: string; columns: Column[] };

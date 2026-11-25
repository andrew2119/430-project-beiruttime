export type Summary = Readonly<{
  schema_version: 'passports.summary.v1'; passport_id: string; issuer_id: string;
  inspected_at: string; issued_at: string;
  scope: 'independent_private_sale_inspection'; watch_reference: string;
  inspected_revision: number; claim: 'historical_inspection_summary_only';
}>;
export type Signed = Readonly<{summary: Summary; key_id: string; signature: string}>;
export type PassportState =
  | {state: 'loading' | 'empty' | 'denied' | 'pending' | 'unavailable' | 'invalid'; operation_id?: string}
  | {state: 'verified'; document: Signed};

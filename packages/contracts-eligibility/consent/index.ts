export type PrivateConsent = {
  id: string; buyer_id: string; brand_id: string; request_id: string;
  request_revision: number; revision: number; purpose: 'brand-request-identity';
  policy_version: 'demo-identity-v1'; status: 'active' | 'refused' | 'withdrawal_pending' | 'withdrawn';
  created_at: string; updated_at: string;
};
export type ConsentResult = { consent: PrivateConsent; effective_grant: false };

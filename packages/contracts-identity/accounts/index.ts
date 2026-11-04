export type CurrentPrincipal = {
  actor: { subject_id: string; session_id: string; organization_id: string | null };
  roles: string[]; permissions: string[]; organizations: string[];
  organization_grants: { organization_id: string; roles: string[]; permissions: string[] }[];
};
export type Session = {
  access_token: string; token_type: 'Bearer'; expires_in: number;
  account: { id: string; email: string; display_name: string };
  principal: CurrentPrincipal; access_fingerprint: string;
};
export type PrivateApplication = {
  id: string; subject_id: string; revision: number;
  status: 'pending' | 'correction' | 'approved' | 'rejected' | 'suspended';
  identity_name: string; contact: string; payout_reference: string; reason: string;
  created_at: string; updated_at: string;
};

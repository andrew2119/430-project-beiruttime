export type BusinessCapability = "sales" | "customization" | "servicing";
export type OfficialBusiness = {
  id: string;
  public_name: string;
  kind: "dealer" | "brand";
  capabilities: BusinessCapability[];
  state: "active" | "revoked";
  revision: number;
  sample: boolean;
  platform_onboarded: boolean;
  authenticated_business: boolean;
  independent_watch_authentication_required: false;
};
export type Membership = {
  id: string;
  business_id: string;
  subject_id: string;
  capabilities: string[];
  qualifications: string[];
  intervention_scope: string;
  state: "active" | "suspended" | "revoked";
  revision: number;
};
export type PrivateReview = {
  id: string;
  application_id: string;
  applicant_id: string;
  reviewer_id: string;
  application_revision: number;
  state: "assigned" | "correction" | "approved" | "rejected" | "suspended";
  revision: number;
};
export type Contacts = {
  revision: number;
  email: string | null;
  phone: string | null;
  email_verified: boolean;
  phone_verified: boolean;
  email_sample?: boolean;
  phone_sample?: boolean;
  pending_challenge?: ContactChallenge | null;
};
export type ContactChallenge = {
  id: string;
  state: "pending";
  expires_at: string;
  delivery_mode: "sample_simulator" | "delivery_pending";
};

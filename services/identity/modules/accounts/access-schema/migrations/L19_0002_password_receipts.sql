CREATE TABLE identity_l19_password_receipts (
 key text PRIMARY KEY,
 digest text NOT NULL,
 subject_id uuid NOT NULL REFERENCES identity_accounts(id)
);

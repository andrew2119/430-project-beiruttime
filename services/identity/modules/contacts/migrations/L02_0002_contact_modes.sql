ALTER TABLE l02_contacts ADD COLUMN email_sample boolean NOT NULL DEFAULT false;
ALTER TABLE l02_contacts ADD COLUMN phone_sample boolean NOT NULL DEFAULT false;

-- Restore the exact accepted challenge mode when upgrading existing contacts.
UPDATE l02_contacts c SET email_sample=EXISTS (
 SELECT 1 FROM l02_contact_challenges h JOIN l02_contact_operations o
 ON o.result->>'id'=h.id::text AND o.subject_id=h.subject_id
 WHERE h.subject_id=c.subject_id AND h.channel='email'
 AND h.consumed_at=c.email_verified_at AND o.result->>'delivery_mode'='sample_simulator'
), phone_sample=EXISTS (
 SELECT 1 FROM l02_contact_challenges h JOIN l02_contact_operations o
 ON o.result->>'id'=h.id::text AND o.subject_id=h.subject_id
 WHERE h.subject_id=c.subject_id AND h.channel='phone'
 AND h.consumed_at=c.phone_verified_at AND o.result->>'delivery_mode'='sample_simulator'
);

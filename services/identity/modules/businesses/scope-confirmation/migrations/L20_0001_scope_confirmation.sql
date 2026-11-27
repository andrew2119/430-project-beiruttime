ALTER TABLE l02_businesses
 ADD COLUMN confirmation_ref uuid,
 ADD COLUMN confirmed_scope text[] NOT NULL DEFAULT '{}',
 ADD COLUMN confirmed_by uuid,
 ADD COLUMN confirmed_at timestamptz,
 ADD CONSTRAINT l20_confirmation_record_complete CHECK (
   (confirmation_ref IS NULL AND confirmed_by IS NULL AND confirmed_at IS NULL
    AND cardinality(confirmed_scope) = 0)
   OR (confirmation_ref IS NOT NULL AND confirmed_by IS NOT NULL
       AND confirmed_at IS NOT NULL AND cardinality(confirmed_scope) > 0)
 );

-- Exact command bindings only: no caller-supplied proof or generic operation disclosure.
CREATE TABLE l13_listing_edit_bindings (
 operation_id uuid PRIMARY KEY REFERENCES l08_operations(id),
 source_id uuid NOT NULL,
 watch_id uuid NOT NULL,
 listing_id uuid NOT NULL,
 listing_revision bigint NOT NULL CHECK(listing_revision>0),
 expected_revision bigint NOT NULL CHECK(expected_revision>0)
);
CREATE INDEX l13_edit_source_lookup ON l13_listing_edit_bindings(source_id);
CREATE FUNCTION l13_edit_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Retained physical edit bindings are immutable'; END $$;
CREATE TRIGGER l13_edit_binding_guard BEFORE UPDATE OR DELETE ON l13_listing_edit_bindings
 FOR EACH ROW EXECUTE FUNCTION l13_edit_binding_immutable();

-- Accepted snapshots remain immutable; permission and payment deadlines are separate.
ALTER TABLE l14_quote_decisions ADD COLUMN accepted_fee_lines jsonb NOT NULL DEFAULT '{}';
ALTER TABLE l14_auction_quotes ALTER COLUMN expires_at DROP NOT NULL;
CREATE TABLE l14_quote_commitments (
 quote_id uuid PRIMARY KEY REFERENCES l07_quotes(id), buyer_id uuid NOT NULL,
 order_id uuid NOT NULL UNIQUE, quote_revision bigint NOT NULL CHECK(quote_revision>0),
 currency text NOT NULL CHECK(currency='USD'), total_minor bigint NOT NULL CHECK(total_minor>0),
 committed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION l14_commitment_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'quote_commitment_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER l14_commitment_guard BEFORE UPDATE OR DELETE ON l14_quote_commitments
 FOR EACH ROW EXECUTE FUNCTION l14_commitment_immutable();

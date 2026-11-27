CREATE TABLE l14_auction_quotes (
 id uuid PRIMARY KEY, auction_id uuid NOT NULL, buyer_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('prebid','winner')), revision bigint NOT NULL DEFAULT 1,
 snapshot jsonb NOT NULL, expires_at timestamptz NOT NULL, reviewed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX l14_auction_quote_buyer ON l14_auction_quotes(buyer_id,created_at DESC);

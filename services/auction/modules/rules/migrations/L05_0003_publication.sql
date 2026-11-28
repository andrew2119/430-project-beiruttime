CREATE TABLE auction_publication_watermarks (
 listing_id uuid PRIMARY KEY,
 revision bigint NOT NULL CHECK (revision > 0)
);

-- CP B-27: one physical listing lot and exact integer economics.
CREATE TABLE auction_lots (
 id uuid PRIMARY KEY,
 listing_id uuid NOT NULL UNIQUE,
 watch_id uuid NOT NULL UNIQUE,
 seller_id uuid NOT NULL,
 seller_organization_id uuid,
 currency text NOT NULL CHECK (currency IN ('USD','LBP')),
 opening_minor bigint NOT NULL CHECK (opening_minor > 0 AND opening_minor <= 9000000000000000),
 current_minor bigint NOT NULL DEFAULT 0 CHECK (current_minor >= 0 AND current_minor <= 9000000000000000),
 reserve_minor bigint CHECK (reserve_minor >= opening_minor AND reserve_minor <= 9000000000000000),
 increment_bands jsonb NOT NULL,
 starts_at timestamptz NOT NULL,
 ends_at timestamptz NOT NULL CHECK (ends_at > starts_at),
 rules_version text NOT NULL DEFAULT 'ordinary.v1',
 extension_policy text NOT NULL DEFAULT 'none.v1',
 high_value_minor bigint NOT NULL,
 revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
 accepted_sequence bigint NOT NULL DEFAULT 0 CHECK (accepted_sequence >= 0),
 leader_id uuid,
 commitment_id text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX auction_seller_idx ON auction_lots(seller_id,created_at DESC);
CREATE TABLE auction_operations (
 id uuid PRIMARY KEY,
 subject_id uuid NOT NULL,
 organization_id uuid,
 operation_key text NOT NULL CHECK (length(operation_key) BETWEEN 1 AND 128),
 request_hash text NOT NULL,
 auction_id uuid,
 outcome jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE (subject_id,operation_key)
);
CREATE INDEX auction_operations_owner_idx ON auction_operations(subject_id,auction_id);

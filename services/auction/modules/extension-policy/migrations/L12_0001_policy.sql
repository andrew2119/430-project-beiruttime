-- Separate policy-owned optional price; canonical timing/mode stays in the kernel.
CREATE TABLE auction_policy_settings (
 auction_id uuid PRIMARY KEY REFERENCES auction_lots(id),
 buy_now_minor bigint CHECK(buy_now_minor>0 AND buy_now_minor<=9000000000000000),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS l18_minimum_rules (
                subject TEXT PRIMARY KEY, watch TEXT NOT NULL, organization TEXT NOT NULL,
                revision INTEGER NOT NULL, minimum INTEGER);
              CREATE TABLE IF NOT EXISTS l18_minimum_receipts (
                operation TEXT PRIMARY KEY, command TEXT NOT NULL, result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS l18_minimum_outbox (
                operation TEXT PRIMARY KEY, event TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS l18_offer_blocks (
                owner TEXT NOT NULL, other TEXT NOT NULL, PRIMARY KEY(owner, other));

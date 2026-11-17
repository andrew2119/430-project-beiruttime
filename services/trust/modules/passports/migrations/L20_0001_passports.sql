CREATE TABLE IF NOT EXISTS l20_passports (
operation_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
request TEXT NOT NULL, inspection_id TEXT NOT NULL UNIQUE,
passport_id TEXT NOT NULL UNIQUE, bindings TEXT NOT NULL,
document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l20_passport_outbox (
event_id TEXT PRIMARY KEY, document TEXT NOT NULL,
delivered INTEGER NOT NULL DEFAULT 0 CHECK(delivered IN (0,1)));

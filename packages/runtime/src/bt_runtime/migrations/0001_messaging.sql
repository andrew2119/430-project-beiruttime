CREATE TABLE outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL,
    destination text NOT NULL,
    envelope jsonb NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    available_at timestamptz NOT NULL DEFAULT now(),
    leased_until timestamptz,
    lease_token uuid,
    delivered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(event_id,destination)
);
CREATE INDEX outbox_due ON outbox(available_at,id) WHERE delivered_at IS NULL;
CREATE TABLE inbox (
    consumer text NOT NULL,
    event_id uuid NOT NULL,
    source text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(consumer,event_id)
);

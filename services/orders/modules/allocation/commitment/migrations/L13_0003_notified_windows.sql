-- Compatible notified clocks. Old deadlines are retained only for reconciliation.
ALTER TABLE l08_orders ALTER COLUMN deadline DROP NOT NULL;
ALTER TABLE l08_orders ADD COLUMN notified_at timestamptz;
ALTER TABLE l08_orders ADD COLUMN payment_method text CHECK(payment_method IN ('card','whish','omt'));
ALTER TABLE l08_orders ADD COLUMN initiation_extended_until timestamptz;
ALTER TABLE l08_orders ADD COLUMN order_kind text NOT NULL DEFAULT 'sale' CHECK(order_kind IN ('sale','service_job','customization_job'));
ALTER TABLE l08_orders DROP CONSTRAINT l08_orders_state_check;
ALTER TABLE l08_orders ADD CONSTRAINT l08_orders_state_check CHECK(state IN ('awaiting_notification','awaiting_payment','payment_unknown','expired_fenced','expired_released','paid_held'));
DROP INDEX l08_one_commitment;
CREATE UNIQUE INDEX l08_one_commitment ON l08_orders(watch_id) WHERE state<>'expired_released';
CREATE TABLE l13_payment_notices (
 order_id uuid PRIMARY KEY REFERENCES l08_orders(id),
 event_id uuid NOT NULL UNIQUE,
 buyer_id uuid NOT NULL,
 notice_id uuid UNIQUE,
 notified_at timestamptz,
 verified_delivery_recorded boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((notice_id IS NULL AND notified_at IS NULL AND NOT verified_delivery_recorded)
    OR (notice_id IS NOT NULL AND notified_at IS NOT NULL AND verified_delivery_recorded))
);
-- No synthetic notice receipt is manufactured for existing commitments.
UPDATE l08_orders SET state='awaiting_notification',deadline=NULL
 WHERE state='awaiting_payment' AND currency='USD';

ALTER TABLE l07_quotes ADD CONSTRAINT l07_quote_snapshot_binding CHECK (
 snapshot ?& ARRAY['id','owner_id','price_minor','buyer_fee_minor','seller_commission_minor','seller_net_minor','shipping_minor','tax_minor','payable_minor','currency','sample','revision','schedule_id','minor_unit_exponent']
 AND (snapshot->>'id')::uuid=id AND (snapshot->>'owner_id')::uuid=owner_id
 AND snapshot->>'currency' IN ('USD','LBP') AND snapshot->>'schedule_id'='sample-v1'
 AND snapshot->>'sample'='true' AND (snapshot->>'revision')::integer=revision
 AND (snapshot->>'minor_unit_exponent')::integer=2
);
ALTER TABLE l07_quotes ADD CONSTRAINT l07_quote_snapshot_balance CHECK (
 jsonb_typeof(snapshot->'price_minor')='number'
 AND jsonb_typeof(snapshot->'buyer_fee_minor')='number'
 AND jsonb_typeof(snapshot->'seller_commission_minor')='number'
 AND jsonb_typeof(snapshot->'seller_net_minor')='number'
 AND jsonb_typeof(snapshot->'shipping_minor')='number'
 AND jsonb_typeof(snapshot->'tax_minor')='number'
 AND jsonb_typeof(snapshot->'payable_minor')='number'
 AND (snapshot->>'price_minor')::bigint BETWEEN 1 AND 9000000000000
 AND (snapshot->>'buyer_fee_minor')::bigint BETWEEN 0 AND 9000000000000
 AND (snapshot->>'seller_commission_minor')::bigint BETWEEN 0 AND 9000000000000
 AND (snapshot->>'seller_net_minor')::bigint BETWEEN 0 AND 9000000000000
 AND (snapshot->>'shipping_minor')::bigint=0 AND (snapshot->>'tax_minor')::bigint=0
 AND (snapshot->>'payable_minor')::bigint=(snapshot->>'price_minor')::bigint+(snapshot->>'buyer_fee_minor')::bigint
 AND (snapshot->>'seller_net_minor')::bigint=(snapshot->>'price_minor')::bigint-(snapshot->>'seller_commission_minor')::bigint
);
CREATE FUNCTION l07_protect_quote_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retained quote snapshots cannot be deleted'; END IF;
 IF ROW(NEW.id,NEW.owner_id,NEW.idempotency_key,NEW.request_hash,NEW.snapshot,NEW.created_at,NEW.expires_at,NEW.revision)
    IS DISTINCT FROM ROW(OLD.id,OLD.owner_id,OLD.idempotency_key,OLD.request_hash,OLD.snapshot,OLD.created_at,OLD.expires_at,OLD.revision)
    OR (OLD.reviewed_at IS NOT NULL AND NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at)
 THEN RAISE EXCEPTION 'Retained quote snapshots are immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l07_quote_immutable BEFORE UPDATE OR DELETE ON l07_quotes FOR EACH ROW EXECUTE FUNCTION l07_protect_quote_snapshot();

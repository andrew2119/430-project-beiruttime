-- First-bid intent also reserves the canonical actor/operation key before HTTP.
ALTER TABLE auction_first_bid_intents ADD COLUMN bid_revision bigint NOT NULL DEFAULT 1 CHECK(bid_revision>0);
ALTER TABLE auction_first_bid_intents ADD COLUMN bid_expires_at timestamptz;
UPDATE auction_first_bid_intents i SET bid_revision=a.revision FROM auction_lots a WHERE a.id=i.auction_id;
WITH pending AS (
 SELECT gen_random_uuid() AS receipt_id,i.* FROM auction_first_bid_intents i
 WHERE NOT EXISTS(SELECT 1 FROM auction_operations o WHERE o.subject_id=i.subject_id AND o.operation_key=i.operation_key)
)
INSERT INTO auction_operations(id,subject_id,organization_id,operation_key,request_hash,auction_id,outcome)
 SELECT receipt_id,subject_id,NULL,operation_key,request_hash,auction_id,
 jsonb_build_object('operation_id',receipt_id::text,'auction_id',auction_id::text,
 'status',CASE WHEN status='denied' THEN 'denied' ELSE 'pending' END,
 'code',CASE WHEN status='denied' THEN 'first_bid_commitment_denied' ELSE 'first_bid_not_confirmed' END,
 'commitment_status',status)
 FROM pending ON CONFLICT(subject_id,operation_key) DO NOTHING;

CREATE FUNCTION l14_first_intent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR
 (NEW.auction_id,NEW.subject_id,NEW.operation_key,NEW.request_hash,NEW.command,NEW.bid_revision,NEW.bid_expires_at,NEW.created_at)
 IS DISTINCT FROM
 (OLD.auction_id,OLD.subject_id,OLD.operation_key,OLD.request_hash,OLD.command,OLD.bid_revision,OLD.bid_expires_at,OLD.created_at) THEN
  RAISE EXCEPTION 'first_bid_intent_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_first_intent_retained BEFORE UPDATE OR DELETE ON auction_first_bid_intents
 FOR EACH ROW EXECUTE FUNCTION l14_first_intent_immutable();
CREATE FUNCTION l14_operation_receipt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'auction_receipt_immutable' USING ERRCODE='23514'; END IF;
 IF (NEW.id,NEW.subject_id,NEW.organization_id,NEW.operation_key,NEW.request_hash,NEW.auction_id,NEW.created_at)
 IS DISTINCT FROM
 (OLD.id,OLD.subject_id,OLD.organization_id,OLD.operation_key,OLD.request_hash,OLD.auction_id,OLD.created_at)
 OR (OLD.outcome->>'status'<>'pending' AND NEW.outcome IS DISTINCT FROM OLD.outcome) THEN
  RAISE EXCEPTION 'auction_receipt_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_operation_receipt_retained BEFORE UPDATE OR DELETE ON auction_operations
 FOR EACH ROW EXECUTE FUNCTION l14_operation_receipt_immutable();

ALTER TABLE l07_quotes DROP CONSTRAINT l07_quote_snapshot_binding;
-- Earlier sample amounts remain simulated; normalize their contract binding.
-- The table lock keeps writes out while the snapshot guard is suspended.
ALTER TABLE l07_quotes DISABLE TRIGGER l07_quote_immutable;
UPDATE l07_quotes
SET snapshot = snapshot || '{"currency":"USD","schedule_id":"usd-v2"}'::jsonb
WHERE snapshot->>'currency' IS DISTINCT FROM 'USD'
   OR snapshot->>'schedule_id' IS DISTINCT FROM 'usd-v2';
ALTER TABLE l07_quotes ENABLE TRIGGER l07_quote_immutable;
ALTER TABLE l07_quotes ADD CONSTRAINT l07_quote_snapshot_binding CHECK (
 snapshot ?& ARRAY['id','owner_id','price_minor','buyer_fee_minor','seller_commission_minor','seller_net_minor','shipping_minor','tax_minor','payable_minor','currency','sample','revision','schedule_id','minor_unit_exponent']
 AND (snapshot->>'id')::uuid=id AND (snapshot->>'owner_id')::uuid=owner_id
 AND snapshot->>'currency'='USD' AND snapshot->>'schedule_id'='usd-v2'
 AND snapshot->>'sample'='true' AND (snapshot->>'revision')::integer=revision
 AND (snapshot->>'minor_unit_exponent')::integer=2
);

INSERT INTO outbox(event_id,destination,envelope)
SELECT event_id,'communications-private-review',envelope FROM outbox
WHERE destination='communications' AND delivered_at IS NULL
AND envelope->>'source'='identity'
AND envelope->>'type' IN ('identity.private-review-assigned.v1','identity.private-seller-reviewed.v1')
ON CONFLICT(event_id,destination) DO NOTHING;
DELETE FROM outbox WHERE destination='communications' AND delivered_at IS NULL
AND envelope->>'source'='identity'
AND envelope->>'type' IN ('identity.private-review-assigned.v1','identity.private-seller-reviewed.v1');

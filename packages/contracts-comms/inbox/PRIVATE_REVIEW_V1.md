# Private review delivery, version 1

`POST /internal/v1/inbox/private-review/events` accepts an event envelope with
source `identity` and exactly `identity.private-review-assigned.v1` or
`identity.private-seller-reviewed.v1`. A signed service token must have subject
`identity`, audience `communications`, the configured issuer, and current expiry.
Other sources and types are refused with 403.

The data contract is `PrivateReviewV1` in `private_review.py`. The envelope subject
must equal `subject_id`; the reviewer must differ from the seller. Both recipients
receive required, non-sample inbox records referencing the review and revision.
Both event types use the existing `case_update` inbox category.
No payment record is created. Navigation rechecks current review access.

The response is `{"accepted": true}` for the first committed event id and
`{"accepted": false}` for a replay. Both recipient records and the event receipt
commit in one transaction. Failed validation or persistence leaves no receipt.
Identity delivers through the `communications-private-review` outbox destination;
pending legacy rows for these two types are migrated to that destination.

# Seller follows v1

Buyer-only personal scope; organization context is denied. Current identity is
rechecked for every read, write and receipt lookup, including duplicate retries.
No seller can enumerate followers. No evidence, draft title or contact is accepted.

Composition supplies current identity and public Catalog facts under serialized
admission. Dependency failure must raise unavailable; it cannot grant permission.
Each dependency call has a 300 ms deadline. No live delivery is implied.

- `GET /v1/seller-follows?page=0`: 50 rows, authoritative total, stable seller order.
- `PUT /v1/seller-follows`: immutable Command from schema.py.
- `GET /v1/seller-follows/operations/{operation_id}`: owner-only receipt or 404.
- Internal publication consumer accepts Publication from schema.py after producer
  authentication. It must never be exposed as a buyer command.
- `GET /v1/seller-follows/notices`: private durable notice availability.
- `GET /v1/seller-follows/notices/{notice_id}/destination`: rechecks publication.

Stable operation references survive uncertain responses and restart. Reuse with a
changed payload conflicts. Expected revision mismatch is stale, not success. A new
follow epoch excludes publications at or before that epoch; unfollow immediately
suppresses later processing, including delayed events. Alert consent defaults off.
A disabled epoch is not replayed when alerts are enabled again.

Publication identity is seller/watch/publication revision, independently of event
identifier. One personal notice per publication. Current public facts must match
seller, revision, publication instant and sample marker. Nonpublic sources expose
nothing. Missing facts remain unavailable, with retry of the same event.
Notice destination is constructed from a validated watch identifier, never an
incoming URL. Opening rechecks current public access. In-app availability is
independent of email/device refusal. No email or device binding is created here.

Runtime composition, Catalog/identity adapters, shared inbox delivery, global page
registration and connected proof remain owed by their composition owners.

## Personal notice lifecycle

An authenticated publication is the occurrence. Until its transaction commits,
local delivery is pending and no personal notice is reported available. Publication
receipt and personal unread availability commit together; rollback leaves the same
publication retryable. Existing notices migrate as unread. External delivery is
separate and remains deferred.

`PUT /v1/seller-follows/notices` accepts NoticeCommand with independent `read` and
`clear` actions, expected notice revision and a stable operation reference. Both
return an owner-only receipt through the existing operation lookup. Unread means
`read_at:null`; read sets that timestamp without clearing. Clear sets `cleared_at`
without marking read or changing the follow. Cleared notices leave the active
paginated list and total but retain their durable receipt and deduplication key.
Both timestamps can coexist. Opening a destination changes neither timestamp.
Stale revisions and changed retries conflict; current scope is checked even for
retained receipts. An uncertain response retries the identical command.

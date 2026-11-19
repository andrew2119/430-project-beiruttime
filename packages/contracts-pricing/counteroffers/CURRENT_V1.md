# Counteroffers v1

Private commands: POST /v1/counteroffers/{subject_id}/commands.
Private current read: GET /v1/counteroffers/{subject_id}.
Private operation lookup: GET /v1/counteroffers/{subject_id}/operations/{operation_id}.
The authenticated principal supplies actor and selected organization; body fields must match.
All reads, including receipt replay, recheck current membership and record scope.
No public listing, event, preview or log contains the private negotiation or evidence.

The Q02 provider serializes the entire decision under its canonical watch/offer lock.
It supplies current identity, membership, seller approval, blocks, watch availability,
source revision, retained sent economics and current quote/policy validation.
The provider stores the predecessor supersession, new current offer, immutable command
receipt and minimal private notification outbox in one transaction. It alone owns offer
history. This module owns neither stock allocation nor a second offer database.
A receipt binds every Command field, authenticated scope revision and resulting revision.
Identical retries recover that receipt; changed bindings deny with operation_conflict.
Operation lookup never executes a command. Missing receipts mean pending, never success.

Propose is seller-only on fixed or offers-only stock, with current approved seller scope.
It supersedes the current sent predecessor and creates a new identifier and revision,
using authoritative UTC sent time plus exactly 48 hours. Source revisions remain distinct
from negotiation revisions. Sent economics are immutable beyond preview's 15 minutes.
Accept/reject are buyer-only and name the current negotiation revision. Acceptance
requires exact economics and explicit reviewed_revision equal to that revision.
Current validation checks permission and applicability without repricing sent economics.
Expiration at equality or later, withdrawal or another stock commitment closes the current
offer, atomically notifying both parties. No timer implies acceptance.

Acceptance calls the Q02 allocation seam with this same operation identifier and retained
economics under the canonical serialization boundary. Orders alone reserves the watch,
retains the economics and starts its notice-dependent payment lifecycle. An uncertain
reservation leaves the offer sent and the same operation pending; while unresolved,
the provider fences competing commands and reconciles that operation before supersession.
Only a confirmed bound order changes the offer to accepted. Provider transaction rollback
must never erase the allocation intent; intent/outbox and inbox receipts are atomic.
Calls have a two-second bound and no blind new-operation retry.

The runtime registration, provider implementation, database restart, actual outbox delivery
and connected Orders/quote validation remain prerequisites. The local fixtures are
synthetic development contracts and do not prove a connected reservation.

Every operation response, including denied, pending and unavailable outcomes, carries
subject_id, watch_id, actor_id, organization_id and expected_revision copied from its
immutable command binding. Consumers validate those fields and operation_id before
retaining a result. These bindings do not grant read permission or replace current scope
checks. Switching subject or physical watch clears the mounted private form and receipt;
changing language preserves that same form and operation reference.

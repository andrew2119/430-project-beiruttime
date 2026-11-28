# Private bid state v2 and fixed deadlines

Revision 2, revised rules D26/D27. The engine remains the only transaction owner.
The pure `auction.proxy.v2` hook receives and returns private state, never a public
response, receipt, event or log. v1 public history remains historical v1 data.

Input state: opening_minor, current_minor (opening for an empty lot), leader_id
(UUID or null), sequence, increment_bands and maxima. Each maximum has bidder_id,
amount_minor, sequence and **active: boolean**. Amounts are bounded integer USD
cents (maximum 9,000,000,000,000). Command: kind (manual/maximum), bidder_id,
amount_minor and sequence (the serialized admission receipt).

Output: leader_id, current_minor, maxima and bids. Bids contain bidder_id,
amount_minor, automatic. No maximum fields may appear in public bids. Only the
current leader may have an active ceiling; displaced ceilings remain stored but
inactive. They never return by sorting. Only a raised ceiling reactivates an
inactive maximum; manual bids below it do not reactivate the old ceiling.

An opening bid may equal opening. A competing bid must meet current + step(current).
A maximum challenges at max(next minimum, min(incoming ceiling, active incumbent
ceiling)), or at next minimum without an active incumbent. A response must reach
challenger amount + step(challenger amount), within the active ceiling. Otherwise
the challenger leads, even at a later equal maximum. No equal-price public row.
A leading ceiling-only raise changes private state but emits no public row.
Only the incoming holder may raise stored amounts/sequences. Other holders may
only be deactivated. An immediately beaten challenger is also outbid.

Migration freezes the canonical tables, activates only the existing leader's
ceiling, marks all others inactive, and retains historical public rows unchanged.
New admissions use private_state_version full-step.v2, exposed as bidding_version
in the public v2 projection. Each v2 public history row retains its own
rules_version (ordinary.v1 for old rows, full-step.v2 for new ones). Unresolved legacy commitments stay
held; no new auction purchase is allowed. Canonical transition refuses new prebid
intents. Bid admission never calls a timing extension hook: scheduled_ends_at is
the authoritative end, and accepted bids cannot change it. Old modes remain
readable for reconciliation by their owners.

Boundary fixtures: Maya ceiling 450000, public 430000, step 10000: Rami manual
445000 or 450000 leads without a response. Rami 420000 against Maya at 400000
permits Maya 430000. At a band boundary use the step at the challenger amount.
Reject unknown fields, non-integers, duplicate holders, unbounded amounts,
inactive automatic responses, equal public bids and private ceiling leakage.

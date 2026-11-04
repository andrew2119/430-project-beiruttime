# Private maximum v1 — frozen Auction core integration

`auction.proxy.v1` is synchronous and pure: `calculate(state, command) -> result`.
L05 invokes it under the single Auction transaction lock and validates/persists
its output. There is no second bidder, write engine, database or commit.

State: `{current_minor,opening_minor,leader_id,sequence,increment_bands:
[{from_minor,step_minor}],maxima:[{bidder_id,amount_minor,sequence}]}`.
Command: `{kind:'manual'|'maximum',bidder_id,amount_minor,sequence}`.
Result: `{leader_id,current_minor,maxima:[{bidder_id,amount_minor,sequence}],
bids:[{bidder_id,amount_minor,automatic}]}`. This result is private transaction
state, never an HTTP receipt, event, public history record or log field. Only
`bids` contains actual public-price transitions. A leading ceiling increase has
no public transition. Equal caps favor the earlier authoritative sequence that
established the cap; a manual bid below an existing own cap does not lower it.
The authoritative receipt sequence must advance even when a ceiling-only
command returns an empty public `bids` list; otherwise a later command could
reuse the sequence that established a private cap. Receipt ordering must not
be inferred from the number of public-price transitions.
Band thresholds apply at the competing amount; price never exceeds the winner's
cap. Integer minor units are bounded to 9,000,000,000,000,000.

`POST /v1/auctions/{id}/maximum` is this module's route. Body is the Auction core
BidCommand v1 shape `{amount_minor,fee_quote_id,expected_revision}` and requires
`Idempotency-Key`. The route invokes
`request.app.state.auction.submit(request,auction_id,command,kind='maximum')`.
That sole owner enforces current identity/eligibility, fee binding, self/late/low
and stale denial, idempotency, database time, receipt order, atomic persistence,
privacy projection and outbox events. Missing runtime returns unavailable.
It returns the core stored operation outcome (`status:succeeded|denied`), never
an independently acknowledged maximum. Only leader displacement emits outbid.

The client retains uncertain body/key in memory, never web storage, and must
obtain/review a current bound fee quote before confirmation. An uncertain retry
keeps its original key even after quote expiry so the runtime can reconcile a
previously committed command. Current Identity session/refresh remains owned by
the shared Identity client. A missing pricing capability disables writes.

Restart and racing admission acceptance must be proved with the actual L05
runtime and real connected services; pure/fixture tests alone do not prove it.
The hook owns no persistent data and requires no artificial migration. L05's
Auction aggregate is the durable owner of the returned private maximum state.

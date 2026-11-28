# Help policies v1

Public guidance is a complete finite document, available without a session. It does not accept terms, create a support case, confirm contact delivery or authorize any commercial action. Published guidance is not a replacement for an earlier accepted E03 artifact.

`v1.ts` defines operation lookup and response types. The private read takes an operation reference, current actor, selected organization, record, subject, watch and expected record revision. Current authorization is required before and after the bounded E03 read. A changed binding fails closed. No private result enters public guidance, a preview, event or log. No private cache or persistence is owned here. The durable original accepted artifact remains with E03; retrying or restarting this read cannot replace it.

One provider attempt per read, at most two seconds. Timeout or a missing provider means unavailable; retry with the same reference. Pending, denied and stale responses never carry an artifact. Equality at a provider deadline is expired. UTC instants must include an explicit UTC offset. Provider implementations must enforce record scope and exact revision; a projection cannot authorize this read.

The local fixtures are synthetic contract examples, not connected acceptance. M04/E03 wiring and current access-revocation, lost-response and restart proofs remain required before connected acceptance.

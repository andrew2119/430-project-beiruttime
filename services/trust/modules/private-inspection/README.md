# Independent private-watch inspection

This additive module consumes current private-sale readiness and the early expert receipt. It never waits for buyer receipt to authenticate. Seller verification and business assurance are separate purposes.

The service takes an asynchronous current-source provider, collection provider, authoritative clock and local database path. `routes.py` exposes a factory requiring the host's authenticated current actor/organization dependency. The host must mount it with private no-store response handling, request deadlines, bounded admission, and production persistence. No shared registration is changed here.

The included local durable adapter uses a serialized transaction for result, immutable acknowledgement and minimal outbox. An operation key is global and conflicting reuse is refused. Historic acknowledgements are recoverable only after a current access check and never grant current permission. Provider implementations must check evidence authorization and all binding revisions on every call. Source observations must be fresh across the complete operation. The host must supply serialized provider authorization for production admission; a timestamp alone does not serialize revocation.

Only the owning Orders journal can collect, refund or release. Inspection facts do not authorize payout. The return-readiness answer requires the same stable simulated collection, exact seller/method/USD amount and a current custody instruction. A failed inspection cannot be overwritten by an ordinary pass. Inconclusive needs follow-up; neither result invents disposal or receipt.

The 24-hour held-state follow-up is an authoritative UTC instant. Two-business-day expert decision scheduling in Asia/Beirut remains a custody/support integration obligation. No demo records are inserted automatically.

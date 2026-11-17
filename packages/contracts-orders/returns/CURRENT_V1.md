# Private returns v1

Commands bind stable operation, actor, organization, order subject, canonical watch,
expected return revision, current source revision and retained policy revision.
The command schema is `v1.py`. Operation lookup uses the same current private scope.
No cached record authorizes an action. Producers must supply a bounded current read
under the same serialized source lease as command acceptance; unavailable sources
fail closed. No live provider is composed by this module.

States: requested → permitted or declined; permitted → received or unresolved.
Unresolved intake can be corrected with another actual receipt. Received creates
one durable refund handoff. Only the financial producer can report refund_pending
or refunded, with the same retained order, quote, principal and operation binding.
Permission and a refund decision never mean money confirmed. No transition releases
stock, relists a watch or certifies authenticity.

Current source facts include buyer, organization, canonical watch, retained quote,
policy, current assignment/permissions, source revision, paid-held status and the
actual reverse custody receipt. Receipt binds watch, authorized recipient, actor,
condition, accessories, location, UTC time and proof revision. Wrong watch, absent
receipt or missing accessories remains unresolved. Evidence references and reasons
are private; neither enters the refund handoff. There are no public reads or logs.

A duplicate identical command returns its original receipt after current scope is
rechecked; conflicting operation reuse is denied. Stale commands change nothing.
Timeout retries use the same operation reference. Acknowledged records, operation
receipts and the handoff survive restart in one transaction. Source time is aware
UTC; future physical receipt is invalid, equality is accepted. Refund amounts are
integer USD cents, limited to retained principal; collected fees are excluded.
The financial producer owns reservation, cumulative limits and the only journal.

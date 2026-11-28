# Return records

`Returns` is an additive, isolated persistence implementation for pure integration
and restart tests. It does not register routes, call payment providers, keep
balances or release custody/stock. Its outbox is a durable refund handoff, not a
refund journal. Runtime composition and production database migration are owed.

The supplied current-source callable accepts actor, organization, subject and a
two-second timeout. It must authenticate the caller, return the same actor/subject,
recheck current business/record/assignment permissions and hold a serialized source
lease through local acceptance. Do not compose a cache or projection here. The
source dictionary shape is exercised by deterministic contract fixtures. It binds
retained quote revision, canonical watch revision, policy and principal. Actual
custody receipt must be obtained from its authority; user-entered evidence is not
that source. A source implementation unable to honor the lease must be unavailable.

Every write and read rechecks private scope. The financial producer alone supplies
refund status bound to the received operation, using the single financial journal
and its cumulative reserved/confirmed refund ceiling. This module cannot execute
money or infer confirmation from a refund decision. Private reasons/receipts never
enter its handoff. Apply access-controlled retention to this private database.

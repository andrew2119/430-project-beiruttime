# Public seller profile v1

GET `/v1/public-profiles/{subject_id}?page=1&operation_id={operation_id}` is read only. The operation reference,
subject and current revision bind each response. A supplied operation reference
matches `[a-zA-Z0-9-]{1,80}` and is echoed for read-only retries; when omitted,
the server creates one. It confers no permission and never skips current checks. No write or financial authority
follows from this view. No private proof, contact or review evidence is public.

Providers supply current identity and organization permission on every read.
Inactive identity is denied. Changed source bindings are stale. Missing sources
remain unavailable independently, never zero history. Only actual released purchases
count, uniquely by a nonempty canonical purchase reference matching
`[a-zA-Z0-9-]{1,80}`. Malformed sale references leave sales and reviews unavailable;
malformed review references leave reviews unavailable. Reviews contain one rating from one to five
per released purchase; the producer enforces buyer authorization and moderation.
Approved dealer assets are same-origin media references. Private sellers have no
public business assets. Membership uses authoritative UTC instants.

Calls have a two-second deadline. History is bounded to 1000 source rows; larger
histories require an authoritative producer aggregate before connection. Listings
have server totals and 20-row pages. Durable producer history survives restart;
this read projection owns no release ledger. Identical release duplicates count
once. Conflicting duplicates fail closed. No synthetic history proves completion.

HTTP 400 rejects malformed input, 403 denies permission, 409 reports stale identity,
and 503 reports unavailability. A response may have independent pending or unavailable
history. Retry is read only and cannot create a sale. Fixtures are synthetic.

Current identity, organization, listing and released-review connections remain owed.

# Publication eligibility

The internal validation route accepts only the catalog service identity, with an
identity audience and the publication operation as its request key. Every retry
checks the active account, current grants and current private approval or active
business sales membership. It never replays a previous authorization.

The listing review boundary is `app.state.listing_eligibility_review`:
`await validate(tx, binding)` returns the published catalog eligibility response.
It must recheck listing ownership, identity digest and revision, assigned review,
consumed private photo challenge and canonical duplicate stock under fences held
through the supplied transaction. The response must match every request binding.
No evidence, serial or reviewer identity is returned.

The module installs the persisted provider through its route lifespan. The first
catalog validation records the trusted listing binding. Private sellers issue a
challenge, submit a private PNG, and receive an independent assignment and
verdict through `/v1/listing-reviews/{listing_id}`. All mutations are audited.
Changed bindings discard prior possession proof. Transaction advisory locks fence
listing, watch and identity-digest admission; stock reservations remain retained
conservatively after admission.

Connected acceptance is deferred. The published binding contains no canonical
serial or external stock registry reference. The local stock ledger checks watch
identifiers and identity digests; cross-identity duplicate detection requires a
canonical stock feed before that wider claim can be established.

A matching model digest on a different watch holds publication for review rather
than establishing a duplicate. An independent qualified reviewer resolves the
match through `POST /v1/listing-reviews/{listing_id}/stock-decision`, with the
listing revision, a `distinct` or `duplicate` verdict, a reason and a stable
request key. Clearance covers only the current binding and matching stock set;
new matches require a new review. A matching watch identifier remains denied.
PNG verification uses bounded standard-library decoding at submission.

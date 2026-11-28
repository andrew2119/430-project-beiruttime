# Review-denied revision abort v1

Proposed consumer extension; connected provider acceptance remains deferred.
Catalog calls authenticated `POST /internal/v3/listing-edits/{operation_id}/abort`
with the same operation as `Idempotency-Key` and the exact binding in
`fixtures/revision-abort-v1.json`.

The canonical admission owner serializes abort with prepare and dispatch. An
unknown operation must create a durable terminal tombstone with this binding,
not return an absence as success. Later prepare or dispatch of that operation
must observe the tombstone. Conflicting bindings deny. Existing prepared or
dispatched operations require authoritative reconciliation of the physical
commitment before a terminal response. A committed edit cannot be aborted.

The response uses the existing exact abort acknowledgement with code
`publication_review_denied`. Only a matching terminal acknowledgement permits
Catalog to mark its retained intent denied. Unknown, unavailable, malformed or
lost responses remain pending; retry the same operation and binding. A denied
intent permits a new explicit correction operation, never reuse of the denied
operation. No remote support for this extension is inferred from a fixture.

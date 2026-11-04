# Identity sibling-module contract v1

## Current account and lock order

Import `live_actor`, `lock_accounts`, `consume_reauthentication` from `service_app.identity` (source included in this handoff). Use the foundation connection-bound `unit_of_work`; no sibling starts another transaction or commits on behalf of the caller.

`await live_actor(tx, request, lock=True)` verifies the RS256 token, active `identity_accounts.status`, and live session lineage, takes the account row lock, and returns `(account_row, session_uuid)`. The shared lock namespace is the **row `identity_accounts.id` using FOR UPDATE**, not an advisory-string namespace. All issuance/refresh/logout/password/suspension fences must share that row lock. For multiple accounts, first `await lock_accounts(tx, actor_uuid, target_uuid, ...)` in UUID order, then perform current-actor checks and protected writes. Do not lock one account and then a lower-sorting account.

`identity_sessions`: `id uuid PK`, `subject_id uuid FK identity_accounts(id)`, `expires_at timestamptz`, `revoked_at timestamptz nullable`, `created_at timestamptz DEFAULT now()`. `id` is the stable session lineage (`sid` in the token); rotation changes the opaque refresh handle, not this id or its original expiry. `identity_refresh_tokens(hash text PK, session_id uuid FK, consumed_at timestamptz nullable)` contains only handle hashes. Never issue a successor to a revoked/expired lineage.

For suspension/grant revocation, under the target account row lock:

```sql
UPDATE identity_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE subject_id=$1;
UPDATE identity_accounts SET access_revision=access_revision+1 WHERE id=$1;
```

Change the account status/grant/case and revoke sessions in the **same** transaction. This fences refresh races and fresh `/internal/v1/principal` reads; token claims contain no role authority.

## Fresh contact reauthentication

Browser: `authenticatedRequest('/api/web/v1/identity/v1/accounts/reauthenticate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password,purpose:'contact-change',binding:'email:'+normalizedNewEmail})})`.

Response: `{proof,purpose,binding_digest,expires_in:300}`. The proof is opaque, memory-only and bound to the exact subject, current session lineage, purpose and recipient binding. For phone use `phone:<canonical phone>` consistently. New proof issuance invalidates prior unused proofs for that session/purpose. No password or raw proof is stored in the ledger or emitted to events.

In the sibling contact command, after its idempotent-outcome lookup and inside its own transaction:

```py
await consume_reauthentication(tx, request, body.proof,
    purpose='contact-change', binding='email:'+normalized_new_email)
# Write pending contact and verification intent here. Delivery stays on the old proved contact.
```

Successful consumption is one-use; wrong recipient/session/actor, used or expired proof fails closed with `reauthentication_required`. If the rest of the transaction fails, consumption rolls back too. Code proof and verification of the new contact remain L02-owned; a password proof alone never verifies a new delivery address.

## Private-seller review and capability

Accounts owns `identity_access_grants(id uuid PK,subject_id uuid FK,organization_id uuid nullable,role text,permissions text[],revoked_at timestamptz nullable,created_at timestamptz)`. Individual/platform grants have NULL organization_id. Business grants remain organization-scoped and never enter top-level platform permissions. Bump `identity_accounts.access_revision` whenever effective access changes.

L02's authorized review transaction must lock actor/applicant accounts consistently, recheck assignment/reviewer permission and forbid self-review, lock `identity_private_applications` and compare expected revision. On an actual approved outcome insert one active individual grant `role='private_seller'`, `permissions=ARRAY['identity.listings.publish']`, `organization_id=NULL` (check under the account lock for an existing active grant). On suspension/rejection/revocation revoke that role's active grant and fence sessions using the SQL above. The case and grant change must be atomic. No public registrant can call a grant command. Official brand/dealer onboarding never uses the private application queue.

Private case schema and evidence/assignment columns are in the included immutable migrations and Accounts README. Evidence reads are owner-or-assigned-current-reviewer and audited; reviewer permission is `identity.private-seller.review`. Private approval is not physical watch authentication.

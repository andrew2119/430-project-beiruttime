"""Identity-local current account/session guard for all Identity modules."""
import hashlib
from uuid import UUID
from fastapi import HTTPException, Request
from bt_runtime.app.auth import require_principal
from bt_contracts_core.errors import PublicError
from service_app.session_slots import demo_switch, link_session_holds


async def live_actor(tx, request: Request, *, lock=False):
    principal = require_principal(request)
    try:
        subject, session = UUID(principal.subject), UUID(principal.session_id)
    except ValueError:
        raise HTTPException(401) from None
    row = await tx.fetchrow('SELECT * FROM identity_accounts WHERE id=$1' + (' FOR UPDATE' if lock else ''), subject)
    # Accounts creates the session and link-session tables together, so both exist here.
    # A link session works only under the current unclosed activation that issued it.
    switch = demo_switch()
    found = await tx.fetchrow('''SELECT s.id, d.role, d.activation FROM identity_sessions s
        LEFT JOIN identity_demo_sessions d ON d.session_id=s.id
        LEFT JOIN identity_demo_activations a ON a.activation=d.activation
        WHERE s.id=$1 AND s.subject_id=$2 AND s.revoked_at IS NULL AND s.expires_at>now()
        AND (d.session_id IS NULL OR (d.activation=$3::text AND a.closed_at IS NULL))''',
        session, subject, switch.activation if switch else None)
    active = found is not None and (found['role'] is None or (row is not None and link_session_holds(found, switch, False, row)))
    if not row or row['status'] != 'active' or not active:
        raise HTTPException(401)
    return row, session


async def lock_accounts(tx, *subjects):
    """Lock all affected Identity accounts in UUID order before multi-account changes."""
    await tx.fetch('SELECT id FROM identity_accounts WHERE id=ANY($1::uuid[]) ORDER BY id FOR UPDATE', sorted(set(UUID(str(value)) for value in subjects)))


async def consume_reauthentication(tx, request: Request, proof: str, *, purpose: str, binding: str):
    """Consume a session/purpose/recipient-bound password proof in the caller's transaction."""
    account, session = await live_actor(tx,request,lock=True)
    if not 32 <= len(proof) <= 200 or not 1 <= len(binding) <= 512 or purpose != 'contact-change':
        raise PublicError('reauthentication_required','Confirm your password again.',status=403)
    accepted = await tx.fetchval('''UPDATE identity_reauth_proofs SET consumed_at=now() WHERE hash=$1
        AND subject_id=$2 AND session_id=$3 AND purpose=$4 AND binding_hash=$5
        AND consumed_at IS NULL AND expires_at>now() RETURNING hash''',
        hashlib.sha256(proof.encode()).hexdigest(),account['id'],session,purpose,hashlib.sha256(binding.encode()).hexdigest())
    if not accepted:
        raise PublicError('reauthentication_required','Confirm your password again.',status=403)
    return account, session

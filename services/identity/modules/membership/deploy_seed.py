"""Deploy-applied sample staff: each set's sample staff account joins that set's own sample business.

This is the seed's one access grant. It is written as the app's own membership grant writes it
(membership row, its first history entry, the access grant through `sync_member` and the changed
event), with the deploy seed as the recorded actor, and every row, the grant included, is entered in the
seed's ownership record. The grant is scoped to that sample business only: its stock and its records.
It is never operator power, never a review permission and never a grant for any business the seed did
not create.
It runs only for the seed's own business and staff account, proven by the ownership record, and only
while that account has no session and no grant for that business at all: then `sync_member`'s revoke
steps match no row, so the seed never revokes, or otherwise rewrites, a grant or session it did not
create. It takes the app's own business and account locks without waiting, and skips when either is held.
Each row it depends on is locked first, without waiting, and only then checked (`demo_seed.locked_owned`), so
the row it checked is the row that stays locked until it commits.
Then, in a transaction of its own after those rows have committed, it sends Catalog's seed Identity's signed
handoff for each set's seller, and for its staff with that staff's business: one event each on every seed run,
through Identity's own outbox and relay. It says 'ready' only while every row it vouches for, locked first and
then checked in that same transaction, is still the very row the seed inserted, and active; once one is not,
or a live writer holds one, it says 'withdrawn'. Removal withdraws each still ready (withdraw).
Each handoff takes the next value of Identity's handoff order and carries an assertion signed with the seed's
own handoff key (`BT_DEMO_SEED_HANDOFF_PRIVATE_KEY`); without that key nothing is sent.
Catalog acts only on the latest handoff by that order and only while it is fresh, so each Identity seed run
renews it.
"""
import json
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime import demo_seed
from .identity_store import sync_member
from .routes import dto

QUALIFICATIONS = ['Sample staff for the demonstration']
# Checked on the locked rows: the account still at its pinned address and active; the seed's own active dealer.
ACCOUNT = "t.email=$4 AND t.status='active'"
DEALER = "t.created_by=$4 AND t.sample AND t.state='active' AND t.kind='dealer' AND 'sales'=ANY(t.capabilities)"
SCOPE = 'Sample business stock and records only'
REASON = 'Sample staff added by the deploy seed; not an operator decision'


async def apply(settings):
    if not demo_seed.enabled():
        return {'skipped': 'switch'}
    counts = {'created': 0, 'kept': 0, 'foreign': 0, 'in_use': 0, 'busy': 0, 'no_business': 0, 'no_account': 0,
              'handoff_sent': 0, 'handoff_withdrawn': 0, 'handoff_waiting': 0, 'handoff_busy': 0,
              'handoff_unsigned': 0}
    async with demo_seed.transaction(settings.database_url, 'identity-membership') as tx:
        for business in demo_seed.businesses():
            staff = demo_seed.account(business.sample_set, 'staff')
            key = business.membership_key
            if await demo_seed.owned(tx, 'l02_memberships', {'id': business.membership_id}, key):
                counts['kept'] += 1
                continue
            # The app's own grant takes this business lock, then the account lock: here, try both, never wait.
            if not await tx.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))',
                                     'l02.business-target:' + str(business.id)):
                demo_seed.report('identity-membership', f'busy {key}: the business is being changed')
                counts['busy'] += 1
                continue
            # The account as the app's own grant locks it, then the seed's own active sample dealer: each locked
            # first without waiting, then checked on the locked row.
            found = await demo_seed.locked_owned(tx, 'identity_accounts', {'id': staff.id}, staff.key, ACCOUNT,
                                                 (staff.email,), 'FOR UPDATE')
            if found:
                found = await demo_seed.locked_owned(tx, 'l02_businesses', {'id': business.id}, business.key,
                                                     DEALER, (demo_seed.ACTOR,))
                missing = 'no_business'
            else:
                missing = 'no_account'
            if found is None:
                what = 'staff account' if missing == 'no_account' else 'business'
                demo_seed.report('identity-membership', f'busy {key}: the {what} is being changed')
                counts['busy'] += 1
                continue
            if not found:
                counts[missing] += 1
                continue
            if await tx.fetchval('SELECT 1 FROM l02_memberships WHERE id=$1 OR (business_id=$2 AND subject_id=$3)',
                                 business.membership_id, business.id, staff.id):
                demo_seed.report('identity-membership', f'foreign {key}: a membership the seed did not create exists')
                counts['foreign'] += 1
                continue
            # A session or grant the seed did not create would be revoked by sync_member: leave the account as is.
            # The account lock above keeps any new session or grant for it from committing until this one does.
            if await tx.fetchval('''SELECT EXISTS(SELECT 1 FROM identity_sessions WHERE subject_id=$1)
                OR EXISTS(SELECT 1 FROM identity_access_grants WHERE subject_id=$1 AND organization_id=$2)''',
                                 staff.id, business.id):
                demo_seed.report('identity-membership',
                                 f'in use {key}: the staff account already has sessions or grants')
                counts['in_use'] += 1
                continue
            row = await tx.fetchrow('''INSERT INTO l02_memberships
                (id,business_id,subject_id,capabilities,qualifications,intervention_scope)
                VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING RETURNING *''',
                business.membership_id, business.id, staff.id, list(demo_seed.STAFF_CAPABILITIES),
                QUALIFICATIONS, SCOPE)
            if row is None:
                demo_seed.report('identity-membership', f'foreign {key}: a membership the seed did not create exists')
                counts['foreign'] += 1
                continue
            await demo_seed.record(tx, key, 'l02_memberships', {'id': row['id']})
            history = await tx.fetchval('''INSERT INTO l02_membership_history
                (membership_id,actor_id,revision,reason,state,snapshot) VALUES($1,$2,1,$3,'active',$4::jsonb)
                RETURNING id''', row['id'], demo_seed.ACTOR, REASON, json.dumps(dto(row)))
            await demo_seed.record(tx, key, 'l02_membership_history', {'id': history})
            await sync_member(tx, row, 'dealer')
            grants = await tx.fetch(f'''SELECT id FROM identity_access_grants WHERE subject_id=$1
                AND organization_id=$2 AND revoked_at IS NULL AND {demo_seed.written_here()}''', staff.id, business.id)
            if len(grants) != 1:
                raise RuntimeError('The sample staff membership must make exactly one grant')
            await demo_seed.record(tx, key, 'identity_access_grants', {'id': grants[0]['id']})
            async with demo_seed.events(tx, key):
                await enqueue(tx, EventEnvelope(
                    type='identity.membership-changed.v1', source='identity', subject=str(staff.id),
                    request_id=demo_seed.REQUEST_ID,
                    data={'subject_id': str(staff.id), 'business_id': str(business.id), 'state': 'active',
                          'revision': 1, 'revoke_sessions': True},
                ), ['catalog', 'service-operations', 'auction'])
            counts['created'] += 1
    await handoff(settings, counts)
    return counts


async def ready(tx, sample_set: str, holder: str) -> bool | None:
    """Whether every Identity row a handoff for this holder vouches for is the very row the seed inserted,
    committed and active: True or False, or None when a live writer holds one of them (busy).

    Each row is share-locked first, without waiting, then checked on the locked row (born, the expected demo key,
    owner fields, active), so it cannot change before the handoff this transaction sends commits.
    """
    person = demo_seed.account(sample_set, holder)
    found = await demo_seed.locked_owned(tx, 'identity_accounts', {'id': person.id}, person.key, ACCOUNT,
                                         (person.email,))
    if not found or holder != 'staff':
        return found
    business = demo_seed.business(sample_set)
    found = await demo_seed.locked_owned(tx, 'l02_businesses', {'id': business.id}, business.key, DEALER,
                                         (demo_seed.ACTOR,))
    if found:
        found = await demo_seed.locked_owned(
            tx, 'l02_memberships', {'id': business.membership_id}, business.membership_key,
            "t.business_id=$4 AND t.subject_id=$5 AND t.state='active'", (business.id, person.id))
    if not found:
        return found
    # The one grant the seed recorded for this membership, itself locked first and then checked unrevoked.
    grants = await tx.fetch(f'''SELECT (row_key->>'id')::uuid AS id FROM {demo_seed.LEDGER}
        WHERE demo_key=$1 AND table_name='identity_access_grants' ''', business.membership_key)
    if len(grants) != 1:
        return False
    return await demo_seed.locked_owned(
        tx, 'identity_access_grants', {'id': grants[0]['id']}, business.membership_key,
        't.subject_id=$4 AND t.organization_id=$5 AND t.revoked_at IS NULL', (person.id, business.id))


async def send(tx, key: str, sample_set: str, holder: str, state: str) -> None:
    """One signed handoff to Catalog's seed through Identity's own outbox, recorded under the handoff's key: the
    next value of Identity's handoff order, and an assertion over exactly its fields signed with `key`."""
    seq = await tx.fetchval(f"SELECT nextval('{demo_seed.HANDOFF_SEQUENCE}')")
    async with demo_seed.events(tx, demo_seed.handoff_key(sample_set, holder)):
        await enqueue(tx, demo_seed.handoff_event(key, sample_set, holder, state, seq),
                      [demo_seed.HANDOFF_DESTINATION])


async def handoff(settings, counts) -> None:
    """Identity's signed handoff to Catalog's seed: on every seed run, one event per set and holder.

    'ready' while ready() proves every row it vouches for; otherwise 'withdrawn' when a handoff was sent
    before, including while a live writer holds one of those rows (busy), and nothing when none was (waiting).
    Without the handoff key nothing is sent (unsigned); a key that is the pair of another key fails the step.
    """
    key = demo_seed.handoff_signing_key()
    if key is None:
        demo_seed.report('identity-handoff', f'unsigned: {demo_seed.HANDOFF_PRIVATE_KEY} is not set; nothing sent')
        counts['handoff_unsigned'] += len(demo_seed.SETS) * len(demo_seed.HOLDERS)
        return
    async with demo_seed.transaction(settings.database_url, 'identity-handoff') as tx:
        for sample_set in demo_seed.SETS:
            for holder in demo_seed.HOLDERS.values():
                state = await ready(tx, sample_set, holder)
                if state:
                    await send(tx, key, sample_set, holder, 'ready')
                    counts['handoff_sent'] += 1
                    continue
                sent = await demo_seed.holds(tx, demo_seed.handoff_key(sample_set, holder), 'outbox')
                if sent:
                    await send(tx, key, sample_set, holder, 'withdrawn')
                counts['handoff_busy' if state is None else 'handoff_withdrawn' if sent else 'handoff_waiting'] += 1


async def latest(tx, sample_set: str, holder: str) -> str | None:
    """The state of the newest handoff the record holds for this set and holder, or None when it holds none."""
    return await tx.fetchval(f'''SELECT o.envelope->'data'->>'state' FROM outbox o JOIN {demo_seed.LEDGER} r
        ON r.table_name='outbox' AND r.row_key=jsonb_build_object('id', o.id::text) AND r.demo_key=$1
        WHERE o.destination=$2 ORDER BY o.id DESC LIMIT 1''',
                             demo_seed.handoff_key(sample_set, holder), demo_seed.HANDOFF_DESTINATION)


async def withdraw(tx) -> dict:
    """Removal's first step (`deploy-remove`), in the removal's own transaction: a 'withdrawn' handoff for each
    set and holder whose latest handoff is still 'ready', sent whether or not the deletions run, so Catalog's
    seed admits nothing more for them. One already withdrawn is not sent again, so removal comes to rest.
    Without the handoff key none can be signed: each still ready is counted unsigned and logged."""
    key = demo_seed.handoff_signing_key()
    counts = {'withdrawn': 0, 'unsigned': 0}
    for sample_set in demo_seed.SETS:
        for holder in demo_seed.HOLDERS.values():
            if await latest(tx, sample_set, holder) != 'ready':
                continue
            if key is None:
                demo_seed.report('remove', f'unsigned {demo_seed.handoff_key(sample_set, holder)}: '
                                 f'{demo_seed.HANDOFF_PRIVATE_KEY} is not set; not withdrawn')
                counts['unsigned'] += 1
                continue
            await send(tx, key, sample_set, holder, 'withdrawn')
            counts['withdrawn'] += 1
    return counts

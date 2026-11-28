"""Switch-gated sample-account entry for one sample tab; see service_app.session_slots.

A sample role enters its listed seed account, and only when the deploy seed's own ownership
record holds that exact account row. The Operator link enters the one existing account the
operator setting names, and only before the Operator link's fixed cutoff, while that account is
active, is none of the deploy seed's accounts and holds a live platform operator grant. Entry
never changes the account: it reads it, opens one link session with exactly its existing grants,
and writes nothing else about it. There is no fallback to any other account.
"""
import asyncio
import logging
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from service_app.session_slots import (
    demo_key_matches, demo_switch, demo_values, is_seed_account, listed_role, operator_email, operator_link_open,
    seed_owner_check, session_slot)
from .security import attempts, audit, cookie, digest, limit, new_session, require_origin

router = APIRouter()
logger = logging.getLogger('beirut_time')
SWEEP_SECONDS = 60
# Budgets are keyed by fixed server-side names, never by an address the gateway forwards:
# wrong keys share one budget, and right keys count per set and role, so guessing never
# uses up the demo's own entry.
REFUSED_BUDGET = 30
ROLE_BUDGET = 20
BUDGET_SECONDS = 900
# The browser gives up on an entry after 4 s and tries again from the same tab, at most 8
# times (web/features/identity/session.ts), so an answer that arrives too late can still have
# opened a session. A try that spends its role's budget and is admitted lets the same tab try
# 7 more times for that set and role in the budget window without spending it, so a late
# success never uses up a second attempt; a refused try lets the tab try nothing for free
# (see admit).
SLOT_TRIES = 8
OWNER_ANSWERS = ('owned', 'foreign', 'stale', 'missing')


class DemoEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    set: Literal['demo', 'click-test']
    role: Literal['buyer', 'seller', 'staff', 'operator', 'rival']
    key: str = Field(min_length=1, max_length=200)


@router.post('/v1/demo-entry/sessions')
async def enter(request: Request, response: Response):
    # Off unless both switch values are valid: answer as if the route did not exist,
    # before reading the body, counting the attempt or writing anything.
    switch = demo_switch()
    if switch is None:
        raise HTTPException(404)
    require_origin(request)
    slot = session_slot(request)
    if slot is None:
        raise PublicError('invalid_session_slot', 'Open the sample tab again.', status=400)
    try:
        body = DemoEntry.model_validate_json(await request.body())
    except ValidationError:
        raise PublicError('validation_error', 'Check the supplied fields.', status=422) from None
    right = demo_key_matches(body.key)
    # Counters commit on their own connection, so a refusal still counts.
    async with request.app.state.pool.acquire() as tx:
        if right:
            await admit(tx, slot, body.set, body.role)
        else:
            await limit(tx, 'demo-entry-refused', maximum=REFUSED_BUDGET)
    operator = body.role == 'operator'
    entry = listed_role(body.set, body.role) if right and not operator else None
    address = (operator_email() if operator else entry.email if entry else None) if right else None
    # Before admitting, this process's values must be on record (fails closed).
    await register_settings(request.app)
    refusal = result = refresh = account = None
    async with unit_of_work(request.app.state.pool, lock_key='account-login:' + address if address else None) as tx:
        if not right:
            refusal = PublicError('demo_entry_refused', 'This sample link is not valid. Ask the presenter for the current kit link.', status=401)
        elif operator and not operator_link_open():
            refusal = operator_unavailable('ended')
        elif operator and address is None:
            refusal = operator_unavailable('setting-unset')
        elif not operator and entry is None:
            refusal = PublicError('sample_account_unavailable', 'This sample account is not ready yet.', status=409)
        elif await tx.fetchval('SELECT activation FROM identity_demo_fence FOR SHARE') != switch.activation:
            # The record names other values: a newer deploy, or this process's values were ended.
            # The share lock orders this entry against a process taking the record.
            logger.warning('demo-entry.superseded', extra={'fields': {'action': 'entry follows the latest deploy'}})
            refusal = HTTPException(404)
        elif await tx.fetchval('''SELECT closed_at IS NULL FROM identity_demo_activations
                WHERE activation=$1 FOR SHARE''', switch.activation) is not True:
            # The share lock orders this entry against a sweep closing the activation.
            logger.warning('demo-entry.activation-closed', extra={'fields': {'action': 'set a fresh key to turn entry on again'}})
            refusal = HTTPException(404)
        elif operator:
            # Bound to the one address the setting names; the row is locked, never written.
            account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE email=$1 FOR UPDATE', address)
            if not account or account['status'] != 'active':
                refusal = operator_unavailable('no-active-account')
            elif is_seed_account(account):
                refusal = operator_unavailable('seed-account')
            elif not await tx.fetchval('''SELECT EXISTS(SELECT 1 FROM identity_access_grants WHERE subject_id=$1
                    AND organization_id IS NULL AND role='operator' AND revoked_at IS NULL)''', account['id']):
                refusal = operator_unavailable('not-an-operator')
        else:
            # Only the exact row the seed inserted and recorded, read under the seed's own row locks.
            check = seed_owner_check()
            owner = await check(tx, body.set, body.role) if check else 'no-seed-check'
            if owner != 'owned':
                answer = owner if owner in OWNER_ANSWERS or owner == 'no-seed-check' else 'unexpected'
                logger.warning('demo-entry.sample-not-seed-owned', extra={'fields': {'owner': answer}})
                refusal = PublicError('sample_account_unavailable', 'This sample account is not ready yet.', status=409)
            else:
                # Bound to the seed's fixed id and address: no other account can be entered.
                account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE id=$1 AND email=$2 FOR UPDATE',
                                            entry.account_id, entry.email)
                if not account or account['status'] != 'active':
                    refusal = PublicError('sample_account_unavailable', 'This sample account is not ready yet.', status=409)
        if refusal is not None:
            await audit(tx, request, None, None, 'demo-entry.session', 'denied')
        else:
            result, refresh = await new_session(tx, request, account, demo=(body.role, switch))
            await audit(tx, request, account['id'], result['principal']['actor']['session_id'], 'demo-entry.session', 'accepted')
    if refusal is not None:
        raise refusal
    cookie(response, refresh, slot=slot)
    return result


async def admit(tx, slot: str, sample_set: str, role: str):
    """Count one right-key try against its role's budget, refusing it with 429 once the budget is spent.

    Only a try that spends the budget and is admitted gives its tab a retry allowance: SLOT_TRIES
    tries in all for that set and role in the budget window, the admitted one included. The
    allowance is written in the same transaction as the budget it was paid from, so a refused try
    gives the tab none, and an overlapping try from the same tab can use it only once that
    transaction has committed. A try that finds no allowance left spends the budget again.
    """
    tab = digest('demo-entry-slot:' + slot + ':' + sample_set + ':' + role)
    async with tx.transaction():
        if await tx.fetchval('''UPDATE identity_auth_limits SET attempts=attempts+1
                WHERE scope=$1 AND resets_at>now() AND attempts<$2 RETURNING true''', tab, SLOT_TRIES):
            return
        spent = await attempts(tx, 'demo-entry-role:' + sample_set + ':' + role, seconds=BUDGET_SECONDS)
        if spent <= ROLE_BUDGET:
            await tx.execute('''INSERT INTO identity_auth_limits(scope,attempts,resets_at)
                VALUES($1,1,now()+$2*interval '1 second') ON CONFLICT(scope) DO UPDATE
                SET attempts=1, resets_at=excluded.resets_at''', tab, BUDGET_SECONDS)
    if spent > ROLE_BUDGET:
        raise PublicError('try_later', 'Try again later.', status=429)


def operator_unavailable(reason: str) -> PublicError:
    """The Operator link's one plain refusal; the log names the reason, never the address."""
    logger.warning('demo-entry.operator-unavailable', extra={'fields': {'reason': reason}})
    return PublicError('operator_link_unavailable', 'The operator link is not set up on this site.', status=409)


async def revoke_closed(tx):
    """Revoke the live sessions of closed activations; a row busy elsewhere waits for the next sweep."""
    return await tx.fetchval('''WITH ended AS (UPDATE identity_sessions SET revoked_at=now() WHERE id IN
        (SELECT s.id FROM identity_sessions s JOIN identity_demo_sessions d ON d.session_id=s.id
         JOIN identity_demo_activations a ON a.activation=d.activation
         WHERE a.closed_at IS NOT NULL AND s.revoked_at IS NULL FOR UPDATE OF s SKIP LOCKED) RETURNING 1)
        SELECT count(*) FROM ended''')


async def start_number(app) -> int:
    """This process's place in the order of process starts: one number from the database's own
    sequence, taken the first time the process needs it and kept for its whole life.

    The lifespan opens the pool and starts the sweep before the process serves anyone. The
    sweep's first pass takes the number, or the process's first request if that comes sooner,
    since every request that needs it takes it first under the same lock.
    """
    state = app.state
    lock = getattr(state, 'demo_starting', None)
    if lock is None:
        lock = state.demo_starting = asyncio.Lock()
    async with lock:
        if getattr(state, 'demo_start', None) is None:
            async with state.pool.acquire() as tx:
                state.demo_start = await tx.fetchval("SELECT nextval('identity_demo_starts')")
        return state.demo_start


async def register_settings(app):
    """Put this process's switch values on record, once per process start and values.

    Processes are ordered by their start numbers (start_number), which only the database issues,
    so no process clock takes part. Every activation gets its row in identity_demo_activations the
    first time any process puts its values on record, whether or not it ever opens a session. The
    one row of identity_demo_fence names the activation entry may use now and the highest start
    number of the processes that put it on record.

    - Values the record has never seen, from a process numbered no lower than the record, take
      the record, and the same transaction closes every other open activation: from then on every
      replica refuses those link sessions at their next refresh or principal check, and a replica
      still running other values admits no one (see enter).
    - A process with the values the record already names moves the record's number on to its own,
      so values first seen from any process started before it are recorded closed.
    - Values already on record never take it back from other values. A replica of an earlier
      deployment that starts again later finds its values closed, even if they never opened a
      session. Deploying earlier values again therefore never turns entry on; a fresh key does.
    - Never-seen values from a process numbered lower than the record are recorded closed.
    - A process with the switch off takes the record with no activation and closes every open
      activation, whatever its number: turning entry off is final once any process of the off
      deploy puts it on record. The record keeps the higher number, so values first seen from a
      process started before it stay closed.

    A closed activation never opens again.
    """
    state = app.state
    lock = getattr(state, 'demo_registering', None)
    if lock is None:
        lock = state.demo_registering = asyncio.Lock()
    async with lock:
        number = await start_number(app)
        values = demo_values()
        current = (number, values.activation if values else None)
        if getattr(state, 'demo_registered', None) == current:
            return
        async with unit_of_work(state.pool, lock_key='identity:demo-activations:v1') as tx:
            fence = await tx.fetchrow('SELECT activation, start_number FROM identity_demo_fence FOR UPDATE')
            latest = fence['start_number'] is None or fence['start_number'] <= number
            if values is None:
                # Off is a configuration too, and it can only take entry away, so it takes the record
                # whatever this process's number, even when entry is already off.
                await tx.execute('UPDATE identity_demo_fence SET activation=NULL, start_number=greatest(start_number,$1)', number)
                await tx.execute('UPDATE identity_demo_activations SET closed_at=now() WHERE closed_at IS NULL')
            elif values.activation == fence['activation']:
                if latest:
                    await tx.execute('UPDATE identity_demo_fence SET start_number=$1', number)
            else:
                new = await tx.fetchval('''INSERT INTO identity_demo_activations(activation,until_at) VALUES($1,$2)
                    ON CONFLICT(activation) DO NOTHING RETURNING true''', values.activation, values.until)
                if new and latest:
                    await tx.execute('UPDATE identity_demo_fence SET activation=$1, start_number=$2', values.activation, number)
                    await tx.execute('''UPDATE identity_demo_activations SET closed_at=now()
                        WHERE closed_at IS NULL AND activation<>$1''', values.activation)
                else:
                    logger.warning('demo-entry.superseded', extra={'fields': {'action': 'entry follows the latest deploy'}})
                    await tx.execute('''UPDATE identity_demo_activations SET closed_at=coalesce(closed_at,now())
                        WHERE activation=$1''', values.activation)
            await revoke_closed(tx)
        state.demo_registered = current


async def note_settings(app):
    """register_settings for refresh and principal checks: a failure never fails ordinary sign-in."""
    try:
        await register_settings(app)
    except Exception:
        logger.warning('demo-entry.register-failed', extra={'fields': {'action': 'tried again on the next call and sweep'}})


async def close_expired(pool):
    async with unit_of_work(pool, lock_key='identity:demo-activations:v1') as tx:
        await tx.execute('UPDATE identity_demo_activations SET closed_at=now() WHERE closed_at IS NULL AND until_at<=now()')
        await revoke_closed(tx)


async def sweep(app, stop):
    """Make turning entry off, or changing its key, end time or Operator setting, final.

    Each pass puts this process's values on record (register_settings, which ends other
    activations once newer values hold the record) and closes activations past their end
    time; the first pass also takes the process's start number. Entry, refresh and principal
    checks never wait for it: each decides from the current values and the activation's
    recorded state.
    """
    while not stop.is_set():
        await register_settings(app)
        await close_expired(app.state.pool)
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_SECONDS)
        except TimeoutError:
            pass

import asyncio
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, Field, StrictInt, ValidationError
from bt_contracts_core.errors import AccessDenied
from bt_contracts_core.models import Contract
from bt_runtime.app.auth import require_principal
from .private import (
    MaximumCommand, MaximumCommandV2, current_provider, has_current_admission,
    operation, own_maximum, submit_maximum,
)
from .proxy import MAX_MINOR

router = APIRouter(prefix='/v1/auctions', tags=['private-maximum'])


class ReadMaximum(Contract):
    action: Literal['read_v2']


class LookupMaximum(Contract):
    action: Literal['lookup_v2']
    operation_id: UUID


class LookupEarlierBid(Contract):
    action: Literal['lookup_v1']
    operation_key: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    command: MaximumCommand


class RecoverEarlierBid(Contract):
    action: Literal['recover_v1']
    command: MaximumCommand


class ListEarlierBids(Contract):
    action: Literal['list_bid_receipts_v1']
    before: UUID | None = None


class SubmitMaximum(Contract):
    action: Literal['submit_v2']
    command: MaximumCommandV2


class EarlierMaximumReceipt(Contract):
    operation_id: UUID
    auction_id: UUID
    status: Literal['succeeded', 'denied', 'pending']
    code: str = Field(pattern=r'^[a-z][a-z0-9_]{0,99}$')
    revision: StrictInt = Field(ge=1, le=MAX_MINOR)
    accepted_sequence: StrictInt | None = Field(default=None, ge=0, le=MAX_MINOR)
    current_minor: StrictInt | None = Field(default=None, ge=0, le=MAX_MINOR)
    next_minimum_minor: StrictInt | None = Field(default=None, ge=1, le=2 * MAX_MINOR)
    server_time: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    end_version: StrictInt | None = Field(default=None, ge=1, le=MAX_MINOR)
    mode: Literal['bidding'] | None = None
    commitment_status: Literal['pending', 'succeeded', 'denied'] | None = None


def earlier_receipt(value, auction_id, command):
    try:
        receipt = EarlierMaximumReceipt.model_validate(value)
    except ValidationError:
        raise HTTPException(503) from None
    if receipt.auction_id != auction_id or (
        receipt.status == 'succeeded' and
        (receipt.code != 'bid_accepted' or receipt.revision <= command.expected_revision)
    ):
        raise HTTPException(503)
    return receipt.model_dump(mode='json', exclude_unset=True)


async def individual_buyer(admission, request, principal):
    current = await admission.dependencies.principal(request)
    if ('buyer' not in current.roles or current.actor.organization_id is not None
            or str(current.actor.subject_id) != principal.subject):
        raise AccessDenied('Individual buyer required')
    return current


async def historical_record(tx, auction_id, current):
    lot = await tx.fetchrow(
        'SELECT revision, watch_id, seller_id, seller_organization_id FROM auction_lots WHERE id=$1',
        auction_id,
    )
    if lot is None:
        raise HTTPException(404)
    if (lot['seller_id'] == current.actor.subject_id
            or lot['seller_organization_id'] in current.organizations):
        raise AccessDenied('Current auction access denied')
    return lot


async def earlier_bid_page(tx, auction_id, buyer_id, before):
    rows = await tx.fetch(
        """WITH own AS NOT MATERIALIZED (
               SELECT id, created_at, outcome FROM auction_operations
               WHERE auction_id=$1 AND subject_id=$2 AND organization_id IS NULL
                 AND (outcome->>'accepted_sequence' IS NOT NULL OR outcome->>'code' = 'legacy_maximum_retired')
                 AND (outcome->>'status' = 'denied'
                      OR (outcome->>'status' = 'succeeded' AND outcome->>'code' = 'bid_accepted'))
           )
           SELECT id, created_at,
               CASE WHEN outcome->>'status' = 'succeeded' THEN 'accepted'
                    WHEN outcome->>'code' = 'stale_revision' THEN 'stale'
                    ELSE 'denied' END AS state
           FROM own
           WHERE $3::uuid IS NULL OR (created_at, id) < (
               SELECT created_at, id FROM own WHERE id=$3
           )
           ORDER BY created_at DESC, id DESC LIMIT 21""",
        auction_id, buyer_id, before,
    )
    if before is not None and not rows:
        raise HTTPException(409)
    return {
        'auction_id': str(auction_id),
        'items': [dict(operation_id=str(row['id']), recorded_at=row['created_at'],
                       state=row['state']) for row in rows[:20]],
        'next_cursor': str(rows[19]['id']) if len(rows) > 20 else None,
    }


async def recover_earlier_bid(request, response, auction_id, command, principal, *, cutover):
    admission = getattr(request.app.state, 'auction', None)
    if admission is None or getattr(admission, 'dependencies', None) is None:
        raise HTTPException(503)
    from service_app.engine import decoded, fingerprint, key_for, unit_of_work

    current = await individual_buyer(admission, request, principal)
    own = await own_maximum(request, response, auction_id, principal) if cutover else None
    async with unit_of_work(request.app.state.pool) as tx:
        lot = await historical_record(tx, auction_id, current)
        if own is not None and (own.revision != lot['revision'] or own.watch_id != lot['watch_id']):
            raise HTTPException(503)
        if isinstance(command, ReadMaximum):
            return {'schema_version': 1, 'auction_id': str(auction_id),
                    'actor_id': principal.subject, 'revision': lot['revision']}
        if isinstance(command, ListEarlierBids):
            return await earlier_bid_page(tx, auction_id, current.actor.subject_id, command.before)
        if isinstance(command, LookupEarlierBid):
            row = await tx.fetchrow(
                """SELECT request_hash, outcome FROM auction_operations WHERE subject_id=$1
                   AND organization_id IS NULL AND auction_id=$2 AND operation_key=$3""",
                current.actor.subject_id, auction_id, command.operation_key,
            )
            expected = fingerprint('maximum', auction_id, command.command)
            if row is None or row['request_hash'] != expected:
                raise HTTPException(404)
            return earlier_receipt(decoded(row['outcome']), auction_id, command.command)

        key = key_for(request)
        original = command.command if isinstance(command, RecoverEarlierBid) else command
        digest = fingerprint('maximum', auction_id, original)
        # The same key lock and unique row as the original command fence
        # delayed delivery and serialize original and recovery requests.
        receipt = await admission.operation(tx, current, key, digest)
        if receipt is not None:
            return earlier_receipt(receipt, auction_id, original)
        if isinstance(command, RecoverEarlierBid):
            receipt = dict(operation_id=str(uuid4()), auction_id=str(auction_id),
                           status='denied', code='legacy_maximum_retired', revision=lot['revision'])
            return await admission.store(tx, current, key, digest, receipt, auction_id)
        return None


@router.post('/{auction_id}/maximum')
async def maximum(request: Request, response: Response, auction_id: UUID,
                  command: MaximumCommand | ReadMaximum | LookupMaximum | LookupEarlierBid | RecoverEarlierBid | ListEarlierBids | SubmitMaximum,
                  principal=Depends(require_principal)):
    """Carry versioned operations through the registered buyer route."""
    response.headers['Cache-Control'] = 'no-store'
    cutover = (getattr(request.app.state, 'proxy_private_v2', None) is not None
               or has_current_admission(request))
    if isinstance(command, ReadMaximum) and current_provider(request) is not None:
        return await own_maximum(request, response, auction_id, principal)
    if isinstance(command, LookupMaximum):
        return await operation(request, response, auction_id, command.operation_id, principal)
    if isinstance(command, SubmitMaximum):
        return await submit_maximum(request, response, auction_id, command.command, principal)
    try:
        async with asyncio.timeout(.6):
            return await legacy_transport(request, response, auction_id, command, principal, cutover=cutover)
    except TimeoutError:
        raise HTTPException(503) from None


async def legacy_transport(request, response, auction_id, command, principal, *, cutover):
    admission = getattr(request.app.state, 'auction', None)
    if (isinstance(command, MaximumCommand) and not cutover
            and getattr(admission, 'dependencies', None) is None):
        # The standalone route delegates to an injected admission service.
        # The installed Auction transaction has dependencies and uses receipt recovery below.
        submit = getattr(admission, 'submit', None)
        if not callable(submit):
            raise HTTPException(503)
        return await submit(request, auction_id, command, kind='maximum')
    receipt = await recover_earlier_bid(request, response, auction_id, command, principal, cutover=cutover)
    provider = current_provider(request)
    if receipt is not None:
        if receipt.get('status') != 'pending' or not isinstance(command, (MaximumCommand, RecoverEarlierBid)):
            return receipt
        reconcile = getattr(provider, 'reconcile_legacy_current', None)
        if not callable(reconcile):
            return receipt
        from service_app.engine import key_for

        original = command.command if isinstance(command, RecoverEarlierBid) else command
        lookup = LookupEarlierBid(action='lookup_v1', operation_key=key_for(request), command=original)
        # Reconciliation owns the persisted intent and rechecks its pending state
        # under the canonical lock. Read back the durable decision, not its reply.
        await reconcile(request, auction_id, original)
        return await recover_earlier_bid(request, response, auction_id, lookup, principal, cutover=True)
    # Only canonical D27 admission can persist a displaced higher ceiling.
    submit_legacy = getattr(provider, 'submit_legacy_current', None)
    if not isinstance(command, MaximumCommand) or not callable(submit_legacy):
        raise HTTPException(503)
    await submit_legacy(request, auction_id, command)
    receipt = await recover_earlier_bid(request, response, auction_id, command, principal, cutover=True)
    if receipt is None:
        raise HTTPException(503)
    return receipt

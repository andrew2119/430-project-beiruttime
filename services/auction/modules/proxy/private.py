"""Fail-closed private read adapters. The owner rechecks current authority."""
import asyncio
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, AwareDatetime, field_validator, model_validator
from bt_runtime.app.auth import require_principal
from bt_contracts_core.models import Contract
from .proxy import MAX_MINOR

router = APIRouter(prefix='/v2/auctions', tags=['private-maximum'])


class OwnMaximum(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: StrictInt = Field(ge=2, le=2)
    auction_id: UUID
    watch_id: UUID
    actor_id: UUID
    revision: StrictInt = Field(ge=1)
    amount_minor: StrictInt | None = Field(ge=1, le=9_000_000_000_000_000)
    active: StrictBool
    standing: Literal['leading', 'outbid'] | None

    @model_validator(mode='after')
    def active_ceiling_has_leader(self):
        if self.active and (self.amount_minor is None or self.standing != 'leading'):
            raise ValueError('invalid_private_maximum')
        return self


@router.get('/{auction_id}/maximum')
async def own_maximum(request: Request, response: Response, auction_id: UUID,
                      principal=Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    provider = getattr(request.app.state, 'proxy_private_v2', None)
    read = getattr(provider, 'read_current', None)
    if not callable(read):
        raise HTTPException(503)
    try:
        async with asyncio.timeout(.6):
            value = OwnMaximum.model_validate(await read(request, auction_id))
        if str(value.actor_id) != principal.subject or value.auction_id != auction_id:
            raise HTTPException(403)
        return value
    except HTTPException:
        raise
    except (TimeoutError, ValueError):
        raise HTTPException(503) from None


class MaximumOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: StrictInt = Field(ge=2, le=2)
    operation_id: UUID
    actor_id: UUID
    organization_id: None
    subject_id: UUID
    watch_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=1)
    quote_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    policy_revision: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern='^(accepted|denied|stale|pending)$')
    pending_reason: str | None = Field(max_length=100)
    next_actor: UUID | None
    next_review_at: AwareDatetime | None

    @model_validator(mode='after')
    def accepted_revision(self):
        if self.state == 'accepted' and self.revision <= self.expected_revision:
            raise ValueError('invalid_accepted_revision')
        return self

    @field_validator('next_review_at')
    @classmethod
    def utc_review(cls, value):
        if value is not None and value.utcoffset().total_seconds() != 0:
            raise ValueError('invalid_instant')
        return value


@router.get('/{auction_id}/maximum/operations/{operation_id}')
async def operation(request: Request, response: Response, auction_id: UUID, operation_id: UUID,
                    principal=Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    provider = getattr(request.app.state, 'proxy_private_v2', None)
    lookup = getattr(provider, 'lookup_current', None)
    if not callable(lookup):
        raise HTTPException(503)
    try:
        async with asyncio.timeout(.6):
            value = MaximumOperation.model_validate(await lookup(request, auction_id, operation_id))
        if (str(value.actor_id) != principal.subject or value.subject_id != auction_id
                or value.operation_id != operation_id):
            raise HTTPException(403)
        return value
    except HTTPException:
        raise
    except (TimeoutError, ValueError):
        raise HTTPException(503) from None


class MaximumCommand(Contract):
    """Auction core bid fields without caller-supplied identity or time."""
    amount_minor: StrictInt = Field(ge=1, le=MAX_MINOR)
    fee_quote_id: UUID
    expected_revision: StrictInt = Field(ge=1)


class MaximumCommandV2(MaximumCommand):
    watch_id: UUID | None = None
    quote_revision: StrictInt | None = Field(default=None, ge=1)
    policy_revision: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def complete_expected_binding(self):
        fields = {'watch_id', 'quote_revision', 'policy_revision'}
        provided = self.model_fields_set & fields
        if provided and (provided != fields or any(getattr(self, name) is None for name in fields)):
            raise ValueError('incomplete_maximum_binding')
        return self


def has_current_admission(request: Request) -> bool:
    # Only the canonical transaction owner can attest that both bid kinds
    # and their outbox use the current competition contract.
    admission = getattr(request.app.state, 'auction', None)
    return getattr(admission, 'bid_admission_version', None) == 'auction.proxy.v2'


def current_provider(request: Request):
    provider = getattr(request.app.state, 'proxy_private_v2', None)
    if has_current_admission(request) and all(
        callable(getattr(provider, method, None))
        for method in ('read_current', 'submit_current', 'lookup_current')
    ):
        return provider
    return None


@router.post('/{auction_id}/maximum')
async def submit_maximum(request: Request, response: Response, auction_id: UUID,
                         command: MaximumCommandV2,
                         principal=Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    # The current provider owns fresh identity, quote, admission and durable receipt.
    provider = current_provider(request)
    if provider is None:
        raise HTTPException(503)
    try:
        operation_id = UUID(request.headers.get('Idempotency-Key', ''))
    except ValueError:
        raise HTTPException(422) from None
    try:
        async with asyncio.timeout(.6):
            value = MaximumOperation.model_validate(await provider.submit_current(request, auction_id, command))
        if str(value.actor_id) != principal.subject or value.subject_id != auction_id:
            raise HTTPException(403)
        if (value.operation_id != operation_id or value.expected_revision != command.expected_revision
                or value.quote_id != command.fee_quote_id
                or (command.watch_id is not None and (value.watch_id != command.watch_id
                    or value.quote_revision != command.quote_revision or value.policy_revision != command.policy_revision))):
            raise HTTPException(403)
        return value
    except HTTPException:
        raise
    except (TimeoutError, ValueError):
        raise HTTPException(503) from None

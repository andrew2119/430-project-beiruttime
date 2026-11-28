"""Bounded owner-private input contracts; no cap field is ever projected here."""
from datetime import timedelta
from re import fullmatch
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


MAX_BID_MINOR = 9_000_000_000_000_000


def require_wire_instant(value):
    if not isinstance(value, str) or not fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})',
        value,
    ):
        raise ValueError('invalid_instant')
    return value


def require_utc(value):
    if value.utcoffset() != timedelta(0):
        raise ValueError('invalid_instant')
    return value


UtcWireInstant = Annotated[AwareDatetime, BeforeValidator(require_wire_instant), AfterValidator(require_utc)]


def require_auction_length(starts_at, ends_at):
    if not timedelta(0) < ends_at - starts_at <= timedelta(days=90):
        raise ValueError('invalid_auction_length')


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Band(Record):
    from_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    step_minor: int = Field(strict=True, ge=1, le=9_000_000_000_000_000)


class Bid(Record):
    """Exact Auction own-bids v1; my_status is NOT the Auction lifecycle."""
    id: UUID
    auction_id: UUID
    listing_id: UUID
    buyer_id: UUID
    currency: Literal['USD', 'LBP']
    opening_minor: int = Field(strict=True, ge=1, le=9_000_000_000_000_000)
    current_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    current_price_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    # A calculated minimum can exceed the bid range: it is price plus one step.
    # It is validated as an integer but never projected into buyer activity.
    next_minimum_minor: int = Field(strict=True, ge=1, le=2 * MAX_BID_MINOR)
    increment_bands: list[Band] = Field(min_length=1, max_length=20)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    server_time: AwareDatetime
    revision: int = Field(strict=True, ge=1)
    accepted_sequence: int = Field(strict=True, ge=0)
    rules_version: str = Field(min_length=1, max_length=80)
    extension_policy: str = Field(min_length=1, max_length=80)
    high_value_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    reserve_set: bool = Field(strict=True)
    leader: str | None = Field(max_length=100)
    status: Literal['live', 'scheduled', 'ended']
    my_status: Literal['leading', 'outbid']
    next_action: Literal['review_bid', 'auction_ended']

    @model_validator(mode='after')
    def consistent(self):
        require_auction_length(self.starts_at, self.ends_at)
        if self.id != self.auction_id or self.current_minor != self.current_price_minor:
            raise ValueError('Inconsistent auction projection')
        if (self.status == 'ended') != (self.next_action == 'auction_ended'):
            raise ValueError('Inconsistent auction action')
        return self


class Bids(Record):
    items: list[Bid] = Field(max_length=100)
    next_cursor: UUID | None = None


class Reservation(Record):
    """Frozen Orders allocation v1 buyer-only reservation projection."""
    reservation_id: UUID
    listing_id: UUID
    buyer_id: UUID
    state: Literal['awaiting_payment']
    total_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    currency: Literal['USD', 'LBP']
    revision: int = Field(strict=True, ge=1)
    expires_at: AwareDatetime
    is_demo: bool = Field(strict=True)


class Reservations(Record):
    items: list[Reservation] = Field(max_length=100)
    next_cursor: UUID | None = None


class CurrentBid(Record):
    listing_title: str | None = Field(default=None, min_length=1, max_length=240)
    is_demo: bool = Field(strict=True)
    auction_id: UUID
    listing_id: UUID
    buyer_id: UUID
    status: Literal['leading', 'outbid'] | None
    lifecycle: Literal['scheduled', 'live']
    current_price_minor: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    currency: Literal['USD']
    revision: int = Field(strict=True, ge=1)
    starts_at: UtcWireInstant
    ends_at: UtcWireInstant

    @model_validator(mode='after')
    def valid_schedule(self):
        require_auction_length(self.starts_at, self.ends_at)
        if self.lifecycle == 'scheduled' and (self.status is not None or self.current_price_minor != 0):
            raise ValueError('invalid_scheduled_activity')
        if self.current_price_minor == 0 and self.status is not None:
            raise ValueError('bid_standing_without_price')
        return self


class CurrentBids(Record):
    items: list[CurrentBid] = Field(max_length=100)
    total: int = Field(strict=True, ge=0)
    next_cursor: str | None = Field(default=None, max_length=200)


class CurrentResult(Record):
    is_demo: bool = Field(strict=True)
    auction_id: UUID
    watch_id: UUID
    listing_id: UUID
    buyer_id: UUID
    revision: int = Field(strict=True, ge=1)
    state: Literal['won', 'lost', 'no_sale']
    currency: Literal['USD']
    final_minor: int | None = Field(ge=1, le=9_000_000_000_000_000, strict=True)
    ended_at: UtcWireInstant
    order_id: UUID | None
    financial_state: Literal['pending', 'unknown', 'unpaid', 'unpaid_released', 'paid_held', 'released'] | None
    allocation_state: Literal['denied'] | None = None
    completed_sale: bool = Field(strict=True)
    next_action: Literal['view_auction', 'review_order', 'contact_support']

    @model_validator(mode='after')
    def truthful(self):
        financial_by_standing = {
            'won': ('pending', 'unknown', 'paid_held', 'unpaid', 'unpaid_released', 'released'),
            'lost': (None,),
            'no_sale': (None,),
        }
        if 'allocation_state' in self.model_fields_set:
            if (self.allocation_state != 'denied' or self.state == 'no_sale' or self.order_id is not None
                    or self.financial_state is not None or self.completed_sale):
                raise ValueError('invalid_allocation_outcome')
        elif self.financial_state not in financial_by_standing[self.state]:
            raise ValueError('invalid_financial_state')
        if self.financial_state not in (None, 'pending') and self.order_id is None:
            raise ValueError('missing_order')
        expected_action = (
            'contact_support' if self.financial_state == 'unknown' or (self.state == 'won' and self.order_id is None) else
            'review_order' if self.order_id is not None else 'view_auction'
        )
        if self.next_action != expected_action:
            raise ValueError('invalid_next_action')
        if self.state in ('won', 'lost') and self.final_minor is None:
            raise ValueError('missing_final_amount')
        if self.state != 'lost' and self.completed_sale != (self.financial_state == 'released'):
            raise ValueError('invalid_completion')
        if self.state in ('lost', 'no_sale') and self.order_id is not None:
            raise ValueError('private_order')
        return self


class CurrentResults(Record):
    schema_version: Literal[2]
    state: Literal['available']
    items: list[CurrentResult] = Field(max_length=100)
    total: int = Field(strict=True, ge=0)
    next_cursor: str | None = Field(default=None, max_length=200)

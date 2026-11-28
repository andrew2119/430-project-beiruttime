"""Versioned private handoffs; the providers retain all mutation authority."""
import asyncio
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt


class Binding(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal[1] = 1
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    quote_id: UUID | None
    quote_revision: StrictInt | None = Field(ge=1)
    policy_revision: StrictInt = Field(ge=1)
    expected_revision: StrictInt = Field(ge=1)


class Cancellation(Binding):
    scheduled_ends_at: AwareDatetime


class Resolution(Binding):
    state: Literal['no_attempt', 'declined', 'pending', 'unknown', 'paid_held', 'released']
    revision: StrictInt = Field(ge=1)
    pending_reason: str | None
    next_actor: UUID
    next_review_at: AwareDatetime


class CancellationReceipt(Binding):
    state: Literal['cancelled', 'denied', 'stale', 'pending']
    revision: StrictInt = Field(ge=1)


MESSAGES = {
    'unavailable': ('The result is unavailable. Retry the same operation reference.',
                    'النتيجة غير متاحة. أعد المحاولة باستخدام مرجع العملية نفسه.'),
    'no_attempt': ('No payment attempt was recorded. Request cancellation review.',
                   'لم تُسجّل أي محاولة دفع. اطلب مراجعة الإلغاء.'),
    'declined': ('The payment attempt was declined. Request cancellation review.',
                 'رُفضت محاولة الدفع. اطلب مراجعة الإلغاء.'),
    'pending': ('The payment outcome is pending. Retry the same operation reference.',
                'نتيجة الدفع قيد الانتظار. أعد المحاولة باستخدام مرجع العملية نفسه.'),
    'unknown': ('The payment outcome is unknown. Contact support using the same operation reference.',
                'نتيجة الدفع غير معروفة. تواصل مع الدعم باستخدام مرجع العملية نفسه.'),
    'paid_held': ('Confirmed funds remain held for reconciliation. Contact support.',
                  'تبقى الأموال المؤكدة محجوزة للمطابقة. تواصل مع الدعم.'),
    'released': ('Orders recorded the release. The auction remains closed.',
                 'سجّلت الطلبات فك الحجز. يبقى المزاد مغلقاً.'),
}


def historical_resolution(binding: Binding, response):
    """Preserve validated recovery details without inferring collected funds."""
    unavailable = {'state': 'unavailable', 'revision': None, 'pending_reason': None,
                   'next_actor': None, 'next_review_at': None}
    try:
        result = Resolution.model_validate(response)
    except ValueError:
        return unavailable
    if any(getattr(result, key) != value for key, value in binding.model_dump().items()):
        return unavailable
    if result.revision < binding.expected_revision:
        return unavailable
    return result.model_dump(mode='json', include={
        'state', 'revision', 'pending_reason', 'next_actor', 'next_review_at'})


def historical_state(binding: Binding, response):
    """A refusal alone says nothing about attempts or release of funds."""
    return historical_resolution(binding, response)['state']


async def cancel_no_bid(kernel, tx, command: Cancellation):
    """Delegate under the canonical lock, without local mode or fence writes.

    The provider must check current authority, revision, zero accepted bids,
    fixed scheduled end and exclusive commitment, and retain an atomic receipt
    and event intent. A retry uses precisely this command and operation id.
    """
    operation = getattr(kernel, 'cancel_no_bid_v1', None)
    if not callable(operation):
        return {'state': 'unavailable', 'operation_id': str(command.operation_id)}
    try:
        async with asyncio.timeout(1):
            response = await operation(tx, command.model_dump(mode='json'))
        receipt = CancellationReceipt.model_validate(response)
        binding = Binding(**{key: getattr(command, key) for key in Binding.model_fields})
        if any(getattr(receipt, key) != value for key, value in binding.model_dump().items()):
            raise ValueError('receipt_binding')
        if receipt.revision < command.expected_revision:
            raise ValueError('receipt_revision')
        return receipt.model_dump(mode='json')
    except ValueError:
        return {'state': 'unavailable', 'operation_id': str(command.operation_id)}
    except (TimeoutError, ConnectionError):
        return {'state': 'pending', 'operation_id': str(command.operation_id)}


async def lookup_resolution(provider, binding: Binding):
    """The supplied bounded Orders reader must never create an allocation."""
    try:
        async with asyncio.timeout(1):
            response = await provider.lookup_historical_v1(binding.model_dump(mode='json'))
    except (AttributeError, TimeoutError, ConnectionError):
        return historical_resolution(binding, None)
    return historical_resolution(binding, response)

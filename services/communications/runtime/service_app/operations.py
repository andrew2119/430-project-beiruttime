"""Closed internal operation lookup; receivers precede destination activation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    service: str
    method: str
    path: str
    timeout: float


OPERATIONS = {
    'payment-notice.v3': Operation('orders', 'POST', '/internal/v3/payment-notices', 1.2),
}


def destinations(receivers: frozenset[str], requested: frozenset[str]) -> tuple[str, ...]:
    if not requested <= receivers:
        raise ValueError('Destination requires a subscribed receiver')
    if not requested <= OPERATIONS.keys():
        raise ValueError('Unknown destination')
    return tuple(sorted(requested))


def pending(operation_id: str, reason: str) -> dict:
    if reason not in {'timeout', 'saturated', 'circuit_open', 'network', 'upstream'}:
        raise ValueError('Unknown dependency outcome')
    return {
        'operation_id': operation_id, 'state': 'pending', 'pending_reason': reason,
        'next_action': {
            'en': 'Check the same action again. Its result is not confirmed.',
            'ar': 'تحقق من الإجراء نفسه مجدداً. لم يتم تأكيد نتيجته.',
        },
    }

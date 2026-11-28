"""Protected watch photos v1. No bearer links or public evidence references."""
from dataclasses import dataclass
from typing import Literal

VERSION = 'communications.message-photos.v1'
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_PHOTOS = 8
ORPHAN_SECONDS = 7 * 24 * 60 * 60

@dataclass(frozen=True)
class Scope:
    actor: str
    business: str
    thread: str
    watch: str
    revision: int

@dataclass(frozen=True)
class Authority:
    scope: Scope
    kind: Literal['listing', 'order', 'business']
    member: bool
    identity_active: bool
    business_active: bool
    record_access: bool
    blocked: bool = False
    support_assignment: bool = False
    active_obligation: bool = False

OPERATIONS = {
    'upload': ('POST', '/v1/message-photos/uploads'),
    'attach': ('POST', '/v1/message-photos/attachments'),
    'list': ('GET', '/v1/message-photos'),
    'metadata': ('GET', '/v1/message-photos/{photo}/metadata'),
    'bytes': ('GET', '/v1/message-photos/{photo}/bytes'),
    'operation': ('GET', '/v1/message-photos/operations/{operation}'),
}
PRIVATE_HEADERS = {'Cache-Control': 'private, no-store, max-age=0',
                   'Pragma': 'no-cache', 'X-Content-Type-Options': 'nosniff',
                   'Cross-Origin-Resource-Policy': 'same-origin',
                   'Referrer-Policy': 'no-referrer'}

"""Version one device delivery commands. Endpoints and keys are private."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Subscription(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    endpoint: str = Field(min_length=10, max_length=2048, pattern=r'^https://[^\s#]+$')
    p256dh: str = Field(pattern=r'^[A-Za-z0-9_-]{87}$')
    auth: str = Field(pattern=r'^[A-Za-z0-9_-]{22}$')


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['browser-push.v1']
    operation_id: UUID
    device_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    action: Literal['opt_in', 'revoke', 'rebind']
    permission: Literal['granted', 'denied', 'default']
    subscription: Subscription | None = None


OPERATIONS = {
    'config': ('GET', '/v1/browser-push/config'),
    'command': ('POST', '/v1/browser-push/devices'),
    'lookup': ('GET', '/v1/browser-push/operations/{operation_id}'),
    'device': ('GET', '/v1/browser-push/devices/{device_id}'),
    'click': ('GET', '/v1/browser-push/notices/{notice_id}/destination'),
}

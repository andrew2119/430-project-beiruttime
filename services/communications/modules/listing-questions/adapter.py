"""Host mounts these operations after authenticating the current request."""
from .model import Rejected


async def dispatch(store, principal, listing, operation, payload=None):
    public_read = operation in ('list', 'suggest')
    if not principal and public_read:
        principal = {}
    if not isinstance(principal, dict) or (not principal.get('actor_id') and not public_read):
        raise Rejected('denied')
    if payload is not None and not isinstance(payload, dict):
        raise Rejected('invalid')
    actor, organization = principal.get('actor_id'), principal.get('organization_id')
    if operation == 'command':
        return await store.command(actor, organization, listing, payload)
    fields = {'lookup': {'operation_id'}, 'suggest': {'text', 'page'}, 'review': {'question_id', 'reports_page', 'appeals_page'}, 'list': {'page'}}
    if operation not in fields or not isinstance(payload, dict) or set(payload) != fields[operation]:
        raise Rejected('invalid')
    if operation == 'lookup':
        key = payload['operation_id']
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise Rejected('invalid')
        return await store.lookup(actor, organization, listing, key)
    if operation == 'review':
        key = payload['question_id']
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise Rejected('invalid')
        return await store.review(actor, organization, listing, key, payload['reports_page'], payload['appeals_page'])
    if operation == 'suggest':
        if not isinstance(payload['text'], str) or not 1 <= len(payload['text']) <= 2000:
            raise Rejected('invalid')
        return await store.listing(actor, organization, listing, match=payload['text'], page=payload['page'])
    result = await store.listing(actor, organization, listing, page=payload['page'])
    return result

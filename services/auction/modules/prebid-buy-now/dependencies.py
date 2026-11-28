"""Read-only historical Orders reconciliation through its bounded client."""
from types import SimpleNamespace
from uuid import UUID
from bt_bulkheads import Unavailable


async def reconcile_remote(app, allocation, remote_key, request_id):
    # An absent legacy operation cannot authorize creating a new auction purchase.
    request = SimpleNamespace(app=app, state=SimpleNamespace(request_id=request_id), headers={})
    deps = app.state.auction.dependencies
    headers = {**deps.service_headers(request, 'orders'), 'X-Request-ID': request_id}
    result = await deps.clients['orders'].request('GET', f'/internal/v2/operations/{remote_key}', headers=headers)
    if isinstance(result, Unavailable) or result.status_code != 200:
        return None
    try:
        value = result.json()
        if value.get('status') not in ('succeeded', 'denied'):
            return None
        UUID(value['id'])
        if value['status'] == 'succeeded':
            order = value['order']
            if (allocation['currency'] != 'USD' or order['watch_id'] != allocation['watch_id']
                    or order['buyer_id'] != allocation['buyer_id'] or order['listing_id'] != allocation['listing_id']
                    or order['quote_id'] != allocation['quote_id'] or order['currency'] != allocation['currency']
                    or type(order['total_minor']) is not int or order['total_minor'] != allocation['total_minor']):
                return None
            UUID(order['id'])
        return value
    except (KeyError, TypeError, ValueError):
        return None

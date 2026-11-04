"""Catalog publication v1 adapter. This is a bounded HTTP read, never Catalog SQL."""
from uuid import UUID
from fastapi import HTTPException
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import PublicError

async def current_listing(request, subject_id, subject_revision, price_minor, currency):
    response = await request.app.state.catalog.request('GET', '/v1/listings/' + str(subject_id) + '/publication',
        headers={'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable):
        raise HTTPException(503)
    if response.status_code != 200:
        raise PublicError('listing_unavailable', 'Review the current published listing.', status=409,
            details={'next_action': 'review_current_listing'})
    try:
        record = response.json()
        facts = record['facts']
        valid = (UUID(record['id']) == subject_id and record['status'] == 'published'
            and type(record['revision']) is int and record['revision'] == subject_revision
            and facts['sale_mode'] == 'fixed_price' and facts['currency'] == currency
            and type(facts['price_minor']) is int and facts['price_minor'] == price_minor)
        UUID(record['physical_watch_id'])
        UUID(record['seller_id'])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503) from None
    if not valid:
        raise PublicError('listing_changed', 'Review the current listing price, currency and revision.', status=409,
            details={'next_action': 'review_current_listing'})
    return record

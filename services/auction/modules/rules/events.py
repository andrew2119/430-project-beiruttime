from pydantic import ValidationError

from bt_contracts.auction.core.invalidation import (
    BusinessStatusChanged, ContactVerified, ListingEditAborted, ListingPublished,
    ListingRevised, MembershipChanged, TimingUpdated,
)
from bt_contracts_core.errors import PublicError
from bt_runtime.event_http import build_event_router


def invalid():
    return PublicError('invalid_invalidation', 'Invalid current-state reference.', status=422)


def read_reference(event, model, subject_field):
    try:
        data = model.model_validate(event.data)
    except ValidationError:
        raise invalid() from None
    if event.subject != str(getattr(data, subject_field)):
        raise invalid()
    return data


async def publication(tx, event):
    data = read_reference(event, ListingPublished, 'listing_id')
    await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", 'listing:' + str(data.listing_id))
    await tx.execute('''INSERT INTO auction_publication_watermarks(listing_id, revision) VALUES($1,$2)
        ON CONFLICT(listing_id) DO UPDATE SET revision=GREATEST(auction_publication_watermarks.revision,
        excluded.revision)''', data.listing_id, data.revision)


def identity_invalidation(model, subject_field):
    async def receive(tx, event):
        # Access and verification are already read from Identity on each command.
        read_reference(event, model, subject_field)
    return receive


async def current_lot(tx, auction_id, listing_id, revision, end_version=1, listing_revision=1):
    row = await tx.fetchrow('''SELECT listing_id,revision,end_version,listing_revision
        FROM auction_lots WHERE id=$1''', auction_id)
    if not row or row['revision'] < revision:
        raise PublicError('timing_not_current', 'Current auction timing is unavailable.', status=503)
    if (row['listing_id'] != listing_id or row['end_version'] < end_version
            or row['listing_revision'] < listing_revision):
        raise invalid()


async def timing_updated(tx, event):
    data = read_reference(event, TimingUpdated, 'auction_id')
    await current_lot(tx, data.auction_id, data.listing_id, data.revision, data.end_version)


async def listing_revised(tx, event):
    data = read_reference(event, ListingRevised, 'auction_id')
    await current_lot(tx, data.auction_id, data.listing_id, data.revision, data.end_version, data.listing_revision)


async def listing_edit_aborted(tx, event):
    data = read_reference(event, ListingEditAborted, 'listing_id')
    if (data.auction_id is None) != (data.auction_revision is None):
        raise invalid()
    edit = await tx.fetchrow('''SELECT listing_id,watch_id,listing_revision,auction_id,state
        FROM auction_listing_edits WHERE operation_id=$1''', data.operation_id)
    if not edit or edit['state'] != 'aborted':
        raise PublicError('timing_not_current', 'Current listing edit status is unavailable.', status=503)
    if any(edit[field] != getattr(data, field) for field in ('listing_id', 'watch_id', 'listing_revision', 'auction_id')):
        raise invalid()
    if data.auction_id is not None:
        await current_lot(tx, data.auction_id, data.listing_id, data.auction_revision,
                          listing_revision=data.listing_revision)


router = build_event_router('auction.current-state', {
    'catalog.listing.published.v1': ('catalog', publication),
    'identity.business-status-changed.v1': ('identity', identity_invalidation(BusinessStatusChanged, 'business_id')),
    'identity.membership-changed.v1': ('identity', identity_invalidation(MembershipChanged, 'subject_id')),
    'identity.contact-verified.v1': ('identity', identity_invalidation(ContactVerified, 'subject_id')),
    'auction.timing-updated.v2': ('auction', timing_updated),
    'auction.listing-revised.v2': ('auction', listing_revised),
    'auction.listing-edit-aborted.v3': ('auction', listing_edit_aborted),
})

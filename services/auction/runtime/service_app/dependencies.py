"""One bounded client per dependency; fixture transports are test injection only."""
import os
import time
from uuid import UUID
import jwt
from fastapi import HTTPException, Request
from pydantic import ValidationError
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import CurrentPrincipal, current_principal
from .fee_quote import BidFeeSnapshot


class Dependencies:
    def __init__(self, clients=None, service_key=None):
        self.service_key = service_key if service_key is not None else os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
        self.clients = clients or {name: DependencyClient(name, os.environ.get(
            f'{name.upper()}_URL', f'http://{name}:8000'), timeout=1.2, concurrency=4)
            for name in ('identity', 'catalog', 'pricing', 'orders')}

    async def json(self, name, method, path, request, **kwargs):
        result = await self.clients[name].request(method, path, headers={
            'Authorization': request.headers.get('authorization', ''),
            'X-Request-ID': request.state.request_id,
            **kwargs.pop('headers', {})}, **kwargs)
        if isinstance(result, Unavailable):
            raise PublicError('dependency_unavailable', 'A required service is unavailable.', status=503)
        if result.status_code in (401, 403):
            raise AccessDenied('Upstream refused current access')
        if result.status_code == 404:
            raise PublicError('prerequisite_missing', 'A required record is not available.', status=409)
        if result.status_code >= 300:
            raise PublicError('prerequisite_denied', 'A current prerequisite was refused.', status=409)
        try:
            data = result.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ValueError:
            raise PublicError('dependency_unavailable', 'A required service is unavailable.', status=503) from None

    async def principal(self, request: Request):
        scheme, _, token = request.headers.get('authorization', '').partition(' ')
        if scheme.lower() != 'bearer' or not token or len(token) > 8192:
            raise HTTPException(401)
        selected = request.query_params.get('organization_id')
        if selected:
            try:
                organization = UUID(selected)
            except ValueError:
                raise PublicError('invalid_organization', 'Select a valid organization.', status=422) from None
            data = await self.json('identity', 'GET', f'/internal/v1/principal?organization_id={organization}', request)
            try:
                principal = CurrentPrincipal.model_validate(data)
            except ValidationError:
                raise PublicError('identity_unavailable', 'Current access cannot be verified.', status=503) from None
            if principal.actor.organization_id != organization:
                raise AccessDenied('Represented organization could not be verified')
        else:
            principal = await current_principal(self.clients['identity'], token, request.state.request_id)
        if isinstance(principal, Unavailable):
            raise PublicError('identity_unavailable', 'Current access cannot be verified.', status=503)
        return principal

    async def listing(self, request, listing_id):
        # Catalog's canonical PublicListing V1 names the physical watch and
        # organization explicitly and includes its immutable Orders registration.
        publication = await self.json('catalog', 'GET', f'/v1/listings/{listing_id}', request)
        try:
            registration = publication['registration']
            watch_id = UUID(publication['physical_watch_id'])
            seller_id = UUID(publication['seller_id'])
            organization = publication['organization_id']
            if organization is not None:
                organization = str(UUID(organization))
            if (UUID(publication['id']) != listing_id
                    or UUID(registration['watch_id']) != watch_id
                    or UUID(registration['listing_id']) != listing_id
                    or registration['sale_mode'] != 'auction'
                    or publication['facts']['sale_mode'] != 'auction'):
                raise ValueError()
            return {'id':str(listing_id), 'watch_id':str(watch_id),
                'seller_id':str(seller_id), 'seller_organization_id':organization,
                'status':publication['status']}
        except (KeyError, TypeError, ValueError):
            raise PublicError('catalog_unavailable', 'The listing cannot currently be verified.', status=503) from None

    def service_headers(self, request, audience):
        if not self.service_key:
            raise PublicError('service_auth_unavailable', 'A required service is unavailable.', status=503)
        now = int(time.time())
        token = jwt.encode({'sub': 'auction', 'type': 'service', 'iss': request.app.state.settings.auth_issuer,
            'aud': audience, 'iat': now, 'exp': now + 60}, self.service_key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    async def fence_state(self, request, watch_id, listing_id, auction_id):
        result = await self.json('orders', 'GET',
            f'/internal/v1/watches/{watch_id}/fence?source_id={auction_id}', request,
            headers=self.service_headers(request, 'orders'))
        if (result.get('watch_id') != str(watch_id) or result.get('listing_id') != str(listing_id)
                or type(result.get('revision')) is not int or result['revision'] < 1):
            raise PublicError('orders_unavailable', 'The sale commitment cannot be verified.', status=503)
        if result.get('sale_mode') != 'auction':
            raise PublicError('sale_mode_denied', 'The watch is not registered for auction.', status=409)
        return result

    async def fence(self, request, listing, auction_id, key):
        state = await self.fence_state(request, listing['watch_id'], listing['id'], auction_id)
        if state.get('status') == 'fenced' and state.get('source_matches') is True:
            # Canonical reread reconciles a remote commit whose response/local transaction was lost.
            return str(auction_id)
        if state.get('status') != 'available':
            raise PublicError('sale_mode_denied', 'The watch has another sale commitment.', status=409)
        result = await self.json('orders', 'POST', f"/internal/v1/watches/{listing['watch_id']}/fences", request,
            headers={**self.service_headers(request, 'orders'), 'Idempotency-Key': 'auction-create:' + str(auction_id)},
            json={'source_id': str(auction_id), 'expected_revision': state['revision'], 'reason': 'Open ordinary auction'})
        if result.get('status') != 'succeeded':
            raise PublicError('sale_mode_pending', 'The sale commitment is not confirmed.', status=409)
        await self.check_fence(request, {'watch_id': listing['watch_id'], 'listing_id': listing['id'], 'id': auction_id})
        return str(auction_id)

    async def check_fence(self, request, lot):
        result = await self.fence_state(request, lot['watch_id'], lot['listing_id'], lot['id'])
        if result.get('status') != 'fenced' or result.get('source_matches') is not True:
            raise PublicError('sale_mode_denied', 'The watch is not committed to this auction.', status=409)

    async def fee(self, request, command, lot, principal, now):
        quote = await self.json('pricing', 'GET', f'/v1/quotes/{command.fee_quote_id}', request)
        try:
            snapshot = BidFeeSnapshot.model_validate(quote)
        except ValidationError:
            raise PublicError('pricing_unavailable', 'The fee preview cannot currently be verified.', status=503) from None
        valid = (snapshot.id == command.fee_quote_id and snapshot.owner_id == principal.actor.subject_id
            and snapshot.purpose == 'bid' and snapshot.subject_id == lot['id']
            and snapshot.subject_revision == lot['revision'] and snapshot.price_minor == command.amount_minor
            and snapshot.currency == lot['currency'] and snapshot.expires_at > now
            and snapshot.sample is True and snapshot.source == 'sample' and snapshot.source_verified is False)
        if not valid:
            raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
        if snapshot.reviewed_at is None:
            raise PublicError('fee_review_required', 'Confirm the retained fee preview before bidding.', status=409)
        # Auction ID/revision binds its immutable listing and economic settings; Pricing's schedule is distinct.
        return snapshot.expires_at

    async def contact(self, request):
        result = await self.json('identity', 'GET', '/v1/contacts', request)
        # Identity contacts v1: only current verification flags qualify, never pending metadata/recipients.
        if type(result.get('email_verified')) is not bool or type(result.get('phone_verified')) is not bool:
            raise PublicError('identity_unavailable', 'Current contact verification is unavailable.', status=503)
        if not (result['email_verified'] or result['phone_verified']):
            raise PublicError('verified_contact_required', 'Verify a current contact before this bid.', status=409)

    async def close(self):
        for client in self.clients.values():
            await client.aclose()

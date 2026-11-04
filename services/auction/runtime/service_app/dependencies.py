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
        return await self.json('catalog', 'GET', f'/v1/listings/{listing_id}', request)

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
        from datetime import datetime
        try:
            valid = (UUID(quote['subject_id']) == principal.actor.subject_id
                and UUID(quote['auction_id']) == lot['id']
                and UUID(quote['listing_id']) == lot['listing_id']
                and quote['amount_minor'] == command.amount_minor and quote['currency'] == lot['currency']
                and quote['rules_version'] == lot['rules_version']
                and quote['auction_revision'] == lot['revision']
                and datetime.fromisoformat(quote['expires_at'].replace('Z', '+00:00')) > now)
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
        return datetime.fromisoformat(quote['expires_at'].replace('Z', '+00:00'))

    async def contact(self, request):
        result = await self.json('identity', 'GET', '/v1/contacts/status', request)
        if result.get('verified') is not True:
            raise PublicError('verified_contact_required', 'Verify a current contact before this bid.', status=409)

    async def close(self):
        for client in self.clients.values():
            await client.aclose()

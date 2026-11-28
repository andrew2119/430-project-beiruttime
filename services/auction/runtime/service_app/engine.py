"""Auction is the only bid transaction and serialized admission owner."""
import hashlib
import json
import re
from uuid import UUID, uuid4
from fastapi import Request
from bt_contracts.auction.core.models import MAX_MINOR, next_minimum, step_at
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from .auction_start import start
from .dependencies import Dependencies
from .kernel import lock_lot, require_bidding
from .proxy_validation import validate_result, expected_result

SUSPENDED_ACTIVITY = 'marketplace.activity.suspended'
TERMINAL_BID_DENIALS = frozenset({
    'stale_revision', 'not_started', 'auction_ended', 'auction_committed',
    'auction_window_or_fee_expired', 'fee_preview_required', 'fee_review_required',
    'bid_too_low', 'bid_amount_limit', 'maximum_must_increase', 'verified_contact_required',
    'listing_changed', 'listing_not_ready', 'sale_mode_denied', 'legacy_reconciliation', 'self_bid',
    'bid_permission_required', 'sale_mode_pending',
})


def require_bid_permission(principal):
    if SUSPENDED_ACTIVITY in principal.permissions:
        raise PublicError('bid_permission_required', 'Current access does not permit new bids.', status=403)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def key_for(request):
    key = request.headers.get('idempotency-key', '')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key):
        raise PublicError('idempotency_required', 'Supply a bounded unique operation key.', status=422)
    return key


def fingerprint(kind, resource, command):
    return hashlib.sha256(json.dumps([kind, str(resource), command.model_dump(mode='json')],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def public_lot(lot, now, *, version=1):
    if lot['currency'] != 'USD':
        raise PublicError('legacy_reconciliation', 'Historic currency is restricted to reconciliation.', status=409)
    bands = decoded(lot['increment_bands'])
    result = {'id': str(lot['id']), 'listing_id': str(lot['listing_id']), 'currency': lot['currency'],
        'opening_minor': lot['opening_minor'], 'current_minor': lot['current_minor'],
        'next_minimum_minor': next_minimum(lot, bands), 'increment_bands': bands,
        'starts_at': lot['starts_at'].isoformat(), 'ends_at': lot['ends_at'].isoformat(),
        'server_time': now.isoformat(), 'revision': lot['revision'],
        'accepted_sequence': lot['accepted_sequence'], 'rules_version': lot['rules_version'],
        'extension_policy': lot['extension_policy'], 'high_value_minor': lot['high_value_minor'],
        'reserve_set': lot['reserve_minor'] is not None,
        'leader': mask(lot['id'], lot['leader_id']) if lot['leader_id'] else None,
        'status': 'scheduled' if now < lot['starts_at'] else 'ended' if now >= lot['ends_at'] else 'live'}
    if version == 2:
        result.update(end_version=lot['end_version'], close_version=lot['close_version'], mode=lot['mode'],
                      bidding_version=lot.get('private_state_version', 'ordinary.v1'),
                      first_bid_committed=lot['first_bid_confirmed'],
                      listing_revision=lot['listing_revision'], scheduled_ends_at=lot['scheduled_ends_at'].isoformat())
    return result


def time_denial(lot, now):
    if lot.get('mode', 'bidding') != 'bidding':
        return 'sale_mode_pending' if lot['mode'] in ('prebid_pending', 'first_bid_pending', 'listing_edit_pending') else 'auction_committed'
    if now < lot['starts_at']:
        return 'not_started'
    if now >= lot['ends_at']:
        return 'auction_ended'
    return None


def mask(auction_id, bidder_id):
    return 'Bidder ' + hashlib.sha256(f'{auction_id}:{bidder_id}'.encode()).hexdigest()[:8]


class AuctionEngine:
    bid_admission_version = 'auction.proxy.v2'

    def __init__(self, dependencies=None):
        self.dependencies = dependencies or Dependencies()

    async def operation(self, tx, principal, key, digest):
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            f'operation:{principal.actor.subject_id}:{key}')
        row = await tx.fetchrow('SELECT * FROM auction_operations WHERE subject_id=$1 AND operation_key=$2',
            principal.actor.subject_id, key)
        if row:
            if row['request_hash'] != digest or row['organization_id'] != principal.actor.organization_id:
                raise PublicError('idempotency_conflict', 'This key belongs to a different request.', status=409)
            return decoded(row['outcome'])

    async def store(self, tx, principal, key, digest, outcome, auction_id, *, maximum_binding=None):
        prior = await tx.fetchrow('SELECT * FROM auction_operations WHERE subject_id=$1 AND operation_key=$2',
                                  principal.actor.subject_id, key)
        if prior:
            if prior['request_hash'] != digest or prior['organization_id'] != principal.actor.organization_id:
                raise PublicError('idempotency_conflict', 'This key belongs to a different request.', status=409)
            saved = decoded(prior['outcome'])
            if saved['status'] != 'pending':
                return saved
            outcome['operation_id'] = str(prior['id'])
            await tx.execute('UPDATE auction_operations SET outcome=$2::jsonb WHERE id=$1', prior['id'], json.dumps(outcome))
            return outcome
        values = (UUID(outcome['operation_id']), principal.actor.subject_id,
                  principal.actor.organization_id, key, digest, auction_id, json.dumps(outcome))
        if maximum_binding is None:
            await tx.execute('''INSERT INTO auction_operations
                (id,subject_id,organization_id,operation_key,request_hash,auction_id,outcome)
                VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''', *values)
        else:
            await tx.execute('''INSERT INTO auction_operations
                (id,subject_id,organization_id,operation_key,request_hash,auction_id,outcome,private_maximum_binding)
                VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb)''', *values, json.dumps(maximum_binding))
        return outcome

    async def create(self, request, command):
        return await start(self, request, command, key_for=key_for, fingerprint=fingerprint,
                           public_lot=public_lot, suspended=SUSPENDED_ACTIVITY, max_minor=MAX_MINOR)

    @staticmethod
    def owner(lot, principal):
        if lot['seller_organization_id']:
            require_scope(principal, 'identity.listings.publish', lot['seller_organization_id'])
        elif lot['seller_id'] != principal.actor.subject_id or principal.actor.organization_id is not None:
            raise AccessDenied('Not the seller')

    @staticmethod
    def published(listing, listing_id, principal=None):
        # Published visibility and the seller's current publishing grant are authoritative;
        # a private watch's independent physical authentication happens after purchase, not here.
        if listing.get('status') != 'published':
            raise PublicError('listing_not_ready', 'Use a currently published visible listing.', status=409)
        try:
            if UUID(listing['id']) != listing_id:
                raise ValueError()
            UUID(listing['watch_id'])
            seller = UUID(listing['seller_id'])
            organization = UUID(listing['seller_organization_id']) if listing.get('seller_organization_id') else None
        except (KeyError, TypeError, ValueError):
            raise PublicError('catalog_unavailable', 'The listing cannot currently be verified.', status=503) from None
        if principal and ((organization is None and (seller != principal.actor.subject_id
                or principal.actor.organization_id is not None)) or organization != principal.actor.organization_id):
            raise AccessDenied('Not the listing owner')

    async def update_rules(self, request, auction_id, command):
        principal = await self.dependencies.principal(request)
        require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
        key = key_for(request)
        revision = request.headers.get('if-match', '').strip('"')
        if not revision.isdecimal() or len(revision) > 15:
            raise PublicError('revision_required', 'Supply the current revision.', status=422)
        digest = fingerprint('rules:' + revision, auction_id, command)
        async with request.app.state.pool.acquire() as tx:
            prior = await tx.fetchrow('SELECT * FROM auction_operations WHERE subject_id=$1 AND operation_key=$2',
                                      principal.actor.subject_id, key)
            preflight = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if prior:
            if prior['request_hash'] != digest or prior['organization_id'] != principal.actor.organization_id:
                raise PublicError('idempotency_conflict', 'This key belongs to a different request.', status=409)
            return decoded(prior['outcome'])
        if not preflight:
            raise PublicError('not_found', 'Auction not found.', status=404)
        self.owner(preflight, principal)
        require_bidding(preflight)
        if preflight['accepted_sequence']:
            raise PublicError('rules_frozen', 'Economic settings are frozen after the first bid.', status=409)
        if preflight['revision'] != int(revision):
            raise PublicError('stale_revision', 'Reload the current auction.', status=409)
        listing = await self.dependencies.listing(request, preflight['listing_id'])
        self.published(listing, preflight['listing_id'], principal)
        if listing['revision'] != preflight['listing_revision']:
            raise PublicError('listing_changed', 'Reconcile the current listing revision first.', status=409)
        await self.dependencies.check_fence(request, preflight)
        async with unit_of_work(request.app.state.pool) as tx:
            replay = await self.operation(tx, principal, key, digest)
            if replay:
                return replay
            await self.lock_publication(tx, preflight['listing_id'], listing['revision'])
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'auction:' + str(auction_id))
            lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1 FOR UPDATE', auction_id)
            if not lot:
                raise PublicError('not_found', 'Auction not found.', status=404)
            self.owner(lot, principal)
            require_bidding(lot)
            if lot['accepted_sequence']:
                raise PublicError('rules_frozen', 'Economic settings are frozen after the first bid.', status=409)
            if lot['revision'] != int(revision):
                raise PublicError('stale_revision', 'Reload the current auction.', status=409)
            # The locked revision/mode still matches the bounded preflight;
            # no peer request waits while holding this aggregate lock.
            now = await tx.fetchval('SELECT clock_timestamp()')
            if command.ends_at <= now or lot['ends_at'] <= now:
                raise PublicError('invalid_schedule', 'The auction must end in the future.', status=409)
            lot = await tx.fetchrow('''UPDATE auction_lots SET currency=$2,opening_minor=$3,reserve_minor=$4,
                increment_bands=$5::jsonb,starts_at=$6,ends_at=$7,scheduled_ends_at=$7,
                end_version=end_version+CASE WHEN ends_at<>$7 THEN 1 ELSE 0 END,
                revision=revision+1 WHERE id=$1 RETURNING *''',
                auction_id, command.currency, command.opening_minor, command.reserve_minor,
                json.dumps([b.model_dump() for b in command.increment_bands]), command.starts_at, command.ends_at)
            result = {'operation_id': str(uuid4()), 'status': 'succeeded', 'code': 'rules_updated',
                'auction_id': str(auction_id), 'auction': public_lot(lot, now)}
            await enqueue(tx, EventEnvelope(type='auction.rules-updated.v1', source='auction', subject=str(auction_id), time=now,
                request_id=request.state.request_id, data=public_lot(lot, now)), ['catalog'])
            return await self.store(tx, principal, key, digest, result, auction_id)

    async def submit(self, request: Request, auction_id: UUID, command, *, kind='manual',
                     maximum_binding=None, quote_expires_at=None, recovery_only=False):
        if kind not in ('manual', 'maximum'):
            raise ValueError('Unknown bid kind')
        principal = await self.dependencies.principal(request)
        # Identity's current buyer role is the published buying capability, not a self-granted claim.
        if 'buyer' not in principal.roles:
            raise AccessDenied('Current buyer capability required')
        if principal.actor.organization_id is not None:
            raise AccessDenied('Bid as an individual buyer')
        key = key_for(request)
        try:
            return await self._submit(request, auction_id, command, principal, key, kind=kind,
                                      maximum_binding=maximum_binding, quote_expires_at=quote_expires_at,
                                      recovery_only=recovery_only)
        except PublicError as error:
            if kind != 'manual' or error.status >= 500 or error.code not in TERMINAL_BID_DENIALS:
                raise
            return await self.manual_denial(request, auction_id, command, principal, key, error.code)

    async def manual_denial(self, request, auction_id, command, principal, key, code):
        digest = fingerprint('manual', auction_id, command)
        async with unit_of_work(request.app.state.pool) as tx:
            existing = await self.operation(tx, principal, key, digest)
            if existing and (existing['status'] != 'pending' or existing.get('commitment_status') != 'succeeded'):
                return existing
            lot = await lock_lot(tx, auction_id)
            outcome = dict(operation_id=existing['operation_id'] if existing else str(uuid4()),
                           auction_id=str(auction_id), status='denied', code=code, revision=lot['revision'])
            return await self.store(tx, principal, key, digest, outcome, auction_id)

    async def _submit(self, request, auction_id, command, principal, key, *, kind, maximum_binding,
                      quote_expires_at, recovery_only):
        if maximum_binding is not None:
            if (kind != 'maximum' or maximum_binding['actor_id'] != str(principal.actor.subject_id)
                    or str(UUID(key)) != maximum_binding['operation_id']):
                raise AccessDenied('Current maximum access denied')
            key = maximum_binding['operation_id']
        digest = fingerprint('maximum-v2' if maximum_binding is not None else kind, auction_id, command)
        # Bounded prerequisite reads precede the aggregate lock. The
        # locked row must still match this version and database time at admission.
        async with request.app.state.pool.acquire() as tx:
            prior = await tx.fetchrow('SELECT * FROM auction_operations WHERE subject_id=$1 AND operation_key=$2',
                principal.actor.subject_id, key)
            preflight = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if recovery_only and prior is None:
            raise PublicError('not_found', 'Operation not found.', status=404)
        if prior:
            if prior['request_hash'] != digest or prior['organization_id'] != principal.actor.organization_id:
                raise PublicError('idempotency_conflict', 'This key belongs to a different request.', status=409)
            saved = decoded(prior['outcome'])
            if saved['status'] != 'pending':
                return saved
            # Reconcile the existing authorized intent BEFORE a fresh fee read.
            # Expiry cannot strand a committed remote fence or imply a bid won.
            from .first_bid import prepare
            await prepare(request, self.dependencies, auction_id, principal, key, digest)
            async with request.app.state.pool.acquire() as tx:
                preflight = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
                saved = decoded(await tx.fetchval('SELECT outcome FROM auction_operations WHERE id=$1', prior['id']))
            if saved['status'] != 'pending':
                return saved
        require_bid_permission(principal)
        if preflight is None:
            raise PublicError('not_found', 'Auction not found.', status=404)
        require_bidding(preflight)
        if preflight['currency'] != 'USD':
            raise PublicError('legacy_reconciliation', 'Historic currency is read-only pending reconciliation.', status=409)
        if principal.actor.subject_id == preflight['seller_id'] or preflight['seller_organization_id'] in principal.organizations:
            raise PublicError('self_bid', 'A seller cannot bid on their own watch.', status=409)
        if command.expected_revision != preflight['revision']:
            raise PublicError('stale_revision', 'Review the current auction and fee preview.', status=409)
        listing = await self.dependencies.listing(request, preflight['listing_id'])
        self.published(listing, preflight['listing_id'])
        if (listing['revision'] != preflight['listing_revision'] or UUID(listing['seller_id']) != preflight['seller_id']
                or UUID(listing['watch_id']) != preflight['watch_id']
                or listing.get('seller_organization_id') != (str(preflight['seller_organization_id']) if preflight['seller_organization_id'] else None)):
            raise PublicError('listing_changed', 'The listing seller has changed.', status=409)
        async with request.app.state.pool.acquire() as tx:
            await self.require_current_publication(tx, preflight['listing_id'], listing['revision'])
        await self.dependencies.check_fence(request, preflight)
        from datetime import datetime, timezone
        if maximum_binding is not None and quote_expires_at is not None:
            fee_expires_at = quote_expires_at
        else:
            options = {'maximum_binding': maximum_binding} if maximum_binding is not None else {}
            fee_expires_at = await self.dependencies.fee(request, command, preflight, principal, datetime.now(timezone.utc), **options)
        if command.amount_minor >= preflight['high_value_minor']:
            await self.dependencies.contact(request)
        now = datetime.now(timezone.utc)
        if now < preflight['starts_at'] or now >= preflight['ends_at'] or fee_expires_at <= now:
            raise PublicError('auction_window_or_fee_expired', 'Review the current auction and fees.', status=409)
        minimum = (preflight['current_minor'] if kind == 'maximum' and preflight['leader_id'] == principal.actor.subject_id
                   else next_minimum(preflight, decoded(preflight['increment_bands'])))
        if command.amount_minor < minimum:
            raise PublicError('bid_too_low', 'Use the current minimum bid.', status=409)
        if kind == 'manual' and command.amount_minor + step_at(decoded(preflight['increment_bands']), command.amount_minor) > MAX_MINOR:
            raise PublicError('bid_amount_limit', 'The next increment exceeds the supported monetary range.', status=409)
        if kind == 'maximum' and request.app.state.hooks.get('auction.proxy.v2') is None:
            raise PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503)
        await self.recheck_bid_permission(request, principal)
        if not preflight['first_bid_confirmed'] and not preflight['accepted_sequence']:
            from .first_bid import prepare
            await prepare(request, self.dependencies, auction_id, principal, key, digest,
                          fee_expires_at=fee_expires_at, maximum_binding=maximum_binding)
            await self.recheck_bid_permission(request, principal)
        async with unit_of_work(request.app.state.pool) as tx:
            replay = await self.operation(tx, principal, key, digest)
            if replay and replay['status'] != 'pending':
                return replay
            await self.lock_publication(tx, preflight['listing_id'], listing['revision'])
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'auction:' + str(auction_id))
            lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1 FOR UPDATE', auction_id)
            if not lot:
                raise PublicError('not_found', 'Auction not found.', status=404)
            now = await tx.fetchval('SELECT clock_timestamp()')
            outcome = {'operation_id': replay['operation_id'] if replay else str(uuid4()), 'auction_id': str(auction_id), 'status': 'denied',
                'code': 'not_confirmed', 'revision': lot['revision'], 'accepted_sequence': lot['accepted_sequence'],
                'current_minor': lot['current_minor'],
                'next_minimum_minor': next_minimum(lot, decoded(lot['increment_bands'])), 'server_time': now.isoformat()}
            try:
                if principal.actor.subject_id == lot['seller_id']:
                    raise PublicError('self_bid', 'A seller cannot bid on their own watch.', status=409)
                if lot['seller_organization_id'] in principal.organizations:
                    raise PublicError('self_bid', 'Business members cannot bid on their business watch.', status=409)
                window_error = time_denial(lot, now)
                if window_error:
                    raise PublicError(window_error, 'Bidding is outside the auction window.', status=409)
                if command.expected_revision != lot['revision'] or (maximum_binding is not None
                        and maximum_binding['watch_id'] != str(lot['watch_id'])):
                    raise PublicError('stale_revision', 'Review the current auction and fee preview.', status=409)
                minimum = (lot['current_minor'] if kind == 'maximum' and lot['leader_id'] == principal.actor.subject_id
                    else outcome['next_minimum_minor'])
                if command.amount_minor < minimum:
                    raise PublicError('bid_too_low', 'Use at least the current minimum bid.', status=409)
                if kind == 'manual' and command.amount_minor + step_at(decoded(lot['increment_bands']), command.amount_minor) > MAX_MINOR:
                    raise PublicError('bid_amount_limit', 'The next increment exceeds the supported monetary range.', status=409)
                # Identity holds its own sanction decision only. This call does
                # not send lot data or call back into Auction while it is locked.
                await self.dependencies.bid_admission(request, tx, principal)
                now = await tx.fetchval('SELECT clock_timestamp()')
                if now >= lot['ends_at']:
                    raise PublicError('auction_ended', 'The auction has ended.', status=409)
                if fee_expires_at <= now:
                    raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
                maxima = [dict(row) for row in await tx.fetch(
                    '''SELECT bidder_id,amount_minor,sequence,active FROM auction_maxima
                       WHERE auction_id=$1 AND verified_ceiling ORDER BY sequence LIMIT 10001''', auction_id)]
                for maximum in maxima:
                    maximum['bidder_id'] = str(maximum['bidder_id'])
                bidder_id = str(principal.actor.subject_id)
                prior = next((maximum for maximum in maxima if maximum['bidder_id'] == bidder_id), None)
                if kind == 'maximum' and prior and command.amount_minor <= prior['amount_minor']:
                    raise PublicError('maximum_must_increase', 'Increase the current private maximum.', status=409)
                # The pure hook's empty-state price is opening; the persisted empty lot remains zero.
                state = {'current_minor': max(lot['current_minor'], lot['opening_minor']), 'opening_minor': lot['opening_minor'],
                    'leader_id': str(lot['leader_id']) if lot['leader_id'] else None,
                    'sequence': lot['accepted_sequence'], 'increment_bands': decoded(lot['increment_bands']), 'maxima': maxima}
                incoming = {'kind': kind, 'bidder_id': bidder_id, 'amount_minor': command.amount_minor,
                    'sequence': lot['accepted_sequence'] + 1}
                hook = request.app.state.hooks.get('auction.proxy.v2')
                active_ceiling = any(maximum['active'] and maximum['amount_minor'] > lot['current_minor'] for maximum in maxima)
                if (kind == 'maximum' or active_ceiling) and hook is None:
                    raise PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503)
                try:
                    result = hook(json.loads(json.dumps(state)), dict(incoming)) if hook else self.manual_result(state, incoming)
                    validate_hook = request.app.state.hooks.get('auction.proxy.validate.v2')
                    if validate_hook is not None:
                        validate_hook(state, incoming, result)
                    self.validate_result(state, incoming, result)
                    if result['current_minor'] + step_at(state['increment_bands'], result['current_minor']) > MAX_MINOR:
                        raise PublicError('bid_amount_limit', 'The next increment exceeds the supported monetary range.', status=409)
                except PublicError:
                    raise
                except Exception:
                    raise PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503) from None
            except PublicError as exc:
                if exc.status >= 500:
                    raise
                outcome.update(code=exc.code, server_time=now.isoformat())
                return await self.store(tx, principal, key, digest, outcome, auction_id, maximum_binding=maximum_binding)
            ends_at, end_version = lot['scheduled_ends_at'], lot['end_version']
            sequence = lot['accepted_sequence']
            operation_id = UUID(outcome['operation_id'])
            for bid in result['bids']:
                sequence += 1
                await tx.execute('''INSERT INTO auction_bids
                    (auction_id,sequence,operation_id,bidder_id,amount_minor,automatic,received_at,public_rule_version)
                    VALUES($1,$2,$3,$4,$5,$6,$7,'full-step.v2')''', auction_id, sequence, operation_id,
                    UUID(bid['bidder_id']), bid['amount_minor'], bid['automatic'], now)
            # A maximum raise with no public price change still advances canonical receipt order.
            if sequence == lot['accepted_sequence']:
                sequence += 1
            await tx.execute('UPDATE auction_maxima SET active=false WHERE auction_id=$1', auction_id)
            for maximum in result['maxima']:
                await tx.execute('''INSERT INTO auction_maxima(auction_id,bidder_id,amount_minor,sequence,active,verified_ceiling)
                    VALUES($1,$2,$3,$4,$5,true) ON CONFLICT(auction_id,bidder_id) DO UPDATE SET
                    amount_minor=excluded.amount_minor,sequence=excluded.sequence,active=excluded.active,verified_ceiling=true''', auction_id,
                    UUID(maximum['bidder_id']), maximum['amount_minor'], maximum['sequence'], maximum['active'])
            updated = await tx.fetchrow('''UPDATE auction_lots SET current_minor=$2,leader_id=$3,
                accepted_sequence=$4,ends_at=$5,end_version=$6,revision=revision+1 WHERE id=$1 RETURNING *''', auction_id,
                result['current_minor'], UUID(result['leader_id']), sequence, ends_at, end_version)
            outcome.update(status='succeeded', code='bid_accepted', revision=updated['revision'],
                accepted_sequence=sequence, current_minor=updated['current_minor'],
                next_minimum_minor=next_minimum(updated, state['increment_bands']), server_time=now.isoformat(),
                ends_at=updated['ends_at'].isoformat(), end_version=updated['end_version'], mode=updated['mode'])
            await self.store(tx, principal, key, digest, outcome, auction_id, maximum_binding=maximum_binding)
            data = {'auction_id': str(auction_id), 'listing_id': str(lot['listing_id']), 'sequence': sequence,
                'revision': updated['revision'], 'current_minor': updated['current_minor'], 'currency': lot['currency'],
                'ends_at': updated['ends_at'].isoformat(), 'bidder_id': bidder_id,
                'previous_leader_id': str(lot['leader_id']) if lot['leader_id'] else None,
                'leader_id': result['leader_id']}
            await enqueue(tx, EventEnvelope(type='auction.bid-accepted.v1', source='auction', subject=str(auction_id), time=now,
                request_id=request.state.request_id, data=data), ['communications'])
            if result['leader_id'] != bidder_id:
                await enqueue(tx, EventEnvelope(type='auction.bid-outbid.v2', source='auction', subject=str(auction_id),
                    time=now, request_id=request.state.request_id,
                    data={'auction_id': str(auction_id), 'listing_id': str(lot['listing_id']),
                          'sequence': sequence, 'revision': updated['revision'], 'bidder_id': bidder_id,
                          'current_minor': updated['current_minor'], 'currency': lot['currency']}), ['bid-notices-v2'])
            await enqueue(tx, EventEnvelope(type='auction.timing-updated.v2', source='auction', subject=str(auction_id),
                time=now, request_id=request.state.request_id,
                data={'auction_id': str(auction_id), 'listing_id': str(lot['listing_id']),
                      'revision': updated['revision'], 'end_version': updated['end_version'],
                      'ends_at': updated['ends_at'].isoformat(), 'mode': updated['mode']}), ['auction-timing-v2'])
            return outcome

    async def recheck_bid_permission(self, request, previous):
        current = await self.dependencies.principal(request)
        if ('buyer' not in current.roles or current.actor.organization_id is not None
                or current.actor.subject_id != previous.actor.subject_id
                or set(current.organizations) != set(previous.organizations)):
            raise AccessDenied('Current buyer scope changed')
        require_bid_permission(current)

    async def lock_publication(self, tx, listing_id, revision):
        # Use the receiver's listing lock even before a watermark row exists.
        # Acquire it before the auction lock, in the same order as listing edits.
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing:' + str(listing_id))
        await self.require_current_publication(tx, listing_id, revision)

    @staticmethod
    async def require_current_publication(tx, listing_id, revision):
        published_revision = await tx.fetchval(
            'SELECT revision FROM auction_publication_watermarks WHERE listing_id=$1', listing_id)
        if published_revision is not None and revision < published_revision:
            raise PublicError('listing_changed', 'Reload the current listing publication.', status=409)

    @staticmethod
    def manual_result(state, command):
        return expected_result(state, command)

    validate_result = staticmethod(validate_result)

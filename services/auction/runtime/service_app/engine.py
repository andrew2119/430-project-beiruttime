"""Auction is the only commit owner. CP B-04/B-09/B-18 transaction protocol."""
import hashlib
import json
import os
import re
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from fastapi import Request
from bt_contracts.auction.core.models import MAX_MINOR, next_minimum, step_at
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from .dependencies import Dependencies


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


def public_lot(lot, now):
    bands = decoded(lot['increment_bands'])
    return {'id': str(lot['id']), 'listing_id': str(lot['listing_id']), 'currency': lot['currency'],
        'opening_minor': lot['opening_minor'], 'current_minor': lot['current_minor'],
        'next_minimum_minor': next_minimum(lot, bands), 'increment_bands': bands,
        'starts_at': lot['starts_at'].isoformat(), 'ends_at': lot['ends_at'].isoformat(),
        'server_time': now.isoformat(), 'revision': lot['revision'],
        'accepted_sequence': lot['accepted_sequence'], 'rules_version': lot['rules_version'],
        'extension_policy': lot['extension_policy'], 'high_value_minor': lot['high_value_minor'],
        'reserve_set': lot['reserve_minor'] is not None,
        'leader': mask(lot['id'], lot['leader_id']) if lot['leader_id'] else None,
        'status': 'scheduled' if now < lot['starts_at'] else 'ended' if now >= lot['ends_at'] else 'live'}


def time_denial(lot, now):
    if now < lot['starts_at']:
        return 'not_started'
    if now >= lot['ends_at']:
        return 'auction_ended'
    return None


def mask(auction_id, bidder_id):
    return 'Bidder ' + hashlib.sha256(f'{auction_id}:{bidder_id}'.encode()).hexdigest()[:8]


class AuctionEngine:
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

    async def store(self, tx, principal, key, digest, outcome, auction_id):
        await tx.execute('''INSERT INTO auction_operations
            (id,subject_id,organization_id,operation_key,request_hash,auction_id,outcome)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''', UUID(outcome['operation_id']),
            principal.actor.subject_id, principal.actor.organization_id, key, digest, auction_id,
            json.dumps(outcome))
        return outcome

    async def create(self, request, command):
        principal = await self.dependencies.principal(request)
        require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
        key = key_for(request)
        digest = fingerprint('create', command.listing_id, command)
        auction_id = uuid5(NAMESPACE_URL, f'auction:{principal.actor.subject_id}:{key}')
        pool = request.app.state.pool
        async with unit_of_work(pool) as tx:
            replay = await self.operation(tx, principal, key, digest)
            if replay:
                return replay
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'listing:' + str(command.listing_id))
            existing = await tx.fetchrow('SELECT * FROM auction_lots WHERE listing_id=$1', command.listing_id)
            if existing:
                self.owner(existing, principal)
                now = await tx.fetchval('SELECT clock_timestamp()')
                result = {'operation_id': str(uuid4()), 'status': 'succeeded', 'code': 'already_opened',
                    'auction_id': str(existing['id']), 'auction': public_lot(existing, now)}
                return await self.store(tx, principal, key, digest, result, existing['id'])
            now = await tx.fetchval('SELECT clock_timestamp()')
            if command.ends_at <= now:
                raise PublicError('invalid_schedule', 'The auction must end in the future.', status=409)
            listing = await self.dependencies.listing(request, command.listing_id)
            self.published(listing, command.listing_id, principal)
            commitment = await self.dependencies.fence(request, listing, auction_id, key)
            now = await tx.fetchval('SELECT clock_timestamp()')
            if command.ends_at <= now:
                raise PublicError('invalid_schedule', 'The auction must end in the future.', status=409)
            defaults = {'USD': '1000000', 'LBP': '89500000000'}
            high_value = int(os.environ.get('AUCTION_HIGH_VALUE_' + command.currency + '_MINOR', defaults[command.currency]))
            if not 1 <= high_value <= MAX_MINOR:
                raise PublicError('rules_unavailable', 'The auction rules are unavailable.', status=503)
            lot = await tx.fetchrow('''INSERT INTO auction_lots
                (id,listing_id,watch_id,seller_id,seller_organization_id,currency,opening_minor,
                 reserve_minor,increment_bands,starts_at,ends_at,commitment_id,high_value_minor)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13) RETURNING *''',
                auction_id, command.listing_id, UUID(listing['watch_id']), UUID(listing['seller_id']),
                principal.actor.organization_id, command.currency, command.opening_minor, command.reserve_minor,
                json.dumps([b.model_dump() for b in command.increment_bands]), command.starts_at,
                command.ends_at, commitment, high_value)
            outcome = {'operation_id': str(uuid4()), 'status': 'succeeded', 'code': 'auction_opened',
                'auction_id': str(auction_id), 'auction': public_lot(lot, now)}
            await enqueue(tx, EventEnvelope(type='auction.opened.v1', source='auction', subject=str(auction_id), time=now,
                request_id=request.state.request_id, data=public_lot(lot, now)), ['catalog'])
            return await self.store(tx, principal, key, digest, outcome, auction_id)

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
        async with unit_of_work(request.app.state.pool) as tx:
            replay = await self.operation(tx, principal, key, digest)
            if replay:
                return replay
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'auction:' + str(auction_id))
            lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1 FOR UPDATE', auction_id)
            if not lot:
                raise PublicError('not_found', 'Auction not found.', status=404)
            self.owner(lot, principal)
            if lot['accepted_sequence']:
                raise PublicError('rules_frozen', 'Economic settings are frozen after the first bid.', status=409)
            if lot['revision'] != int(revision):
                raise PublicError('stale_revision', 'Reload the current auction.', status=409)
            self.published(await self.dependencies.listing(request, lot['listing_id']), lot['listing_id'], principal)
            await self.dependencies.check_fence(request, lot)
            now = await tx.fetchval('SELECT clock_timestamp()')
            if command.ends_at <= now or lot['ends_at'] <= now:
                raise PublicError('invalid_schedule', 'The auction must end in the future.', status=409)
            lot = await tx.fetchrow('''UPDATE auction_lots SET currency=$2,opening_minor=$3,reserve_minor=$4,
                increment_bands=$5::jsonb,starts_at=$6,ends_at=$7,revision=revision+1 WHERE id=$1 RETURNING *''',
                auction_id, command.currency, command.opening_minor, command.reserve_minor,
                json.dumps([b.model_dump() for b in command.increment_bands]), command.starts_at, command.ends_at)
            result = {'operation_id': str(uuid4()), 'status': 'succeeded', 'code': 'rules_updated',
                'auction_id': str(auction_id), 'auction': public_lot(lot, now)}
            await enqueue(tx, EventEnvelope(type='auction.rules-updated.v1', source='auction', subject=str(auction_id), time=now,
                request_id=request.state.request_id, data=public_lot(lot, now)), ['catalog'])
            return await self.store(tx, principal, key, digest, result, auction_id)

    async def submit(self, request: Request, auction_id: UUID, command, *, kind='manual'):
        if kind not in ('manual', 'maximum'):
            raise ValueError('Unknown bid kind')
        principal = await self.dependencies.principal(request)
        # Identity's current buyer role is the published buying capability, not a self-granted claim.
        if 'buyer' not in principal.roles:
            raise AccessDenied('Current buyer capability required')
        if principal.actor.organization_id is not None:
            raise AccessDenied('Bid as an individual buyer')
        key = key_for(request)
        digest = fingerprint(kind, auction_id, command)
        async with unit_of_work(request.app.state.pool) as tx:
            replay = await self.operation(tx, principal, key, digest)
            if replay:
                return replay
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'auction:' + str(auction_id))
            lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1 FOR UPDATE', auction_id)
            if not lot:
                raise PublicError('not_found', 'Auction not found.', status=404)
            now = await tx.fetchval('SELECT clock_timestamp()')
            outcome = {'operation_id': str(uuid4()), 'auction_id': str(auction_id), 'status': 'denied',
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
                if command.expected_revision != lot['revision']:
                    raise PublicError('stale_revision', 'Review the current auction and fee preview.', status=409)
                minimum = (lot['current_minor'] if kind == 'maximum' and lot['leader_id'] == principal.actor.subject_id
                    else outcome['next_minimum_minor'])
                if command.amount_minor < minimum:
                    raise PublicError('bid_too_low', 'Use at least the current minimum bid.', status=409)
                if kind == 'manual' and command.amount_minor + step_at(decoded(lot['increment_bands']), command.amount_minor) > MAX_MINOR:
                    raise PublicError('bid_amount_limit', 'The next increment exceeds the supported monetary range.', status=409)
                listing = await self.dependencies.listing(request, lot['listing_id'])
                self.published(listing, lot['listing_id'])
                if (UUID(listing['seller_id']) != lot['seller_id']
                        or listing.get('seller_organization_id') != (str(lot['seller_organization_id']) if lot['seller_organization_id'] else None)):
                    raise PublicError('listing_changed', 'The listing seller has changed.', status=409)
                await self.dependencies.check_fence(request, lot)
                fee_expires_at = await self.dependencies.fee(request, command, lot, principal, now)
                if command.amount_minor >= lot['high_value_minor']:
                    await self.dependencies.contact(request)
                # Recheck authoritative time after bounded prerequisite calls; no late commit.
                now = await tx.fetchval('SELECT clock_timestamp()')
                if now >= lot['ends_at']:
                    raise PublicError('auction_ended', 'The auction has ended.', status=409)
                if fee_expires_at <= now:
                    raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
                maxima = [dict(row) for row in await tx.fetch(
                    'SELECT bidder_id,amount_minor,sequence FROM auction_maxima WHERE auction_id=$1', auction_id)]
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
                hook = request.app.state.hooks.get('auction.proxy.v1')
                active_ceiling = any(maximum['amount_minor'] > lot['current_minor'] for maximum in maxima)
                if (kind == 'maximum' or active_ceiling) and hook is None:
                    raise PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503)
                try:
                    result = hook(json.loads(json.dumps(state)), dict(incoming)) if hook else self.manual_result(state, incoming)
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
                return await self.store(tx, principal, key, digest, outcome, auction_id)
            sequence = lot['accepted_sequence']
            operation_id = UUID(outcome['operation_id'])
            for bid in result['bids']:
                sequence += 1
                await tx.execute('''INSERT INTO auction_bids
                    (auction_id,sequence,operation_id,bidder_id,amount_minor,automatic,received_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7)''', auction_id, sequence, operation_id,
                    UUID(bid['bidder_id']), bid['amount_minor'], bid['automatic'], now)
            # A maximum raise with no public price change still advances canonical receipt order.
            if sequence == lot['accepted_sequence']:
                sequence += 1
            for maximum in result['maxima']:
                await tx.execute('''INSERT INTO auction_maxima(auction_id,bidder_id,amount_minor,sequence)
                    VALUES($1,$2,$3,$4) ON CONFLICT(auction_id,bidder_id) DO UPDATE SET
                    amount_minor=excluded.amount_minor,sequence=excluded.sequence''', auction_id,
                    UUID(maximum['bidder_id']), maximum['amount_minor'], maximum['sequence'])
            updated = await tx.fetchrow('''UPDATE auction_lots SET current_minor=$2,leader_id=$3,
                accepted_sequence=$4,revision=revision+1 WHERE id=$1 RETURNING *''', auction_id,
                result['current_minor'], UUID(result['leader_id']), sequence)
            outcome.update(status='succeeded', code='bid_accepted', revision=updated['revision'],
                accepted_sequence=sequence, current_minor=updated['current_minor'],
                next_minimum_minor=next_minimum(updated, state['increment_bands']), server_time=now.isoformat())
            await self.store(tx, principal, key, digest, outcome, auction_id)
            data = {'auction_id': str(auction_id), 'listing_id': str(lot['listing_id']), 'sequence': sequence,
                'revision': updated['revision'], 'current_minor': updated['current_minor'], 'currency': lot['currency'],
                'ends_at': lot['ends_at'].isoformat(), 'bidder_id': bidder_id,
                'previous_leader_id': str(lot['leader_id']) if lot['leader_id'] else None,
                'leader_id': result['leader_id']}
            await enqueue(tx, EventEnvelope(type='auction.bid-accepted.v1', source='auction', subject=str(auction_id), time=now,
                request_id=request.state.request_id, data=data), ['communications'])
            return outcome

    @staticmethod
    def manual_result(state, command):
        # Preserve manual caps too: installing the pure proxy hook never invents historical state.
        maxima = [dict(maximum) for maximum in state['maxima'] if maximum['bidder_id'] != command['bidder_id']]
        maxima.append({'bidder_id': command['bidder_id'], 'amount_minor': command['amount_minor'],
            'sequence': command['sequence']})
        return {'leader_id': command['bidder_id'], 'current_minor': command['amount_minor'], 'maxima': maxima,
            'bids': [{'bidder_id': command['bidder_id'], 'amount_minor': command['amount_minor'], 'automatic': False}]}

    @staticmethod
    def validate_result(state, command, result):
        # Frozen seam is private, but malformed implementations cannot corrupt the canonical engine.
        def invalid():
            raise PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503)
        try:
            if set(result) != {'leader_id', 'current_minor', 'maxima', 'bids'}:
                invalid()
            UUID(result['leader_id'])
            price = result['current_minor']
            if type(price) is not int or not max(state['current_minor'], state['opening_minor']) <= price <= MAX_MINOR:
                invalid()
            if len(result['maxima']) > 10000 or len(result['bids']) > 8:
                invalid()
            old = {m['bidder_id']: m for m in state['maxima']}
            new = {m['bidder_id']: m for m in result['maxima']}
            if not new or len(new) != len(result['maxima']) or not set(old) <= set(new):
                invalid()
            if len({maximum['sequence'] for maximum in new.values()}) != len(new):
                invalid()
            for bidder, maximum in new.items():
                UUID(bidder)
                if set(maximum) != {'bidder_id', 'amount_minor', 'sequence'}:
                    invalid()
                if type(maximum['amount_minor']) is not int or not state['opening_minor'] <= maximum['amount_minor'] <= MAX_MINOR:
                    invalid()
                if type(maximum['sequence']) is not int or not 1 <= maximum['sequence'] <= command['sequence']:
                    invalid()
                if bidder != command['bidder_id'] and maximum != old.get(bidder):
                    invalid()
                if bidder == command['bidder_id'] and maximum != old.get(bidder):
                    if maximum['amount_minor'] > command['amount_minor'] or maximum['sequence'] != command['sequence']:
                        invalid()
                    if bidder in old and maximum['amount_minor'] <= old[bidder]['amount_minor']:
                        invalid()
            winner = min(new.values(), key=lambda maximum: (-maximum['amount_minor'], maximum['sequence']))
            if result['leader_id'] != winner['bidder_id']:
                invalid()
            previous = state['current_minor'] if state['sequence'] else 0
            allowed = {command['bidder_id'], *old}
            if result['leader_id'] not in allowed:
                invalid()
            for bid in result['bids']:
                if set(bid) != {'bidder_id', 'amount_minor', 'automatic'} or bid['bidder_id'] not in allowed:
                    invalid()
                if (bid['automatic'] and bid['bidder_id'] != result['leader_id']) or (not bid['automatic']
                        and (command['kind'] != 'manual' or bid['bidder_id'] != command['bidder_id']
                             or bid['amount_minor'] != command['amount_minor'])):
                    invalid()
                cap = command['amount_minor'] if bid['bidder_id'] == command['bidder_id'] else old[bid['bidder_id']]['amount_minor']
                minimum = state['opening_minor'] if previous == 0 else previous + step_at(state['increment_bands'], previous)
                capped_response = (bid['automatic'] is True and bid['bidder_id'] == result['leader_id']
                    and bid['amount_minor'] == cap and cap >= previous)
                earlier_tie = (cap == previous and bid['bidder_id'] in old
                    and old[bid['bidder_id']]['sequence'] < command['sequence'])
                if (type(bid['amount_minor']) is not int or type(bid['automatic']) is not bool
                        or bid['amount_minor'] > cap or (bid['amount_minor'] < minimum and not capped_response)
                        or (bid['amount_minor'] <= previous and not (capped_response and earlier_tie))):
                    invalid()
                previous = bid['amount_minor']
            if result['bids'] and (previous != price or result['bids'][-1]['bidder_id'] != result['leader_id']):
                invalid()
            if not result['bids'] and (price != state['current_minor'] or result['leader_id'] != state['leader_id']):
                invalid()
        except (KeyError, TypeError, ValueError):
            invalid()

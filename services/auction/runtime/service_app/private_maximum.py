"""Owner-only maximum views of the canonical Auction transaction and receipts."""
from uuid import UUID, uuid4

from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work

from .engine import TERMINAL_BID_DENIALS, decoded, fingerprint, key_for
from .kernel import lock_lot


def missing():
    return PublicError('not_found', 'Operation not found.', status=404)


def unavailable():
    return PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503)


def conflict():
    return PublicError('idempotency_conflict', 'This key belongs to a different request.', status=409)


def require_access(lot, principal):
    if lot is None:
        raise PublicError('not_found', 'Auction not found.', status=404)
    if lot['seller_id'] == principal.actor.subject_id or lot['seller_organization_id'] in principal.organizations:
        raise AccessDenied('Current auction access denied')
    if lot['currency'] != 'USD':
        raise PublicError('legacy_reconciliation', 'Historic currency is restricted to reconciliation.', status=409)


async def own_bidder(engine, request):
    principal = await engine.dependencies.principal(request)
    if 'buyer' not in principal.roles or principal.actor.organization_id is not None:
        raise AccessDenied('Individual buyer required')
    return principal


class PrivateMaximum:
    def __init__(self, engine):
        self.engine = engine

    async def read_current(self, request, auction_id):
        principal = await own_bidder(self.engine, request)
        actor = principal.actor.subject_id
        async with request.app.state.pool.acquire() as tx:
            # A single snapshot ties the ceiling and standing to the displayed revision.
            lot = await tx.fetchrow('''SELECT a.*, m.amount_minor AS own_ceiling, m.active AS own_active,
                EXISTS(SELECT 1 FROM auction_operations AS o WHERE o.auction_id=a.id
                    AND o.subject_id=$2 AND o.organization_id IS NULL
                    AND o.outcome->>'status'='succeeded' AND o.outcome->>'code'='bid_accepted') AS has_bid
                FROM auction_lots AS a LEFT JOIN auction_maxima AS m
                  ON m.auction_id=a.id AND m.bidder_id=$2 AND m.verified_ceiling
                WHERE a.id=$1''', auction_id, actor)
        require_access(lot, principal)
        standing = 'leading' if lot['leader_id'] == actor else 'outbid' if lot['has_bid'] else None
        return dict(schema_version=2, auction_id=str(auction_id), watch_id=str(lot['watch_id']), actor_id=str(actor),
                    revision=lot['revision'], amount_minor=lot['own_ceiling'],
                    active=lot['own_active'] is True and standing == 'leading', standing=standing)

    async def context(self, request, auction_id, key):
        principal = await own_bidder(self.engine, request)
        async with request.app.state.pool.acquire() as tx:
            async with tx.transaction(isolation='repeatable_read', readonly=True):
                lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
                require_access(lot, principal)
                prior = await tx.fetchrow('''SELECT * FROM auction_operations
                    WHERE subject_id=$1 AND operation_key=$2''', principal.actor.subject_id, key)
        return principal, lot, prior

    @staticmethod
    def project(prior, lot, principal, key, *, digest=None):
        if not prior or prior['organization_id'] is not None or prior['auction_id'] != lot['id']:
            raise conflict() if prior and digest is not None else missing()
        binding = decoded(prior['private_maximum_binding'])
        if digest is not None and (prior['request_hash'] != digest or not binding):
            raise conflict()
        if not binding:
            raise missing()
        if (not isinstance(binding, dict) or binding.get('operation_id') != key
                or binding.get('actor_id') != str(principal.actor.subject_id)
                or binding.get('subject_id') != str(lot['id']) or binding.get('watch_id') != str(lot['watch_id'])):
            raise unavailable()
        outcome = decoded(prior['outcome'])
        if not isinstance(outcome, dict) or type(outcome.get('revision')) is not int or not isinstance(outcome.get('code'), str):
            raise unavailable()
        status, code = outcome.get('status'), outcome['code']
        state = ('accepted' if status == 'succeeded' and code == 'bid_accepted'
                 else 'pending' if status == 'pending'
                 else ('stale' if code == 'stale_revision' else 'denied') if status == 'denied' else None)
        if state is None:
            raise unavailable()
        return {**binding, 'schema_version': 2, 'organization_id': None, 'state': state,
                'revision': outcome['revision'], 'pending_reason': outcome['code'] if state == 'pending' else None,
                'next_actor': None, 'next_review_at': None}

    async def lookup_current(self, request, auction_id, operation_id):
        key = str(operation_id)
        principal, lot, prior = await self.context(request, auction_id, key)
        return self.project(prior, lot, principal, key)

    async def submit_current(self, request, auction_id, command):
        key = str(UUID(key_for(request)))
        digest = fingerprint('maximum-v2', auction_id, command)
        principal, lot, prior = await self.context(request, auction_id, key)
        expiry = None
        if prior:
            existing = self.project(prior, lot, principal, key, digest=digest)
            if existing['state'] != 'pending':
                return existing
            binding = decoded(prior['private_maximum_binding'])
        else:
            # Even a suspended buyer can read their retained reviewed quote to
            # bind a definitive denial to the exact command. This does not admit a bid.
            quote = await self.engine.dependencies.bid_quote(request, command, lot, principal)
            if quote.policy is None:
                raise unavailable()
            policy_revision = str(quote.policy.revision)
            if command.watch_id is not None and (command.watch_id != lot['watch_id']
                    or command.quote_revision != quote.revision or command.policy_revision != policy_revision):
                raise AccessDenied('The submitted quote or watch binding is not current')
            binding = dict(operation_id=key, subject_id=str(auction_id), actor_id=str(principal.actor.subject_id),
                           watch_id=str(lot['watch_id']), quote_id=str(quote.id), quote_revision=quote.revision,
                           policy_revision=policy_revision, expected_revision=command.expected_revision)
            expiry = quote.expires_at
        try:
            await self.engine.submit(request, auction_id, command, kind='maximum', maximum_binding=binding,
                                     quote_expires_at=expiry, recovery_only=prior is not None)
        except PublicError as exc:
            if exc.status < 500 and exc.code in TERMINAL_BID_DENIALS:
                await self.settle_denial(request, auction_id, command, key, digest, exc.code, binding=binding)
            elif exc.status < 500 and exc.code != 'sale_mode_pending':
                raise
        principal, lot, saved = await self.context(request, auction_id, key)
        if not saved:
            raise unavailable()
        return self.project(saved, lot, principal, key, digest=digest)

    async def settle_denial(self, request, auction_id, command, key, digest, code, *, binding=None):
        principal = await own_bidder(self.engine, request)
        if binding is not None and binding['actor_id'] != str(principal.actor.subject_id):
            raise AccessDenied('Current maximum access denied')
        async with unit_of_work(request.app.state.pool) as tx:
            previous = await self.engine.operation(tx, principal, key, digest)
            lot = await lock_lot(tx, auction_id)
            require_access(lot, principal)
            if previous is not None:
                if previous['status'] != 'pending' or previous.get('commitment_status') != 'succeeded':
                    return
            elif binding is None:
                # Historical reconciliation is allowed only for a persisted intent.
                raise missing()
            if binding is not None and binding['watch_id'] != str(lot['watch_id']):
                raise AccessDenied('The submitted watch binding is not current')
            if code != 'bid_permission_required' and lot['revision'] != command.expected_revision:
                code = 'stale_revision'
            outcome = dict(operation_id=previous['operation_id'] if previous else str(uuid4()),
                           auction_id=str(auction_id), status='denied', code=code, revision=lot['revision'])
            await self.engine.store(tx, principal, key, digest, outcome, auction_id, maximum_binding=binding)

    async def submit_legacy_current(self, request, auction_id, command):
        return await self.engine.submit(request, auction_id, command, kind='maximum')

    async def reconcile_legacy_current(self, request, auction_id, command):
        key = key_for(request)
        _, lot, prior = await self.context(request, auction_id, key)
        digest = fingerprint('maximum', auction_id, command)
        if (prior is None or prior['auction_id'] != lot['id']
                or prior['organization_id'] is not None or prior['request_hash'] != digest):
            raise missing()
        if decoded(prior['outcome'])['status'] != 'pending':
            return
        try:
            await self.engine.submit(request, auction_id, command, kind='maximum', recovery_only=True)
        except PublicError as exc:
            if exc.status >= 500 or exc.code not in TERMINAL_BID_DENIALS:
                raise
            await self.settle_denial(request, auction_id, command, key, digest, exc.code)

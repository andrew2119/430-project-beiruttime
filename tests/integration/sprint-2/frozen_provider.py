"""Deterministic local doubles for embedded freezes, never connected proof."""
from copy import deepcopy
from datetime import timedelta
from proof import instant, minor


class Denied(ValueError):
    pass


class Stale(Denied):
    pass


class LostResponse(TimeoutError):
    pass


def proxy_v2(source, command):
    """Private hook shape. Canonical admission/time/serialization stays external."""
    state = deepcopy(source)
    maxima = state['maxima']
    bidder, amount = command['bidder_id'], minor(command['amount_minor'])
    if command['kind'] not in {'manual', 'maximum'}:
        raise Denied('unsupported command')
    if command['sequence'] <= state['sequence']:
        raise Stale('sequence')
    bands = state['increment_bands']
    def step(value):
        found = [b for b in bands if value >= b['from_minor']]
        if not found:
            raise Denied('increment unavailable')
        result = found[-1]['step_minor']
        if type(result) is not int or result <= 0:
            raise Denied('invalid increment')
        return result
    own = next((m for m in maxima if m['bidder_id'] == bidder), None)
    leader, current = state['leader_id'], state['current_minor']
    if command['kind'] == 'maximum' and own and amount <= own['amount_minor']:
        raise Denied('raise only')
    if leader == bidder:
        if command['kind'] != 'maximum':
            raise Denied('no self competition')
        if amount < current:
            raise Denied('ceiling below public price')
        if own:
            own.update(amount_minor=amount, sequence=command['sequence'], active=True)
        else:
            maxima.append(dict(bidder_id=bidder, amount_minor=amount,
                               sequence=command['sequence'], active=True))
        return dict(leader_id=leader, current_minor=current, maxima=maxima, bids=[])
    minimum = state['opening_minor'] if leader is None else current + step(current)
    if amount < minimum:
        raise Denied('below next minimum')
    incumbent = next((m for m in maxima if m['bidder_id'] == leader and m['active']), None)
    challenge = amount
    if command['kind'] == 'maximum':
        challenge = minimum if incumbent is None else max(minimum, min(amount, incumbent['amount_minor']))
        if own:
            own.update(amount_minor=amount, sequence=command['sequence'], active=True)
        else:
            own = dict(bidder_id=bidder, amount_minor=amount,
                       sequence=command['sequence'], active=True)
            maxima.append(own)
    bids = [dict(bidder_id=bidder, amount_minor=challenge, automatic=False)]
    result_leader, result_price = bidder, challenge
    if incumbent and incumbent['amount_minor'] >= challenge + step(challenge):
        result_leader, result_price = incumbent['bidder_id'], challenge + step(challenge)
        bids.append(dict(bidder_id=result_leader, amount_minor=result_price, automatic=True))
    for maximum in maxima:
        maximum['active'] = maximum['bidder_id'] == result_leader
    return dict(leader_id=result_leader, current_minor=result_price, maxima=maxima, bids=bids)


class FrozenSources:
    """In-memory fixture store. A copied store simulates acknowledged restart."""
    def __init__(self, store=None):
        self.store = deepcopy(store) if store is not None else {'receipts': {}, 'quotes': {}, 'notices': {}}

    def command(self, operation, actor, body, apply, lose_response=False):
        binding = dict(actor=actor, body=deepcopy(body))
        old = self.store['receipts'].get(operation)
        if old:
            if old['binding'] != binding:
                raise Denied('conflicting replay')
            return deepcopy(old['result'])
        result = apply()
        self.store['receipts'][operation] = dict(binding=binding, result=deepcopy(result))
        if lose_response:
            raise LostResponse('acknowledged result unavailable')
        return deepcopy(result)

    def quote(self, quote_id, buyer, kind, now):
        base = 500000
        value = dict(quote_id=quote_id, quote_revision=1, buyer_id=buyer,
                     order_kind=kind, currency='USD', base_minor=base,
                     buyer_fee_minor=15000 if kind == 'watch' else 0,
                     business_fee_minor=25000, total_minor=515000 if kind == 'watch' else base,
                     expires_at=(instant(now) + timedelta(minutes=15)).isoformat(), order_id=None)
        self.store['quotes'][quote_id] = value
        return deepcopy(value)

    def validate_quote(self, quote_id, consumer, buyer, now, current):
        if consumer not in {'orders', 'service-operations'}:
            raise Denied('internal consumer required')
        quote = self.store['quotes'][quote_id]
        if buyer != quote['buyer_id'] or not current:
            raise Denied('current subject scope business assessment required')
        if quote['expires_at'] is not None and instant(now) >= instant(quote['expires_at']):
            raise Stale('preview expired')
        return deepcopy(quote)

    def commit_quote(self, quote_id, consumer, operation, body, current=True, lose_response=False):
        if consumer != 'orders':
            raise Denied('orders required')
        def apply():
            quote = self.validate_quote(quote_id, consumer, body['buyer_id'], body['committed_at'], current)
            if body['quote_revision'] != quote['quote_revision']:
                raise Stale('quote revision')
            if minor(body['total_minor']) != quote['total_minor']:
                raise Denied('total mismatch')
            if quote['order_id'] not in {None, body['order_id']}:
                raise Denied('already committed')
            quote.update(order_id=body['order_id'], expires_at=None)
            self.store['quotes'][quote_id] = quote
            return quote
        return self.command(operation, consumer, {'quote_id': quote_id, **body}, apply, lose_response)

    def retained(self, quote_id, consumer):
        if consumer != 'orders':
            raise Denied('orders required')
        quote = self.store['quotes'][quote_id]
        if quote['order_id'] is None:
            raise Denied('not committed')
        return deepcopy(quote)

    def payment_notice(self, consumer, intent, receipt, durable_notice, operation, lose_response=False):
        if consumer != 'communications':
            raise Denied('communications required')
        def apply():
            for key in ('event_id', 'order_id', 'buyer_id'):
                if receipt[key] != intent[key] or receipt[key] != durable_notice[key]:
                    raise Denied('notice binding')
            if (receipt['verified_delivery_recorded'] is not True
                or receipt['notice_id'] != durable_notice['notice_id']
                or receipt['notified_at'] != durable_notice['available_at']
                or durable_notice['verified_delivery_recorded'] is not True):
                raise Denied('durable verified notice required')
            instant(receipt['notified_at'])
            existing = self.store['notices'].get(intent['order_id'])
            if existing is not None and existing != receipt:
                raise Denied('conflicting receipt')
            self.store['notices'][intent['order_id']] = deepcopy(receipt)
            return dict(notified_at=receipt['notified_at'], state='awaiting_payment')
        return self.command(operation, consumer, receipt, apply, lose_response)


def authorize_job(facts):
    """Local contract expectation; current facts must come from real owners later."""
    if facts['kind'] not in {'customization', 'service'} or facts['business_type'] not in {'brand', 'dealer'}:
        raise Denied('unsupported business or job kind')
    if not all(facts[k] for k in ('current_identity', 'current_membership', 'current_assignment',
                                  'current_revision', 'current_consent', 'current_approval',
                                  'current_custody', 'allocated', 'accepted_scope')):
        raise Denied('current prerequisites required')
    if facts['selected_business'] != facts['job_business']:
        raise Denied('business scope')
    if facts['kind'] == 'customization' and facts['business_type'] != 'brand':
        raise Denied('brand required')
    roles = [facts[k] for k in ('assessor_id', 'approver_id', 'quality_reviewer_id')]
    if len(set(roles)) != 3:
        raise Denied('independent people required')
    if (facts['kind'] == 'customization'
        and facts['eligibility_reviewer_id'] in {facts['buyer_id'], facts['approver_id']}):
        raise Denied('independent people required')
    payment, quote = facts['readiness'], facts['quote']
    if payment['buyer_id'] != facts['buyer_id'] or quote['buyer_id'] != facts['buyer_id']:
        raise Denied('current buyer binding required')
    for key in ('buyer_id', 'order_id', 'watch_id', 'quote_id', 'quote_revision', 'currency', 'total_minor'):
        if payment[key] != quote[key]:
            raise Denied('exact readiness binding')
    if payment['order_kind'] != facts['kind']:
        raise Denied('payment job kind mismatch')
    minor(payment['total_minor'])
    if payment['state'] != 'paid_held' or payment['currency'] != 'USD':
        raise Denied('platform held payment required')
    return 'authorized_expectation'

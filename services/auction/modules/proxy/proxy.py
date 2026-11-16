"""Pure auction.proxy.v1 arithmetic, invoked in the owning Auction transaction.

No IO, clocks, randomness, connection or commit. The return value is
private transaction state, NEVER a public DTO, diagnostic, event or receipt.
"""
from copy import deepcopy

MAX_MINOR = 9_000_000_000_000_000


def _integer(value, *, minimum=0, maximum=MAX_MINOR):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_minor_units')
    return value


def _identity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError('invalid_bidder')
    return value


def calculate(state: dict, command: dict) -> dict:
    """Frozen L05 contract; sequences are authoritative, never browser timestamps.

    A ceiling increase gets the sequence that established the new ceiling. A
    manual bid below an existing own ceiling preserves that ceiling and sequence.
    Only public-price transitions enter `bids`; raising a leading private ceiling
    cannot create a public bid against oneself or disclose the new ceiling.
    """
    opening = _integer(state['opening_minor'], minimum=1)
    current = _integer(state['current_minor'], minimum=opening)
    sequence = _integer(state['sequence'])
    amount = _integer(command['amount_minor'], minimum=1)
    receipt = _integer(command['sequence'], minimum=sequence + 1)
    bidder = _identity(command['bidder_id'])
    kind = command['kind']
    if kind not in ('manual', 'maximum'):
        raise ValueError('invalid_bid_kind')
    bands = state['increment_bands']
    if not isinstance(bands, list) or not 1 <= len(bands) <= 20:
        raise ValueError('invalid_increment_bands')
    previous_threshold = -1
    for band in bands:
        threshold = _integer(band['from_minor'])
        _integer(band['step_minor'], minimum=1)
        if threshold <= previous_threshold:
            raise ValueError('invalid_increment_bands')
        previous_threshold = threshold
    if bands[0]['from_minor'] != 0:
        raise ValueError('invalid_increment_bands')

    def step_at(value):
        return next(band['step_minor'] for band in reversed(bands) if value >= band['from_minor'])

    maxima = deepcopy(state['maxima'])
    if not isinstance(maxima, list) or len(maxima) > 10000:
        raise ValueError('proxy_capacity')
    seen, receipt_sequences = set(), set()
    for maximum in maxima:
        identity = _identity(maximum['bidder_id'])
        if identity in seen:
            raise ValueError('invalid_maxima')
        seen.add(identity)
        _integer(maximum['amount_minor'], minimum=opening)
        prior_receipt = _integer(maximum['sequence'], minimum=1, maximum=sequence)
        if prior_receipt in receipt_sequences:
            raise ValueError('invalid_sequence')
        receipt_sequences.add(prior_receipt)
    old_leader = state['leader_id']
    if maxima:
        prior_winner = min(maxima, key=lambda maximum: (-maximum['amount_minor'], maximum['sequence']))
        if prior_winner['bidder_id'] != old_leader or current > prior_winner['amount_minor']:
            raise ValueError('invalid_bid_state')
    elif old_leader is not None or sequence != 0 or current != opening:
        raise ValueError('invalid_bid_state')
    prior = next((entry for entry in maxima if entry['bidder_id'] == bidder), None)
    if kind == 'maximum' and prior and amount <= prior['amount_minor']:
        raise ValueError('maximum_must_increase')
    minimum = (current if kind == 'maximum' and bidder == old_leader else
               opening if not maxima else current + step_at(current))
    if amount < minimum:
        raise ValueError('below_next_bid')
    if prior is None and len(maxima) == 10000:
        raise ValueError('proxy_capacity')
    if prior is None or amount > prior['amount_minor']:
        maxima = [entry for entry in maxima if entry['bidder_id'] != bidder]
        maxima.append({'bidder_id': bidder, 'amount_minor': amount, 'sequence': receipt})
    maxima.sort(key=lambda entry: (-entry['amount_minor'], entry['sequence']))
    winner = maxima[0]
    competitive = maxima[1]['amount_minor'] + step_at(maxima[1]['amount_minor']) if len(maxima) > 1 else opening
    manual_floor = amount if kind == 'manual' else opening
    price = min(winner['amount_minor'], max(current, competitive, manual_floor))
    if price < current or price > MAX_MINOR:
        raise ValueError('invalid_bid_state')
    bids = []
    if kind == 'manual':
        bids.append({'bidder_id': bidder, 'amount_minor': amount, 'automatic': False})
    if (kind == 'maximum' and (price != current or winner['bidder_id'] != old_leader)) or (
            kind == 'manual' and winner['bidder_id'] != bidder):
        bids.append({'bidder_id': winner['bidder_id'], 'amount_minor': price, 'automatic': True})
    return {'leader_id': winner['bidder_id'], 'current_minor': price, 'maxima': maxima, 'bids': bids}

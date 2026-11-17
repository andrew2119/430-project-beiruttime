"""Private v2 compatibility hook; admission and persistence stay in the engine."""
from copy import deepcopy
from uuid import UUID
from .proxy_validation import expected_result, validate_result

MAX_MINOR = 9_000_000_000_000


def integer(value, minimum=0, maximum=MAX_MINOR):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid private bid integer')
    return value


def identity(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Invalid private bidder')
    return value


def calculate(state, command):
    if (set(state) != {'opening_minor', 'current_minor', 'leader_id', 'sequence', 'increment_bands', 'maxima'}
            or set(command) != {'kind', 'bidder_id', 'amount_minor', 'sequence'}):
        raise ValueError('Invalid private bid fields')
    opening = integer(state['opening_minor'], 1)
    current = integer(state['current_minor'], opening)
    sequence = integer(state['sequence'])
    integer(command['sequence'], sequence + 1, sequence + 1)
    amount = integer(command['amount_minor'], opening)
    bidder = identity(command['bidder_id'])
    if command['kind'] not in ('manual', 'maximum'):
        raise ValueError('Invalid private bid kind')
    bands, maxima = state['increment_bands'], state['maxima']
    if type(bands) is not list or not 1 <= len(bands) <= 20:
        raise ValueError('Invalid increment bands')
    last = -1
    for band in bands:
        if set(band) != {'from_minor', 'step_minor'}:
            raise ValueError('Invalid increment fields')
        last = integer(band['from_minor'], last + 1)
        integer(band['step_minor'], 1)
    if bands[0]['from_minor'] != 0:
        raise ValueError('Missing opening increment band')
    if type(maxima) is not list or len(maxima) > 10000:
        raise ValueError('Invalid private maximum count')
    seen, receipts, active = set(), set(), []
    for maximum in maxima:
        if set(maximum) != {'bidder_id', 'amount_minor', 'sequence', 'active'}:
            raise ValueError('Invalid private maximum fields')
        holder = identity(maximum['bidder_id'])
        receipt = integer(maximum['sequence'], 1, sequence)
        integer(maximum['amount_minor'], opening)
        if holder in seen or receipt in receipts or type(maximum['active']) is not bool:
            raise ValueError('Invalid private maximum binding')
        seen.add(holder)
        receipts.add(receipt)
        if maximum['active']:
            active.append(maximum)
    leader = state['leader_id']
    if leader is not None:
        identity(leader)
    if (len(active) > 1 or any(m['bidder_id'] != leader or m['amount_minor'] < current for m in active)
            or (sequence == 0 and (leader is not None or maxima or current != opening))
            or (sequence > 0 and leader is None)):
        raise ValueError('Invalid private leader state')
    prior = next((m for m in maxima if m['bidder_id'] == bidder), None)
    if command['kind'] == 'maximum' and prior and amount <= prior['amount_minor']:
        raise ValueError('Private maximum must increase')
    step = next(b['step_minor'] for b in reversed(bands) if current >= b['from_minor'])
    minimum = opening if sequence == 0 else current + step
    if bidder == leader and command['kind'] == 'maximum':
        minimum = current
    if amount < minimum or (prior is None and len(maxima) == 10000):
        raise ValueError('Private bid cannot be admitted')
    result = expected_result(deepcopy(state), dict(command))
    validate_result(state, command, result)
    return result

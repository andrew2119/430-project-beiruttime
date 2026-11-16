"""Validate private full-step state before the canonical transaction writes it."""
from uuid import UUID
from bt_contracts.auction.core.models import MAX_MINOR, step_at
from bt_contracts_core.errors import PublicError


def expected_result(state, command):
    """Small independent admission specification, not a second commit authority."""
    old = {m['bidder_id']: dict(m) for m in state['maxima']}
    bidder, amount = command['bidder_id'], command['amount_minor']
    incumbent = next((m for m in old.values() if m['active']), None)
    prior = old.get(bidder)
    maxima = {key: dict(value) for key, value in old.items()}
    if prior is None or amount > prior['amount_minor']:
        maxima[bidder] = {'bidder_id': bidder, 'amount_minor': amount,
                          'sequence': command['sequence'], 'active': True}
    if bidder == state['leader_id'] and command['kind'] == 'maximum':
        return {'leader_id': bidder, 'current_minor': state['current_minor'],
                'maxima': list(maxima.values()), 'bids': []}
    minimum = (state['opening_minor'] if not state['sequence'] else
               state['current_minor'] + step_at(state['increment_bands'], state['current_minor']))
    challenge = amount if command['kind'] == 'manual' else max(minimum, min(amount,
        incumbent['amount_minor'] if incumbent and incumbent['bidder_id'] != bidder else minimum))
    bids = [{'bidder_id': bidder, 'amount_minor': challenge, 'automatic': command['kind'] == 'maximum'}]
    response = challenge + step_at(state['increment_bands'], challenge)
    leader, price = bidder, challenge
    if incumbent and incumbent['bidder_id'] != bidder and response <= incumbent['amount_minor']:
        leader, price = incumbent['bidder_id'], response
        bids.append({'bidder_id': leader, 'amount_minor': price, 'automatic': True})
    for holder in maxima.values():
        holder['active'] = holder['bidder_id'] == leader and holder['active']
    return {'leader_id': leader, 'current_minor': price, 'maxima': list(maxima.values()), 'bids': bids}


def validate_result(state, command, result):
    def invalid():
        raise PublicError('proxy_unavailable', 'Private maximum admission is unavailable.', status=503)
    try:
        if type(result) is not dict or set(result) != {'leader_id', 'current_minor', 'maxima', 'bids'}:
            invalid()
        UUID(result['leader_id'])
        if type(result['current_minor']) is not int or not 1 <= result['current_minor'] <= MAX_MINOR:
            invalid()
        if type(result['maxima']) is not list or not 1 <= len(result['maxima']) <= 10000:
            invalid()
        if type(result['bids']) is not list or len(result['bids']) > 2:
            invalid()
        seen, sequences = set(), set()
        for maximum in result['maxima']:
            if set(maximum) != {'bidder_id', 'amount_minor', 'sequence', 'active'}:
                invalid()
            UUID(maximum['bidder_id'])
            if maximum['bidder_id'] in seen or maximum['sequence'] in sequences:
                invalid()
            seen.add(maximum['bidder_id'])
            sequences.add(maximum['sequence'])
            if (type(maximum['active']) is not bool or type(maximum['amount_minor']) is not int
                    or not state['opening_minor'] <= maximum['amount_minor'] <= MAX_MINOR
                    or type(maximum['sequence']) is not int or not 1 <= maximum['sequence'] <= command['sequence']):
                invalid()
        for bid in result['bids']:
            if (set(bid) != {'bidder_id', 'amount_minor', 'automatic'} or type(bid['amount_minor']) is not int
                    or type(bid['automatic']) is not bool):
                invalid()
        expected = expected_result(state, command)
        if ({**result, 'maxima': sorted(result['maxima'], key=lambda m: m['bidder_id'])}
                != {**expected, 'maxima': sorted(expected['maxima'], key=lambda m: m['bidder_id'])}):
            invalid()
    except (KeyError, TypeError, ValueError, StopIteration):
        invalid()

"""Bounded native second-sprint execution with explicit incomplete coverage."""
import argparse
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from connected_steps import ConnectedSteps

ROOT = Path(__file__).resolve().parents[3]
CASES = ('positive', 'denied', 'stale', 'cross_account', 'cross_business',
         'timeout', 'lost_response', 'duplicate', 'restart', 'recovery')
JOURNEYS = ('protected_purchase', 'paid_auction', 'customization', 'service')


def payment_request(order):
    if order['currency'] != 'USD' or type(order['total_minor']) is not int or not 0 < order['total_minor'] <= 2**53 - 1:
        raise ValueError('invalid_payment_economics')
    if type(order['revision']) is not int or order['revision'] < 1:
        raise ValueError('invalid_payment_revision')
    return {'expected_revision': order['revision'], 'route': 'card'}


def attempt_request(order, quote):
    body = payment_request(order)
    revision = quote['revision']
    if type(revision) is not int or revision < 1:
        raise ValueError('invalid_quote_revision')
    return {**body, 'quote_revision': revision,
            'total_minor': order['total_minor'], 'currency': order['currency']}


def quote_request(subject, revision, amount, purpose='bid', source='sample'):
    payment_request({'currency': 'USD', 'total_minor': amount, 'revision': revision})
    return {'subject_id': subject, 'subject_revision': revision, 'purpose': purpose,
            'source': source, 'schedule_id': 'usd-v2', 'currency': 'USD', 'price_minor': amount}


def submission_request(draft, movement, validation):
    if (not draft.get('configuration_id') or not draft.get('configuration_revision')
            or validation.get('status') not in ('valid', 'manual_assessment')):
        raise MissingCapability('customization.current_complete_configuration')
    return {'draft_revision': draft['revision'],
            'configuration_id': draft['configuration_id'],
            'configuration_revision': draft['configuration_revision'],
            'movement_selection_id': movement['id'],
            'movement_revision': movement['revision'],
            'expected_digest': validation['digest']}


def sample_options():
    label = {'en': 'Sample finish', 'ar': 'تشطيب تجريبي'}
    return (
        ('color', 'case', {'color': label, 'finish': label, 'swatch': '#445566'}),
        ('material', 'case', {'material': label, 'grade': 'Sample grade', 'construction': 'solid'}),
        ('dial', 'dial', {'dial': label, 'hands': label, 'markers': label,
                          'provenance': 'aftermarket', 'source_reference': 'Sample dial'}),
        ('sophistication', 'package', {'interventions': [label], 'exclusions': [label],
            'required_tests': [label], 'price_reference': 'sample-finish',
            'price_minor': 10000, 'currency': 'USD', 'conversion': 'none'}))


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_walkthrough():
    spec = importlib.util.spec_from_file_location(
        'sprint_one_walkthrough', ROOT / 'tests/integration/sprint-1/connected_walkthrough.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class CurrentWalkthrough(module.Walkthrough):
        sample_password = module.PASSWORD
        def reconcile_phase(self, phase):
            if phase == 'purchases':
                reservation = self.state['reservation']
                current = self.call('orders', 'GET', '/v1/orders/' +
                    reservation['resource_id'], reservation['winner'], durable=False)['order']
                if (current['state'] not in ('awaiting_payment', 'paid_held', 'paid_out')
                        or current['quote_id'] != reservation['quote']['id']
                        or current['total_minor'] != reservation['quote']['payable_minor']):
                    raise MissingCapability('setup.retained_purchase_binding')
            elif phase == 'request':
                identifier = self.state['request_draft']['resource_id']
                current = self.call('catalog', 'GET', '/v1/request-drafts/' +
                                    identifier, 'buyer-a', durable=False)
                if (current['id'] != identifier or current['kind'] != 'customization'
                        or current['brand_id'] != self.state['businesses']['brand']['id']):
                    raise MissingCapability('setup.retained_customization_draft')
                submitted = current.get('submitted_request_id')
                if submitted:
                    retained = self.call('catalog', 'GET', '/v1/customization-requests/' +
                                         submitted, 'buyer-a', durable=False)
                    if retained['draft_id'] != identifier:
                        raise MissingCapability('setup.retained_customization_submission')
            else:
                super().reconcile_phase(phase)

        def quote(self, name, subject, revision, amount, purpose='bid', source='sample'):
            body = quote_request(subject, revision, amount, purpose, source)
            quote = self.call('pricing', 'POST', '/v1/quotes', name, body)
            reviewed = self.call('pricing', 'POST', '/v1/quotes/' + quote['id'] + '/review', name,
                {**body, 'quote_revision': quote['revision'], 'payable_minor': quote['payable_minor']})
            if not reviewed.get('reviewed_at'):
                raise MissingCapability('pricing.current_quote_review')
            return reviewed
    return CurrentWalkthrough


class MissingCapability(Exception):
    """Public capability identifiers only; never include upstream response bodies."""

    def __init__(self, *names):
        self.names = list(names)


def auction_request(listing, now):
    return {'listing_id': listing['id'], 'currency': 'USD',
            'opening_minor': 400000,
            'increment_bands': [{'from_minor': 0, 'step_minor': 10000}],
            'starts_at': (now + timedelta(seconds=3)).isoformat(),
            'ends_at': (now + timedelta(seconds=25)).isoformat()}


def maintenance_request(context, destination, operation):
    if 'limited_maintenance' not in destination['interventions']:
        raise MissingCapability('service.supported_limited_maintenance')
    return {'schema_version': 'service.maintenance.v1', 'operation_id': operation,
            'actor_id': context['actor_id'], 'subject_id': context['subject_id'],
            'watch_id': context['watch_id'], 'watch_revision': context['watch_revision'],
            **{field: destination[field] for field in (
                'organization_id', 'brand_id', 'capability_revision', 'policy_revision')},
            'expected_revision': 0, 'intervention': 'limited_maintenance',
            'reported_symptoms': 'Sample watch requires a maintenance assessment.',
            'known_modifications': '', 'photo_refs': [],
            'limited_assessment_permission': True}


def release_request(snapshot, actor, operation):
    return {'schema_version': 'orders.releases.v1', 'operation_id': operation,
            'actor_id': actor, **{field: snapshot[field] for field in (
                'organization_id', 'subject_id', 'watch_id', 'quote_id',
                'quote_revision', 'policy_revision', 'recipient_id', 'recipient_revision')},
            'expected_revision': snapshot['revision']}


class Runner:
    def __init__(self, run_dir, walk, revision):
        self.run_dir, self.walk, self.revision = Path(run_dir), walk, revision
        self.results = []
        self.observed_operations = []
        self.connected = ConnectedSteps(self, MissingCapability)

    def record(self, identifier, action):
        started = time.monotonic()
        before = set(self.walk.state.get('call_journal', {}))
        operation_start = len(self.observed_operations)
        result = {'id': identifier, 'state': 'failed', 'operation_ids': [],
                  'source_revision': self.revision}
        try:
            action()
            result['state'] = 'passed'
        except MissingCapability as error:
            result['missing_capabilities'] = error.names
        except Exception:
            # Response bodies and exception messages may contain private records.
            result['missing_capabilities'] = [identifier]
        finally:
            journal = self.walk.state.get('call_journal', {})
            result['operation_ids'] = list(dict.fromkeys(
                self.observed_operations[operation_start:] +
                [journal[key]['operation_id'] for key in journal if key not in before]))
            result['seconds'] = round(time.monotonic() - started, 6)
            self.results.append(result)
            self.save()
        return result['state'] == 'passed'

    def save(self):
        private_json(self.run_dir / 'scenarios/e06/summary.json', {
            'schema_version': 1, 'source_revision': self.revision,
            'state': 'passed' if {journey + '.' + case for journey in JOURNEYS for case in CASES}
            <= {row['id'] for row in self.results if row['state'] == 'passed'} and all(
                row['state'] == 'passed' for row in self.results) else 'failed',
            'scenarios': self.results})

    def call(self, service, method, route, actor=None, body=None, *, key=None,
             expected=(200, 201), content=None, headers=None):
        # Bypass cached walkthrough responses: every assertion observes the gateway.
        key = key or str(uuid4())
        self.observed_operations.append(key)
        return self.walk.call(service, method, route, actor, body,
                              headers={**(headers or {}), 'Idempotency-Key': key}, expected=expected,
                              **({'content': content} if content is not None else {}), durable=False)

    def capability_call(self, capability, *args, **kwargs):
        try:
            return self.call(*args, **kwargs)
        except Exception:
            raise MissingCapability(capability) from None

    def service_request(self):
        saved = self.walk.state.setdefault('e06_service', {})
        if 'request' not in saved:
            listing = next(row for row in self.walk.state['listings']
                           if row['facts']['reference'] == 'DEMO-WATCH-02')
            actor = self.walk.state['reservation']['winner']
            context = self.capability_call('service.owned_watch_maintenance_context',
                'service-operations', 'GET', '/v1/maintenance/context/' +
                listing['physical_watch_id'], actor)
            organization = self.walk.state['businesses']['dealer']['id']
            destination = next((row for row in context['destinations']
                                if row['organization_id'] == organization), None)
            if destination is None:
                raise MissingCapability('service.current_supported_business')
            saved.update(actor=actor, request=maintenance_request(
                context, destination, self.stable_key('service-request')))
            self.walk.save()
        body, actor = saved['request'], saved['actor']
        result = self.capability_call('service.authorized_request_submission',
            'service-operations', 'POST', '/v1/maintenance/requests', actor,
            body, key=body['operation_id'])
        if result['state'] != 'submitted' or any(result[field] != body[field]
                for field in ('operation_id', 'actor_id', 'organization_id', 'watch_id',
                              'watch_revision', 'capability_revision', 'policy_revision')):
            raise MissingCapability('service.retained_request_binding')
        saved['result'] = result
        self.walk.save()
        if self.service_lookup(saved) != result:
            raise MissingCapability('service.durable_request_receipt')
        return saved

    def service_lookup(self, saved, actor=None, organization=None):
        body = saved['request']
        return self.call('service-operations', 'GET', '/v1/maintenance/operations/' +
            body['operation_id'] + '?organization_id=' +
            (organization or body['organization_id']), actor or saved['actor'])

    def release(self, journey):
        reservation = self.private_order(journey)
        actor, identifier = reservation['winner'], reservation['resource_id']
        name = 'release:' + identifier
        retained = self.walk.state.get('e06_bindings', {}).get(name)
        if retained:
            current = self.call('orders', 'GET', '/v1/releases/operations/' +
                retained['operation_id'], actor, expected=(200, 404))
            if current.get('operation_id') == retained['operation_id']:
                self.verify_release(retained, current)
                if current['state'] != 'paid_out' or current['gross_minor'] != reservation['quote']['payable_minor']:
                    raise MissingCapability('release.confirmed_retained_transfer')
                self.walk.state.setdefault('e06_releases', {})[journey] = {
                    'actor': actor, 'request': retained, 'result': current}
                self.walk.save()
                return
        preview = self.capability_call('release.current_source', 'orders', 'GET',
                                       '/v1/releases/' + identifier, actor)
        snapshot = preview['snapshot']
        if snapshot['subject_id'] != identifier or snapshot['total_minor'] != reservation['quote']['payable_minor']:
            raise MissingCapability('release.retained_order_economics')
        if preview['missing']:
            allowed = {'stale_revision', 'binding_changed', 'sources_unavailable',
                'economics_unaccepted', 'payment_not_held', 'principal_unavailable',
                'refund_active', 'recipient_unverified', 'inspection_required',
                'assurance_required', 'quality_required', 'receipt_required',
                'window_open', 'hold_active', 'hold_unknown', 'release_exists'}
            if any(name not in allowed for name in preview['missing']):
                raise MissingCapability('release.invalid_condition_response')
            raise MissingCapability(*('release.' + name for name in preview['missing']))
        name = 'release:' + identifier
        body = self.bound_request(name, release_request(snapshot,
            self.walk.state['accounts'][actor]['account']['id'], self.stable_key(name)))
        result = self.call('orders', 'POST', '/v1/releases', actor, body,
                           key=body['operation_id'])
        self.verify_release(body, result)
        if result['state'] != 'paid_out' or result['gross_minor'] != snapshot['total_minor']:
            raise MissingCapability('release.confirmed_transfer')
        current = self.call('orders', 'GET', '/v1/releases/operations/' + body['operation_id'], actor)
        self.verify_release(body, current)
        if current != result:
            raise MissingCapability('release.durable_transfer_receipt')
        saved = self.walk.state.setdefault('e06_releases', {})
        saved[journey] = {'actor': actor, 'request': body, 'result': result}
        self.walk.save()

    def release_case(self, journey, case):
        saved = self.walk.state.get('e06_releases', {}).get(journey)
        if not saved:
            raise MissingCapability('release.acknowledged_operation_required')
        actor, body, original = saved['actor'], saved['request'], saved['result']
        route = '/v1/releases/operations/' + body['operation_id']
        before = self.call('orders', 'GET', route, actor)
        self.verify_release(body, before)
        if before != original:
            raise MissingCapability('release.retained_transfer_changed')
        if case == 'duplicate':
            actual = self.call('orders', 'POST', '/v1/releases', actor, body,
                               key=body['operation_id'])
            self.call('orders', 'POST', '/v1/releases', actor,
                      {**body, 'recipient_revision': body['recipient_revision'] + 1},
                      key=body['operation_id'], expected=(403,))
        elif case == 'recovery':
            actual = self.call('orders', 'POST', route + '/recover', actor,
                               key=body['operation_id'])
        else:
            raise MissingCapability('release.unsupported_case')
        self.verify_release(body, actual)
        if actual != before or self.call('orders', 'GET', route, actor) != before:
            raise MissingCapability('release.single_retained_transfer')

    @staticmethod
    def verify_release(body, result):
        if any(result.get(field) != value for field, value in body.items()):
            raise MissingCapability('release.exact_operation_binding')
        if result['state'] == 'paid_out' and (
                type(result.get('gross_minor')) is not int or
                type(result.get('fee_minor')) is not int or
                type(result.get('net_minor')) is not int or
                result['gross_minor'] <= 0 or result['fee_minor'] < 0 or result['net_minor'] < 0 or
                result['gross_minor'] != result['fee_minor'] + result['net_minor']):
            raise MissingCapability('release.exact_transfer_economics')

    def wait(self, capability, read, accept, seconds=55):
        deadline = time.monotonic() + seconds
        while True:
            current = read()
            if accept(current):
                return current
            if time.monotonic() >= deadline:
                raise MissingCapability(capability)
            time.sleep(1)

    def payment(self, reservation=None):
        walk = self.walk
        reservation = reservation or walk.state['reservation']
        actor, order_id = reservation['winner'], reservation['resource_id']
        walk.phase, walk.positions = 'e06-payment', {}
        try:
            current = self.call('orders', 'GET', '/v1/orders/' + order_id + '/checkout', actor)
            if current['order']['state'] not in ('paid_held', 'paid_out') and not current['order'].get('notified_at'):
                current = self.wait('orders.durable_verified_recipient_notice',
                    lambda: self.call('orders', 'GET', '/v1/orders/' + order_id + '/checkout', actor),
                    lambda row: bool(row['order'].get('notified_at')))
            order = current['order']
            if order['state'] not in ('paid_held', 'paid_out'):
                if not current['payable'] or not order.get('notified_at') or not order.get('deadline'):
                    raise ValueError('durable_notice_clock_required')
                selected = self.call('orders', 'POST', '/v1/orders/' + order_id + '/payment-method',
                                     actor, self.bound_request('method:' + order_id, payment_request(order)), key=self.stable_key('method:' + order_id))
                if selected['status'] != 'succeeded':
                    raise ValueError('method_not_selected')
                attempt = self.call('orders', 'POST', '/v1/orders/' + order_id + '/payment-attempts',
                                    actor, self.bound_request('attempt:' + order_id, attempt_request(selected['order'], current['quote'])), key=self.stable_key('attempt:' + order_id))
                if attempt['status'] != 'succeeded':
                    raise ValueError('attempt_not_started')
                self.call('orders', 'POST', '/v1/payment-attempts/' + attempt['attempt']['id'] + '/simulate',
                          actor, {'outcome': 'confirmed'}, key=self.stable_key('confirmation:' + order_id))
            actual = self.call('orders', 'GET', '/v1/orders/' + order_id + '/checkout', actor)
            if actual['order']['state'] not in ('paid_held', 'paid_out'):
                raise ValueError('held_payment_required')
            if actual['order']['total_minor'] != reservation['quote']['payable_minor']:
                raise ValueError('retained_economics_changed')
        finally:
            walk.phase = None

    @staticmethod
    def payment_facts(checkout):
        return {field: checkout[field] for field in ('order', 'attempts', 'quote')}

    def payment_boundary_case(self, journey, case):
        reservation = self.private_order(journey)
        actor, identifier = reservation['winner'], reservation['resource_id']
        route = '/v1/orders/' + identifier
        before = self.call('orders', 'GET', route + '/checkout', actor)
        if before['order']['state'] != 'paid_held':
            raise MissingCapability('payment.confirmed_held_receipt')
        body = payment_request(before['order'])
        if case == 'stale':
            result = self.call('orders', 'POST', route + '/payment-method', actor,
                {**body, 'expected_revision': body['expected_revision'] + 1},
                key=self.stable_key('stale:' + identifier))
            if result.get('status') != 'denied' or result.get('code') != 'stale_revision':
                raise MissingCapability('payment.stale_revision_denial')
        elif case in ('denied', 'cross_business'):
            actors = ('seller',) if case == 'denied' else ('dealer', 'brand')
            for other in actors:
                self.call('orders', 'GET', route + '/checkout', other, expected=(403, 404))
                self.call('orders', 'POST', route + '/payment-attempts', other,
                    attempt_request(before['order'], before['quote']), expected=(403, 404))
        elif case in ('duplicate', 'recovery'):
            name = 'attempt:' + identifier
            retained = self.walk.state.get('e06_bindings', {}).get(name)
            if retained is None:
                raise MissingCapability('payment.original_attempt_binding')
            # Read the authoritative attempt before replaying the original delivery.
            attempts = before['attempts']
            if len(attempts) != 1:
                raise MissingCapability('payment.single_retained_attempt')
            result = self.call('orders', 'POST', route + '/payment-attempts', actor,
                retained, key=self.stable_key(name))
            if result.get('status') != 'succeeded' or result['attempt']['id'] != attempts[0]['id']:
                raise MissingCapability('payment.exact_attempt_replay')
            self.call('orders', 'POST', '/v1/payment-attempts/' + attempts[0]['id'] + '/simulate',
                actor, {'outcome': 'confirmed'}, key=self.stable_key('confirmation:' + identifier))
        else:
            raise MissingCapability('payment.' + case + '.runtime_control_contract')
        after = self.call('orders', 'GET', route + '/checkout', actor)
        if self.payment_facts(before) != self.payment_facts(after):
            raise MissingCapability('payment.unchanged_retained_economics_and_attempts')

    def payment_case(self, journey, case):
        return self.connected.fault_case(journey, case)

    def lost_payment_response(self, journey):
        reservation = self.private_order(journey)
        actor, identifier = reservation['winner'], reservation['resource_id']
        route = '/v1/orders/' + identifier
        before = self.call('orders', 'GET', route + '/checkout', actor)
        body = self.walk.state.get('e06_bindings', {}).get('attempt:' + identifier)
        if body is None or len(before['attempts']) != 1:
            raise MissingCapability('payment.original_attempt_binding')
        # Deliver the retained command, deliberately discard its response, then
        # reconcile through a new current read before exact replay.
        self.call('orders', 'POST', route + '/payment-attempts', actor, body,
                  key=self.stable_key('attempt:' + identifier))
        observed = self.call('orders', 'GET', route + '/checkout', actor)
        replay = self.call('orders', 'POST', route + '/payment-attempts', actor, body,
                           key=self.stable_key('attempt:' + identifier))
        after = self.call('orders', 'GET', route + '/checkout', actor)
        if (self.payment_facts(before) != self.payment_facts(observed)
                or self.payment_facts(before) != self.payment_facts(after)
                or replay.get('status') != 'succeeded'
                or replay['attempt']['id'] != before['attempts'][0]['id']):
            raise MissingCapability('payment.lost_response_single_retained_attempt')

    def bound_request(self, name, body):
        bindings = self.walk.state.setdefault('e06_bindings', {})
        if name not in bindings:
            bindings[name] = body
            self.walk.save()
        return bindings[name]

    def stable_key(self, name):
        keys = self.walk.state.setdefault('e06_keys', {})
        if name not in keys:
            keys[name] = str(uuid4())
            self.walk.save()
        return keys[name]

    def auction(self):
        walk = self.walk
        listing = next(row for row in walk.state['listings']
                       if row['facts']['reference'] == 'DEMO-WATCH-01')
        walk.phase, walk.positions = 'e06-auction', {}
        saved = walk.state.setdefault('e06_auction', {})
        if 'created' not in saved:
            # Persist the exact clock binding before delivery, including on timeout.
            if 'request' not in saved:
                saved['request'] = auction_request(listing, datetime.now(timezone.utc))
                walk.save()
            created = self.call('auction', 'POST', '/v1/auctions', 'seller',
                                saved['request'], key=self.stable_key('auction-create'))
            if created['status'] != 'succeeded':
                raise MissingCapability('auction.listing_admission')
            saved['created'] = created
            walk.save()
        identifier = saved['created']['auction_id']
        route = '/v1/auctions/' + identifier
        if 'bid' not in saved:
            if 'bid_request' not in saved:
                self.wait('auction.live_clock', lambda: self.call('auction', 'GET', route),
                          lambda row: row['status'] == 'live', 15)
                lot = self.call('auction', 'GET', route)
                quote = walk.quote('buyer-a', identifier, lot['revision'], 400000)
                saved['bid_request'] = {'amount_minor': 400000,
                    'fee_quote_id': quote['id'], 'expected_revision': lot['revision']}
                walk.save()
            bid = self.call('auction', 'POST', route + '/bids', 'buyer-a',
                            saved['bid_request'], key=self.stable_key('auction-bid'))
            if bid['status'] != 'succeeded':
                raise MissingCapability('auction.bid_admission')
            saved['bid'] = bid
            walk.save()
        result = self.wait('auction.close_worker_winner_allocation',
            lambda: self.call('auction', 'GET', route + '/my-fixed-end-result', 'buyer-a'),
            lambda row: row.get('won') is True and bool(row.get('order_id')))
        checkout = self.call('orders', 'GET', '/v1/orders/' + result['order_id'] + '/checkout', 'buyer-a')
        if result['closing_minor'] != 400000 or checkout['quote']['price_minor'] != 400000:
            raise MissingCapability('auction.retained_winner_economics')
        saved['reservation'] = {'winner': 'buyer-a', 'resource_id': result['order_id'],
                                'quote': {'payable_minor': checkout['order']['total_minor']}}
        walk.save()
        self.payment(saved['reservation'])

    def private_order(self, journey):
        if journey == 'paid_auction':
            return self.walk.state['e06_auction']['reservation']
        if journey in ('customization', 'service'):
            return self.walk.state['e06_job_orders'][journey]
        return self.walk.state['reservation']

    def cross_account(self, journey):
        reservation = self.private_order(journey)
        actor = 'buyer-b' if reservation['winner'] == 'buyer-a' else 'buyer-a'
        route = '/v1/orders/' + reservation['resource_id'] + '/checkout'
        before = self.call('orders', 'GET', route, reservation['winner'])
        self.call('orders', 'GET', route, actor, expected=(403, 404))
        self.call('orders', 'POST', '/v1/orders/' + reservation['resource_id'] + '/payment-method',
                  actor, payment_request(before['order']), expected=(403, 404))
        after = self.call('orders', 'GET', route, reservation['winner'])
        if before != after:
            # Server time changes on reads; compare commercial facts only.
            if before['order'] != after['order'] or before['attempts'] != after['attempts']:
                raise MissingCapability('orders.cross_account_no_mutation')

    def downstream(self, journey):
        if journey in ('protected_purchase', 'paid_auction'):
            reservation = self.private_order(journey)
            identifier = reservation['resource_id']
            receipt = self.capability_call('custody.current_receipt_producer',
                'orders', 'GET', '/v1/custody/' + identifier, reservation['winner'])['result']
            if receipt is None:
                if not (self.run_dir / 'e06-inputs.json').is_file():
                    raise MissingCapability('custody.authorized_physical_handoff_producer')
                self.connected.handoffs(journey)
                return self.receipt_and_release(journey)
            if not receipt.get('buyer_received_at') or receipt.get('held'):
                raise MissingCapability('custody.actual_unheld_buyer_receipt')
            return self.release(journey)
        if journey == 'customization':
            return self.customization()
        self.service_request()
        return self.connected.journey('service')

    def receipt_and_release(self, journey):
        reservation = self.private_order(journey)
        receipt = self.capability_call('custody.current_receipt_producer',
            'orders', 'GET', '/v1/custody/' + reservation['resource_id'],
            reservation['winner'])['result']
        if not receipt or not receipt.get('buyer_received_at') or receipt.get('held'):
            raise MissingCapability('custody.actual_unheld_buyer_receipt')
        return self.release(journey)

    def customization(self):
        draft_id = self.walk.state['request_draft']['resource_id']
        draft = self.call('catalog', 'GET', '/v1/request-drafts/' + draft_id, 'buyer-a')
        saved = self.walk.state.setdefault('e06_customization', {})
        if not draft.get('submitted_request_id'):
            configuration, movement = self.customization_configuration()
            if 'draft_binding' not in saved:
                fields = ('brand_id', 'kind', 'watch_context', 'watch_reference',
                          'scope_intent', 'notes', 'options')
                saved['draft_binding'] = {**{name: draft[name] for name in fields},
                    'expected_revision': draft['revision'],
                    'configuration_id': configuration['id'],
                    'configuration_revision': configuration['revision']}
                self.walk.save()
            self.call('catalog', 'PATCH', '/v1/request-drafts/' + draft_id, 'buyer-a',
                saved['draft_binding'], key=self.stable_key('customization-draft-binding'))
            draft = self.call('catalog', 'GET', '/v1/request-drafts/' + draft_id, 'buyer-a')
            saved['current_draft'] = draft
            self.walk.save()
            if (self.run_dir / 'e06-inputs.json').is_file():
                self.connected.execute('customization', 'consent')
            validation = self.call('catalog', 'POST', '/v1/configurations/' +
                configuration['id'] + '/validate', 'buyer-a', {
                    'configuration_revision': configuration['revision'],
                    'movement_selection_id': movement['id'],
                    'movement_revision': movement['revision']})
            body = self.bound_request('customization-submit', submission_request(
                draft, movement, validation))
            result = self.call('catalog', 'POST', '/v1/request-drafts/' + draft_id +
                '/submit', 'buyer-a', body, key=self.stable_key('customization-submit'))
            if (result['status'] != 'succeeded'
                    or result['resource_id'] != result['request']['id']
                    or result['request']['draft_id'] != draft_id):
                raise MissingCapability('customization.exact_submission_binding')
            saved['submission'] = result
            self.walk.save()
            receipt = self.call('catalog', 'GET', '/v1/customization-operations/' +
                                result['id'], 'buyer-a')
            if receipt != result:
                raise MissingCapability('customization.durable_submission_receipt')
            request_id = result['resource_id']
        else:
            request_id = draft['submitted_request_id']
            body = self.walk.state.get('e06_bindings', {}).get('customization-submit')
            operation = self.walk.state.get('e06_keys', {}).get('customization-submit')
            if body is None or operation is None:
                raise MissingCapability('customization.original_submission_binding')
            result = self.call('catalog', 'POST', '/v1/request-drafts/' + draft_id +
                '/submit', 'buyer-a', body, key=operation)
            if (result.get('status') != 'succeeded'
                    or result.get('resource_id') != request_id
                    or result.get('request', {}).get('id') != request_id
                    or result['request'].get('draft_id') != draft_id):
                raise MissingCapability('customization.exact_submission_binding')
            receipt = self.call('catalog', 'GET', '/v1/customization-operations/' +
                                result['id'], 'buyer-a')
            if receipt != result:
                raise MissingCapability('customization.durable_submission_receipt')
            saved['submission'] = receipt
            self.walk.save()
        current = self.call('catalog', 'GET', '/v1/customization-requests/' +
                            request_id, 'buyer-a')
        if current['draft_id'] != draft_id:
            raise MissingCapability('customization.retained_request_binding')
        organization = self.walk.state['businesses']['brand']['id']
        context = self.capability_call('customization.current_business_assessment_context',
            'service-operations', 'GET', '/v1/brand-assessments/' + request_id +
            '?organization_id=' + organization, 'brand')
        self.assessment_claim(request_id, organization, context)
        return self.connected.journey('customization')

    def customization_case(self, case):
        return self.connected.fault_case('customization', case)

    def assessment_claim(self, request_id, organization, context):
        name = 'assessment-claim:' + request_id
        body = self.bound_request(name, {
            'schema_version': 'brand-assessment.v1',
            'operation_id': self.stable_key(name), 'subject_id': request_id,
            'watch_id': context['current_watch_id'], 'actor_id': context['actor_id'],
            'organization_id': organization, 'expected_revision': context['revision'],
            'request_revision': context['current_request_revision'],
            'assignment_revision': context['assignment_revision'],
            'capability_revision': context['current_capability_revision'], 'kind': 'claim'})
        route = '/v1/brand-assessments/' + request_id
        result = self.capability_call('customization.current_assessor_claim',
            'service-operations', 'POST', route + '/commands?organization_id=' + organization,
            'brand', body, key=body['operation_id'])
        if (result.get('state') != 'claimed' or result.get('claimant') != body['actor_id']
                or any(result.get(field) != body[field] for field in (
                    'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id',
                    'request_revision', 'capability_revision'))
                or result.get('revision') != body['expected_revision'] + 1
                or result.get('assignment_revision') != body['assignment_revision'] + 1):
            raise MissingCapability('customization.exact_assessor_claim')
        receipt = self.call('service-operations', 'GET', route + '/operations/' +
            body['operation_id'] + '?organization_id=' + organization, 'brand')
        if receipt != result:
            raise MissingCapability('customization.durable_assessor_claim')
        self.walk.state.setdefault('e06_customization', {})['claim'] = result
        self.walk.save()

    def customization_configuration(self):
        organization = self.walk.state['businesses']['brand']['id']
        configuration_id = self.stable_key('customization-configuration')
        configuration = None
        for index, (kind, component, details) in enumerate(sample_options()):
            option_id = self.stable_key('customization-option:' + kind)
            body = {'expected_revision': 0, 'component': component,
                'label': {'en': 'Sample ' + kind, 'ar': 'خيار تجريبي'},
                'base_models': ['SampleBase'], 'calibers': ['SampleCaliber'],
                'available': True, 'details': details}
            self.call('catalog', 'PUT', '/v1/brand-options/brands/' + organization +
                '/' + kind + '/' + option_id + '?organization_id=' + organization,
                'brand', body, key=self.stable_key('customization-publish:' + kind))
            selection = {'brand_id': organization, 'base_model': 'SampleBase',
                'caliber': 'SampleCaliber', 'option_id': option_id,
                'option_revision': 1, 'expected_revision': index,
                'component': component, 'reference_ids': []}
            configuration = self.call('catalog', 'PUT',
                '/v1/brand-options/configurations/' + configuration_id + '/' + kind,
                'buyer-a', selection, key=self.stable_key('customization-select:' + kind))
        option_id = self.stable_key('customization-movement-option')
        self.call('catalog', 'PUT', '/v1/options/movement/' + option_id +
            '?organization_id=' + organization, 'brand', {
                'brand_id': organization, 'expected_revision': 0,
                'label_en': 'Sample movement', 'label_ar': 'حركة تجريبية',
                'caliber': 'SampleCaliber', 'cases': ['SampleBase'],
                'dials': ['SampleDial'], 'hands': ['SampleHands'], 'functions': [],
                'quote_minor': 10000, 'currency': 'USD', 'active': True,
                'compatibility_rules': []}, key=self.stable_key('customization-movement-publish'))
        previous = self.call('catalog', 'GET', '/v1/options/movement/selections/current?brand_id=' +
                             organization, 'buyer-a')
        selection = self.bound_request('customization-movement-selection', {
            'brand_id': organization, 'option_id': option_id, 'option_revision': 1,
            'expected_revision': previous['selection_revision'],
            'configuration': {'case': 'SampleBase', 'dial': 'SampleDial',
                              'hands': 'SampleHands', 'functions': []}})
        movement = self.call('catalog', 'POST', '/v1/options/movement/selections',
            'buyer-a', selection, key=self.stable_key('customization-movement-selection'))
        current = self.call('catalog', 'GET', '/v1/brand-options/configurations/' +
                            configuration_id, 'buyer-a')
        if current['revision'] != configuration['revision'] or len(current['selections']) != 4:
            raise MissingCapability('customization.current_four_dimension_configuration')
        return current, movement

    def service_case(self, case):
        return self.connected.fault_case('service', case)

    def run(self, ready=True):
        for phase in ('accounts', 'bootstrap', 'onboard', 'contacts', 'publication', 'purchases', 'directory', 'request'):
            if ready:
                ready = self.record('setup.' + phase, lambda phase=phase: self.walk.run_phase(phase))
        if ready and (self.run_dir / 'e06-inputs.json').is_file():
            ready = self.record('setup.business_actors', self.connected.actors)
        stages = {}
        if ready:
            stages['protected_purchase'] = self.record('protected_purchase.payment_held', self.payment)
            stages['paid_auction'] = self.record('paid_auction.winner_payment_held', self.auction)
            self.record('service.request_submitted', self.service_request)
        for journey in JOURNEYS:
            for case in CASES:
                def execute(journey=journey, case=case):
                    if not ready:
                        raise MissingCapability('setup.current_signed_in_actors')
                    if journey in ('protected_purchase', 'paid_auction') and not stages.get(journey):
                        raise MissingCapability(journey + '.confirmed_held_payment')
                    if case == 'positive':
                        return self.downstream(journey)
                    return self.connected.fault_case(journey, case)
                self.record(journey + '.' + case, execute)
        self.save()
        return 0 if all(row['state'] == 'passed' for row in self.results) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if run_dir == ROOT or ROOT in run_dir.parents:
        parser.error('run directory must be outside the repository')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    walk = load_walkthrough()('http://127.0.0.1:3000', backend='native', run_dir=run_dir)
    # Resolve owning runtime configuration before issuing any gateway request.
    runner = Runner(run_dir, walk, revision)
    try:
        ready = runner.record('native_configuration', lambda: walk.native_plan('identity', ['service_app.bootstrap_operator']))
        return runner.run(ready)
    finally:
        walk.client.close()


if __name__ == '__main__':
    raise SystemExit(main())

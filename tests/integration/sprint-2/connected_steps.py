"""Ordered connected producer execution; inputs contain commands, never outcomes."""
import json
import re
import httpx
import socket
import time
from urllib.parse import quote

PRODUCERS = {
    'allocation': ('orders', None, None, 'succeeded'),
    'service_assessment': ('service-operations', None, None, 'assessed'),
    'inspection': ('trust', '/v1/private-inspections/results', '/v1/private-inspections/operations/{operation}?subject_id={subject}', 'passed'),
    'assessment': ('service-operations', '/v1/brand-assessments/{subject}/commands', '/v1/brand-assessments/{subject}/operations/{operation}', 'assessed'),
    'scope': ('service-operations', '/v1/case-lines/{subject}/acceptance', '/v1/case-lines/operations/{operation}', 'accepted'),
    'consent': ('eligibility', '/v1/consents', '/v1/consents/operations/{operation}', 'active'),
    'eligibility_review': ('eligibility', '/v1/eligibility-decisions', '/v1/eligibility-decisions/operations/{operation}', 'eligible'),
    'eligibility': ('eligibility', '/v1/eligibility-decisions', '/v1/eligibility-decisions/operations/{operation}', 'prepared'),
    'approval': ('catalog', '/v2/customization-requests/{subject}/decisions', '/v2/brand-decision-operations/{operation}', 'approved'),
    'authorization': ('orders', '/internal/v1/brand-jobs', '/internal/v1/brand-jobs/operations/{operation}', 'authorized'),
    'repair_authorization': ('orders', '/internal/v1/service-jobs/paid-scope', '/internal/v1/brand-jobs/operations/{operation}', 'authorized'),
    'work': ('service-operations', '/internal/v1/authorized-work/commands', '/internal/v1/authorized-work/operations/{operation}', 'recorded'),
    'quality': ('service-operations', '/internal/v1/quality/records', '/internal/v1/quality/operations/{operation}', 'satisfactory'),
    'custody': ('orders', '/internal/v1/custody/commands', '/internal/v1/custody/{subject}/operations/{operation}', 'received'),
}


def absence_status(kind):
    # Work conceals unknown operations with the same status as denied reads.
    return (403,) if kind == 'work' else (404,)


def resolve(value, facts):
    if isinstance(value, dict):
        if set(value) == {'reference'}:
            current = facts
            for part in value['reference'].split('.'):
                current = current[int(part)] if isinstance(current, list) else current[part]
            return current
        return {key: resolve(item, facts) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, facts) for item in value]
    return value


class ConnectedSteps:
    def __init__(self, runner, missing_type):
        self.runner = runner
        self.missing_type = missing_type

    def missing(self, name):
        raise self.missing_type(name)

    def inputs(self, journey):
        path = self.runner.run_dir / 'e06-inputs.json'
        if not path.is_file():
            self.missing(journey + '.current_producer_inputs')
        if path.stat().st_mode & 0o077:
            self.missing('native.private_producer_inputs')
        if path.stat().st_size > 1048576:
            self.missing('native.bounded_producer_inputs')
        value = json.loads(path.read_text())
        if value.get('schema_version') != 1 or journey not in value:
            self.missing(journey + '.producer_input_contract')
        return value[journey]

    def actors(self):
        runner, walk = self.runner, self.runner.walk
        # The same registration and membership commands as the walkthrough;
        # authority is granted by the current signed-in operator, never seeded.
        self.inputs('customization')
        data = json.loads((runner.run_dir / 'e06-inputs.json').read_text())
        for alias, assignment in data.get('actors', {}).items():
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', alias):
                self.missing('native.sample_actor_alias')
            if alias not in walk.state.get('accounts', {}):
                registered = runner.call('identity', 'POST', '/v1/accounts/register', body={
                    'email': alias + '.s1@example.test', 'password': walk.sample_password,
                    'display_name': 'Sample ' + alias.title()},
                    key=runner.stable_key('actor:' + alias), expected=(201, 409))
                if 'account' in registered:
                    walk.state.setdefault('accounts', {})[alias] = registered
                    walk.save()
            walk.login(alias)
            organization = walk.state['businesses'][assignment['business']]['id']
            body = runner.bound_request('membership:' + alias, {
                'business_id': organization, 'subject_id': walk.state['accounts'][alias]['account']['id'],
                'capabilities': ['business.jobs.write', 'business.records.read'],
                'qualifications': assignment['qualifications'],
                'intervention_scope': 'Sample authorized journey observations',
                'reason': 'Authorize independent sample business reviewer'})
            runner.call('identity', 'POST', '/v1/memberships', 'operator', body,
                        key=runner.stable_key('membership:' + alias))

    def control(self, journey, case, phase, operation):
        request = {'schema_version': 1, 'journey': journey, 'case': case,
                   'phase': phase, 'operation_id': operation}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(5)
                channel.connect(str(self.runner.run_dir / 'e06-control.sock'))
                channel.sendall(json.dumps(request).encode() + b'\n')
                raw = bytearray()
                while b'\n' not in raw:
                    chunk = channel.recv(4096)
                    if not chunk or len(raw) + len(chunk) > 16384:
                        self.missing('native.bounded_control_response')
                    raw.extend(chunk)
                answer = json.loads(raw.split(b'\n', 1)[0])
        except (OSError, ValueError):
            self.missing('native.' + case + '.' + phase + '_control')
        expected = {**request, 'acknowledged': True}
        if phase == 'signed_callback' and set(answer) == set(expected) | {'callback'}:
            payload = answer.pop('callback')
            if answer == expected:
                return payload
        if case == 'restart' and phase == 'restart':
            interruption = answer.pop('interruption', None)
            if interruption != {'operation_id': operation, 'acknowledged': True,
                                'response_delivered': False}:
                self.missing(journey + '.restart.acknowledged_interruption')
        if answer != expected:
            self.missing('native.' + case + '.control_acknowledgement')

    def duplicate_callback(self, journey, operation):
        runner = self.runner
        reservation = runner.private_order(journey)
        actor, order_id = reservation['winner'], reservation['resource_id']
        route = '/v1/orders/' + order_id + '/checkout'
        before = runner.call('orders', 'GET', route, actor)
        if len(before['attempts']) != 1 or before['order']['state'] not in ('paid_held', 'paid_out'):
            self.missing(journey + '.duplicate.single_held_attempt')
        payload = self.control(journey, 'duplicate', 'signed_callback', operation)
        if not isinstance(payload, dict) or set(payload) != {'raw', 'signature'}:
            self.missing(journey + '.duplicate.signed_callback_capture')
        raw = payload['raw'].encode()
        callback = json.loads(raw)
        attempt = before['attempts'][0]
        binding = {'order_id': order_id, 'attempt_id': attempt['id'],
                   'buyer_id': runner.walk.state['accounts'][actor]['account']['id'],
                   'quote_id': before['order']['quote_id'],
                   'quote_revision': before['quote']['revision'],
                   'currency': 'USD', 'total_minor': before['order']['total_minor'],
                   'outcome': 'confirmed'}
        if any(callback.get(key) != value for key, value in binding.items()):
            self.missing(journey + '.duplicate.callback_binding')
        # The same bytes and signature reach the actual signed receiver twice.
        for index in range(2):
            runner.call('orders', 'POST', '/callbacks/v1/simulated', content=raw,
                headers={'Content-Type': 'application/json', 'X-BT-Signature': payload['signature']},
                key=runner.stable_key(journey + ':callback:' + str(index)))
        after = runner.call('orders', 'GET', route, actor)
        if runner.payment_facts(before) != runner.payment_facts(after):
            self.missing(journey + '.duplicate.single_charge_and_attempt')

    def facts(self, journey):
        state = self.runner.walk.state
        return {'state': state, 'steps': state.setdefault('e06_jobs', {}).setdefault(journey, {})}

    def prepare(self, journey, name, supplied=None):
        runner = self.runner
        entry = supplied or self.inputs(journey).get(name)
        if not isinstance(entry, dict):
            self.missing(journey + '.' + name + '.current_producer_input')
        kind = entry.get('producer', name)
        if kind not in PRODUCERS:
            self.missing(journey + '.' + name + '.published_producer')
        actor = entry['actor']
        if actor not in runner.walk.state['accounts']:
            self.missing(journey + '.' + name + '.signed_in_actor')
        body = resolve(entry['body'], self.facts(journey))
        if any(field in body for field in ('state', 'paid', 'winner', 'release_eligible')):
            self.missing(journey + '.' + name + '.command_only_input')
        operation = runner.stable_key(journey + ':' + name)
        for key in ('operation_id', 'operation_key'):
            if key in body:
                body[key] = operation
        if 'actor_id' in body and body['actor_id'] != runner.walk.state['accounts'][actor]['account']['id']:
            self.missing(journey + '.' + name + '.actor_binding')
        body = runner.bound_request(journey + ':' + name, body)
        subject = quote(str(resolve(entry['subject'], self.facts(journey))), safe='')
        service, command, lookup, state = PRODUCERS[kind]
        if command is None:
            transport = self.inputs(journey).get('composition', {}).get(kind, {})
            command, lookup = transport.get('command'), transport.get('lookup')
            if not all(isinstance(path, str) and path.startswith('/internal/')
                       and '..' not in path and '?' not in path and '#' not in path
                       for path in (command, lookup)):
                self.missing(journey + '.' + kind + '.current_transport')
        if kind == 'eligibility_review':
            if body.get('kind') != 'review' or body.get('verdict') != 'eligible':
                self.missing(journey + '.eligibility_review.independent_review_command')
        if kind == 'eligibility':
            review = self.facts(journey)['steps'].get('eligibility_review', {})
            review_body = runner.walk.state.get('e06_bindings', {}).get(
                journey + ':eligibility_review', {})
            if (body.get('kind') != 'prepare' or review.get('state') != 'eligible'
                    or body.get('expected_revision') != review.get('revision')
                    or not review_body.get('consent_id')
                    or body.get('consent_id') != review_body['consent_id']):
                self.missing(journey + '.eligibility.current_review_binding')
        if kind == 'custody':
            states = {'prepare': 'prepared', 'dispatch': 'in_transit', 'ready': 'ready_for_pickup',
                      'expert_receipt': 'expert_received', 'job_intake': 'job_received',
                      'buyer_receipt': 'received', 'return_receipt': 'returned'}
            state = states.get(body.get('action'))
            if state is None:
                self.missing(journey + '.' + name + '.actual_handoff_command')
        values = dict(subject=subject, operation=operation)
        suffix = '?organization_id=' + quote(body['organization_id'], safe='') if body.get('organization_id') else ''
        receipt_route = lookup.format(**values)
        receipt_route += suffix.replace('?', '&', 1) if '?' in receipt_route else suffix
        return service, command.format(**values) + suffix, receipt_route, actor, body, operation, state

    def execute(self, journey, name):
        runner = self.runner
        service, route, lookup, actor, body, operation, state = self.prepare(journey, name)
        saved = self.facts(journey)['steps']
        kind = self.inputs(journey)[name].get('producer', name)
        if name not in saved and kind != 'approval':
            runner.capability_call(journey + '.' + name + '.unrecorded_operation',
                service, 'GET', lookup, actor, expected=absence_status(kind))
            saved[name] = {'operation_id': operation, 'pending': True}
            runner.walk.save()
        result = runner.capability_call(journey + '.' + name + '.producer',
            service, 'POST', route, actor, body, key=operation, expected=(200, 201, 202))
        if kind == 'approval':
            lookup = lookup.replace(operation, result['operation_id'])
        receipt = runner.capability_call(journey + '.' + name + '.receipt', service, 'GET', lookup, actor)
        if kind == 'custody':
            result, receipt = result['result'], receipt['result']
        if receipt != result or (kind not in ('approval', 'consent', 'allocation') and receipt.get('operation_id', receipt.get('operation_key', receipt.get('id'))) != operation):
            self.missing(journey + '.' + name + '.durable_receipt_binding')
        if kind == 'consent':
            result, receipt = result['consent'], receipt['consent']
        if receipt.get('state', receipt.get('status')) != state:
            self.missing(journey + '.' + name + '.' + state)
        if kind == 'allocation':
            order = receipt.get('order', {})
            expected = {key: body[key] for key in ('watch_id', 'quote_id', 'buyer_id', 'currency', 'total_minor')}
            if order.get('id') != body['order_id'] or any(order.get(key) != value for key, value in expected.items()):
                self.missing(journey + '.allocation.exact_order_binding')
        for key in (() if kind == 'allocation' else ('actor_id', 'organization_id', 'subject_id', 'watch_id', 'quote_id', 'quote_revision')):
            if key in body and receipt.get(key) != body[key]:
                self.missing(journey + '.' + name + '.exact_binding')
        saved[name] = receipt
        runner.walk.save()
        return receipt

    def requester(self, journey):
        if journey == 'service':
            return self.runner.walk.state['e06_service']['actor']
        return 'buyer-a'

    def quote(self, journey):
        runner = self.runner
        data = self.inputs(journey)['quote']
        buyer = self.requester(journey)
        kind = 'brand' if journey == 'customization' else 'repair'
        body = runner.bound_request(journey + ':quote', resolve(data['body'], self.facts(journey)))
        source = (runner.walk.state['e06_customization']['submission']['resource_id']
                  if journey == 'customization' else runner.walk.state['e06_service']['result']['request_id'])
        if body.get('source_id') != source:
            self.missing(journey + '.quote.submitted_source_binding')
        if body.get('currency') != 'USD':
            self.missing(journey + '.quote.usd_economics')
        route = '/v1/' + kind + '-quotes'
        query = '&'.join(key + '=' + quote(str(body[key]), safe='') for key in
                         ('source_id', 'source_revision', 'assessment_id', 'assessment_revision'))
        runner.capability_call(journey + '.quote.current_assessment', 'pricing', 'GET',
                              route + '/context?' + query, data['actor'])
        issued = runner.capability_call(journey + '.quote.issue', 'pricing', 'POST', route,
            data['actor'], body, key=runner.stable_key(journey + ':quote'))
        issued = issued['quote']
        current = runner.call('pricing', 'GET', route + '/' + issued['id'], buyer)
        if current['id'] != issued['id'] or current['currency'] != 'USD':
            self.missing(journey + '.quote.retained_economics')
        acceptance = runner.bound_request(journey + ':accept', {
            'quote_revision': current['revision'], 'selected_line_ids': [line['id'] for line in current['lines']],
            'payable_minor': current['full_total']['payable_minor'], 'terms_digest': current['terms_digest'],
            'accept_assessment_fee': True, 'accept_return_fee': True})
        accepted = runner.capability_call(journey + '.quote.accept', 'pricing', 'POST',
            route + '/' + issued['id'] + '/accept', buyer, acceptance,
            key=runner.stable_key(journey + ':accept'))
        readback = runner.call('pricing', 'GET', route + '/' + issued['id'], buyer)
        if accepted.get('status') != 'succeeded' or readback.get('state') != 'accepted':
            self.missing(journey + '.quote.durable_acceptance')
        self.facts(journey)['steps'].update(quote=readback, acceptance=accepted)
        runner.walk.save()

    def handoffs(self, journey):
        data = self.inputs(journey)
        names = data.get('handoffs')
        if not isinstance(names, list) or not names or len(names) > 20:
            self.missing(journey + '.ordered_actual_handoffs')
        for name in names:
            if data.get(name, {}).get('producer') not in ('custody', 'inspection', 'quality'):
                self.missing(journey + '.handoff_producer')
            self.execute(journey, name)

    def journey(self, journey):
        runner = self.runner
        self.execute(journey, 'assessment' if journey == 'customization' else 'service_assessment')
        self.quote(journey)
        for stage in (('consent', 'eligibility_review', 'eligibility', 'approval') if journey == 'customization' else ('scope',)):
            self.execute(journey, stage)
        allocated = self.execute(journey, 'allocation')
        order_id = allocated.get('order_id', allocated.get('resource_id', allocated.get('order', {}).get('id')))
        if not order_id:
            self.missing(journey + '.accepted_order_allocation')
        buyer = self.requester(journey)
        current = runner.call('orders', 'GET', '/v1/orders/' + order_id + '/checkout', buyer)
        retained = self.facts(journey)['steps']['quote']
        if current['order']['quote_id'] != retained['id'] or current['order']['total_minor'] != retained['decision']['amounts']['payable_minor']:
            self.missing(journey + '.allocated_order_binding')
        reservation = {'winner': buyer, 'resource_id': order_id,
                       'quote': {'payable_minor': retained['decision']['amounts']['payable_minor']}}
        runner.walk.state.setdefault('e06_job_orders', {})[journey] = reservation
        runner.walk.save()
        runner.payment(reservation)
        for stage in (('authorization' if journey == 'customization' else 'repair_authorization'), 'work', 'quality', 'custody'):
            self.execute(journey, stage)
        runner.receipt_and_release(journey)

    def verify_fault_receipt(self, journey, case, body, operation, receipt, producer=None):
        # Equality between two reads cannot establish the retained command binding.
        value = receipt.get('result', receipt.get('consent', receipt))
        if producer == 'work':
            # Operation retains authority and scheduling bindings, not observations.
            # The original complete command is retained privately for exact replay.
            fields = ('schema_version', 'subject_id', 'watch_id', 'actor_id',
                      'organization_id', 'expected_revision', 'source_revision',
                      'quote_id', 'quote_revision', 'policy_revision',
                      'next_actor', 'next_review_at')
        else:
            fields = tuple(key for key in body
                           if key not in ('expected_revision', 'operation_id', 'operation_key'))
        if (value.get('operation_id', value.get('operation_key', value.get('id'))) != operation
                or any(key not in body or key not in value or value[key] != body[key]
                       for key in fields)):
            self.missing(journey + '.' + case + '.exact_receipt_binding')

    def fault_case(self, journey, case):
        runner = self.runner
        supplied = self.inputs(journey)['cases'][case]
        service, route, lookup, actor, body, operation, state = self.prepare(journey, 'case_' + case, supplied)
        kind = supplied.get('producer', 'case_' + case)
        # Dedicated commands make first-delivery loss distinguishable from replay.
        intents = runner.walk.state.setdefault('e06_case_intents', {})
        if operation not in intents:
            runner.call(service, 'GET', lookup, actor, expected=absence_status(kind))
            intents[operation] = {'journey': journey, 'case': case}
            runner.walk.save()
        guard_name = supplied.get('guard')
        if not guard_name:
            self.missing(journey + '.' + case + '.acknowledged_guard')
        gs, guard_route, guard_lookup, ga, guard_body, guard_operation, _ = self.prepare(journey, guard_name)
        original = runner.call(gs, 'GET', guard_lookup, ga)
        armed = case in ('denied', 'stale', 'cross_business', 'timeout', 'restart', 'recovery')
        try:
            if armed:
                self.control(journey, case, 'arm', operation)
            if case in ('denied', 'cross_business', 'cross_account'):
                other = supplied['other_actor'] if case == 'cross_account' else actor
                if case == 'cross_account' and (other == ga or
                        runner.walk.state['accounts'][other]['account']['id'] ==
                        runner.walk.state['accounts'][ga]['account']['id']):
                    self.missing(journey + '.cross_account.distinct_actor')
                runner.call(gs, 'GET', guard_lookup, other, expected=(403, 404))
                if case == 'cross_account':
                    runner.call(gs, 'POST', guard_route, other, guard_body,
                                key=guard_operation, expected=(403, 404))
                else:
                    runner.call(service, 'GET', lookup, other, expected=(403, 404))
                    runner.call(service, 'POST', route, other, body, key=operation, expected=(403, 404))
            elif case == 'stale':
                result = runner.call(service, 'POST', route, actor, body, key=operation, expected=(409,))
                code = result.get('error', result.get('code', result.get('detail')))
                if isinstance(code, dict):
                    code = code.get('code')
                if code not in ('stale', 'stale_revision', 'source_changed', 'stale_scope'):
                    self.missing(journey + '.stale.authoritative_source_rejection')
            elif case == 'timeout':
                started = time.monotonic()
                result = runner.call(service, 'POST', route, actor, body, key=operation, expected=(200, 202, 503))
                if time.monotonic() - started > 5:
                    self.missing(journey + '.timeout.bounded_dependency')
                if result.get('state') not in ('pending', 'unavailable') or not all(result.get(key) for key in ('pending_reason', 'next_actor', 'next_action', 'next_review_at')):
                    self.missing(journey + '.timeout.responsible_pending_receipt')
            elif case == 'recovery':
                pending = runner.call(service, 'POST', route, actor, body, key=operation, expected=(200, 202, 503))
                if pending.get('state') not in ('pending', 'unavailable') or pending.get('operation_id') != operation:
                    self.missing(journey + '.recovery.original_pending_reference')
                if not all(pending.get(key) for key in ('pending_reason', 'next_actor', 'next_action', 'next_review_at')):
                    self.missing(journey + '.recovery.responsible_pending_receipt')
                self.control(journey, case, 'resolve', operation)
                runner.call(service, 'GET', lookup, actor)
                recovered = runner.call(service, 'POST', route, actor, body, key=operation, expected=(200, 201, 202))
                self.verify_fault_receipt(journey, case, body, operation, recovered, kind)
                if recovered.get('state', recovered.get('status')) != state or runner.call(service, 'GET', lookup, actor) != recovered:
                    self.missing(journey + '.recovery.authoritative_resolution')
            else:
                interrupted = False
                try:
                    runner.call(service, 'POST', route, actor, body, key=operation, expected=(200, 201, 202))
                except (httpx.TimeoutException, httpx.NetworkError):
                    if case not in ('restart', 'lost_response'):
                        raise
                    interrupted = True
                if case == 'restart':
                    if not interrupted:
                        self.missing(journey + '.restart.response_was_delivered')
                    self.control(journey, case, 'restart', operation)
                receipt = runner.call(service, 'GET', lookup, actor)
                replay = runner.call(service, 'POST', route, actor, body, key=operation, expected=(200, 201, 202))
                self.verify_fault_receipt(journey, case, body, operation, receipt, kind)
                self.verify_fault_receipt(journey, case, body, operation, replay, kind)
                if receipt != replay or receipt.get('state', receipt.get('status')) != state:
                    self.missing(journey + '.' + case + '.single_durable_effect')
                if case == 'duplicate':
                    runner.call(service, 'POST', route, actor, {**body, 'expected_revision': body['expected_revision'] + 1}, key=operation, expected=(403, 409))
                    self.duplicate_callback(journey, operation)
                if runner.call(service, 'GET', lookup, actor) != receipt:
                    self.missing(journey + '.' + case + '.unchanged_receipt')
        finally:
            if armed:
                self.control(journey, case, 'restore', operation)
        if runner.call(gs, 'GET', guard_lookup, ga) != original:
            self.missing(journey + '.' + case + '.unchanged_retained_history')
        if case in ('denied', 'cross_business', 'cross_account'):
            runner.call(service, 'GET', lookup, actor, expected=absence_status(kind))
        if case == 'timeout':
            pending = runner.call(service, 'GET', lookup, actor)
            if pending.get('operation_id') != operation:
                self.missing(journey + '.timeout.retained_pending_operation')
            recovered = runner.call(service, 'POST', route, actor, body, key=operation, expected=(200, 201, 202))
            self.verify_fault_receipt(journey, case, body, operation, recovered, kind)
            if (recovered.get('state', recovered.get('status')) != state or
                    runner.call(service, 'GET', lookup, actor) != recovered):
                self.missing(journey + '.timeout.exact_recovery')
        if journey in ('customization', 'service') and journey not in runner.walk.state.get('e06_releases', {}):
            self.journey(journey)
        else:
            runner.receipt_and_release(journey)

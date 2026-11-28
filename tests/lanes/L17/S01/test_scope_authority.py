"""New accepted scopes require current diagnosis authority."""
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from service_app.modules import discover
from bt_contracts.service.case_lines import v1 as scope_contract

MODULES = Path('/app/modules')
if not MODULES.is_dir():
    MODULES = Path(__file__).resolve().parents[4] / 'services/service-operations/modules'


@pytest.mark.asyncio
@pytest.mark.parametrize(('received_offset', 'incident_revision'), [(0, 0), (-1, 0), (0, 1)])
async def test_scope_requires_current_custody_and_incident(monkeypatch, received_offset, incident_revision):
    import sys
    from datetime import datetime, timedelta, timezone

    module = next(item for item in discover(MODULES) if item.id == 'L17.case-lines')
    check = module.load('routes.py:current_source')
    routes = sys.modules[check.__module__]
    keys = ('case_id', 'request_id', 'watch_id', 'buyer_id', 'order_id',
            'actor_id', 'organization_id', 'receipt_id')
    ids = {key: UUID(int=i) for i, key in enumerate(keys, 1)}
    received_at = datetime.now(timezone.utc) - timedelta(days=1)
    revisions = dict(receipt_revision=1, watch_revision=2, consent_revision=1,
                     accepted_terms_revision=1)
    quote = UUID(int=20)
    saved = {key: str(value) for key, value in ids.items()} | revisions | dict(
        intake_revision=1, assignment_revision=1, fee_quote_id=str(quote), fee_quote_revision=1,
        incident_revision=0)
    intake = dict(state='received', revision=1, order_id=ids['order_id'],
                  organization_id=ids['organization_id'], custody_receipt_id=ids['receipt_id'],
                  custody_revision=1, received_at=received_at,
                  private_record=dict(diagnostic_opening_permission=True, fee_acknowledged=True,
                                      no_polish_acknowledged=True, fee_minor=500, currency='USD'))
    opening = {key: ids[key] for key in ('actor_id', 'organization_id', 'order_id', 'receipt_id', 'watch_id')}
    opening.update(revisions, reservation_input_watch_revision=1, incident_revision=incident_revision, current=True, assigned=True, permission=True,
                   customer_opening_permission=True, accepted_assessment_fee=True,
                   customer_no_polish_acknowledged=True, accepted_fee_minor=500, currency='USD',
                   quote_id=quote, quote_revision=1, maintenance_request_id=ids['request_id'],
                   received_at=received_at + timedelta(seconds=received_offset))
    sources = {
        'intake_opening_authority': opening,
        'intake_record_access': {key: ids[key] for key in ('actor_id', 'organization_id', 'order_id')}
        | dict(permission='write', allowed=True, assignment_revision=1),
    }

    async def prerequisite(request, name, *args):
        return sources[name]

    async def commitment(request, order_id):
        return SimpleNamespace(**opening, buyer_id=ids['buyer_id'])

    from service_app import received_case

    class Transaction:
        async def fetchrow(self, query, *args):
            if 'FROM maintenance_received_cases' in query:
                return dict(request_id=ids['request_id'], fee_quote_id=quote, fee_quote_revision=1)
            if 'FROM maintenance_requests' in query:
                return dict(id=ids['request_id'], actor_id=ids['buyer_id'], watch_revision=1)
            return intake

    monkeypatch.setattr(routes, 'prerequisite', prerequisite)
    monkeypatch.setattr(received_case, 'current_commitment', commitment)
    if received_offset or incident_revision:
        with pytest.raises(HTTPException) as error:
            await check(None, Transaction(), saved)
        assert error.value.status_code == 409
    else:
        assert await check(None, Transaction(), saved) == intake


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['outage', 'revoked', 'reassigned'])
async def test_scope_refuses_unavailable_or_revoked_authority(monkeypatch, failure):
    import sys
    module = next(item for item in discover(MODULES)
                  if item.id == 'L17.case-lines')
    check = module.load('routes.py:current_source')
    routes = sys.modules[check.__module__]
    saved = {key: str(UUID(int=index)) for index, key in enumerate(
        ('order_id', 'actor_id', 'organization_id', 'case_id', 'request_id', 'watch_id', 'buyer_id'), 1)}
    saved.update(intake_revision=1, assignment_revision=1)

    async def read(request, name, *args):
        if failure == 'outage':
            raise ConnectionError('test-outage')
        return {}

    monkeypatch.setattr(routes, 'prerequisite', read)
    monkeypatch.setattr(routes.OpeningAuthority, 'model_validate', lambda value: SimpleNamespace())
    monkeypatch.setattr(routes.RecordAccess, 'model_validate', lambda value: SimpleNamespace(
        actor_id=UUID(saved['actor_id']), organization_id=UUID(saved['organization_id']),
        order_id=UUID(saved['order_id']), permission='write',
        allowed=failure != 'revoked', assignment_revision=2 if failure == 'reassigned' else 1))

    class Transaction:
        async def fetchrow(self, *args):
            return dict(state='received', revision=1)

    with pytest.raises(HTTPException) as error:
        await check(SimpleNamespace(), Transaction(), saved)
    assert error.value.status_code == (503 if failure == 'outage' else 409)


@pytest.mark.asyncio
async def test_historical_receipt_uses_acknowledged_request_revision():
    import json
    from bt_contracts.service.case_lines.v1 import ScopeReceipt

    module = next(item for item in discover(MODULES)
                  if item.id == 'L17.case-lines')
    receipt = json.loads((Path(scope_contract.__file__).with_name('fixtures.json')).read_text())['success']
    legacy = {key: value for key, value in receipt.items()
              if key not in ('subject_id','request_revision','schema_version','next_actor')}
    bindings = dict(case_id=str(UUID(int=80)), assessment_id=str(UUID(int=81)), assessment_revision=2)
    legacy['accepted_line_ids'] = []

    class Transaction:
        async def fetchval(self, query, *bindings):
            assert bindings == tuple(UUID(receipt[key]) for key in
                                     ('request_id','actor_id','organization_id','watch_id'))
            return 7

    recover = module.load('routes.py:scope_receipt')
    result = await recover(Transaction(), legacy, bindings)
    assert ScopeReceipt.model_validate(result).request_revision == 7
    assert result == {**receipt, **bindings, 'request_revision': 7}
    assert await recover(None, {**receipt, 'request_revision': 7}, bindings) == result
    assert await recover(None, result) == result


@pytest.mark.asyncio
async def test_current_quote_rejects_superseded_acceptance(monkeypatch):
    import sys

    module = next(item for item in discover(MODULES)
                  if item.id == 'L17.case-lines')
    check = module.load('routes.py:current_quote')
    quote_id = UUID(int=1)
    buyer = str(UUID(int=2))
    quote = dict(id=str(quote_id), currency='USD', state='accepted', buyer_id=buyer,
                 decision={'state': 'accepted', 'actor_id': buyer})

    async def read(*args):
        return quote

    monkeypatch.setattr(sys.modules[check.__module__], 'read', read)
    assert (await check(None, quote_id, {'buyer_id': buyer}))[0] == quote
    quote['state'] = 'superseded'
    with pytest.raises(HTTPException) as error:
        await check(None, quote_id, {'buyer_id': buyer})
    assert error.value.status_code == 409


def test_published_scope_maps_pricing_lines_to_the_diagnosis():
    from bt_contracts.service.case_lines.v1 import Scope

    module = next(item for item in discover(MODULES)
                  if item.id == 'L17.case-lines')
    publish = module.load('routes.py:published_scope')
    request, assessment, line = (str(UUID(int=n)) for n in range(1, 4))
    saved = dict(request_id=request, request_revision=3, revision=4, assessment_id=assessment,
                 assessment_revision=2, accepted_line_ids=[line],
                 lines=[dict(id=line, label='Movement inspection', kind='labor',
                             mandatory=True, amount_minor=500)])
    scope = Scope.model_validate(publish(saved).model_dump(mode='json'))
    assert scope.accepted_total() == 500
    assert scope.lines[0].model_dump(mode='json') == dict(
        line_id=line, description='Movement inspection', kind='labor', required=True,
        amount_minor=500, currency='USD', assessment_id=assessment, assessment_revision=2)
    with pytest.raises(HTTPException):
        publish({**saved, 'accepted_line_ids': []})


def test_quote_scope_compares_exact_assessed_fields_by_line_id():
    module = next(item for item in discover(MODULES)
                  if item.id == 'L17.case-lines')
    matches = module.load('routes.py:matching_assessed_lines')
    assessed = [dict(id=str(UUID(int=index)), label=label, kind='labor', mandatory=True)
                for index, label in enumerate(('Inspection', 'Regulation'), 1)]
    quoted = [{**line, 'amount_minor': 500} for line in reversed(assessed)]
    assert matches(quoted, assessed)
    assert not matches([quoted[0], quoted[0], quoted[1]], assessed)
    assert not matches(quoted[:1], assessed)
    assert not matches([{**quoted[0], 'mandatory': 1}, quoted[1]], assessed)
    assert not matches([{**quoted[0], 'label': 'Different work'}, quoted[1]], assessed)


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [
    'quote_id', 'quote_revision', 'watch_revision', 'submission_watch_revision',
    'signed_request', 'missing_signed_request', 'missing_link', 'missing_reservation_input', None,
])
async def test_diagnosis_fee_quote_is_bound_to_current_commitment(monkeypatch, changed):
    import sys

    module = next(item for item in discover(MODULES) if item.id == 'L17.maintenance-requests')
    bind_case = module.load('diagnosis.py:case_binding')
    received_case = sys.modules[bind_case.__module__]
    case, request, order, watch, org, buyer, quote = (UUID(int=i) for i in range(1, 8))
    opening = SimpleNamespace(order_id=order, watch_id=watch, organization_id=org,
                              watch_revision=2, quote_id=quote, quote_revision=1,
                              maintenance_request_id=request, reservation_input_watch_revision=1)

    class Transaction:
        async def fetchrow(self, query, *args):
            if 'FROM maintenance_received_cases' in query:
                assert args == (case,)
                if changed != 'missing_link':
                    return dict(request_id=request, fee_quote_id=quote, fee_quote_revision=1)
                return None
            assert args == (request, org, watch)
            return dict(id=request, actor_id=buyer,
                        watch_revision=2 if changed == 'submission_watch_revision' else 1)

    async def read_commitment(_, order_id):
        assert order_id == order
        facts = {**vars(opening), 'current': True, 'buyer_id': buyer}
        if changed:
            facts[changed] = UUID(int=9) if changed == 'quote_id' else 3
        return SimpleNamespace(**facts)

    monkeypatch.setattr(received_case, 'current_commitment', read_commitment)
    if changed == 'missing_reservation_input':
        opening.reservation_input_watch_revision = None
    if changed == 'signed_request':
        opening.maintenance_request_id = UUID(int=9)
    if changed == 'missing_signed_request':
        opening.maintenance_request_id = None
    if changed:
        with pytest.raises(HTTPException) as error:
            await bind_case(None, Transaction(), case, opening)
        assert error.value.status_code == 409
    else:
        assert (await bind_case(None, Transaction(), case, opening)).request_id == request


@pytest.mark.asyncio
async def test_missing_maintenance_operation_is_scoped_and_requires_current_ownership(monkeypatch):
    import sys
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    module = next(item for item in discover(MODULES) if item.id == 'L17.maintenance-requests')
    routes = sys.modules[module.load('routes.py:operation').__module__]
    provider = sys.modules[routes.Provider.__module__]
    operation, buyer, organization, other, watch = (UUID(int=n) for n in range(1, 6))
    person = buyer
    watch_owned = True
    intervention = 'limited_maintenance'

    async def admission(request, name, *bindings):
        assert name == 'maintenance_admission'
        assert bindings == (buyer, watch, organization, operation, intervention)
        return dict(actor_id=buyer, subject_id=buyer, watch_id=watch,
                    organization_id=organization, operation_id=operation, brand_id=other,
                    intervention=intervention, watch_revision=1, capability_revision=1,
                    policy_revision=1, identity_current=True, watch_owned=watch_owned,
                    business_active=True, assessment_supported=True, commitment_available=False)

    async def identity(request):
        return person

    class Transaction:
        async def fetchrow(self, query, *bindings):
            if bindings == (operation, buyer, organization):
                return {'result': '{"state": "submitted"}', 'watch_id': watch,
                        'intervention': intervention}
            return None

    @asynccontextmanager
    async def acquire():
        yield Transaction()

    monkeypatch.setattr(provider, 'prerequisite', admission)
    app = FastAPI()
    app.include_router(routes.router)
    app.state.maintenance_identity = identity
    app.state.pool = SimpleNamespace(acquire=acquire)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        path = '/v1/maintenance/operations/'
        params = {'organization_id': str(organization)}
        assert (await client.get(path + str(other), params=params)).status_code == 404
        assert (await client.get(path + str(operation), params=params)).json() == {'state': 'submitted'}
        watch_owned = False
        assert (await client.get(path + str(operation), params=params)).status_code == 403
        person = other
        assert (await client.get(path + str(operation), params=params)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    None, 'replacement', 'intake_revision', 'consent', 'custody', 'incident',
    'opening_not_current', 'opening_not_assigned', 'linked_not_current', 'linked_not_assigned',
    'linked_watch_revision', 'missing_signed_request', 'different_signed_request',
    'missing_diagnosis_receipt', 'different_diagnosis_receipt',
    'missing_submission_receipt', 'different_submission_receipt', 'missing_case_link',
])
async def test_current_diagnosis_requires_matching_acknowledgements(monkeypatch, database_url, change):
    import hashlib
    import json
    import sys
    from datetime import datetime, timedelta, timezone

    from bt_contracts.orders.allocation.v3 import CurrentCommitment
    from bt_contracts.service.maintenance.diagnosis import Diagnose, DiagnosisRecoveryFence, DiagnosisWriteFence
    from bt_contracts.service.intake.intake_command import Intake
    from service_app import received_case
    from bt_runtime.app.db import create_pool, unit_of_work
    from test_maintenance import Provider, request as maintenance_request

    module = next(item for item in discover(MODULES) if item.id == 'L17.maintenance-requests')
    diagnose = module.load('diagnosis.py:diagnose')
    routes = sys.modules[diagnose.__module__]
    submission, watch, buyer, order, person, org, receipt, quote, operation, line = (
        UUID(int=i) for i in range(1, 11))
    received_at = datetime.now(timezone.utc)
    opening = dict(actor_id=person, order_id=order, watch_id=watch, organization_id=org,
                   watch_revision=2, reservation_input_watch_revision=1, receipt_id=receipt, receipt_revision=1,
                   quote_id=quote, quote_revision=1, consent_revision=1,
                   accepted_terms_revision=1, received_at=received_at,
                   incident_revision=0, current=True, assigned=True, permission=True,
                   customer_opening_permission=True, accepted_assessment_fee=True,
                   customer_no_polish_acknowledged=True, accepted_fee_minor=500, currency='USD')
    advance_incident_before_fence=False
    native_incident=0

    async def prerequisite(_, name, *scope):
        nonlocal native_incident
        if name=='diagnosis_write_fence':
            raw,=scope
            fence=DiagnosisWriteFence.model_validate_json(raw)
            assert fence.binding.assignment_revision==1 and fence.binding.session_id=='assessor-session'
            assert fence.binding.opening.order_id==order and fence.binding.commitment.order_revision==3
            assert fence.binding.reviewed_intake.receipt_id==receipt
            if advance_incident_before_fence:
                native_incident+=1
            if fence.binding.opening.incident_revision!=native_incident:
                return False
            return {'binding_hash':hashlib.sha256(raw).hexdigest(),'held_until':fence.hold_until}
        if name=='diagnosis_recovery_fence':
            raw,=scope
            fence=DiagnosisRecoveryFence.model_validate_json(raw)
            assert fence.binding.session_id=='assessor-session' and fence.binding.mode=='lookup'
            return {'binding_hash':hashlib.sha256(raw).hexdigest(),'held_until':fence.hold_until}
        if name == 'intake_opening_authority':
            assert scope == (person, org, order)
            return opening
        if name == 'intake_record_access':
            assert scope == (person, org, order, 'assess')
            return dict(actor_id=person, organization_id=org, order_id=order,
                        permission='assess', allowed=True, assignment_revision=1)
        if name == 'intake_current_custody':
            assert scope == (person,org,order,receipt)
            return dict(id=receipt, order_id=order, actor_id=person, organization_id=org, watch_id=watch,
                revision=1,valid=True,received_at=received_at,watch_revision=2,incident_revision=0,
                current_watch_id=watch,current_watch_revision=2,current_incident_revision=0)
        if name=='repair_custody_transition':
            assessor,organization,assessment_order,repair_order,subject,original_receipt=scope
            assert (assessor,organization,assessment_order,subject,original_receipt)==(person,org,order,watch,receipt)
            if not (opening['assigned'] and opening['permission'] and opening['receipt_id']==receipt
                    and opening['receipt_revision']==1):
                return False
            return dict(actor_id=person,organization_id=org,assessment_order_id=order,repair_order_id=repair_order,
                watch_id=watch,assessment_receipt_id=receipt,assessment_receipt_revision=1,assessment_watch_revision=2,
                assessment_incident_revision=0,repair_watch_revision=3,current_incident_revision=0,current=True,work_hold=False)
        pytest.fail(f'Unexpected dependency {name}')

    async def commitment(_, order_id):
        assert order_id==order
        return CurrentCommitment(order_id=order_id,watch_id=watch,organization_id=org,buyer_id=buyer,
            quote_id=quote,quote_revision=1,order_revision=3,watch_revision=opening['watch_revision'],
            current=opening['current'],state='paid_held',notified_at=None,deadline=None)

    servicing_enabled = True

    async def servicing(_, organization, capability):
        assert (organization, capability) == (org, 'servicing')
        if not servicing_enabled:
            raise ConnectionError('business_unavailable')

    monkeypatch.setattr(routes, 'official_business', servicing)
    monkeypatch.setattr(routes, 'prerequisite', prerequisite)
    monkeypatch.setattr(routes, 'current_commitment', commitment)
    monkeypatch.setattr(received_case, 'current_commitment', commitment)
    pool = await create_pool(database_url)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    actor = SimpleNamespace(actor=SimpleNamespace(subject_id=person,organization_id=org,session_id='assessor-session'))
    try:
        submit = module.load('commands.py:submit')
        admission = maintenance_request(operation_id=submission, actor_id=buyer, subject_id=buyer,
                                        watch_id=watch, organization_id=org, watch_revision=1)
        submitted_receipt = await submit(admission, actor_id=buyer, provider=Provider(watch_revision=1),
                                        transaction=lambda key: unit_of_work(pool, lock_key=str(key)))
        submitted = UUID(submitted_receipt['request_id'])
        from bt_contracts.service.maintenance.opening import OpeningAcknowledgement, PreferenceReceipt
        preference=PreferenceReceipt(operation_id=UUID(int=51),request_id=submitted,request_revision=1,
            buyer_id=buyer,organization_id=org,watch_id=watch,revision=1,expected_revision=0,
            opening_permitted=True,no_polish=True,recorded_at=received_at)
        acknowledged=OpeningAcknowledgement(operation_id=UUID(int=52),request_id=submitted,request_revision=1,
            consent_revision=1,assignment_revision=1,order_id=order,receipt_id=receipt,receipt_revision=1,
            fee_acceptance_operation_id=UUID(int=53),offer_id=quote,offer_revision=1,actor_id=person,buyer_id=buyer,
            organization_id=org,watch_id=watch,watch_revision=2,incident_revision=0,customer_opening_permission=True,
            customer_no_polish_acknowledged=True,no_polish=True,accepted_assessment_fee=True,
            accepted_fee_minor=500,policy_revision=1,received_at=received_at)
        async with pool.acquire() as tx:
            await tx.execute('''INSERT INTO maintenance_assessment_assignments
                (request_id,organization_id,assessor_id,revision,request_revision) VALUES($1,$2,$3,1,1)''',submitted,org,person)
            await tx.execute('''INSERT INTO maintenance_assessment_decisions
                (request_id,actor_id,organization_id,watch_id,assignment_revision,request_revision,custody_receipt_id,
                 custody_receipt_revision,order_id,watch_revision,incident_revision,state)
                VALUES($1,$2,$3,$4,1,1,$5,1,$6,2,0,'confirmed')''',submitted,person,org,watch,receipt,order)
            await tx.execute('INSERT INTO maintenance_opening_preferences VALUES($1,$2,1,$3::jsonb)',
                preference.operation_id,submitted,preference.model_dump_json())
            await tx.execute('INSERT INTO maintenance_opening_acknowledgements VALUES($1,$2,1,$3::jsonb)',
                acknowledged.operation_id,submitted,acknowledged.model_dump_json())
        save = next(item for item in discover(MODULES) if item.id == 'L09.intake').load('current_routes.py:save')
        intake_routes = sys.modules[save.__module__]

        async def organization(*args):
            return org

        write_allowed = True

        async def assigned(p, request, org, order, permission):
            if permission == 'write' and not write_allowed:
                raise HTTPException(403)

        async def current_opening(*args):
            return opening if write_allowed else opening|{'permission':False}

        audit_status = 409
        custody_reads = []

        async def current_custody(*args):
            assert args==(person,org,order,receipt)
            custody_reads.append(receipt)
            return False if audit_status==409 else await prerequisite(request,'intake_current_custody',*args)

        monkeypatch.setattr(intake_routes, 'organization', organization)
        monkeypatch.setattr(intake_routes, 'record_access', assigned)
        monkeypatch.setattr(intake_routes, 'require_private_assignment', assigned)
        request.app.state.intake_current_authority=SimpleNamespace(current=current_opening,current_custody=current_custody)
        request.headers = {'Idempotency-Key': 'test-intake', 'Authorization': 'Bearer test-intake'}
        request.url = SimpleNamespace(path='/v1/intake/records')
        request.state = SimpleNamespace(request_id='test-intake')
        intake = Intake(order_id=order, custody_receipt_id=receipt, serial='test-serial',
            reference='test-reference', movement='Automatic', received_condition='Received',
            accessories='', reported_issue='Winding issue', assessed_issue='',
            diagnostic_opening_permission=True, fee_acknowledged=True,
            no_polish_acknowledged=True, currency='USD', fee_minor=500,
            opening_acceptance=dict(quote_id=quote,quote_revision=1,consent_revision=1,accepted_terms_revision=1))
        opening['maintenance_request_id'] = submitted
        with pytest.raises(intake_routes.PublicError) as error:
            await save(intake, request, actor)
        assert error.value.code == 'custody_unconfirmed'
        audit_status = 200
        if change in ('opening_not_current', 'opening_not_assigned'):
            opening[change.removeprefix('opening_not_')] = False
            physical_only=intake.model_copy(update=dict(diagnostic_opening_permission=False,fee_acknowledged=False,
                no_polish_acknowledged=False,fee_minor=0,opening_acceptance=None))
            received=await save(physical_only,request,actor)
            assert received['state'] == 'received'
            assert received['diagnosis_allowed'] is False
            assert 'maintenance_request_id' not in received
            async with pool.acquire() as tx:
                case = UUID(received['id'])
                assert await tx.fetchval('SELECT custody_receipt_id FROM technical_intakes WHERE id=$1', case) == receipt
                assert await tx.fetchval('SELECT state FROM technical_intake_audit WHERE record_id=$1', case) == 'received'
                assert await tx.fetchval('SELECT count(*) FROM maintenance_received_cases') == 0
            return
        async with pool.acquire() as tx:
            await tx.execute("""UPDATE maintenance_request_operations
                SET result = result || '{"watch_revision":2}'::jsonb WHERE operation_id=$1""", submission)
        with pytest.raises(HTTPException) as error:
            await save(intake, request, actor)
        assert error.value.status_code == 409
        async with pool.acquire() as tx:
            assert await tx.fetchval('SELECT count(*) FROM technical_intakes') == 0
            await tx.execute("""UPDATE maintenance_request_operations
                SET result = result || '{"watch_revision":1}'::jsonb WHERE operation_id=$1""", submission)
        opening['watch_revision'] = 3
        with pytest.raises(intake_routes.PublicError) as error:
            await save(intake, request, actor)
        assert error.value.code=='opening_acceptance_unconfirmed'
        async with pool.acquire() as tx:
            assert await tx.fetchval('SELECT count(*) FROM maintenance_received_cases') == 0
        opening['watch_revision'] = 2
        received = await save(intake, request, actor)
        assert received['maintenance_request_id'] == str(submitted)
        assert await save(intake,request,actor)=={**received,'diagnosis_allowed':False}
        assert custody_reads == [receipt] * 4
        case = UUID(received['id'])
        assert case != submitted
        if change in ('linked_watch_revision', 'missing_signed_request', 'different_signed_request'):
            assert (await intake_routes.detail(case, request, actor))['diagnosis_allowed'] is True
            write_allowed = False
            detail = await intake_routes.detail(case, request, actor)
            assert detail['custody_verification'] == 'current'
            assert detail['diagnosis_allowed'] is False
            write_allowed = True
            if change == 'linked_watch_revision':
                opening['watch_revision'] = 3
            elif change == 'missing_signed_request':
                del opening['maintenance_request_id']
            else:
                opening['maintenance_request_id'] = submission
            assert (await intake_routes.detail(case, request, actor))['diagnosis_allowed'] is False
            request.headers.update({'Idempotency-Key': 'test-intake-update', 'If-Match': '1'})
            request.url.path += f'/{case}'
            with pytest.raises(intake_routes.PublicError) as error:
                await save(intake,request,actor,case)
            assert error.value.code=='stale_case_binding'
            async with pool.acquire() as tx:
                assert await tx.fetchval('SELECT revision FROM technical_intakes WHERE id=$1', case) == 1
                assert await tx.fetchval('SELECT count(*) FROM technical_intake_operations') == 1
            return
        if change in ('linked_not_current', 'linked_not_assigned'):
            opening[change.removeprefix('linked_not_')] = False
            request.headers.update({'Idempotency-Key': 'test-intake-update', 'If-Match': '1'})
            request.url.path += f'/{case}'
            with pytest.raises(intake_routes.PublicError) as error:
                await save(intake.model_copy(update={'reported_issue': 'Updated issue'}), request, actor, case)
            assert error.value.code=='stale_case_binding'
            async with pool.acquire() as tx:
                assert await tx.fetchval('SELECT revision FROM technical_intakes WHERE id=$1', case) == 1
                assert await tx.fetchval('SELECT count(*) FROM technical_intake_operations') == 1
            return
        body = Diagnose(operation_id=operation, case_id=case, request_id=submitted,
                        watch_id=watch, actor_id=person, organization_id=org,
                        expected_revision=0, assignment_revision=1, diagnosis='Worn winding components',
                        reviewed_intake=dict(intake_revision=1,receipt_id=receipt,receipt_revision=1,watch_revision=2,incident_revision=0),
                        lines=[dict(id=line, label='Inspect winding assembly', kind='labor', mandatory=True)],
                        required_tests={line:['winding_efficiency']},finish_requirements={line:[]})
        opening['received_at'] = received_at - timedelta(seconds=1)
        with pytest.raises(HTTPException) as error:
            await diagnose(case, body, request, actor)
        assert error.value.status_code == 409
        opening['received_at'] = received_at
        with pytest.raises(HTTPException) as error:
            await diagnose(case, body.model_copy(update={'request_id': submission}), request, actor)
        assert error.value.status_code == 409
        if change is None:
            servicing_enabled = False
            with pytest.raises(HTTPException) as error:
                await diagnose(case, body, request, actor)
            assert error.value.status_code == 503
            async with pool.acquire() as tx:
                assert not await tx.fetchval('SELECT count(*) FROM service_diagnosis_operations')
            servicing_enabled=True
            advance_incident_before_fence=True
            with pytest.raises(HTTPException) as stale_preflight:
                await diagnose(case,body,request,actor)
            assert stale_preflight.value.status_code==409
            async with pool.acquire() as tx:
                for table in ('service_diagnoses','service_diagnosis_operations','service_diagnosis_outbox'):
                    assert not await tx.fetchval(f'SELECT count(*) FROM {table}')
            advance_incident_before_fence=False
            native_incident=0
        result = await diagnose(case, body, request, actor)
        assert result['state'] == 'assessed'
        assert 'current' not in result and 'diagnosis_allowed' not in result
        assert (result['case_id'], result['request_id'], result['watch_revision']) == (
            str(case), str(submitted), 2)
        assert result['incident_revision'] == 0
        assert await diagnose(case, body, request, actor) == result
        if change == 'incident':
            opening['incident_revision'] = 1

        # Change retained facts after the initial read while current authority is being checked.
        bind = routes.case_binding
        updates = {
            'replacement': 'UPDATE service_diagnoses SET revision=2',
            'intake_revision': 'UPDATE technical_intakes SET revision=2',
            'consent': """UPDATE technical_intakes SET private_record=private_record
                          || '{"diagnostic_opening_permission": false}'::jsonb""",
            'custody': 'UPDATE technical_intakes SET custody_revision=2',
            'missing_diagnosis_receipt': 'DELETE FROM service_diagnosis_operations',
            'different_diagnosis_receipt': """UPDATE service_diagnosis_operations
                SET receipt=receipt || '{"diagnosis": "Different findings"}'::jsonb""",
            'missing_submission_receipt': 'DELETE FROM maintenance_request_operations',
            'missing_case_link': 'DELETE FROM maintenance_received_cases',
            'different_submission_receipt': """UPDATE maintenance_request_operations
                SET result=result || '{"watch_revision": 2}'::jsonb""",
        }

        async def bind_and_change(*args):
            if change in updates:
                async with pool.acquire() as tx:
                    if change == 'missing_diagnosis_receipt':
                        await tx.execute('DELETE FROM service_diagnosis_outbox')
                    await tx.execute(updates[change])
            return await bind(*args)

        monkeypatch.setattr(routes, 'case_binding', bind_and_change)
        monkeypatch.setattr(routes, 'service', lambda *args: None)
        if change:
            with pytest.raises(HTTPException) as error:
                await routes.current(case, request)
            assert error.value.status_code == 409
        else:
            exported = await routes.current(case, request)
            assert exported['current'] is True and exported['diagnosis_allowed'] is True
            assert exported['assessment_id'] == result['assessment_id']
            assert exported['diagnosis'] == body.diagnosis
            assert exported['lines'] == result['lines']
            del opening['maintenance_request_id']
            with pytest.raises(HTTPException) as error:
                await routes.current(case, request)
            assert error.value.status_code == 409
            opening['maintenance_request_id'] = submitted

            from bt_contracts.service.maintenance.diagnosis import DiagnosisAuthorization

            decision = DiagnosisAuthorization(
                operation_key='test-repair-accept', quote_id=UUID(int=100), quote_revision=1,
                buyer_id=buyer, organization_id=org, case_revision=1,
                assessment_id=UUID(result['assessment_id']), assessment_revision=1)
            with pytest.raises(HTTPException) as error:
                async with routes.hold_diagnosis(request, case, decision.model_copy(update={'case_revision': 2})):
                    pytest.fail('Stale diagnosis was authorized')
            assert error.value.status_code == 409
            from asyncpg import LockNotAvailableError

            async with routes.hold_diagnosis(request, case, decision) as proof:
                assert proof == {'authorization': decision.model_dump(mode='json'), 'diagnosis': exported}
                with pytest.raises(LockNotAvailableError):
                    async with pool.acquire() as writer, writer.transaction():
                        await writer.execute("SET LOCAL lock_timeout = '50ms'")
                        await writer.execute('SELECT 1 FROM service_diagnoses WHERE case_id=$1 FOR UPDATE', case)
            async with pool.acquire() as writer:
                await writer.execute('SELECT 1 FROM service_diagnoses WHERE case_id=$1 FOR UPDATE', case)
            await assert_stalled_fence_expires(routes, request, case, decision, pool, monkeypatch)
            from bt_contracts.service.case_lines.acceptance import Acceptance
            from bt_contracts.service.quality.v1 import Binding, RepairScope
            from service_app.repair_scope import repair_scope_current

            scope_module = next(item for item in discover(MODULES) if item.id == 'L17.case-lines')
            accept = scope_module.load('routes.py:accept')
            scope_routes = sys.modules[accept.__module__]
            repair_quote = UUID(int=20)
            accepted = Acceptance(operation_id=UUID(int=21), case_id=case, request_id=submitted,
                actor_id=buyer, organization_id=org, watch_id=watch, expected_revision=0,
                assessment_id=result['assessment_id'], assessment_revision=1,
                quote_id=repair_quote, quote_revision=1, policy_revision=2)
            terms_digest='a'*64
            decision = dict(selected_line_ids=[str(line)],terms_digest=terms_digest,
                amounts=dict(assessment_fee_minor=500, payable_minor=1000),
                accepted_fee_lines=dict(assessment=True))

            async def quote_current(request, quote_id, bindings, **kwargs):
                assert UUID(str(quote_id)) == repair_quote
                return dict(revision=1,terms_digest=terms_digest,policy={'revision': 2}, source_revision=1, diagnosis=body.diagnosis,
                            lines=[{**result['lines'][0], 'amount_minor': 500}],
                            assessment_fee_minor=500, decision=decision), decision

            monkeypatch.setattr(scope_routes, 'current_quote', quote_current)
            monkeypatch.setattr(scope_routes, 'current_commitment', commitment)
            monkeypatch.setattr(scope_routes, 'prerequisite', prerequisite)
            buyer_actor = SimpleNamespace(actor=SimpleNamespace(subject_id=buyer, organization_id=None))
            async with pool.acquire() as tx:
                saved_operation = await tx.fetchrow(
                    'SELECT * FROM service_diagnosis_operations WHERE operation_id=$1', operation)
                saved_event = await tx.fetchrow(
                    'SELECT * FROM service_diagnosis_outbox WHERE operation_id=$1', operation)
                await tx.execute(updates['different_diagnosis_receipt'])
                with pytest.raises(HTTPException) as error:
                    await accept(submitted, accepted, request, buyer_actor)
                assert error.value.status_code == 409
                await tx.execute('DELETE FROM service_diagnosis_outbox WHERE operation_id=$1', operation)
                await tx.execute(updates['missing_diagnosis_receipt'])
                with pytest.raises(HTTPException) as error:
                    await accept(submitted, accepted, request, buyer_actor)
                assert error.value.status_code == 409
                for table in ('service_case_scopes', 'service_case_scope_operations', 'service_case_scope_outbox'):
                    assert await tx.fetchval(f'SELECT count(*) FROM {table}') == 0
                await tx.execute('INSERT INTO service_diagnosis_operations VALUES($1,$2,$3,$4,$5)',
                                 *saved_operation.values())
                await tx.execute('INSERT INTO service_diagnosis_outbox VALUES($1,$2,$3,$4)',
                                 *saved_event.values())
            from fastapi import FastAPI
            from httpx import ASGITransport, AsyncClient
            from service_app import sources
            from bt_runtime.principal import CurrentPrincipal

            async def personal(client, token, request_id):
                assert token == 'test-buyer'
                return CurrentPrincipal.model_validate(dict(
                    actor=dict(subject_id=buyer, session_id='test-session'), roles=['buyer']))

            async def selected(*args):
                pytest.fail('Buyer acceptance and receipt recovery must use personal authority')

            monkeypatch.setattr(sources, 'current_principal', personal)
            monkeypatch.setattr(sources, 'client', lambda *args: None)
            monkeypatch.setattr(sources, 'read', selected)
            app = FastAPI()
            app.state.pool = pool
            app.include_router(scope_routes.router)

            @app.middleware('http')
            async def request_id(request, call_next):
                request.state.request_id = 'test-request'
                return await call_next(request)

            params = {'organization_id': str(org)}
            command_path = f'/v1/case-lines/{submitted}/acceptance'
            receipt_path = f'/v1/case-lines/operations/{accepted.operation_id}'
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test',
                                   headers={'Authorization': 'Bearer test-buyer'}) as client:
                assert (await client.get(receipt_path, params=params)).status_code == 404
                wrong_business = {'organization_id': str(UUID(int=99))}
                payload = accepted.model_dump(mode='json')
                assert (await client.post(command_path, params=wrong_business, json=payload)).status_code == 403
                response = await client.post(command_path, params=params, json=payload)
                assert response.status_code == 200
                receipt = response.json()
                assert receipt['operation_id'] == str(accepted.operation_id)
                assert (await client.get(receipt_path, params=params)).json() == receipt
                assert (await client.get(receipt_path, params=wrong_business)).status_code == 404
                assert (await client.post(command_path, params=params, json=payload)).json() == receipt
            retry = accepted.model_copy(update={'operation_id': UUID(int=22), 'expected_revision': 1})
            assert await accept(submitted, retry, request, buyer_actor) == receipt
            assert await accept(submitted, retry, request, buyer_actor) == receipt
            assert await scope_routes.lookup(retry.operation_id, request, buyer_actor) == receipt
            conflict = retry.model_copy(update={'operation_id': UUID(int=23), 'policy_revision': 3})
            with pytest.raises(HTTPException) as error:
                await accept(submitted, conflict, request, buyer_actor)
            assert error.value.status_code == 409

            binding = Binding(job_id=UUID(int=24), watch_id=watch, organization_id=org,
                scope_revision=1, work_revision=1, assignment_revision=1,
                quote_id=repair_quote, quote_revision=1, policy_revision=2)
            repair = RepairScope(case_id=case, assessment_id=accepted.assessment_id, buyer_id=buyer)
            work_module = next(item for item in discover(MODULES) if item.id == 'L19.authorized-work')
            work = work_module.load('provider.py:Provider')(request)
            work_authority = SimpleNamespace(**binding.model_dump(), source_revision=1)
            paid = SimpleNamespace(buyer_id=buyer, total_minor=1000, order_id=UUID(int=25))
            job_receipt = dict(service_acceptance_id=str(accepted.operation_id), service_total_minor=1000)
            quote = dict(source_id=str(case), assessment_id=str(repair.assessment_id),
                         assessment_fee_minor=500, decision=decision)
            args = (work_authority, paid, job_receipt, quote, [str(line)])
            assert (await work.verify_repair_acceptance(*args))[:3] == (
                case, repair.assessment_id, accepted.operation_id)
            async with pool.acquire() as tx:
                await tx.execute(
                    "UPDATE service_case_scope_operations SET receipt = receipt || '{\"policy_revision\":3}'::jsonb "
                    "WHERE operation_id=$1", accepted.operation_id)
            with pytest.raises(ConnectionError, match='case_scope_unavailable'):
                await work.verify_repair_acceptance(*args)
            async with pool.acquire() as tx:
                await tx.execute('UPDATE service_case_scope_operations SET receipt=$2::jsonb WHERE operation_id=$1',
                                 accepted.operation_id, json.dumps(receipt))

            async def assessment_commitment(_, order_id):
                if order_id == order:
                    return SimpleNamespace(**{**opening, 'current': False}, buyer_id=buyer)
                assert order_id == paid.order_id
                return SimpleNamespace(order_id=order_id,watch_id=watch,buyer_id=buyer,
                    organization_id=org,quote_id=repair_quote,quote_revision=1,watch_revision=3,
                    order_revision=2,current=True,state='paid_held')

            async def paid_fact(_, order_id):
                assert order_id == paid.order_id
                return SimpleNamespace(order_id=order_id, watch_id=watch, buyer_id=buyer,
                    organization_id=org, quote_id=repair_quote, quote_revision=1, revision=2,
                    paid=True, state='paid_held', is_demo=False, currency='USD',
                    order_kind='service_job', total_minor=1000)

            async def reserved_watch(_, service, path):
                assert (service, path) == ('orders', f'/internal/v2/watches/{watch}')
                return dict(watch_id=str(watch), status='reserved', source_kind='service_job',
                            source_id=str(paid.order_id))

            monkeypatch.setattr(scope_routes, 'current_commitment', assessment_commitment)
            monkeypatch.setattr(scope_routes, 'paid_order', paid_fact)
            monkeypatch.setattr(scope_routes, 'internal_read', reserved_watch)
            for repair_order in (None, paid.order_id):
                assert (await scope_routes.current(submitted, request, buyer_actor, repair_order)).revision == 1

            for decision in ('assigned', 'permission'):
                opening[decision] = False
                for repair_order in (None, paid.order_id):
                    with pytest.raises(HTTPException) as error:
                        await scope_routes.current(submitted, request, buyer_actor, repair_order)
                    assert error.value.status_code == 409
                opening[decision] = True

            from unittest.mock import AsyncMock
            from bt_contracts_core.errors import AccessDenied

            async def business_prerequisite(request, name, *scope):
                if name == 'intake_record_access' and scope == (person, org, order, 'read'):
                    return dict(actor_id=person, organization_id=org, order_id=order,
                                permission='read', allowed=True, assignment_revision=1)
                return await prerequisite(request, name, *scope)

            permissions = ['business.records.read']
            business_actor = CurrentPrincipal.model_validate(dict(
                actor=dict(subject_id=person, organization_id=org, session_id='test-session'),
                organizations=[org], organization_grants=[dict(organization_id=org, permissions=permissions)]))
            with monkeypatch.context() as patch:
                discovery = AsyncMock(wraps=reserved_watch)
                payment = AsyncMock(wraps=paid_fact)
                patch.setattr(scope_routes, 'prerequisite', business_prerequisite)
                patch.setattr(scope_routes, 'internal_read', discovery)
                patch.setattr(scope_routes, 'paid_order', payment)
                for repair_order in (None, paid.order_id):
                    with pytest.raises(AccessDenied):
                        await scope_routes.current(submitted, request, business_actor, repair_order)
                discovery.assert_not_awaited()
                payment.assert_not_awaited()
                business_actor.organization_grants[0].permissions.append('orders.read')
                for repair_order in (None, paid.order_id):
                    assert (await scope_routes.current(
                        submitted, request, business_actor, repair_order)).revision == 1

            # Orders advances custody while the local diagnosis and held payment stay unchanged.
            opening.update(receipt_id=UUID(int=26), receipt_revision=2)
            for repair_order in (None, paid.order_id):
                with pytest.raises(HTTPException) as error:
                    await scope_routes.current(submitted, request, buyer_actor, repair_order)
                assert error.value.status_code == 409
            opening.update(receipt_id=receipt, receipt_revision=1)

            missing_acceptance = 'DELETE FROM service_case_scope_operations WHERE operation_id=$1'
            async with pool.acquire() as tx:
                saved_acceptance = await tx.fetchrow(
                    'SELECT * FROM service_case_scope_operations WHERE operation_id=$1', accepted.operation_id)
                saved_scope_event = await tx.fetchrow(
                    'SELECT * FROM service_case_scope_outbox WHERE operation_id=$1', accepted.operation_id)
                saved_submission = await tx.fetchrow('SELECT * FROM maintenance_request_operations')
            failures = (
                (missing_acceptance,
                 'INSERT INTO service_case_scope_operations VALUES($1,$2,$3,$4)', tuple(saved_acceptance.values())),
                (updates['missing_diagnosis_receipt'],
                 'INSERT INTO service_diagnosis_operations VALUES($1,$2,$3,$4,$5)', tuple(saved_operation.values())),
                (updates['missing_submission_receipt'],
                 'INSERT INTO maintenance_request_operations VALUES($1,$2,$3,$4,$5)', tuple(saved_submission.values())),
                (updates['missing_case_link'],
                 'INSERT INTO maintenance_received_cases VALUES($1,$2,$3,$4)', (case, submitted, UUID(result['fee_quote_id']), 1)),
            )
            for damage, restore, restore_args in failures:
                async with pool.acquire() as tx:
                    if damage == updates['missing_diagnosis_receipt']:
                        await tx.execute('DELETE FROM service_diagnosis_outbox')
                    if damage == missing_acceptance:
                        await tx.execute('DELETE FROM service_case_scope_outbox WHERE operation_id=$1', accepted.operation_id)
                        await tx.execute(damage, accepted.operation_id)
                    else:
                        await tx.execute(damage)
                    assert not await repair_scope_current(tx, binding, 1, repair, [line])
                with pytest.raises(ConnectionError, match='case_scope_unavailable'):
                    await work.verify_repair_acceptance(*args)
                for repair_order in (None, paid.order_id):
                    with pytest.raises(HTTPException) as error:
                        await scope_routes.current(submitted, request, buyer_actor, repair_order)
                    assert error.value.status_code == 409
                async with pool.acquire() as tx:
                    await tx.execute(restore, *restore_args)
                    if damage == missing_acceptance:
                        await tx.execute('INSERT INTO service_case_scope_outbox VALUES($1,$2,$3,$4)',
                                         *saved_scope_event.values())
                    if damage == updates['missing_diagnosis_receipt']:
                        await tx.execute('INSERT INTO service_diagnosis_outbox VALUES($1,$2,$3,$4)',
                                         *saved_event.values())

            async with unit_of_work(pool) as tx:
                assert await tx.fetchval('SELECT count(*) FROM service_case_scope_outbox') == 1
                assert await tx.fetchval("SELECT body->>'operation_id' FROM service_case_scopes") == str(accepted.operation_id)
                assert await repair_scope_current(tx, binding, 1, repair, [line], lock=True)
                await tx.execute('UPDATE technical_intakes SET revision=2 WHERE id=$1', case)
                assert not await repair_scope_current(tx, binding, 1, repair, [line])
    finally:
        await pool.close()


def test_published_scope_accepts_pricing_line_limit():
    module = next(item for item in discover(MODULES) if item.id == 'L17.case-lines')
    publish = module.load('routes.py:published_scope')
    request, assessment, line = (str(UUID(int=n)) for n in range(1, 4))
    maximum = 9_000_000_000_000
    item = dict(id=line, label='Movement inspection', kind='labor', mandatory=True, amount_minor=maximum)
    saved = dict(request_id=request, request_revision=1, revision=1, assessment_id=assessment,
                 assessment_revision=1, accepted_line_ids=[line], lines=[item])
    assert publish(saved).accepted_total() == maximum
    item['amount_minor'] += 1
    with pytest.raises(HTTPException) as error:
        publish(saved)
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [None, 'fee_quote', 'repair_quote', 'repair_watch', 'repair_current', 'payable',
                                    'receipt', 'stale_custody', 'custody_unavailable', 'assigned', 'permission'])
async def test_paid_scope_uses_repair_reservation(monkeypatch, change):
    import sys
    from datetime import datetime, timezone

    module = next(item for item in discover(MODULES) if item.id == 'L17.case-lines')
    verify = module.load('routes.py:paid_source')
    routes = sys.modules[verify.__module__]
    fee_order, repair_order, fee_quote, quote, buyer, watch, org, request, other = (
        UUID(int=n) for n in range(1, 10))
    scope = dict(watch_id=str(watch), actor_id=str(buyer), organization_id=str(org),
                 request_id=str(request), quote_id=str(quote), quote_revision=3)
    diagnosis = dict(
        watch_id=str(watch), buyer_id=str(buyer), organization_id=str(org), request_id=str(request),
        order_id=str(fee_order), fee_quote_id=str(fee_quote), fee_quote_revision=2,
        case_id=str(UUID(int=10)), operation_id=str(UUID(int=11)), actor_id=str(UUID(int=12)),
        intake_revision=1, receipt_id=str(UUID(int=13)), receipt_revision=1,
    )
    shared = dict(watch_id=watch, buyer_id=buyer, organization_id=org)
    assessment = SimpleNamespace(**shared, order_id=fee_order, current=False,
                                 quote_id=other if change == 'fee_quote' else fee_quote, quote_revision=2)
    repair = SimpleNamespace(**shared, order_id=repair_order, current=change != 'repair_current',
                             quote_id=quote, quote_revision=3, order_revision=4, state='paid_held')
    if change == 'repair_quote':
        repair.quote_id = other
    if change == 'repair_watch':
        repair.watch_id = other

    async def commitment(request, order):
        return {fee_order: assessment, repair_order: repair}[order]

    async def paid_order(request, order):
        assert order == repair_order
        return SimpleNamespace(**shared, order_id=order, quote_id=quote, quote_revision=3,
                               revision=4, paid=True, state='paid_held', is_demo=False,
                               currency='USD', order_kind='service_job',
                               total_minor=600 if change == 'payable' else 500)

    received_at = datetime.now(timezone.utc)

    async def opening(_, name, actor, organization, order):
        assert (name, actor, organization, order) == (
            'intake_opening_authority', UUID(diagnosis['actor_id']), org, fee_order)
        if change == 'custody_unavailable':
            raise ConnectionError
        return dict(
            actor_id=actor, organization_id=org, order_id=fee_order, watch_id=watch,
            receipt_id=diagnosis['receipt_id'], receipt_revision=2 if change == 'stale_custody' else 1,
            received_at=received_at,
            current=False, assigned=change != 'assigned', permission=change != 'permission',
            watch_revision=2, incident_revision=0,
            customer_opening_permission=True, accepted_assessment_fee=True,
            customer_no_polish_acknowledged=True, consent_revision=1, accepted_terms_revision=1,
            quote_id=fee_quote, quote_revision=2, accepted_fee_minor=0, currency='USD')

    class Transaction:
        async def fetchval(self, query, *args):
            assert 'service_diagnosis_operations' in query
            return None if change == 'receipt' else received_at

    monkeypatch.setattr(routes, 'prerequisite', opening)
    monkeypatch.setattr(routes, 'current_commitment', commitment)
    monkeypatch.setattr(routes, 'paid_order', paid_order)
    if change:
        with pytest.raises(HTTPException) as error:
            await verify(None, Transaction(), diagnosis, scope, repair_order, 500)
        assert error.value.status_code == (503 if change == 'custody_unavailable' else 409)
    else:
        await verify(None, Transaction(), diagnosis, scope, repair_order, 500)


@pytest.mark.asyncio
@pytest.mark.parametrize(('change', 'status'), [
    ({}, None),
    ({'status': 'available', 'source_id': None}, 409),
    ({'watch_id': str(UUID(int=99))}, 409),
    ({'source_kind': 'fixed'}, 409),
    ({'source_id': 'invalid'}, 503),
    (None, 503),
])
async def test_paid_repair_discovery_reads_exact_scoped_order(monkeypatch, change, status):
    import sys

    module = next(item for item in discover(MODULES) if item.id == 'L17.case-lines')
    resolve_order = module.load('routes.py:repair_commitment_order')
    watch, order = UUID(int=1), UUID(int=2)

    async def orders(_, service, path):
        assert (service, path) == ('orders', f'/internal/v2/watches/{watch}')
        if change is None:
            raise ConnectionError
        return dict(watch_id=str(watch), source_id=str(order), status='reserved',
                    source_kind='service_job') | change

    monkeypatch.setattr(sys.modules[resolve_order.__module__], 'internal_read', orders)
    if status is None:
        assert await resolve_order(None, watch) == order
    else:
        with pytest.raises(HTTPException) as error:
            await resolve_order(None, watch)
        assert error.value.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize('business_member', [False, True])
async def test_buyer_recovers_case_scope_with_destination_query(monkeypatch, business_member):
    from contextlib import asynccontextmanager
    import sys

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from bt_contracts.service.case_lines.acceptance import Acceptance
    from bt_runtime.principal import CurrentPrincipal
    from service_app import sources

    module = next(item for item in discover(MODULES) if item.id == 'L17.case-lines')
    routes = sys.modules[module.load('routes.py:lookup').__module__]
    command = Acceptance(**{
        key: UUID(int=index) for index, key in enumerate((
            'operation_id', 'case_id', 'request_id', 'actor_id', 'organization_id',
            'watch_id', 'assessment_id', 'quote_id',
        ), 1)
    }, expected_revision=0, assessment_revision=1, quote_revision=1, policy_revision=1)
    saved = command.model_dump(mode='json', exclude_none=True)
    receipt = routes.accepted_receipt({**saved, 'state': 'accepted', 'revision': 1}, 1)

    async def personal(client, token, request_id):
        assert token == 'test-buyer'
        return CurrentPrincipal.model_validate(dict(
            actor=dict(subject_id=command.actor_id, session_id='test-session'),
            roles=['buyer'], organizations=[command.organization_id] if business_member else []))

    async def selected(*args):
        pytest.fail('The owning buyer should recover the receipt under personal authority')

    class Transaction:
        async def execute(self, query, identifier):
            assert 'pg_advisory_xact_lock' in query and identifier == str(command.operation_id)

        async def fetchrow(self, query, identifier):
            if 'FROM service_case_scope_operations' in query:
                if identifier == command.operation_id:
                    return dict(command=saved, receipt=receipt)
                return None
            assert identifier == command.case_id
            return dict(buyer_id=command.actor_id, organization_id=command.organization_id)

    @asynccontextmanager
    async def acquire():
        yield Transaction()

    @asynccontextmanager
    async def transaction(pool, *, lock_key):
        assert lock_key == f'case-lines:{command.case_id}'
        yield Transaction()

    monkeypatch.setattr(routes, 'unit_of_work', transaction)
    monkeypatch.setattr(sources, 'current_principal', personal)
    monkeypatch.setattr(sources, 'client', lambda *args: None)
    monkeypatch.setattr(sources, 'read', selected)
    app = FastAPI()
    app.state.pool = SimpleNamespace(acquire=acquire)
    app.include_router(routes.router)

    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = 'test-request'
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test',
                           headers={'Authorization': 'Bearer test-buyer'}) as client:
        path = f'/v1/case-lines/operations/{command.operation_id}'
        params = {'organization_id': str(command.organization_id)}
        command_path = f'/v1/case-lines/{command.request_id}/acceptance'
        replay = await client.post(command_path, params=params, json=command.model_dump(mode='json'))
        assert replay.status_code == 200
        assert replay.json() == receipt
        response = await client.get(path, params=params)
        assert response.status_code == 200
        assert response.json() == receipt
        assert (await client.get(path, params={'organization_id': str(UUID(int=99))})).status_code == 404


async def assert_stalled_fence_expires(routes, request, case, decision, pool, monkeypatch):
    import asyncio

    monkeypatch.setattr(routes, 'FENCE_TIMEOUT_SECONDS', 1)
    streamed = asyncio.Event()

    async def send(message):
        if message['type'] == 'http.response.body':
            streamed.set()

    response = routes.DiagnosisFenceResponse(request, case, decision)
    stalled = asyncio.Event()
    stream = asyncio.create_task(response({}, stalled.wait, send))
    try:
        await asyncio.wait_for(streamed.wait(), timeout=1)
        with pytest.raises(HTTPException) as error:
            await routes.DiagnosisFenceResponse(request, case, decision)({}, stalled.wait, send)
        assert error.value.status_code == 503
        with pytest.raises(HTTPException) as error:
            await routes.DiagnosisFenceResponse(request, UUID(int=999), decision)({}, stalled.wait, send)
        assert error.value.status_code == 404
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(stream), timeout=2)
        assert stream.done()
        async with pool.acquire() as writer, writer.transaction():
            await writer.execute("SET LOCAL lock_timeout = '50ms'")
            await writer.execute('SELECT 1 FROM service_diagnoses WHERE case_id=$1 FOR UPDATE', case)
    finally:
        if not stream.done():
            stream.cancel()
            await asyncio.gather(stream, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('disconnect', [True, False])
async def test_pricing_fence_response_releases_authority(monkeypatch, disconnect):
    import asyncio
    import json
    import sys
    from contextlib import asynccontextmanager

    from bt_contracts.service.maintenance.diagnosis import DiagnosisAuthorization

    module = next(item for item in discover(MODULES) if item.id == 'L17.maintenance-requests')
    authorize = module.load('diagnosis.py:authorize_decision')
    routes = sys.modules[authorize.__module__]
    case, quote, buyer, org, assessment = (UUID(int=index) for index in range(1, 6))
    decision = DiagnosisAuthorization(
        operation_key='test-repair-accept', quote_id=quote, quote_revision=1,
        buyer_id=buyer, organization_id=org, case_revision=1, assessment_id=assessment,
        assessment_revision=1)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    held = False
    response_messages = []

    def only_pricing(call, allowed):
        assert call is request and allowed == {'pricing'}

    @asynccontextmanager
    async def hold(call, case_id, binding):
        nonlocal held
        assert (call, case_id, binding) == (request, case, decision)
        held = True
        try:
            yield {'authorization': binding.model_dump(mode='json'), 'diagnosis': {'case_id': str(case)}}
        finally:
            held = False

    async def send(message):
        assert held
        response_messages.append(message)

    async def receive():
        assert held and len(response_messages) == 2
        if not disconnect:
            await asyncio.Event().wait()
        return {'type': 'http.disconnect'}

    monkeypatch.setattr(routes, 'service', only_pricing)
    monkeypatch.setattr(routes, 'hold_diagnosis', hold)
    response = await authorize(case, decision, request)
    if disconnect:
        await response({}, receive, send)
    else:
        monkeypatch.setattr(routes, 'FENCE_TIMEOUT_SECONDS', 0.05)
        with pytest.raises(TimeoutError):
            await response({}, receive, send)
    assert not held
    assert response_messages[0]['status'] == 200
    assert response_messages[1]['more_body'] is True
    assert json.loads(response_messages[1]['body'])['authorization'] == decision.model_dump(mode='json')

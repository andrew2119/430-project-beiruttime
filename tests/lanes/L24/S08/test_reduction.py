import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
import pytest
from pydantic import ValidationError
from bt_contracts.service.reduction.v1 import Authority, Command, Measurement
from reduction_local.domain import authorize, Rejected

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((ROOT / 'packages/contracts-service/reduction/fixtures' / (name + '.json')).read_text())


def pair():
    data = fixture('success')
    return Command.model_validate(data['command']), Authority.model_validate(data['authority'])


def test_actual_return():
    command, authority = pair()
    assert authorize(command, authority, NOW) == 'recorded'


def test_missing_buyer_links_unresolved_even_with_exception():
    command, authority = pair()
    command.returned_link_ids = []
    assert authorize(command, authority, NOW) == 'unresolved'
    exception = fixture('accepted-exception')['exception']
    authority.accepted_exceptions = [type(authority).model_fields['accepted_exceptions'].annotation.__args__[0].model_validate(exception)]
    command.exception_id = authority.accepted_exceptions[0].id
    assert authorize(command, authority, NOW) == 'unresolved'


def test_supplier_exchange_requires_actual_acceptance():
    command, authority = pair()
    command.returned_link_ids = []
    authority.buyer_owned_link_ids = []
    assert authorize(command, authority, NOW) == 'unresolved'
    exception = fixture('accepted-exception')['exception']
    data = authority.model_dump(mode='json')
    data['accepted_exceptions'] = [exception]
    authority = Authority.model_validate(data)
    command.exception_id = UUID(exception['id'])
    assert authorize(command, authority, NOW) == 'recorded'
    authority.accepted_exceptions[0].accepted_by = UUID(int=999)
    with pytest.raises(Rejected) as error:
        authorize(command, authority, NOW)
    assert error.value.code == 'denied'


@pytest.mark.parametrize('field', ['fit_confirmed', 'custody_current', 'accepted_scope'])
def test_current_work_prerequisites(field):
    command, authority = pair()
    setattr(authority, field, False)
    if field == 'fit_confirmed':
        assert authorize(command, authority, NOW) == 'unresolved'
    else:
        with pytest.raises(Rejected):
            authorize(command, authority, NOW)


def test_measurement_never_confirms_fit():
    command, authority = pair()
    command.fit_confirmed = False
    assert command.target.millimeters == 175
    assert authorize(command, authority, NOW) == 'unresolved'


@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
def test_expiry_boundary(offset, allowed):
    command, authority = pair()
    now = authority.valid_until + timedelta(microseconds=offset)
    if allowed:
        assert authorize(command, authority, now) == 'recorded'
    else:
        with pytest.raises(Rejected) as error:
            authorize(command, authority, now)
        assert error.value.code == 'unavailable'


@pytest.mark.parametrize('field,value', [('source_revision', 2), ('organization_id', UUID(int=888)), ('subject_id', UUID(int=888)), ('watch_id', UUID(int=888)), ('quote_revision', 2), ('policy_revision', 2)])
def test_binding_changes(field, value):
    command, authority = pair()
    setattr(command, field, value)
    with pytest.raises(Rejected) as error:
        authorize(command, authority, NOW)
    assert error.value.code == 'stale'


@pytest.mark.parametrize('name,code', [('denied', 'denied'), ('stale', 'stale')])
def test_contract_negative_fixtures(name, code):
    data = fixture(name)
    with pytest.raises(Rejected) as error:
        authorize(Command.model_validate(data['command']), Authority.model_validate(data['authority']), NOW)
    assert error.value.code == code


@pytest.mark.parametrize('value', ['17,5', '17.55', 'NaN', '0', '351', ' 175', '١٧٥'])
def test_measurement_correction(value):
    with pytest.raises(ValidationError):
        Measurement(value=value, unit='mm', source='buyer', method='tape')


@pytest.mark.parametrize('field,value', [('total_minor', 1.1), ('total_minor', True), ('total_minor', -1), ('total_minor', float('inf')), ('currency', 'EUR')])
def test_exact_currency(field, value):
    data = fixture('success')['authority']
    data[field] = value
    with pytest.raises(ValidationError):
        Authority.model_validate(data)


def test_request_is_not_completed_work():
    command, authority = pair()
    command.kind = 'request'
    command.removed_link_ids = []
    command.returned_link_ids = []
    command.fit_confirmed = False
    authority.permission = 'buyer_request'
    authority.actor_id = command.subject_id
    assert authorize(command, authority, NOW) == 'requested'
    authority.actor_id = UUID(int=99)
    with pytest.raises(Rejected):
        authorize(command, authority, NOW)


def test_bounded_parts_and_unique_ids():
    data = fixture('success')['command']
    data['removed_link_ids'] *= 101
    with pytest.raises(ValidationError):
        Command.model_validate(data)
    data['removed_link_ids'] = data['removed_link_ids'][:2]
    with pytest.raises(ValidationError):
        Command.model_validate(data)


@pytest.mark.parametrize('offset', [-1, 0, 86401])
def test_responsible_followup_is_current_and_bounded(offset):
    command, authority = pair()
    authority.next_review_at = NOW + timedelta(seconds=offset)
    with pytest.raises(Rejected) as error:
        authorize(command, authority, NOW)
    assert error.value.code == 'unavailable'


def test_published_json_and_schemas_are_current():
    from bt_contracts.service.reduction.v1 import Result
    root = ROOT / 'packages/contracts-service/reduction'
    for path in root.rglob('*.json'):
        json.loads(path.read_text())
    for name, model in [('command', Command), ('authority', Authority), ('result', Result)]:
        assert json.loads((root / (name + '.schema.v1.json')).read_text()) == model.model_json_schema()
    operations = json.loads((root / 'operations.v1.json').read_text())
    assert operations['commands']['schema'] == 'command.schema.v1.json'


@pytest.mark.parametrize('change', ['missing', 'arbitrary', 'incompatible', 'choice', 'source', 'quote', 'policy', 'duplicate'])
def test_replacement_requires_current_compatible_accepted_part(change):
    from bt_contracts.service.reduction.v1 import AcceptedStrap, Choice
    command, authority = pair()
    command.removed_link_ids = []
    command.returned_link_ids = []
    command.choice_id = 'strap-scope'
    command.actual_strap_id = 'accepted-strap'
    authority.choices = [Choice(id='strap-scope', kind='strap_change', compatible=True)]
    part = AcceptedStrap.model_validate(fixture('accepted-strap')['part'])
    authority.accepted_straps = [part]
    assert authorize(command, authority, NOW) == 'recorded'
    if change == 'missing':
        authority.accepted_straps = []
    elif change == 'arbitrary':
        command.actual_strap_id = 'unaccepted-strap'
    elif change == 'incompatible':
        part.compatible = False
    elif change == 'choice':
        part.choice_id = 'another-scope'
    elif change == 'duplicate':
        authority.accepted_straps.append(part)
    else:
        setattr(part, change + '_revision', 2)
    with pytest.raises(Rejected) as error:
        authorize(command, authority, NOW)
    assert error.value.code == 'denied'

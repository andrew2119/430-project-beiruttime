"""Deterministic boundary tests; these fixtures are not live provider sign-off."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from bt_contracts_core.errors import PublicError

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def authority(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'l15_authority_time', Path('/app/modules/brand-decisions/authority.py')
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(module, 'datetime', Clock)
    return module


def scope():
    row = dict(id=uuid4(), revision=1, buyer_id=uuid4(), brand_id=uuid4())
    common = dict(request_id=str(row['id']), request_revision=1,
                  brand_id=str(row['brand_id']), revision=1)
    assessment = dict(common, id=str(uuid4()), current=True, qualified=True, status='feasible')
    quote = dict(common, id=str(uuid4()), status='accepted', buyer_id=str(row['buyer_id']),
                 assessment_id=assessment['id'], assessment_revision=1, total_minor=500000,
                 currency='USD', expires_at=None)
    grant = dict(common, id=str(uuid4()), status='valid', current=True,
                 subject_id=str(row['buyer_id']), purpose='brand_approval',
                 quote_id=quote['id'], quote_revision=1, amount_minor=500000,
                 currency='USD', reviewer_id=str(uuid4()), expires_at=(NOW+timedelta(hours=1)).isoformat())
    values = dict(assessment=assessment, quote=quote, grant=grant)
    intent = {kind+suffix: value['id' if suffix == '_id' else 'revision']
              for kind, value in values.items() for suffix in ('_id', '_revision')}
    return row, values, intent


@pytest.mark.parametrize('microseconds', [-1, 0, 1])
def test_grant_expiry_before_equal_after_with_nonexpiring_economics(authority, microseconds):
    row, values, intent = scope()
    values['grant']['expires_at'] = (NOW+timedelta(microseconds=microseconds)).isoformat()
    if microseconds > 0:
        assert authority.bind(values, row, intent, uuid4())['amount_minor'] == 500000
    else:
        with pytest.raises(PublicError) as error:
            authority.bind(values, row, intent, uuid4())
        assert error.value.code == 'scope_expired'


@pytest.mark.asyncio
@pytest.mark.parametrize('microseconds', [-1, 0, 1])
@pytest.mark.parametrize('schedule,policy_revision', [('usd-job-v2', 2), ('sample-v1', 1), ('usd-v2', 2), ('usd-job-v2', True)])
async def test_current_quote_acceptance_and_policy_boundaries(authority, monkeypatch, microseconds, schedule, policy_revision):
    row, values, intent = scope()
    quote = values['quote']
    raw_quote = dict(quote, quote_id=quote['id'], quote_revision=1, kind='brand', status='valid',
                     source_id=str(row['id']), source_revision=1,
                     organization_id=str(row['brand_id']), schedule_id=schedule,
                     policy_revision=policy_revision, rounding='half_up', economics='committed',
                     execution_authority='not_granted',
                     accepted_at=(NOW+timedelta(microseconds=microseconds)).isoformat())

    async def remote(request, service, method, path, **kwargs):
        if service == 'eligibility':
            assert kwargs['params']['purpose'] == 'brand_approval'
            return values['grant']
        if service == 'pricing':
            assert path == f'/internal/v3/quotes/{quote["id"]}/validation'
            assert kwargs['params']['buyer_id'] == str(row['buyer_id'])
            return raw_quote
        return dict(values['assessment'], organization_id=str(row['brand_id']))

    monkeypatch.setattr(authority, 'service_request', remote)
    if microseconds > 0 or schedule != 'usd-job-v2' or policy_revision != 2:
        with pytest.raises(PublicError) as error:
            await authority.current(None, row, intent)
        assert error.value.status == 503
    else:
        assert (await authority.current(None, row, intent))['quote']['status'] == 'accepted'


@pytest.mark.parametrize('invalid', [True, 1, None, '2026-11-05T13:00:00'])
def test_malformed_or_naive_grant_expiry_is_unavailable_not_a_pass(authority, invalid):
    row, values, intent = scope()
    values['grant']['expires_at'] = invalid
    with pytest.raises(PublicError) as error:
        authority.bind(values,row,intent,uuid4())
    assert error.value.status == 503 and error.value.code == 'approval_unavailable'

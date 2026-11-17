"""Deterministic policy and strict-boundary checks with synthetic current facts."""
import importlib.util
import json
from pathlib import Path
from uuid import UUID
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]


def load(relative):
    spec = importlib.util.spec_from_file_location('eligibility_test_' + Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


domain = load('services/eligibility/modules/decisions/domain.py')
schema = load('packages/contracts-eligibility/decisions/v1.py')


def identifier(number):
    return str(UUID(int=number))


def command(kind, revision=0, **extra):
    return dict(schema_version='eligibility-command.v1', operation_id=identifier(10 + revision),
                consent_id=identifier(8), expected_revision=revision, kind=kind, reason='Synthetic identity criteria checked.', **extra)


def initial():
    return dict(revision=0, reviews=[], grants=[])


def reviewed(current, consent):
    return domain.transition(initial(), command('review', verdict='eligible'), current, current['reviewer_id'], consent)[0]


def prepared(current, consent, use='execution'):
    state = reviewed(current, consent)
    return domain.transition(state, command('prepare', 1, use=use), current, current['brand_approver_id'], consent)[0]


def test_independent_review_prepare_consume(current, consent):
    schema.Current.model_validate(current)
    schema.Command.model_validate(command('review', verdict='eligible'))
    state = prepared(current, consent)
    grant = state['grants'][0]
    state, result = domain.transition(state, command('consume', 2, use='execution', grant_id=grant['grant_id']),
                                      current, current['brand_approver_id'], consent)
    assert result['state'] == 'consumed'
    assert state['grants'][0]['consumed_at'] == current['now']
    assert domain.transition(state, command('consume', 3, use='execution', grant_id=grant['grant_id']),
                             current, current['brand_approver_id'], consent)[1]['state'] == 'denied'
    assert domain.transition(state, command('prepare', 3, use='execution'), current,
                             current['brand_approver_id'], consent)[1]['state'] == 'denied'
    assert 'reason' not in result and 'synthetic_identity_pass' not in result


@pytest.mark.parametrize('who', ['subject_id', 'brand_approver_id'])
def test_no_same_case_review(current, consent, who):
    current['reviewer_id'] = current[who]
    assert domain.transition(initial(), command('review', verdict='eligible'), current,
                             current['reviewer_id'], consent)[1]['reason_code'] == 'independence_required'


@pytest.mark.parametrize('field', ['identity_current', 'organization_current', 'assignment_current',
                                   'accepted_scope_current', 'commitment_current', 'source_facts_current'])
def test_current_authority_required(current, consent, field):
    state = prepared(current, consent)
    current[field] = False
    assert domain.transition(state, command('consume', 2, use='execution', grant_id=state['grants'][0]['grant_id']),
                             current, current['brand_approver_id'], consent)[1]['state'] == 'denied'


@pytest.mark.parametrize('field', ['request_revision', 'quote_revision', 'consent_revision', 'assignment_revision'])
def test_material_revision_invalidates(current, consent, field):
    state = prepared(current, consent)
    current[field] += 1
    assert domain.transition(state, command('consume', 2, use='execution', grant_id=state['grants'][0]['grant_id']),
                             current, current['brand_approver_id'], consent)[1]['state'] == 'denied'


@pytest.mark.parametrize('status', ['withdrawal_pending', 'withdrawn', 'refused'])
def test_withdrawal_persisted_state_never_restores_grant(current, consent, status, tmp_path):
    state = prepared(current, consent)
    consent['status'] = status
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'state': state, 'consent': consent}))
    restored = json.loads(path.read_text())
    for kind in ('prepare', 'consume'):
        assert domain.transition(restored['state'], command(kind, 2, use='execution', grant_id=state['grants'][0]['grant_id']),
                                 current, current['brand_approver_id'], restored['consent'])[1]['state'] == 'denied'


@pytest.mark.parametrize('instant,expected', [('12:59:59', 'consumed'), ('13:00:00', 'denied'), ('13:00:01', 'denied')])
def test_expiry_boundary(current, consent, instant, expected):
    state = prepared(current, consent)
    current['now'] = '2026-11-16T' + instant + '+00:00'
    assert domain.transition(state, command('consume', 2, use='execution', grant_id=state['grants'][0]['grant_id']),
                             current, current['brand_approver_id'], consent)[1]['state'] == expected


def test_correction_history_and_new_review_invalidates_grant(current, consent):
    state = prepared(current, consent)
    state, result = domain.transition(state, command('review', 2, verdict='correction'), current, current['reviewer_id'], consent)
    assert [r['verdict'] for r in state['reviews']] == ['eligible', 'correction']
    assert result['state'] == 'correction'
    assert domain.transition(state, command('consume', 3, use='execution', grant_id=state['grants'][0]['grant_id']),
                             current, current['brand_approver_id'], consent)[1]['state'] == 'denied'


def test_revoke_survives_restore(current, consent):
    state = prepared(current, consent)
    grant_id = state['grants'][0]['grant_id']
    state, result = domain.transition(state, command('revoke', 2, grant_id=grant_id), current, current['brand_approver_id'], consent)
    assert result['state'] == 'revoked'
    assert domain.transition(json.loads(json.dumps(state)), command('consume', 3, grant_id=grant_id, use='execution'),
                             current, current['brand_approver_id'], consent)[1]['state'] == 'denied'


def test_wrong_actor_and_objective_fact(current, consent):
    assert domain.transition(initial(), command('review', verdict='eligible'), current, identifier(99), consent)[1]['state'] == 'denied'
    current['synthetic_identity_pass'] = False
    assert domain.transition(initial(), command('review', verdict='eligible'), current, current['reviewer_id'], consent)[1]['state'] == 'denied'
    assert domain.transition(initial(), command('review', verdict='not_eligible'), current, current['reviewer_id'], consent)[1]['state'] == 'not_eligible'


@pytest.mark.parametrize('change', [{'request_revision': True}, {'identity_current': 'yes'}, {'now': '2026-11-16T12:00:00'},
                                   {'expires_at': '2026-11-16T15:00:00+02:00'}, {'raw_evidence': 'private'}])
def test_strict_current_contract(current, change):
    with pytest.raises(ValidationError):
        schema.Current.model_validate({**current, **change})


def test_stale_does_not_mutate(current, consent):
    before = reviewed(current, consent)
    after, result = domain.transition(before, command('prepare', 0, use='approval'), current, current['brand_approver_id'], consent)
    assert after == before and result['state'] == 'stale'


def test_fixture_lost_response_is_exact_receipt():
    fixtures = json.loads((ROOT / 'packages/contracts-eligibility/decisions/fixtures.json').read_text())
    assert fixtures['success'] == fixtures['lost_response']
    assert fixtures['timeout']['state'] == 'pending'


@pytest.mark.parametrize('instant,valid', [('12:59:59', True), ('13:00:00', False), ('13:00:01', False)])
@pytest.mark.parametrize('ineffective', ['withdrawn', 'expired', 'changed_scope'])
def test_revoke_requires_current_permission(current, consent, instant, valid, ineffective):
    state = prepared(current, consent)
    if ineffective == 'withdrawn':
        consent['status'] = 'withdrawn'
    elif ineffective == 'expired':
        state['grants'][0]['expires_at'] = '2026-11-16T12:30:00+00:00'
    else:
        current['request_revision'] += 1
    current['now'] = '2026-11-16T' + instant + '+00:00'
    restored = json.loads(json.dumps(state))
    after, result = domain.transition(restored, command('revoke', 2, grant_id=state['grants'][0]['grant_id']),
                                      current, current['brand_approver_id'], consent)
    if valid:
        assert result['state'] == 'revoked'
        assert after['revision'] == 3
        assert after['grants'][0]['revoked_at'] == current['now']
    else:
        assert result['reason_code'] == 'permission_expired'
        assert result['state'] == 'denied'
        assert after == state
    assert restored == state

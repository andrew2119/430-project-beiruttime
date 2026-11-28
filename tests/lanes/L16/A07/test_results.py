import importlib.util
from pathlib import Path
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'services').is_dir())
spec = importlib.util.spec_from_file_location('results_v2', ROOT / 'services/auction/modules/my-results/projection.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


ORDER_ID = "00000000-0000-4000-8000-000000000005"


def facts():
    return dict(is_demo=True, buyer_id='00000000-0000-4000-8000-000000000001', auction_id='00000000-0000-4000-8000-000000000003', watch_id='00000000-0000-4000-8000-000000000004', listing_id='00000000-0000-4000-8000-000000000005',
                revision=2, source_revision=3, currency='USD', result_recorded=True,
                participated=True, ended_at='2030-01-01T00:00:00Z', final_minor=500000,
                sale_qualified=True, winner_id='00000000-0000-4000-8000-000000000001', order_id=ORDER_ID, financial_state='pending')


def authority():
    return dict(actor_id='00000000-0000-4000-8000-000000000001', organization_id=None, allowed=True, expected_source_revision=3)


@pytest.mark.parametrize('financial', ['pending', 'unknown', 'paid_held', 'unpaid', 'unpaid_released', 'released'])
def test_truthful_financial_outcomes(financial):
    result = module.project(dict(facts(), financial_state=financial), authority())
    assert result['state'] == 'won'
    assert result['financial_state'] == financial
    assert result['next_action'] == ('contact_support' if financial == 'unknown' else 'review_order')
    assert result['completed_sale'] == (financial == 'released')
    assert 'maxima' not in result


def test_no_sale_and_other_winner_never_expose_order():
    result = module.project(dict(facts(), winner_id='00000000-0000-4000-8000-000000000002'), authority())
    assert result['state'] == 'lost' and result['order_id'] is None
    result = module.project(dict(facts(), sale_qualified=False, winner_id=None, order_id=None), authority())
    assert result['state'] == 'no_sale' and not result['completed_sale']


@pytest.mark.parametrize('change', [dict(actor_id='00000000-0000-4000-8000-000000000002'),dict(allowed=False),dict(organization_id='business')])
def test_current_scope_denies(change):
    with pytest.raises(PermissionError):
        module.project(facts(), dict(authority(), **change))


@pytest.mark.parametrize('change', [dict(source_revision=4),dict(result_recorded=False),dict(final_minor=True),dict(final_minor=float('inf')),dict(ended_at='2030-01-01T00:00:00'),dict(financial_state='released',order_id=None)])
def test_stale_missing_and_invalid_facts_fail_closed(change):
    with pytest.raises(ValueError):
        module.project(dict(facts(), **change), authority())


def test_duplicate_projection_is_pure():
    source = facts()
    assert module.project(source,authority()) == module.project(source,authority())
    assert source == facts()


def test_published_result_fixtures():
    import json
    cases = json.loads((ROOT / 'packages/contracts-auction/results/fixtures/current.v2.json').read_text())
    for case in cases:
        if case['case'] == 'success':
            assert module.project(case['source'],case['authority']) == case['response']['items'][0]
        elif case['case'] in ('denied','stale'):
            with pytest.raises(PermissionError if case['case'] == 'denied' else ValueError):
                module.project(case['source'],case['authority'])
        else:
            assert case['response']['state'] == 'unavailable' and not case['response']['items']


def test_releasing_unpaid_commitment_keeps_order_history_without_recording_sale():
    result = module.project(dict(facts(), financial_state='unpaid_released'), authority())
    assert result['state'] == 'won'
    assert result['completed_sale'] is False
    assert result['order_id'] == ORDER_ID
    assert result['next_action'] == 'review_order'


@pytest.mark.parametrize('financial,completed', [('unpaid_released', False), ('released', True)])
def test_losing_standing_preserves_sale_outcome_without_order(financial, completed):
    result = module.project(dict(facts(), winner_id='00000000-0000-4000-8000-000000000002', financial_state=financial), authority())
    assert result['state'] == 'lost'
    assert result['completed_sale'] is completed
    assert result['order_id'] is None
    assert result['financial_state'] is None


@pytest.mark.parametrize('final_minor', [None, 430000])
def test_recorded_no_sale_without_a_payment_state(final_minor):
    source = dict(facts(), sale_qualified=False, winner_id=None, order_id=None,
                  financial_state=None, final_minor=final_minor)
    result = module.project(source, authority())
    assert result['state'] == 'no_sale'
    assert result['final_minor'] == final_minor
    assert result['financial_state'] is None
    assert result['order_id'] is None
    assert result['completed_sale'] is False
    assert result['next_action'] == 'view_auction'


@pytest.mark.parametrize('order_id', [{'private_evidence': 'synthetic-evidence'}, '', 'not-an-order', 123])
def test_pending_result_rejects_malformed_order_references(order_id):
    with pytest.raises(ValueError):
        module.project(dict(facts(), order_id=order_id), authority())


def test_pending_allocation_without_an_order_remains_available():
    result = module.project(dict(facts(), order_id=None), authority())
    assert result['financial_state'] == 'pending'
    assert result['order_id'] is None
    assert result['next_action'] == 'contact_support'


@pytest.mark.parametrize('expected_revision', [True, False, 0, -1, 1.0, '1', None])
def test_authority_requires_positive_integer_revision(expected_revision):
    with pytest.raises(ValueError, match='invalid_revision'):
        module.project(dict(facts(), source_revision=1),
                       dict(authority(), expected_source_revision=expected_revision))


@pytest.mark.parametrize('key', ['auction_id', 'watch_id', 'listing_id', 'buyer_id', 'winner_id'])
def test_projection_rejects_non_uuid_references(key):
    current = authority()
    if key == 'buyer_id':
        current['actor_id'] = 'invalid-reference'
    with pytest.raises(ValueError):
        module.project(dict(facts(), **{key: 'invalid-reference'}), current)

@pytest.mark.parametrize('winner_spelling', [str.lower, str.upper])
@pytest.mark.parametrize('actor_spelling', [str.lower, str.upper])
def test_uuid_spelling_does_not_change_authority_or_standing(winner_spelling, actor_spelling):
    buyer = 'abcdef01-0000-4000-8000-000000000001'
    source = dict(facts(), buyer_id=buyer, winner_id=winner_spelling(buyer))
    result = module.project(source, dict(authority(), actor_id=actor_spelling(buyer)))
    assert result['state'] == 'won'
    assert result['buyer_id'] == buyer
    assert result['order_id'] == ORDER_ID
    with pytest.raises(PermissionError):
        module.project(source, dict(authority(), actor_id=actor_spelling(buyer[:-1] + '2')))


@pytest.mark.parametrize('instant', [None, 123, {}, '20300101T000000Z',
                                    '2030-01-01 00:00:00Z', '2030-02-30T00:00:00Z',
                                    '2030-01-01T02:00:00+02:00'])
def test_result_rejects_invalid_wire_instants(instant):
    with pytest.raises(ValueError, match='invalid_instant'):
        module.project(dict(facts(), ended_at=instant), authority())


def test_result_requires_an_end_instant_and_preserves_utc_precision():
    source = facts()
    del source['ended_at']
    with pytest.raises(ValueError, match='invalid_instant'):
        module.project(source, authority())
    source['ended_at'] = '2030-01-01T00:00:00.123456+00:00'
    assert module.project(source, authority())['ended_at'] == '2030-01-01T00:00:00.123456Z'

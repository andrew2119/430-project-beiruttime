"""Privacy handoffs reject counts, incomplete authority and revision rollback."""
import pytest

from privacy_watermarks import WatermarkError, check_current, from_rows, validate

OPERATIONS = {'I07': ['test-operation']}
FACTS = {'test-operation': {'deletion': 2, 'revocation': 3, 'retention': 4}}


@pytest.mark.parametrize('value', [None, {}, {'removed': 1},
    {'test-other': FACTS['test-operation']},
    {'test-operation': {'deletion': 2, 'revocation': 3}},
    {'test-operation': {'deletion': True, 'revocation': 3, 'retention': 4}},
    {'test-operation': {'deletion': 0, 'revocation': 3, 'retention': 4}},
])
def test_incomplete_or_unbound_authority_is_rejected(value):
    with pytest.raises(WatermarkError):
        validate(value, OPERATIONS)


def test_source_results_bind_watermarks_to_exact_operations():
    row = {'operation_id': 'test-operation', 'deletion_watermark': 2,
           'revocation_watermark': 3, 'retention_watermark': 4}
    assert from_rows([row], OPERATIONS) == FACTS
    with pytest.raises(WatermarkError):
        from_rows([row, row], OPERATIONS)
    with pytest.raises(WatermarkError):
        from_rows([{**row, 'operation_id': 'test-other'}], OPERATIONS)


@pytest.mark.parametrize('kind', ['deletion', 'revocation', 'retention'])
def test_current_authority_cannot_move_backwards(kind):
    check_current(FACTS, FACTS, OPERATIONS)
    newer = {'test-operation': {**FACTS['test-operation'], kind: 9}}
    check_current(FACTS, newer, OPERATIONS)
    with pytest.raises(WatermarkError, match='stale'):
        check_current(newer, FACTS, OPERATIONS)

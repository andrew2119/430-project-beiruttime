"""Fixed read identities and fail-closed current provenance."""
import pytest

from connected import CapabilityError, producer_read
from producer_reads import PRODUCER_READS, ProvenanceError, validate_provenance


def row(name='I07', **changes):
    return {'operation_id': 'test-operation', 'producer': name, 'source_revision': 2,
            'authority_revision': 2, 'durable': True, 'seeded': False, 'synthetic': False,
            'authorized': True, **changes}


def test_five_fixed_versioned_domain_reads_bind_operation_array():
    assert set(PRODUCER_READS) == {'I07', 'O08', 'S11', 'A10', 'file_store'}
    for name, read in PRODUCER_READS.items():
        specification = {key: read[key] for key in ('domain', 'query_id')}
        specification['operation_ids'] = ['test-operation']
        sql = producer_read(specification, name)
        assert '$1::text[]' in sql
        assert 'public.e04_' in sql
        assert 'SELECT true' not in sql
        assert read['query_id'].endswith('.v1')
        validate_provenance([row(name)], specification['operation_ids'], name)
        with pytest.raises(CapabilityError):
            producer_read({**specification, 'domain': 'test-other'}, name)


@pytest.mark.parametrize('change', [
    {'producer': 'test-other'}, {'durable': False}, {'seeded': True}, {'synthetic': True},
    {'authorized': False}, {'source_revision': 1}, {'authority_revision': 3},
    {'source_revision': True}, {'source_revision': 0, 'authority_revision': 0},
    {'operation_id': 'test-other'},
])
def test_noncurrent_or_unbound_receipt_is_rejected(change):
    with pytest.raises(ProvenanceError):
        validate_provenance([row(**change)], ['test-operation'], 'I07')


@pytest.mark.parametrize('rows', [[], [row(), row()], [{}]])
def test_missing_duplicate_or_incomplete_provenance_is_rejected(rows):
    with pytest.raises(ProvenanceError):
        validate_provenance(rows, ['test-operation'], 'I07')

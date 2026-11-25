"""Fixed consumer read contract. Producers own the underlying durable views."""

FIELDS = {
    'I07': ('deletion_preserved', 'revocation_preserved', 'retention_preserved',
            'deletion_watermark', 'revocation_watermark', 'retention_watermark'),
    'O08': ('principal_preserved', 'fees_excluded', 'journal_balanced'),
    'S11': ('actual_receipt_preserved', 'current_checks_preserved', 'custody_preserved'),
    'A10': ('dispute_hold_preserved', 'release_authority_preserved', 'totals_preserved'),
    'file_store': ('current', 'file_id', 'tombstoned', 'checksum', 'size', 'content'),
}
DOMAINS = {'I07': 'identity', 'O08': 'orders', 'S11': 'service-operations',
           'A10': 'trust', 'file_store': 'identity'}
PROVENANCE = ('operation_id', 'producer', 'source_revision', 'authority_revision',
              'durable', 'seeded', 'synthetic', 'authorized')

# These views are a consumer contract, not installed substitutes. An absent view
# must fail the connected exercise. No input can choose a relation or expression.
PRODUCER_READS = {
    name: {
        'query_id': 'e04.' + name.lower() + '.v1',
        'domain': DOMAINS[name],
        'sql': 'SELECT ' + ', '.join((*PROVENANCE, *(() if name == 'file_store' else ('passed',)),
                                     *fields))
               + ' FROM public.e04_' + name.lower() + '_v1'
               + ' WHERE operation_id = ANY($1::text[]) ORDER BY operation_id LIMIT 11',
    }
    for name, fields in FIELDS.items()
}


class ProvenanceError(ValueError):
    pass


def validate_provenance(rows, operations, name):
    """A receipt must be durable and authorized by its current owning source."""
    if (not operations or len(operations) > 10 or len(set(operations)) != len(operations)
            or len(rows) != len(operations)
            or {row.get('operation_id') for row in rows} != set(operations)):
        raise ProvenanceError('producer_operation_provenance')
    for row in rows:
        if (row.get('producer') != name or row.get('durable') is not True
                or row.get('seeded') is not False or row.get('synthetic') is not False
                or row.get('authorized') is not True
                or type(row.get('source_revision')) is not int
                or row['source_revision'] < 1
                or type(row.get('authority_revision')) is not int
                or row['source_revision'] != row['authority_revision']):
            raise ProvenanceError('producer_current_provenance')
    return rows

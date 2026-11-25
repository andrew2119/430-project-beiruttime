"""Operation-bound privacy revisions from reviewed durable producer reads."""

KINDS = ('deletion', 'revocation', 'retention')


class WatermarkError(ValueError):
    pass


def validate(value, operations):
    expected = operations.get('I07', [])
    if (not expected or not isinstance(value, dict) or set(value) != set(expected)):
        raise WatermarkError('privacy_watermark_operations')
    for revisions in value.values():
        if (not isinstance(revisions, dict) or set(revisions) != set(KINDS)
                or any(type(revision) is not int or revision < 1
                       for revision in revisions.values())):
            raise WatermarkError('durable_privacy_watermarks_required')
    return value


def from_rows(rows, operations):
    """Only reviewed I07 results may supply these facts, never run input."""
    result = {}
    for row in rows:
        operation = row['operation_id']
        if operation in result:
            raise WatermarkError('duplicate_privacy_operation')
        result[operation] = {kind: row.get(kind + '_watermark') for kind in KINDS}
    return validate(result, operations)


def check_current(saved, current, operations):
    validate(saved, operations)
    validate(current, operations)
    if any(current[operation][kind] < revisions[kind]
           for operation, revisions in saved.items() for kind in KINDS):
        raise WatermarkError('stale_privacy_watermarks')

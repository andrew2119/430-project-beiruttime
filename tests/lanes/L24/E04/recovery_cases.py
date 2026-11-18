"""Recovery sequencing against an owning runtime, never against seeded rows."""
import asyncio
from collections.abc import Mapping
from copy import deepcopy


class RecoveryError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise RecoveryError(reason)


def effects(value):
    """Stable effect identities and totals, measured at the owning sources."""
    require(isinstance(value, Mapping) and set(value) == {'charges', 'payouts', 'custody'},
            'effect_coverage')
    for rows in value.values():
        require(isinstance(rows, dict), 'effect_identity')
    return deepcopy(dict(value))


async def privacy_case(provider, operation_ids):
    """The provider must use real producer commands, not direct row updates.

    Backup returns a private handle. Authority returns source-bound revisions;
    restore reconciles current authority before exposing any restored read.
    The runtime owns authentication, immutable commands and clock admission.
    """
    before = deepcopy(await provider.measure(operation_ids))
    backup = await provider.backup(operation_ids)
    try:
        for action in ('delete', 'revoke', 'retain'):
            await provider.command(action, operation_ids)
        current = deepcopy(await provider.measure(operation_ids))
        for kind in ('deletion', 'revocation', 'retention'):
            require(current['watermarks'][kind] > before['watermarks'][kind],
                    'privacy_transition_not_measured:' + kind)
        require(bool(current['redactions']), 'expected_redactions_missing')
        require(current['unaffected'] == before['unaffected'], 'source_unaffected_digest')
        restored = deepcopy(await provider.restore(backup, operation_ids))
        require(restored['redactions'] == current['redactions'], 'restored_redactions')
        require(restored['watermarks'] == current['watermarks'], 'restored_authority')
        require(restored['unaffected'] == before['unaffected'], 'unaffected_digest')
        require(effects(restored['effects']) == effects(current['effects'])
                == effects(before['effects']), 'privacy_changed_effects')
        # Damage copies of the private representation; never damage source bytes.
        for failure in ('missing_file', 'checksum', 'denied', 'stale'):
            result = await provider.restore_rejected(backup, operation_ids, failure)
            require(result == {'reason': failure, 'exposed_bytes': 0}, 'unsafe_restore:' + failure)
        return {'redactions': restored['redactions'], 'watermarks': restored['watermarks']}
    finally:
        await provider.discard(backup)


async def replay_case(provider, operation_id, held_unknown=False):
    """Interrupt after dispatch, then use the original ID for every lookup/retry."""
    before = effects(await provider.effects(operation_id))
    await provider.lose_response(operation_id)
    await provider.dispatch(operation_id)
    await provider.interrupt(operation_id)
    await provider.restart(operation_id)
    lookup = await provider.lookup(operation_id)
    require(lookup['operation_id'] == operation_id, 'lookup_operation_mismatch')
    require(lookup['state'] == ('pending' if held_unknown else 'acknowledged'), 'lookup_state')
    acknowledged = effects(await provider.effects(operation_id))
    for kind, prior in before.items():
        measured = acknowledged[kind]
        if prior:
            require(measured == prior, 'dispatch_duplicate_effect')
        else:
            require(len(measured) <= 1, 'dispatch_duplicate_effect')
            require(all(isinstance(receipt, Mapping)
                        and receipt.get('operation_id') == operation_id
                        for receipt in measured.values()), 'dispatch_effect_binding')
    results = await asyncio.gather(*(provider.retry(operation_id) for _ in range(2)))
    require(all(row['operation_id'] == operation_id and row['state'] == lookup['state']
                for row in results), 'retry_binding')
    after = effects(await provider.effects(operation_id))
    require(after == acknowledged, 'duplicate_effect')
    if held_unknown:
        require(after == before and all(row.get('held') is True for row in results),
                'unknown_effect_not_held')
    else:
        require(all(row == lookup for row in results), 'acknowledged_receipt_changed')
    return {'operation_id': operation_id, 'state': lookup['state']}


async def recovery_cases(provider, operations):
    """A runtime composition is required; a preparation summary is insufficient."""
    require(provider is not None, 'owning_recovery_runtime_unavailable')
    result = {'privacy': await privacy_case(provider, operations['I07'])}
    for name in ('O08', 'S11', 'A10'):
        require(len(operations[name]) >= 2, 'acknowledged_and_unknown_operations:' + name)
        result[name] = [await replay_case(provider, operations[name][0]),
                        await replay_case(provider, operations[name][1], held_unknown=True)]
    return result

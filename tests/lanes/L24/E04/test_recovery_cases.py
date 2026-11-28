"""Recovery sequencing with local doubles; not connected acceptance."""
import asyncio

import pytest

from recovery_cases import RecoveryError, privacy_case, recovery_cases, replay_case


class Runtime:
    def __init__(self, unknown=False, damage=None):
        self.unknown = unknown
        self.damage = damage
        self.calls = []
        self.changed = False
        self.discarded = False
        self.effect = {'charges': {}, 'payouts': {}, 'custody': {}}
        self.active = 0
        self.overlap = False

    async def measure(self, operations):
        return {'watermarks': {kind: 2 if self.changed else 1
                               for kind in ('deletion', 'revocation', 'retention')},
                'redactions': ['test-file'] if self.changed else [],
                'unaffected': 'test-digest', 'effects': self.effect}

    async def backup(self, operations):
        self.calls.append('backup')
        return 'test-backup'

    async def command(self, action, operations):
        self.calls.append(action)
        self.changed = True

    async def restore(self, backup, operations):
        result = await self.measure(operations)
        if self.damage == 'redactions':
            result['redactions'] = []
        if self.damage == 'digest':
            result['unaffected'] = 'test-corruption'
        return result

    async def restore_rejected(self, backup, operations, failure):
        return {'reason': failure, 'exposed_bytes': 1 if self.damage == 'exposure' else 0}

    async def discard(self, backup):
        self.discarded = True

    async def effects(self, operation):
        return {kind: {key: value for key, value in rows.items()
                       if not isinstance(value, dict) or value.get('operation_id') == operation}
                for kind, rows in self.effect.items()}

    async def lose_response(self, operation):
        self.calls.append(('lose_response', operation))

    async def dispatch(self, operation):
        self.calls.append(('dispatch', operation))
        if not self.unknown:
            self.effect['custody'][operation] = {'operation_id': operation, 'receipt': 'test-receipt'}

    async def interrupt(self, operation):
        self.calls.append(('interrupt', operation))

    async def restart(self, operation):
        self.calls.append(('restart', operation))

    async def lookup(self, operation):
        return {'operation_id': operation, 'state': 'pending' if self.unknown else 'acknowledged',
                'held': self.unknown}

    async def retry(self, operation):
        self.active += 1
        await asyncio.sleep(0)
        self.overlap |= self.active == 2
        self.active -= 1
        if self.damage == 'duplicate':
            self.effect['payouts']['test-duplicate'] = 'test-extra'
        return await self.lookup(operation)


@pytest.mark.asyncio
async def test_privacy_commands_cannot_rewrite_shared_before_effects():
    class ChangedEffects(Runtime):
        async def command(self, action, operations):
            await super().command(action, operations)
            self.effect['charges']['test-charge'] = {
                'operation_id': operations[0], 'total': 100,
            }

    runtime = ChangedEffects()
    with pytest.raises(RecoveryError, match='privacy_changed_effects'):
        await privacy_case(runtime, ['test-operation'])
    assert runtime.discarded


@pytest.mark.asyncio
async def test_backup_precedes_producer_changes_and_cleanup_follows_restore():
    runtime = Runtime()
    result = await privacy_case(runtime, ['test-operation'])
    assert runtime.calls == ['backup', 'delete', 'revoke', 'retain']
    assert result['redactions'] == ['test-file']
    assert runtime.discarded


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['redactions', 'digest', 'exposure'])
async def test_incorrect_restore_never_passes_and_backup_is_reclaimed(damage):
    runtime = Runtime(damage=damage)
    with pytest.raises(RecoveryError):
        await privacy_case(runtime, ['test-operation'])
    assert runtime.discarded


@pytest.mark.asyncio
@pytest.mark.parametrize('unknown', [False, True])
async def test_restart_and_concurrent_retries_preserve_original_operation(unknown):
    runtime = Runtime(unknown)
    result = await replay_case(runtime, 'test-operation', unknown)
    assert runtime.overlap
    assert runtime.calls == [(name, 'test-operation') for name in
                             ('lose_response', 'dispatch', 'interrupt', 'restart')]
    assert result['state'] == ('pending' if unknown else 'acknowledged')


@pytest.mark.asyncio
async def test_duplicate_effect_is_blocking():
    with pytest.raises(RecoveryError, match='duplicate_effect'):
        await replay_case(Runtime(damage='duplicate'), 'test-operation')


@pytest.mark.asyncio
async def test_missing_runtime_cannot_claim_connected_recovery():
    with pytest.raises(RecoveryError, match='owning_recovery_runtime_unavailable'):
        await recovery_cases(None, {})


@pytest.mark.asyncio
async def test_dispatch_cannot_create_two_results_of_one_kind():
    class DuplicateDispatch(Runtime):
        async def dispatch(self, operation):
            await super().dispatch(operation)
            self.effect['custody']['test-second'] = 'test-second-receipt'

    with pytest.raises(RecoveryError, match='dispatch_duplicate_effect'):
        await replay_case(DuplicateDispatch(), 'test-operation')


@pytest.mark.asyncio
async def test_unknown_dispatch_cannot_release_an_effect():
    class ReleasedUnknown(Runtime):
        async def dispatch(self, operation):
            self.effect['payouts'][operation] = {'operation_id': operation, 'receipt': 'test-incorrect-release'}

    with pytest.raises(RecoveryError, match='unknown_effect_not_held'):
        await replay_case(ReleasedUnknown(unknown=True), 'test-operation', True)


@pytest.mark.asyncio
async def test_unchanged_privacy_revision_cannot_prove_a_transition():
    class NoChange(Runtime):
        async def command(self, action, operations):
            pass

    runtime = NoChange()
    with pytest.raises(RecoveryError, match='privacy_transition_not_measured'):
        await privacy_case(runtime, ['test-operation'])
    assert runtime.discarded


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['charges', 'payouts', 'custody'])
async def test_existing_result_cannot_gain_a_second_result(kind):
    class SecondResult(Runtime):
        async def dispatch(self, operation):
            self.effect[kind]['test-second'] = {'operation_id': operation}

    runtime = SecondResult()
    runtime.effect[kind]['test-original'] = {'operation_id': 'test-operation'}
    with pytest.raises(RecoveryError, match='dispatch_duplicate_effect'):
        await replay_case(runtime, 'test-operation')


@pytest.mark.asyncio
async def test_first_result_must_bind_original_operation():
    class WrongOperation(Runtime):
        async def effects(self, operation):
            return {kind: dict(rows) for kind, rows in self.effect.items()}

        async def dispatch(self, operation):
            self.effect['charges']['test-result'] = {'operation_id': 'test-other'}

    with pytest.raises(RecoveryError, match='dispatch_effect_binding'):
        await replay_case(WrongOperation(), 'test-operation')

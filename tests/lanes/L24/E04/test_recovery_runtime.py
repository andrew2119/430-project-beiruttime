"""Command composition checks without service connections."""
from contextlib import asynccontextmanager
import json
import sys
from types import SimpleNamespace

import pytest

import connected
from handoff import consume, publish
from recovery_cases import RecoveryError, recovery_cases
from recovery_runtime import open_runtime
from test_connected import inputs
from test_recovery_cases import Runtime


def install(monkeypatch, factory):
    monkeypatch.setitem(sys.modules, 'test_recovery_owner', SimpleNamespace(open=factory))
    return 'test_recovery_owner:open'


@pytest.mark.parametrize('mode', ['default', 'retain', 'consume'])
def test_command_binds_runtime_and_reaches_publication_or_consumption(tmp_path, monkeypatch, mode):
    inputs(tmp_path)
    path = tmp_path / 'e04-inputs.json'
    value = json.loads(path.read_text())
    for name in ('O08', 'S11', 'A10'):
        value['probes'][name]['operation_ids'] = [f'test-{name}-known', f'test-{name}-unknown']
    path.write_text(json.dumps(value))
    operations = connected.summary_operation_ids(tmp_path)
    lifecycle = []

    class Owner(Runtime):
        async def dispatch(self, operation):
            self.unknown = operation.endswith('-unknown')
            await super().dispatch(operation)

    owner = Owner()

    @asynccontextmanager
    async def factory(*, run, operations):
        assert run == tmp_path
        assert operations == connected.summary_operation_ids(tmp_path)
        lifecycle.append('open')
        try:
            yield owner
        finally:
            lifecycle.append('closed')

    reference = install(monkeypatch, factory)
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'backup-files').mkdir()
    for domain in connected.DOMAINS:
        (work / (domain + '.dump')).write_bytes(b'test-dump')
    facts = {'source_revision': 'test-revision', 'databases': {
        domain: {'migration_ledger': {'rows': 1, 'sha256': 'test-schema'}}
        for domain in connected.DOMAINS}, 'privacy_watermarks': {
            'test-operation': {'deletion': 1, 'revocation': 1, 'retention': 1}}}
    target = tmp_path / 'retained'
    if mode == 'consume':
        publish(target, work, facts, operations, [])

    async def exercise(run, port, record, backup, retain, recovery_provider):
        assert recovery_provider is owner
        assert lifecycle == ['open']
        assert run == tmp_path
        record['recovery_cases'] = await recovery_cases(recovery_provider, operations)
        if retain is not None:
            publish(retain, work, facts, operations, [])
        if backup is not None:
            with consume(backup, 'test-revision', operations) as saved:
                assert len(saved['domains']) == 9

    monkeypatch.setattr(connected, 'connected', exercise)
    arguments = ['--run-dir', str(tmp_path), '--recovery-runtime', reference]
    if mode != 'default':
        arguments += ['--retain-backup' if mode == 'retain' else '--consume-backup', str(target)]
    assert connected.main(arguments) == 0
    assert lifecycle == ['open', 'closed']
    summary = json.loads((tmp_path / 'scenarios/e04/summary.json').read_text())
    assert summary['connected']
    assert set(summary['recovery_cases']) == {'privacy', 'O08', 'S11', 'A10'}
    assert target.exists() == (mode == 'retain')


@pytest.mark.asyncio
async def test_runtime_closes_on_failure_and_cannot_mutate_operation_binding(tmp_path, monkeypatch):
    lifecycle = []
    operations = {'I07': ['test-operation']}

    @asynccontextmanager
    async def factory(*, run, operations):
        operations['I07'].clear()
        try:
            yield Runtime()
        finally:
            lifecycle.append('closed')

    reference = install(monkeypatch, factory)
    with pytest.raises(RuntimeError, match='test-failure'):
        async with open_runtime(reference, tmp_path, operations):
            raise RuntimeError('test-failure')
    assert operations == {'I07': ['test-operation']}
    assert lifecycle == ['closed']


@pytest.mark.asyncio
async def test_preparation_summary_is_rejected_and_context_closed(tmp_path, monkeypatch):
    lifecycle = []

    @asynccontextmanager
    async def factory(**kwargs):
        try:
            yield {'passed': True}
        finally:
            lifecycle.append('closed')

    reference = install(monkeypatch, factory)
    with pytest.raises(RecoveryError, match='recovery_runtime_methods'):
        async with open_runtime(reference, tmp_path, {}):
            pytest.fail('invalid runtime admitted')
    assert lifecycle == ['closed']


@pytest.mark.asyncio
@pytest.mark.parametrize('reference', ['', 'test_owner', 'test_owner:', 'test_owner:open:extra',
                                       'test-owner:open'])
async def test_invalid_factory_reference_fails_closed(tmp_path, reference):
    with pytest.raises(RecoveryError, match='recovery_runtime_reference'):
        async with open_runtime(reference, tmp_path, {}):
            pytest.fail('invalid runtime admitted')

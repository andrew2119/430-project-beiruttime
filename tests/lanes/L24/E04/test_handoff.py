"""Retained backups are private, complete and consumed after a restore attempt."""
import json
import stat

import pytest

from fixtures import DOMAINS
from handoff import HandoffError, consume, load, publish


def prepare(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'backup-files').mkdir()
    for domain in DOMAINS:
        (work / (domain + '.dump')).write_bytes(b'test-dump-' + domain.encode())
    record = {'source_revision': 'test-revision', 'databases': {
        domain: {'migration_ledger': {'rows': 1, 'sha256': 'test-schema'}}
        for domain in DOMAINS}, 'privacy_watermarks': {'test-operation': {
            'deletion': 1, 'revocation': 2, 'retention': 3}}}
    operations = {'I07': ['test-operation']}
    target = tmp_path / 'backup'
    publish(target, work, record, operations, [])
    return target, work, record, operations


def test_nine_verified_dumps_and_schema_revision(tmp_path):
    target, _, _, operations = prepare(tmp_path)
    manifest = load(target, 'test-revision', operations)
    assert set(manifest['domains']) == set(DOMAINS)
    assert manifest['privacy_watermarks']['test-operation']['revocation'] == 2
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600
               for path in target.iterdir() if path.is_file())
    with consume(target, 'test-revision', operations) as restored:
        assert restored == manifest
    assert not target.exists()


@pytest.mark.parametrize('damage', ['missing', 'changed', 'revision', 'operations', 'schema', 'permissions'])
def test_invalid_handoff_fails_before_restore(tmp_path, damage):
    target, _, _, operations = prepare(tmp_path)
    revision = 'test-revision'
    dump = target / (DOMAINS[0] + '.dump')
    if damage == 'missing':
        dump.unlink()
    elif damage == 'changed':
        dump.write_bytes(b'test-corrupted')
    elif damage == 'revision':
        revision = 'test-other-revision'
    elif damage == 'operations':
        operations = {'I07': ['test-other-operation']}
    elif damage == 'permissions':
        dump.chmod(0o644)
    else:
        path = target / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['domains'][DOMAINS[0]]['schema_revision'] = {}
        path.write_text(json.dumps(manifest))
    with pytest.raises((HandoffError, FileNotFoundError)):
        load(target, revision, operations)


def test_rehearsal_failure_still_reclaims_artifacts(tmp_path):
    target, _, _, operations = prepare(tmp_path)
    with pytest.raises(RuntimeError, match='test-interrupted'):
        with consume(target, 'test-revision', operations):
            raise RuntimeError('test-interrupted')
    assert not target.exists()


def test_failed_publication_removes_partial_backup(tmp_path):
    target, work, record, operations = prepare(tmp_path)
    (work / (DOMAINS[-1] + '.dump')).unlink()
    failed = tmp_path / 'failed'
    with pytest.raises(FileNotFoundError):
        publish(failed, work, record, operations, [])
    assert not failed.exists()
    assert target.exists()


def test_counts_cannot_publish_a_privacy_handoff(tmp_path):
    from privacy_watermarks import WatermarkError

    _, work, record, operations = prepare(tmp_path)
    del record['privacy_watermarks']
    record['identity_authority'] = {'test-relation': {'removed': 1}}
    target = tmp_path / 'rejected'
    with pytest.raises(WatermarkError):
        publish(target, work, record, operations, [])
    assert not target.exists()


def test_missing_manifest_watermarks_prevent_consumption(tmp_path):
    from privacy_watermarks import WatermarkError

    target, _, _, operations = prepare(tmp_path)
    path = target / 'manifest.json'
    manifest = json.loads(path.read_text())
    del manifest['privacy_watermarks']
    path.write_text(json.dumps(manifest))
    with pytest.raises(WatermarkError):
        with consume(target, 'test-revision', operations):
            pytest.fail('restore must not start')
    assert target.exists()

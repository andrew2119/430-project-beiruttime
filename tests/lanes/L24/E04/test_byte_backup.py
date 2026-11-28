"""Byte representation checks without a running service."""
import stat

import pytest

from byte_backup import ByteBackupError, export_bytes, restore_bytes
from restore import digest


def fact(**changes):
    return dict(operation_id='test-operation', file_id='test-file', current=True,
                tombstoned=False, checksum=digest(b'test-bytes'), size=10,
                **changes)


def test_bytes_are_private_and_current_deletion_suppresses_old_backup(tmp_path):
    source = tmp_path / 'backup'
    manifest = export_bytes([{**fact(), 'content': b'test-bytes'}], source)
    assert 'content' not in manifest[0]
    assert stat.S_IMODE(source.stat().st_mode) == 0o700
    assert stat.S_IMODE((source / 'test-file').stat().st_mode) == 0o600
    result = restore_bytes(manifest, [{**fact(), 'tombstoned': True}], source,
                           tmp_path / 'restore')
    assert result == {'restored': [], 'redacted': ['test-file']}
    assert list((tmp_path / 'restore').iterdir()) == []


def test_unchanged_bytes_restore(tmp_path):
    source = tmp_path / 'backup'
    manifest = export_bytes([{**fact(), 'content': b'test-bytes'}], source)
    result = restore_bytes(manifest, [fact()], source, tmp_path / 'restore')
    assert result == {'restored': ['test-file'], 'redacted': []}
    assert (tmp_path / 'restore/test-file').read_bytes() == b'test-bytes'


@pytest.mark.parametrize('change', [
    {'current': False}, {'operation_id': 'test-other'}, {'checksum': digest(b'test-other')},
    {'size': 11}, {'tombstoned': 'yes'},
])
def test_denied_stale_and_mismatched_authority_exposes_no_bytes(tmp_path, change):
    source = tmp_path / 'backup'
    manifest = export_bytes([{**fact(), 'content': b'test-bytes'}], source)
    with pytest.raises(ByteBackupError):
        restore_bytes(manifest, [{**fact(), **change}], source, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


@pytest.mark.parametrize('damage', ['missing', 'checksum', 'duplicate', 'absent'])
def test_damaged_or_missing_files_and_authority_fail_closed(tmp_path, damage):
    source = tmp_path / 'backup'
    manifest = export_bytes([{**fact(), 'content': b'test-bytes'}], source)
    current = [fact()]
    if damage == 'missing':
        (source / 'test-file').unlink()
    elif damage == 'checksum':
        (source / 'test-file').write_bytes(b'test-wrong')
    elif damage == 'duplicate':
        current *= 2
    else:
        current = []
    with pytest.raises(ByteBackupError):
        restore_bytes(manifest, current, source, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


def test_export_rejects_unbound_bytes_and_removes_partial_output(tmp_path):
    with pytest.raises(ByteBackupError, match='integrity'):
        export_bytes([{**fact(), 'content': b'test-wrong'}], tmp_path / 'backup')
    assert not (tmp_path / 'backup').exists()


def test_connected_export_requires_actual_requested_operation(tmp_path):
    from connected import CapabilityError, export_producer_bytes

    specification = {'operation_ids': ['test-other']}
    with pytest.raises(CapabilityError, match='provenance'):
        export_producer_bytes([{**fact(), 'content': b'test-bytes'}], specification,
                              tmp_path / 'backup')
    assert not (tmp_path / 'backup').exists()

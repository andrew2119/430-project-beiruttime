"""Private byte snapshots; current producer authority always precedes restoration."""
import os
from pathlib import Path

from restore import CONTRACT, digest


class ByteBackupError(ValueError):
    pass


def metadata(rows):
    rows = list(rows)
    if not rows or len(rows) > CONTRACT['limits']['files']:
        raise ByteBackupError('file_bounds')
    result = {}
    for row in rows:
        name = row['file_id']
        if (not isinstance(name, str) or not name or Path(name).name != name
                or name in ('.', '..') or name in result):
            raise ByteBackupError('file_identity')
        if (row.get('current') is not True or type(row.get('tombstoned')) is not bool
                or not isinstance(row.get('operation_id'), str) or not row['operation_id']
                or type(row.get('size')) is not int
                or not 0 <= row['size'] <= CONTRACT['limits']['file_bytes']
                or not isinstance(row.get('checksum'), str)
                or len(row['checksum']) != 64
                or any(c not in '0123456789abcdef' for c in row['checksum'])):
            raise ByteBackupError('current_file_facts')
        result[name] = dict(row)
    return result


def private_directory(path):
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def write_private(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)


def export_bytes(rows, target):
    """Rows and content must come from the same producer snapshot transaction."""
    facts = metadata(rows)
    private_directory(target)
    manifest = []
    try:
        for name, row in facts.items():
            content = row.pop('content', None)
            if not row['tombstoned']:
                if not isinstance(content, (bytes, memoryview)):
                    raise ByteBackupError('missing_file')
                content = bytes(content)
                if len(content) != row['size'] or digest(content) != row['checksum']:
                    raise ByteBackupError('file_integrity')
                write_private(target / name, content)
            manifest.append(row)
    except BaseException:
        for path in target.iterdir():
            path.unlink()
        target.rmdir()
        raise
    return manifest


def restore_bytes(manifest, current_rows, source, target):
    """Missing authority fails closed; current deletion wins over older bytes."""
    saved = metadata(manifest)
    current = metadata(current_rows)
    if set(saved) != set(current):
        raise ByteBackupError('missing_current_file_facts')
    permitted = []
    for name, old in saved.items():
        now = current[name]
        if old['operation_id'] != now['operation_id']:
            raise ByteBackupError('file_provenance_mismatch')
        if now['tombstoned']:
            continue
        if old['tombstoned'] or any(old[k] != now[k] for k in ('checksum', 'size')):
            raise ByteBackupError('stale_file_facts')
        path = source / name
        if source.is_symlink() or path.is_symlink() or not path.is_file():
            raise ByteBackupError('missing_file')
        if path.stat().st_size != old['size']:
            raise ByteBackupError('file_integrity')
        content = path.read_bytes()
        if digest(content) != old['checksum']:
            raise ByteBackupError('file_integrity')
        permitted.append({**now, 'content': content})
    # Validate every byte before exposing even a private partial destination.
    private_directory(target)
    try:
        for row in permitted:
            write_private(target / row['file_id'], row['content'])
    except BaseException:
        for path in target.iterdir():
            path.unlink()
        target.rmdir()
        raise
    return {'restored': sorted(row['file_id'] for row in permitted),
            'redacted': sorted(name for name in saved if current[name]['tombstoned'])}

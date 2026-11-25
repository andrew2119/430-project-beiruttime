"""Private, versioned dump handoff; preparation alone is never restore proof."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from fixtures import DOMAINS
from privacy_watermarks import validate


class HandoffError(ValueError):
    pass


def file_hash(path):
    if path.is_symlink() or not path.is_file():
        raise HandoffError('backup_file_unavailable')
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def private_file(path):
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise HandoffError('backup_file_permissions')


def publish(target, work, record, operations, files):
    """Publish only completed backups. Never retain cluster credentials or logs."""
    watermarks = validate(record.get('privacy_watermarks'), operations)
    target = Path(target)
    target.mkdir(mode=0o700)
    try:
        manifest = {'schema_version': 2, 'source_revision': record['source_revision'],
                    'acknowledged_operations': operations, 'domains': {}, 'files': files,
                    'privacy_watermarks': watermarks}
        for domain in DOMAINS:
            source = work / (domain + '.dump')
            destination = target / source.name
            with source.open('rb') as incoming, destination.open('xb') as outgoing:
                os.chmod(destination, 0o600)
                shutil.copyfileobj(incoming, outgoing)
            tables = record['databases'][domain]
            schema = {name: value for name, value in tables.items() if 'migration_ledger' in name}
            if not schema:
                raise HandoffError('backup_schema_revision_missing')
            manifest['domains'][domain] = {'sha256': file_hash(destination),
                                           'schema_revision': schema, 'inventory': tables}
        byte_source = work / 'backup-files'
        byte_target = target / 'backup-files'
        byte_target.mkdir(mode=0o700)
        for row in files:
            if not row['tombstoned']:
                destination = byte_target / row['file_id']
                with (byte_source / row['file_id']).open('rb') as incoming, destination.open('xb') as outgoing:
                    os.chmod(destination, 0o600)
                    shutil.copyfileobj(incoming, outgoing)
        descriptor = os.open(target / 'manifest.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(manifest, stream, sort_keys=True)
    except BaseException:
        shutil.rmtree(target)
        raise


def load(target, revision, operations):
    target = Path(target)
    if target.is_symlink() or stat.S_IMODE(target.stat().st_mode) != 0o700:
        raise HandoffError('backup_directory_permissions')
    path = target / 'manifest.json'
    private_file(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise HandoffError('backup_manifest_bounds')
    manifest = json.loads(path.read_text())
    if (manifest.get('schema_version') != 2 or manifest.get('source_revision') != revision
            or manifest.get('acknowledged_operations') != operations
            or set(manifest.get('domains', {})) != set(DOMAINS)):
        raise HandoffError('backup_provenance_mismatch')
    validate(manifest.get('privacy_watermarks'), operations)
    for domain, facts in manifest['domains'].items():
        dump = target / (domain + '.dump')
        private_file(dump)
        schema = {name: value for name, value in facts['inventory'].items() if 'migration_ledger' in name}
        if (not schema or facts.get('schema_revision') != schema
                or file_hash(dump) != facts['sha256']):
            raise HandoffError('backup_integrity')
    return manifest


@contextmanager
def consume(target, revision, operations):
    """A rehearsal consumes its retained private artifacts, including on failure."""
    manifest = load(target, revision, operations)
    try:
        yield manifest
    finally:
        shutil.rmtree(target)


@contextmanager
def workspace(run, backup, revision, operations):
    if backup is None:
        with tempfile.TemporaryDirectory(prefix='e04-', dir=run) as temporary:
            yield Path(temporary), None
    else:
        with consume(backup, revision, operations) as manifest:
            with tempfile.TemporaryDirectory(prefix='e04-', dir=run) as temporary:
                yield Path(temporary), manifest

"""Refresh private restored rows from fixed current Identity relations."""
from contextlib import AsyncExitStack
from hashlib import sha256


# Keys are fixed by the published migrations, never by run input.
RELATIONS = {
    'identity_private_evidence': ('id',),
    'identity_l19_possession_photos': ('id',),
    'l02_listing_reviews': ('listing_id',),
    'identity_private_assignments': ('application_id', 'reviewer_id'),
    'identity_access_grants': ('id',),
    # Remove dependent credentials before a missing session. Current consumption
    # and expiry facts must also replace those in an older backup.
    'identity_refresh_tokens': ('hash',),
    'identity_reauth_proofs': ('hash',),
    'identity_password_resets': ('hash',),
    'identity_sessions': ('id',),
    'identity_accounts': ('id',),
}
BYTE_COLUMNS = {'identity_private_evidence': 'content',
                'identity_l19_possession_photos': 'content',
                'l02_listing_reviews': 'photo'}
ROW_LIMIT = 1000


def verify_retained_bytes(table, old, current):
    column = BYTE_COLUMNS.get(table)
    if column is None or current.get(column) is None:
        return
    saved, retained = old.get(column), current[column]
    if (not isinstance(saved, (bytes, memoryview))
            or not isinstance(retained, (bytes, memoryview))
            or len(saved) != len(retained)
            or sha256(saved).digest() != sha256(retained).digest()
            or (table == 'identity_private_evidence'
                and current.get('sha256') != sha256(saved).hexdigest())):
        raise AuthorityError('restored_byte_integrity')


class AuthorityError(RuntimeError):
    pass


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


async def reconcile_identity(source, destination):
    """No private restored row is read until current authority is available.

    Missing current rows are removed, including physically deleted photos.
    Retained bytes must match current checksum and size before any replacement.
    Existing rows receive measured current authority and explicit redactions.
    New grants or evidence are never imported into an older backup.
    Both snapshots remain private and the destination changes atomically.
    Authentication rows include current account status, password and access
    revision, session revocations, and consumed one-time credentials.
    This does not replace durable producer deletion receipts or retention work.
    """
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(source.transaction(isolation='repeatable_read', readonly=True))
        await stack.enter_async_context(destination.transaction())
        facts = {}
        for table, keys in RELATIONS.items():
            rows = await source.fetch('SELECT * FROM ' + quoted(table) + ' LIMIT 1001')
            if len(rows) > ROW_LIMIT:
                raise AuthorityError('current_authority_bounds')
            current = {}
            for row in rows:
                key = tuple(row[column] for column in keys)
                if key in current or any(value is None for value in key):
                    raise AuthorityError('current_authority_identity')
                current[key] = dict(row)
            facts[table] = current
        result = {}
        for table, keys in RELATIONS.items():
            old = await destination.fetch('SELECT * FROM ' + quoted(table) + ' LIMIT 1001')
            if len(old) > ROW_LIMIT:
                raise AuthorityError('restored_authority_bounds')
            removed = refreshed = 0
            expected = {}
            for row in old:
                key = tuple(row[column] for column in keys)
                where = ' AND '.join(quoted(column) + '=$' + str(index + 1)
                                     for index, column in enumerate(keys))
                current = facts[table].get(key)
                if current is None:
                    await destination.execute('DELETE FROM ' + quoted(table) + ' WHERE ' + where, *key)
                    removed += 1
                else:
                    verify_retained_bytes(table, row, current)
                    expected[key] = current
                    columns = [column for column in current if column not in keys]
                    assignments = ','.join(quoted(column) + '=$' + str(len(keys) + index + 1)
                                           for index, column in enumerate(columns))
                    await destination.execute('UPDATE ' + quoted(table) + ' SET ' + assignments
                                              + ' WHERE ' + where,
                                              *key, *(current[column] for column in columns))
                    refreshed += 1
            actual = await destination.fetch('SELECT * FROM ' + quoted(table) + ' LIMIT 1001')
            if ({tuple(row[column] for column in keys): dict(row) for row in actual}
                    != expected or len(actual) != len(expected)):
                raise AuthorityError('restored_authority_mismatch')
            result[table] = {'removed': removed, 'refreshed': refreshed}
        return result


def check_unaffected(before, after):
    """Only the fixed private relations may differ after authority refresh."""
    allowed = {'"public".' + quoted(table) for table in RELATIONS}
    if set(before) != set(after) or any(before[key] != after[key]
                                      for key in before if key not in allowed):
        raise AuthorityError('unaffected_rows_mismatch')

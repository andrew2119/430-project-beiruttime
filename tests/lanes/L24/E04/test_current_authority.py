"""Current private authority precedes restored content reads."""
from contextlib import asynccontextmanager

import pytest
from hashlib import sha256

from current_authority import AuthorityError, RELATIONS, check_unaffected, reconcile_identity


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.commands = []
        self.active = False

    @asynccontextmanager
    async def transaction(self, **options):
        self.active = True
        try:
            yield
        finally:
            self.active = False

    async def fetch(self, query):
        assert self.active
        table = query.split(' FROM "')[1].split('"')[0]
        if query.startswith('SELECT *'):
            return self.rows.get(table, [])
        keys = RELATIONS[table]
        return [{key: row[key] for key in keys} for row in self.rows.get(table, [])]

    async def execute(self, query, *values):
        assert self.active
        self.commands.append((query, values))
        table = query.split('"')[1]
        keys = RELATIONS[table]
        rows = self.rows.get(table, [])
        matches = [row for row in rows if tuple(row[key] for key in keys) == values[:len(keys)]]
        if query.startswith('DELETE'):
            self.rows[table] = [row for row in rows if row not in matches]
        else:
            columns = [part.split('"')[1] for part in query.split(' SET ')[1].split(' WHERE ')[0].split(',')]
            for row in matches:
                row.update(zip(columns, values[len(keys):]))


@pytest.mark.asyncio
async def test_current_deletion_bytes_and_revocation_precede_reads():
    source = Connection({
        'identity_private_evidence': [{'id': 'test-kept', 'content': b'test-current',
                                      'sha256': sha256(b'test-current').hexdigest()}],
        'identity_access_grants': [{'id': 'test-grant', 'revoked_at': 'test-revoked'}],
    })
    destination = Connection({
        'identity_private_evidence': [{'id': 'test-kept', 'content': b'test-current'},
                                      {'id': 'test-removed'}],
        'identity_access_grants': [{'id': 'test-grant'}, {'id': 'test-missing'}],
    })
    result = await reconcile_identity(source, destination)
    assert result['identity_private_evidence'] == {'removed': 1, 'refreshed': 1}
    assert result['identity_access_grants'] == {'removed': 1, 'refreshed': 1}
    assert destination.commands == [
        ('UPDATE "identity_private_evidence" SET "content"=$2,"sha256"=$3 WHERE "id"=$1',
         ('test-kept', b'test-current', sha256(b'test-current').hexdigest())),
        ('DELETE FROM "identity_private_evidence" WHERE "id"=$1', ('test-removed',)),
        ('UPDATE "identity_access_grants" SET "revoked_at"=$2 WHERE "id"=$1',
         ('test-grant', 'test-revoked')),
        ('DELETE FROM "identity_access_grants" WHERE "id"=$1', ('test-missing',)),
    ]


@pytest.mark.asyncio
async def test_new_current_grants_are_not_added_to_old_backup():
    source = Connection({'identity_access_grants': [{'id': 'test-new', 'revoked_at': None}]})
    destination = Connection({})
    await reconcile_identity(source, destination)
    assert destination.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize('rows', [
    [{'id': 'test-duplicate'}] * 2,
    [{'id': None}],
    [{'id': str(index)} for index in range(1001)],
])
async def test_bad_current_authority_prevents_all_destination_changes(rows):
    source = Connection({'identity_access_grants': rows})
    destination = Connection({'identity_private_evidence': [{'id': 'test-old'}]})
    with pytest.raises(AuthorityError):
        await reconcile_identity(source, destination)
    assert destination.commands == []


@pytest.mark.asyncio
async def test_unavailable_source_prevents_old_content_reads():
    class Unavailable(Connection):
        async def fetch(self, query):
            raise ConnectionError('test-unavailable')

    destination = Connection({'identity_private_evidence': [{'id': 'test-old'}]})
    with pytest.raises(ConnectionError):
        await reconcile_identity(Unavailable({}), destination)
    assert destination.commands == []


def test_unaffected_digests_must_match():
    before = {'"public"."identity_private_evidence"': 'test-old',
              '"public"."orders"': 'test-original'}
    check_unaffected(before, {**before, '"public"."identity_private_evidence"': 'test-redacted'})
    with pytest.raises(AuthorityError, match='unaffected'):
        check_unaffected(before, {**before, '"public"."orders"': 'test-changed'})
    with pytest.raises(AuthorityError):
        check_unaffected(before, {})


@pytest.mark.asyncio
async def test_authentication_authority_replaces_old_backup_and_removes_credentials():
    source = Connection({
        'identity_accounts': [{'id': 'test-account', 'status': 'suspended',
                               'access_revision': 7, 'password_hash': 'test-current-password'}],
        'identity_sessions': [{'id': 'test-session', 'revoked_at': 'test-revoked'}],
        'identity_refresh_tokens': [{'hash': 'test-refresh', 'consumed_at': 'test-consumed'}],
        'identity_password_resets': [{'hash': 'test-reset', 'consumed_at': 'test-consumed'}],
    })
    destination = Connection({
        'identity_accounts': [{'id': 'test-account'}],
        'identity_sessions': [{'id': 'test-session'}, {'id': 'test-removed-session'}],
        'identity_refresh_tokens': [{'hash': 'test-refresh'}, {'hash': 'test-removed-refresh'}],
        'identity_reauth_proofs': [{'hash': 'test-removed-proof'}],
        'identity_password_resets': [{'hash': 'test-reset'}],
    })
    result = await reconcile_identity(source, destination)
    assert result['identity_sessions'] == {'removed': 1, 'refreshed': 1}
    assert result['identity_reauth_proofs'] == {'removed': 1, 'refreshed': 0}
    assert destination.commands[-1] == (
        'UPDATE "identity_accounts" SET "status"=$2,"access_revision"=$3,"password_hash"=$4 WHERE "id"=$1',
        ('test-account', 'suspended', 7, 'test-current-password'))
    assert ('UPDATE "identity_sessions" SET "revoked_at"=$2 WHERE "id"=$1',
            ('test-session', 'test-revoked')) in destination.commands
    assert ('UPDATE "identity_refresh_tokens" SET "consumed_at"=$2 WHERE "hash"=$1',
            ('test-refresh', 'test-consumed')) in destination.commands
    commands = [query for query, _ in destination.commands]
    assert commands.index('DELETE FROM "identity_reauth_proofs" WHERE "hash"=$1') < commands.index(
        'DELETE FROM "identity_sessions" WHERE "id"=$1')
    assert ('UPDATE "identity_password_resets" SET "consumed_at"=$2 WHERE "hash"=$1',
            ('test-reset', 'test-consumed')) in destination.commands


def test_authentication_redactions_are_allowed_but_other_tables_are_preserved():
    before = {'"public"."' + table + '"': 'test-old' for table in RELATIONS}
    before['"public"."identity_security_audit"'] = 'test-audit'
    after = {key: 'test-current' for key in before}
    after['"public"."identity_security_audit"'] = 'test-audit'
    check_unaffected(before, after)
    after['"public"."identity_security_audit"'] = 'test-changed'
    with pytest.raises(AuthorityError, match='unaffected'):
        check_unaffected(before, after)


@pytest.mark.asyncio
@pytest.mark.parametrize('table,column', [
    ('identity_private_evidence', 'content'),
    ('identity_l19_possession_photos', 'content'),
    ('l02_listing_reviews', 'photo'),
])
@pytest.mark.parametrize('saved', [None, b'test-damaged', b'test-short'])
async def test_retained_bytes_cannot_be_repaired_from_source(table, column, saved):
    keys = {'listing_id': 'test-row'} if column == 'photo' else {'id': 'test-row'}
    current = {**keys, column: b'test-current', 'sha256': sha256(b'test-current').hexdigest()}
    destination = Connection({table: [{**keys, column: saved}]})
    with pytest.raises(AuthorityError, match='byte_integrity'):
        await reconcile_identity(Connection({table: [current]}), destination)
    assert destination.commands == []


@pytest.mark.asyncio
async def test_explicit_photo_redaction_is_permitted():
    source = Connection({'l02_listing_reviews': [{'listing_id': 'test-row', 'photo': None}]})
    destination = Connection({'l02_listing_reviews': [
        {'listing_id': 'test-row', 'photo': b'test-old'}]})
    await reconcile_identity(source, destination)
    assert destination.rows['l02_listing_reviews'][0]['photo'] is None


@pytest.mark.asyncio
async def test_unexpected_authority_row_change_is_rejected():
    class CorruptDestination(Connection):
        async def execute(self, query, *values):
            await super().execute(query, *values)
            self.rows['identity_access_grants'][0]['unexpected'] = 'test-corruption'

    source = Connection({'identity_access_grants': [{'id': 'test-row', 'revoked_at': None}]})
    destination = CorruptDestination({'identity_access_grants': [{'id': 'test-row'}]})
    with pytest.raises(AuthorityError, match='authority_mismatch'):
        await reconcile_identity(source, destination)

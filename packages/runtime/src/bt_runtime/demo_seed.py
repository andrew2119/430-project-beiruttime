"""Deploy-applied demonstration seed: made-up sample accounts, sample businesses and drafts, off unless opted in.

It runs after migrations inside each service's existing pre-deploy step. Each service writes only its own
database through the `deploy-seed` entry of its own modules. Every row the seed inserts is entered, in the
same transaction, in `demo_seed_rows`, the seed's ownership record, which the runtime role can read but never
write. A pinned id or address that exists without an entry there belongs to someone else: the seed logs one
line and never updates it, attaches anything to it or syncs it. With `BT_DEMO_SEED=remove-sample-accounts`
the same step deletes exactly the recorded rows and nothing else, keeping any row that later activity refers to,
that a live writer holds, or that is no longer the row the seed inserted.
Catalog admits a sample draft only for the exact owner account and business named in Identity's latest signed
handoff, and only while it is fresh: Identity's seed sends one on every run, after its own rows have committed,
saying whether it still vouches for them, and its removal withdraws them. Each handoff carries an assertion
signed with a key pair of its own that only Identity's seed holds, and Catalog's owner-run seed step verifies it
before it writes anything; the latest is decided by Identity's own order, never by a clock.
Seed accounts are password-free by class: the accounts module refuses password sign-in, recovery and reset
for any account in the record.
Its only access grant is each set's sample staff membership of that set's own sample business, written by
the app's own membership grant code; it never grants operator power, never assigns a reviewer and never
records a review decision.
The seed is best-effort and time-bounded: it never waits for a lock it can skip, it gives up at its total
budget, and a failure is reported in the deploy log without failing or holding up the deploy. The pre-deploy
step runs it in a separately supervised child process with a hard deadline (`demo_seed_deadline`).
"""
import asyncio
import concurrent.futures
import contextlib
import inspect
import json
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import asyncpg
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from bt_contracts_core.models import EventEnvelope

from .demo_seed_deadline import SWITCH
from .modules import discover

SWITCH_VALUE = 'sample-accounts-only'
REMOVE_VALUE = 'remove-sample-accounts'
ENTRY = 'deploy-seed'
LEDGER = 'demo_seed_rows'
# Seeded audit rows and outbox events carry this request id instead of an HTTP request's.
REQUEST_ID = 'demo-seed-v1'
REQUEST = SimpleNamespace(state=SimpleNamespace(request_id=REQUEST_ID))
NAMESPACE = uuid5(NAMESPACE_URL, 'urn:beirut-time:demo-seed:v1')
# Recorded as the actor on the sample business and membership history: the deploy, never an account.
ACTOR_KEY = 'DEMO-SEED-ACTOR-DEPLOY'

# Cooperative time budget of one service's seed, inside the hard deadline of demo_seed_deadline.
CONNECT_SECONDS = 5
LOCK_MS = 2000
STATEMENT_MS = 5000
IDLE_MS = 10000
TOTAL_SECONDS = 30
CLOSE_SECONDS = 2
# How soon a seed backend whose process was killed notices, even in the middle of a statement.
CHECK_INTERVAL = '1s'
# Fixed output formats, so a row's recorded creation time or text reads the same at seed and at removal.
FORMATS = {'TimeZone': 'UTC', 'DateStyle': 'ISO, YMD', 'IntervalStyle': 'postgres', 'bytea_output': 'hex',
           'extra_float_digits': '1'}

# Two independent copies of the storyline: Sunday's click test uses up one-shot states
# (approval, publish, auction, Buy Now, report decision) without touching Tuesday's.
SETS = ('demo', 'click-test')
# buyer and rival buy and bid as every active account can; operator is a plain account the seed never
# gives operator power; staff belongs to its set's own sample business, the one grant the seed makes.
ROLES = ('buyer', 'seller', 'rival', 'operator', 'staff')
# Made-up people with ordinary Lebanese names; the ownership record, not the name, marks a seed row.
PEOPLE = {
    'demo': {'buyer': 'Karim Nassar', 'seller': 'Lina Saab', 'rival': 'Ziad Mansour',
             'operator': 'Nour Bitar', 'staff': 'Elie Daher'},
    'click-test': {'buyer': 'Rania Moussa', 'seller': 'Fadi Najjar', 'rival': 'Hiba Tannous',
                   'operator': 'Samir Azar', 'staff': 'Joelle Ghanem'},
}
# Made-up shop names; each row is also marked sample=true and created by the seed's actor.
BUSINESS_NAMES = {'demo': 'Zayzafoun Watch House', 'click-test': 'Sanawbar Watch House'}
# What that staff membership may do: save, open and publish the business's stock and read its records.
STAFF_CAPABILITIES = ('business.stock.write', 'business.records.read')
LISTINGS = {'auction': 'private', 'buy-now': 'dealer', 'spare': 'dealer'}
# The one cross-service step. Identity's last seed step sends Catalog one signed event per set and holder on
# every run, through Identity's own outbox and relay to Catalog's event ingress, after Identity's seed has
# inserted, recorded and committed that set's seller account, or its staff account with that staff's own
# business, membership and grant. Catalog's seed admits a draft, or attaches its photo, only for exactly the ids
# the latest such handoff names.
HANDOFF_TYPE = 'identity.demo-seed.handoff.v1'
HANDOFF_DESTINATION = 'catalog-demo-seed'
HANDOFF_AUDIENCE = 'catalog'
HOLDERS = {'private': 'seller', 'dealer': 'staff'}
# Each handoff says whether Identity's seed vouches for its holder now ('ready') or no longer ('withdrawn').
# Catalog acts only on the latest one by Identity's producer order (seq, from an Identity sequence only its seed
# draws), and only while that one was issued at most HANDOFF_FRESH_SECONDS ago, allowing HANDOFF_SKEW_SECONDS
# of clock difference between the two services: order decides which is current, issue time only freshness.
HANDOFF_STATES = ('ready', 'withdrawn')
HANDOFF_FRESH_SECONDS = 1800
HANDOFF_SKEW_SECONDS = 120
# The handoff fields Identity signs, besides the event id, seq and issue time.
HANDOFF_FIELDS = ('sample_set', 'holder', 'subject_id', 'business_id', 'state')
# Each handoff carries an RS256 assertion over exactly its fields, signed with a disposable key pair used for
# nothing else. Only Identity holds the private half; only Catalog holds the public half. It must never be the
# pair of the service tokens: Catalog's running app holds a service signing key, so a token or receipt that
# app could sign proves nothing. Throwaway demo environment only, like the switch.
HANDOFF_PRIVATE_KEY = 'BT_DEMO_SEED_HANDOFF_PRIVATE_KEY'
HANDOFF_PUBLIC_KEY = 'BT_DEMO_SEED_HANDOFF_PUBLIC_KEY'
HANDOFF_ISSUER = 'identity'
HANDOFF_ASSERTION_AUDIENCE = 'catalog.demo-seed'
HANDOFF_ASSERTION_TYPE = 'demo-seed-handoff'
HANDOFF_CLAIMS = ('iss', 'aud', 'type', 'event_id', 'seq', *HANDOFF_FIELDS, 'issued_us')
HANDOFF_ASSERTION_LIMIT = 4096
# Identity's producer order and Catalog's per-holder lock (see holder_lock).
HANDOFF_SEQUENCE = 'demo_seed_handoff_seq'
# A module's optional removal step, run first inside the removal's own transaction (Identity's withdrawals).
REMOVE_ENTRY = 'deploy-remove'
# The roles the sample sign-in may sign in; the Operator tab is its own separately reviewed link (decision 252).
SIGN_IN_ROLES = ('buyer', 'seller', 'rival', 'staff')


def demo_key(sample_set: str, kind: str, item: str) -> str:
    return f'DEMO-SEED-{sample_set}-{kind}-{item}'.upper()


def seed_id(key: str) -> UUID:
    """Public and deterministic: derived from strings in this repository, never a secret."""
    return uuid5(NAMESPACE, key)


ACTOR = seed_id(ACTOR_KEY)


@dataclass(frozen=True)
class Account:
    sample_set: str
    role: str
    key: str
    id: UUID
    email: str
    display_name: str


@dataclass(frozen=True)
class Business:
    sample_set: str
    key: str
    id: UUID
    public_name: str
    membership_key: str
    membership_id: UUID


@dataclass(frozen=True)
class Listing:
    sample_set: str
    item: str
    seller: str
    key: str
    id: UUID
    watch_id: UUID
    photo_id: UUID


def accounts(role: str | None = None) -> list[Account]:
    found = []
    for sample_set in SETS:
        for name in ROLES:
            if role is None or role == name:
                key = demo_key(sample_set, 'account', name)
                found.append(Account(sample_set, name, key, seed_id(key), f'{name}.{sample_set}@example.test',
                                     PEOPLE[sample_set][name]))
    return found


def account(sample_set: str, role: str) -> Account:
    return next(item for item in accounts(role) if item.sample_set == sample_set)


def businesses() -> list[Business]:
    found = []
    for sample_set in SETS:
        key = demo_key(sample_set, 'business', 'dealer')
        membership = demo_key(sample_set, 'membership', 'staff')
        found.append(Business(sample_set, key, seed_id(key), BUSINESS_NAMES[sample_set], membership,
                              seed_id(membership)))
    return found


def business(sample_set: str) -> Business:
    return next(item for item in businesses() if item.sample_set == sample_set)


def listings() -> list[Listing]:
    found = []
    for sample_set in SETS:
        for item, seller in LISTINGS.items():
            key = demo_key(sample_set, 'listing', item)
            found.append(Listing(sample_set, item, seller, key, seed_id(key), seed_id(key + ':watch'),
                                 seed_id(key + ':photo')))
    return found


def handoff_key(sample_set: str, holder: str) -> str:
    return demo_key(sample_set, 'handoff', holder)


def handoff_ids(sample_set: str, holder: str) -> tuple[UUID, UUID | None]:
    """The account, and for staff the business, that one set's handoff vouches for."""
    subject = account(sample_set, holder).id
    return subject, business(sample_set).id if holder == 'staff' else None


def handoff_data(sample_set: str, holder: str, state: str) -> dict:
    if state not in HANDOFF_STATES:
        raise ValueError('A handoff is ready or withdrawn')
    subject, organization = handoff_ids(sample_set, holder)
    return {'sample_set': sample_set, 'holder': holder, 'subject_id': str(subject),
            'business_id': None if organization is None else str(organization), 'state': state}


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def issued_us(issued: datetime) -> int:
    """A handoff's issue time as whole microseconds since the epoch, exactly, as Identity signs it."""
    return (issued - EPOCH) // timedelta(microseconds=1)


def handoff_claims(event_id, seq: int, data: dict, issued: datetime) -> dict:
    """The exact claims of one handoff's assertion: its event id, Identity's order, its fields and issue time."""
    return {'iss': HANDOFF_ISSUER, 'aud': HANDOFF_ASSERTION_AUDIENCE, 'type': HANDOFF_ASSERTION_TYPE,
            'event_id': str(event_id), 'seq': seq, **{name: data[name] for name in HANDOFF_FIELDS},
            'issued_us': issued_us(issued)}


def pem(value: str | None) -> str:
    return (value or '').replace('\\n', '\n').strip()


def public_numbers(value: str, private: bool):
    """The public numbers of a PEM key, or None when it is not one this process can read."""
    try:
        if private:
            return serialization.load_pem_private_key(value.encode(), None).public_key().public_numbers()
        return serialization.load_pem_public_key(value.encode()).public_numbers()
    except (ValueError, TypeError, AttributeError, UnsupportedAlgorithm):
        return None


def other_keys(env, skip: tuple[str, ...]) -> list:
    """The RSA public numbers of every BT_*_PRIVATE_KEY and BT_*_PUBLIC_KEY this process holds, but `skip`."""
    found = []
    for name, value in env.items():
        if name in skip or not name.startswith('BT_') or not pem(value):
            continue
        if name.endswith('_PRIVATE_KEY'):
            found.append(public_numbers(pem(value), True))
        elif name.endswith('_PUBLIC_KEY'):
            found.append(public_numbers(pem(value), False))
    return [numbers for numbers in found if numbers is not None]


class HandoffKey(Exception):
    """The handoff key pair is set wrongly: not RSA, held where it must not be, or the pair of another key."""


def handoff_signing_key(environ=None) -> str | None:
    """Identity's handoff signing key, or None when the throwaway environment did not set one (nothing is sent).

    It refuses (HandoffKey) a key that is not an RSA private key, or whose pair is any other key Identity holds,
    its event and token keys and the service verifying key among them: such an assertion would be no stronger
    than the service token beside it.
    """
    env = os.environ if environ is None else environ
    value = pem(env.get(HANDOFF_PRIVATE_KEY))
    if not value:
        return None
    numbers = public_numbers(value, True)
    if numbers is None or numbers in other_keys(env, (HANDOFF_PRIVATE_KEY, HANDOFF_PUBLIC_KEY)):
        raise HandoffKey(HANDOFF_PRIVATE_KEY)
    return value


def handoff_verifying_key(environ=None) -> str:
    """Catalog's handoff verifying key; HandoffKey when it is missing, not an RSA public key, the pair of any
    other key Catalog holds (its service signing key among them), or when Catalog also holds the private half."""
    env = os.environ if environ is None else environ
    value = pem(env.get(HANDOFF_PUBLIC_KEY))
    numbers = public_numbers(value, False) if value else None
    if numbers is None or pem(env.get(HANDOFF_PRIVATE_KEY)) or numbers in other_keys(env, (HANDOFF_PUBLIC_KEY,)):
        raise HandoffKey(HANDOFF_PUBLIC_KEY)
    return value


def sign_handoff(key: str, event_id, seq: int, data: dict, issued: datetime) -> str:
    return jwt.encode(handoff_claims(event_id, seq, data, issued), key, algorithm='RS256')


def verify_handoff(key: str, assertion, event_id, seq: int, data: dict, issued: datetime) -> bool:
    """Whether `assertion` is Identity's handoff signature over exactly this event id, order, fields and time."""
    if not isinstance(assertion, str) or len(assertion) > HANDOFF_ASSERTION_LIMIT:
        return False
    try:
        # A null business id never counts as present, so presence is checked by the exact comparison below.
        claims = jwt.decode(assertion, key, algorithms=['RS256'], issuer=HANDOFF_ISSUER,
                            audience=HANDOFF_ASSERTION_AUDIENCE,
                            options={'require': [name for name in HANDOFF_CLAIMS if name != 'business_id']})
    except jwt.InvalidTokenError:
        return False
    return claims == handoff_claims(event_id, seq, data, issued)


def handoff_event(key: str, sample_set: str, holder: str, state: str, seq: int, *, event_id=None,
                  issued: datetime | None = None) -> EventEnvelope:
    """One handoff as Identity's seed enqueues it: its fields, Identity's order (seq) and the signed assertion."""
    data = handoff_data(sample_set, holder, state)
    event_id = uuid4() if event_id is None else event_id
    issued = datetime.now(timezone.utc) if issued is None else issued
    return EventEnvelope(id=event_id, time=issued, type=HANDOFF_TYPE, source='identity',
                         subject=data['subject_id'], request_id=REQUEST_ID,
                         data={**data, 'seq': seq, 'assertion': sign_handoff(key, event_id, seq, data, issued)})


def holder_lock(sample_set: str, holder: str) -> str:
    """One holder's lock in Catalog. Its receipt function and its seed steps each take it without waiting and
    hold it to commit, so a receipt never arrives between a step's handoff check and its write."""
    return f'demo-seed-handoff:{sample_set}:{holder}'


def mode(environ=None) -> str | None:
    """'seed' or 'remove' for the two documented values; anything else, unset included, does nothing."""
    value = (os.environ if environ is None else environ).get(SWITCH, '')
    return {SWITCH_VALUE: 'seed', REMOVE_VALUE: 'remove'}.get(value)


def enabled(environ=None) -> bool:
    return mode(environ) == 'seed'


def report(scope: str, message: str) -> None:
    # Counts, public demo keys and error classes only: never an address, a key value or a row.
    # A closed or broken log loses the line; it never raises into the seed.
    if sys.stderr is not None:
        with contextlib.suppress(OSError, ValueError):
            print(f'DEMO SEED {scope}: {message}', file=sys.stderr, flush=True)


def summary(result) -> str:
    if isinstance(result, dict) and result:
        return ' '.join(f'{name}={result[name]}' for name in sorted(result))
    return 'done'


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_name(table: str) -> str:
    if not re.fullmatch(r'[a-z][a-z0-9_]*', table):
        raise ValueError('Seed tables are plain lower-case names')
    return quote(table)


def row_key(row: dict) -> str:
    """The recorded primary key of one row: each key column's value as text, in stable JSON."""
    return json.dumps({name: str(value) for name, value in row.items()}, sort_keys=True)


def written_here(alias: str = '') -> str:
    """SQL that is true only for a row version this transaction wrote outside any savepoint.

    pg_current_xact_id() is the 64-bit transaction id and xmin its low 32 bits. The seed modules use no
    savepoints, so this is the proof that a row the seed is about to record is one it just inserted.
    """
    column = f'{alias}.xmin' if alias else 'xmin'
    return f'{column}::text::bigint = pg_current_xact_id()::text::bigint % 4294967296'


async def primary_key(tx, table: str) -> list[str] | None:
    return await tx.fetchval('''SELECT array_agg(a.attname::text ORDER BY a.attnum) FROM pg_index i
        JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
        WHERE i.indrelid=to_regclass($1) AND i.indisprimary''', table_name(table))


def matching(table: str, columns: list[str]) -> str:
    """FROM and WHERE clauses that find one row of `table` by the recorded key passed as $1."""
    relation = table_name(table)
    where = ' AND '.join(f't.{quote(column)} = k.{quote(column)}' for column in columns)
    return f'{relation} AS t, jsonb_populate_record(NULL::{relation}, $1::jsonb) AS k WHERE {where}'


# A row's incarnation: its creation time when its table keeps one, which edits never change, or else its whole
# text, so for those tables a later edit makes removal keep the row as if it had been replaced. Either is a proxy,
# not an unforgeable identity: a row made again with the same creation time, or the same text, reads the same.
BORN_COLUMNS = ('created_at', 'occurred_at', 'received_at')
# Creation times are written in UTC in this one form, so they read the same in any session, whatever its settings;
# Catalog's receipt function in L03_0003 writes the same form. The value is only ever compared, never parsed.
BORN_FORMAT = 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'


async def born(tx, table: str) -> str:
    """SQL for the incarnation of row t of `table`, which ownership checks and removal compare with the recorded one.

    The creation-time form does not depend on session settings. The whole-text form does, so it is only ever
    computed in the seed's own sessions, which fix their output formats (FORMATS).
    """
    found = await tx.fetchrow('''SELECT attname::text AS name, format_type(atttypid, NULL) AS type
        FROM pg_attribute WHERE attrelid=to_regclass($1) AND attnum > 0 AND NOT attisdropped
        AND attname::text = ANY($2::text[]) ORDER BY array_position($2::text[], attname::text) LIMIT 1''',
                              table_name(table), list(BORN_COLUMNS))
    if found is None:
        return "'row:' || md5(t::text)"
    column = 't.' + quote(found['name'])
    if found['type'] == 'timestamp with time zone':
        value = f"to_char({column} AT TIME ZONE 'UTC', '{BORN_FORMAT}')"
    elif found['type'] == 'timestamp without time zone':
        value = f"to_char({column}, '{BORN_FORMAT}')"
    else:
        value = f'{column}::text'
    return f"'created:' || coalesce({value}, '')"


async def record(tx, seed_key: str, table: str, row: dict) -> None:
    """Enter one row in the ownership record; only a row this transaction itself wrote can be entered.

    An earlier entry at the same key is stale, since the seed could insert a row there: it is replaced, so the
    record holds this incarnation, as the newest step.
    """
    columns = await primary_key(tx, table)
    if not columns or sorted(columns) != sorted(row):
        raise RuntimeError('Seed ownership needs the whole primary key')
    key = row_key(row)
    incarnation = await tx.fetchval(
        f'SELECT {await born(tx, table)} FROM {matching(table, columns)} AND {written_here("t")}', key)
    if incarnation is None:
        raise RuntimeError('Seed ownership is only for rows the seed itself inserted')
    await tx.execute(f'DELETE FROM {LEDGER} WHERE table_name=$1 AND row_key=$2::jsonb', table, key)
    await tx.execute(f'INSERT INTO {LEDGER}(demo_key,table_name,row_key,born) VALUES($1,$2,$3::jsonb,$4)',
                     seed_key, table, key, incarnation)


async def owned(tx, table: str, row: dict, seed_key: str | None = None) -> bool:
    """Whether the ownership record holds this row (under this demo key, when one is given) and the row there is
    still the one the seed inserted: the same incarnation. A row deleted and made again at that key is not owned."""
    columns = await primary_key(tx, table)
    if not columns or sorted(columns) != sorted(row):
        raise RuntimeError('Seed ownership needs the whole primary key')
    return bool(await tx.fetchval(f'''SELECT 1 FROM {LEDGER} AS r, {matching(table, columns)}
        AND r.table_name=$2 AND r.row_key=$1::jsonb AND ($3::text IS NULL OR r.demo_key=$3)
        AND r.born = {await born(tx, table)}''', row_key(row), table, seed_key))


async def locked_owned(tx, table: str, row: dict, seed_key: str, condition: str = 'true', args=(),
                       lock: str = 'FOR SHARE') -> bool | None:
    """Lock first, then check: the row at this full primary key is locked without waiting, and only then is it
    checked to be the seed's own row under this demo key, still the incarnation it inserted, and to meet
    `condition` (SQL on the row as t, its parameters `args` from $4).

    True or False, or None when a live writer holds the row (never waited for). The row checked is the row
    locked, and it stays locked to the end of this transaction: at read committed, a row checked first and
    locked after could be replaced in between, and the lock would then protect the replacement. No savepoint
    is used, so written_here() still holds for the caller.
    """
    columns = await primary_key(tx, table)
    if not columns or sorted(columns) != sorted(row):
        raise RuntimeError('Seed ownership needs the whole primary key')
    key = row_key(row)
    if not await tx.fetchval(f'SELECT 1 FROM {matching(table, columns)} {lock} OF t SKIP LOCKED', key):
        return None if await tx.fetchval(f'SELECT 1 FROM {matching(table, columns)}', key) else False
    return bool(await tx.fetchval(f'''SELECT 1 FROM {LEDGER} AS r, {matching(table, columns)}
        AND r.table_name=$2 AND r.row_key=$1::jsonb AND r.demo_key=$3 AND r.born = {await born(tx, table)}
        AND ({condition})''', key, table, seed_key, *args))


async def recorded(tx, table: str, row: dict) -> bool:
    """Whether the ownership record holds this key at all, whatever row is there now.

    The password-free class uses this, so it fails closed: an account id the record still holds never gets a
    password path, even if the row there is no longer the one the seed inserted.
    """
    return bool(await tx.fetchval(f'SELECT 1 FROM {LEDGER} WHERE table_name=$1 AND row_key=$2::jsonb',
                                  table, row_key(row)))


async def account_owner(tx, sample_set: str, role: str) -> str:
    """Whether the seed owns this set's sample account for this role, for the sample sign-in to check first.

    Call it on the entry route's own transaction before it signs anyone in, and sign in only on 'owned', still
    checking the account's status is 'active'. It locks FOR UPDATE the row at the pinned id and any row at the
    pinned address, so neither can change before that transaction ends. account(sample_set, role) gives the
    pinned id (.id) and address (.email). It returns:
    'owned': the row at the pinned id has the pinned address, is recorded under the account's demo key and is
      still the row the seed inserted (the same incarnation);
    'foreign': a row at the pinned id or address that the record does not hold at all, or holds for another row;
    'stale': the record holds the pinned id, but the row there is gone, made again, or no longer at the address;
    'missing': no row and no record.
    An unknown set, or a role outside SIGN_IN_ROLES, raises ValueError.
    """
    if sample_set not in SETS or role not in SIGN_IN_ROLES:
        raise ValueError('Not a sample sign-in account')
    person = account(sample_set, role)
    rows = await tx.fetch(f'''SELECT t.id, t.email, {await born(tx, 'identity_accounts')} AS born,
        EXISTS(SELECT 1 FROM {LEDGER} r WHERE r.table_name='identity_accounts'
          AND r.row_key=jsonb_build_object('id', t.id::text)) AS held
        FROM identity_accounts AS t WHERE t.id=$1 OR t.email=$2 FOR UPDATE OF t''', person.id, person.email)
    entry = await tx.fetchrow(f'SELECT demo_key, born FROM {LEDGER} WHERE table_name=$1 AND row_key=$2::jsonb',
                              'identity_accounts', row_key({'id': person.id}))
    if entry is not None and entry['demo_key'] == person.key and any(
            row['id'] == person.id and row['email'] == person.email and row['born'] == entry['born']
            for row in rows):
        return 'owned'
    if any(not row['held'] for row in rows):
        return 'foreign'
    if entry is not None:
        return 'stale'
    return 'foreign' if rows else 'missing'


async def holds(tx, seed_key: str, table: str) -> bool:
    """Whether the ownership record holds any row of `table` under this demo key."""
    return bool(await tx.fetchval(f'SELECT 1 FROM {LEDGER} WHERE demo_key=$1 AND table_name=$2 LIMIT 1',
                                  seed_key, table))


@asynccontextmanager
async def events(tx, seed_key: str):
    """Enter in the ownership record every outbox event the enclosed code enqueues in this transaction."""
    since = await tx.fetchval('SELECT coalesce(max(id),0) FROM outbox')
    yield
    for row in await tx.fetch(f'SELECT id FROM outbox WHERE id > $1 AND {written_here()} ORDER BY id', since):
        await record(tx, seed_key, 'outbox', {'id': row['id']})


class Busy(Exception):
    """Another seed run, a removal or a live writer holds what this step needs: skipped, never waited for."""


class Refused(Exception):
    """A recorded row that removal must keep: deleting it could reach rows the seed does not own, it is still
    active, or it is no longer the row the seed inserted."""


@asynccontextmanager
async def transaction(database_url: str, scope: str, *, exclusive: bool = False):
    """One bounded seed transaction: short connect, lock and statement limits, and try-locks only.

    Every seed step, and Catalog's handoff receipt, shares the 'demo-seed' lock and a removal takes it alone,
    so the two never overlap. On any error or cancellation the connection is dropped and the server rolls the
    transaction back on its own; nothing here waits for that, and nothing here promises when the server finishes
    it. If the whole process is killed at the hard deadline, the server notices within its own limits: when idle
    in the transaction, after CHECK_INTERVAL in a statement where it can check the client, else after LOCK_MS,
    STATEMENT_MS or IDLE_MS. A commit the server had already accepted stays committed, so a step that finished
    before a later one was stopped leaves a partial seed, which the deploy log reports as such.
    """
    conn = await asyncpg.connect(
        database_url, timeout=CONNECT_SECONDS, command_timeout=STATEMENT_MS / 1000 + 1,
        server_settings={'application_name': 'bt-demo-seed', 'lock_timeout': str(LOCK_MS),
                         'statement_timeout': str(STATEMENT_MS),
                         'idle_in_transaction_session_timeout': str(IDLE_MS), **FORMATS})
    try:
        # Best-effort: an older server, or a platform without the check, keeps the plain limits above.
        with contextlib.suppress(asyncpg.PostgresError):
            await conn.execute(f"SET client_connection_check_interval = '{CHECK_INTERVAL}'")
        tx = conn.transaction(isolation='read_committed')
        await tx.start()
        shared = 'pg_try_advisory_xact_lock' if exclusive else 'pg_try_advisory_xact_lock_shared'
        if not await conn.fetchval(f'''SELECT {shared}(hashtextextended('demo-seed',0))
            AND pg_try_advisory_xact_lock(hashtextextended($1,0))''', 'demo-seed:' + scope):
            raise Busy(scope)
        yield conn
        await tx.commit()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(conn.close(), CLOSE_SECONDS)
    finally:
        if not conn.is_closed():
            conn.terminate()


# Recorded rows that must already be revoked in the app before removal may delete them.
ACTIVE = {'identity_access_grants': 't.revoked_at IS NULL'}


async def referenced(tx, relation: int, table: str, columns: list[str], key: str) -> bool:
    """Whether any row refers to this one through a foreign key that a delete would cascade, null or reset."""
    for link in await tx.fetch('''SELECT c.conrelid::regclass::text AS source,
        array(SELECT quote_ident(a.attname) FROM unnest(c.conkey) WITH ORDINALITY u(n,i)
          JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=u.n ORDER BY u.i) AS source_columns,
        array(SELECT quote_ident(a.attname) FROM unnest(c.confkey) WITH ORDINALITY u(n,i)
          JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=u.n ORDER BY u.i) AS target_columns
        FROM pg_constraint c WHERE c.contype='f' AND c.confrelid=$1 AND c.confdeltype IN ('c','n','d')''',
                               relation):
        joined = ' AND '.join(f'r.{source} = t.{target}'
                              for source, target in zip(link['source_columns'], link['target_columns']))
        if await tx.fetchval(f'SELECT 1 FROM {link["source"]} AS r, {matching(table, columns)} AND {joined} '
                             'LIMIT 1', key):
            return True
    return False


async def delete_recorded(tx, entry) -> None:
    table = entry['table_name']
    relation = await tx.fetchval('SELECT to_regclass($1)::oid', table_name(table))
    if relation is not None:
        columns = await primary_key(tx, table)
        key = json.loads(entry['row_key'])
        if not columns or sorted(columns) != sorted(key):
            raise Refused('key')
        # A delete trigger or rule could write or delete rows the seed does not own.
        if await tx.fetchval('''SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=$1 AND NOT tgisinternal
            AND (tgtype::int & 8) <> 0) OR EXISTS(SELECT 1 FROM pg_rewrite WHERE ev_class=$1 AND ev_type='4')''',
                             relation):
            raise Refused('trigger')
        # Lock exactly this row first, without waiting, and keep the lock until the removal commits. A writer
        # adding a row that refers to it must lock it too, so from here on no such row can appear: the check
        # below stays true through the delete. A row a live writer holds raises LockNotAvailable and is kept.
        row = await tx.fetchrow(f'''SELECT {await born(tx, table)} AS born, ({ACTIVE.get(table, 'false')}) AS active
            FROM {matching(table, columns)} FOR UPDATE OF t NOWAIT''', entry['row_key'])
        if row is not None:
            # The same key on a row the seed did not insert: it was deleted and made again, or for a table
            # without a creation time, edited since.
            if row['born'] != entry['born']:
                raise Refused('replaced' if entry['born'].startswith('created:') else 'changed')
            if row['active']:
                raise Refused('active')
            # A cascading or nulling foreign key would change the rows referring to this one: keep it instead.
            if await referenced(tx, relation, table, columns, entry['row_key']):
                raise Refused('referenced')
            clause = matching(table, columns).split(' AS t, ', 1)[1]
            await tx.execute(f'DELETE FROM {table_name(table)} AS t USING {clause}', entry['row_key'])
    await tx.execute(f'DELETE FROM {LEDGER} WHERE step=$1', entry['step'])


async def remove(database_url: str, steps=()) -> dict:
    """Delete exactly the rows in the ownership record, newest first, one demo key at a time.

    A demo key whose rows something else now refers to (a session, a later review, a revoke's history), that
    a live writer holds, or whose row is no longer the one the seed inserted is kept whole, still recorded, so
    the account stays password-free. Rows the record does not hold are never deleted, in any table: Catalog's
    handoff receipts and their ingress entries go only by their own entries, like every other row.
    First, in the same transaction and also when an active grant blocks the deletions, each module's removal
    step runs (`steps`, the `deploy-remove` entries): Identity's withdraws there each handoff whose latest is
    still 'ready', so the withdrawals commit together with the removal or not at all. The deletions then go only
    by the entries made before those steps, so the withdrawals stay. A second removal deletes the first one's
    withdrawals and sends none, so the record ends holding only what was kept; on a database the seed never
    wrote, removal writes nothing. It never claims a full cleanup: what it keeps, and what other services
    derived from delivered events, stays.
    """
    async with transaction(database_url, 'remove', exclusive=True) as tx:
        await tx.execute('SET CONSTRAINTS ALL IMMEDIATE')
        blocked = False
        for table, condition in ACTIVE.items():
            if await tx.fetchval('SELECT to_regclass($1) IS NOT NULL', table_name(table)) and await tx.fetchval(
                    f'''SELECT 1 FROM {table_name(table)} t JOIN {LEDGER} r ON r.table_name=$1
                    AND r.row_key=jsonb_build_object('id', t.id::text) WHERE {condition} LIMIT 1''', table):
                blocked = True
        before = await tx.fetchval(f'SELECT coalesce(max(step), 0) FROM {LEDGER}')
        # Outside every savepoint, so what a step writes was written here and can be recorded.
        done = {}
        for step in steps:
            for name, value in (await step(tx) or {}).items():
                done[name] = done.get(name, 0) + value
        removed, kept = await sweep(tx, before) if not blocked else (0, {})
        result = {'blocked': 'active-grant'} if blocked else {'removed': removed, 'kept': len(kept)}
        result.update(done)
    if blocked:
        report('remove', 'blocked: revoke the sample businesses in the app first')
    for seed_key, reason in sorted(kept.items()):
        report('remove', f'kept {seed_key}: {reason}')
    return result


async def sweep(tx, upto: int) -> tuple[int, dict]:
    """Removal's deletions, of the entries up to step `upto`: how many recorded rows went, and why each kept demo
    key stayed."""
    groups = {}
    for entry in await tx.fetch(f'''SELECT step,demo_key,table_name,row_key::text AS row_key,born
        FROM {LEDGER} WHERE step <= $1 ORDER BY step DESC''', upto):
        groups.setdefault(entry['demo_key'], []).append(entry)
    removed, kept, pending = 0, {}, list(groups.items())
    while pending:
        waiting = []
        for seed_key, entries in pending:
            try:
                async with tx.transaction():
                    for entry in entries:
                        await delete_recorded(tx, entry)
            except Refused as reason:
                kept[seed_key] = str(reason)
            except asyncpg.ForeignKeyViolationError:
                kept[seed_key] = 'referenced'
            except (asyncpg.LockNotAvailableError, asyncpg.QueryCanceledError):
                kept[seed_key] = 'busy'
            else:
                removed += len(entries)
                kept.pop(seed_key, None)
                continue
            waiting.append((seed_key, entries))
        if len(waiting) == len(pending):
            break
        pending = waiting
    return removed, kept


async def bounded(work, deadline: float) -> dict:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        work.close()
        return {'skipped': 'time'}
    try:
        return await asyncio.wait_for(work, remaining)
    except (Busy, asyncpg.LockNotAvailableError):
        return {'skipped': 'busy'}
    except asyncio.TimeoutError:
        return {'failed': 'timeout'}
    except Exception as error:
        return {'failed': type(error).__name__}


async def entry(module, settings):
    result = module.load(module.fixtures[ENTRY])(settings)
    return await result if inspect.isawaitable(result) else result


# Counts that mean a step's rows are in place. Any other nonzero count, a skip or a failure leaves the seed
# partial: what the steps before it committed stays, and the deploy log says so instead of calling it done.
COMPLETE_COUNTS = ('created', 'kept', 'attached', 'unchanged', 'handoff_sent')


def complete(result) -> bool:
    return isinstance(result, dict) and 'failed' not in result and 'skipped' not in result and not any(
        value for name, value in result.items() if name not in COMPLETE_COUNTS)


async def apply(settings, environ=None) -> dict:
    """Seed or remove, by the switch, within TOTAL_SECONDS; never raises into the deploy."""
    deadline = asyncio.get_running_loop().time() + TOTAL_SECONDS
    try:
        chosen = mode(environ)
        if chosen is None:
            if (os.environ if environ is None else environ).get(SWITCH):
                report('switch', f'ignored; {SWITCH} acts only on its documented values')
            return {}
        modules = discover(settings.modules_path)
        if chosen == 'remove':
            steps = [item.load(item.fixtures[REMOVE_ENTRY]) for item in modules if REMOVE_ENTRY in item.fixtures]
            result = await bounded(remove(settings.database_url, steps), deadline)
            report('remove', summary(result))
            return {'remove': result}
        results = {}
        for module in [item for item in modules if ENTRY in item.fixtures]:
            results[module.id] = await bounded(entry(module, settings), deadline)
            report(module.id, summary(results[module.id]))
        unfinished = [name for name, result in results.items() if not complete(result)]
        report('seed', 'partial; not finished: ' + ' '.join(unfinished) if unfinished else 'complete')
        return results
    except Exception as error:
        report('seed', f'failed: {type(error).__name__}')
        return {'failed': type(error).__name__}


class AbandonedThreads(concurrent.futures.ThreadPoolExecutor):
    """The seed loop's default executor: one daemon thread per call, and shutdown never waits.

    asyncpg resolves the database host and the photo step normalizes images in this executor; a call that
    outlives the seed's budget is abandoned instead of holding the deploy step open until it returns.
    """

    def submit(self, fn, /, *args, **kwargs):
        future = concurrent.futures.Future()

        def work():
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(fn(*args, **kwargs))
                except BaseException as error:
                    future.set_exception(error)

        threading.Thread(target=work, name='demo-seed-work', daemon=True).start()
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


def run(settings, environ=None) -> dict:
    """The pre-deploy hook's entry: apply() on its own event loop; never raises and never overstays."""
    async def main():
        asyncio.get_running_loop().set_default_executor(AbandonedThreads())
        return await apply(settings, environ)
    try:
        return asyncio.run(main())
    except Exception as error:
        report('seed', f'failed: {type(error).__name__}')
        return {'failed': type(error).__name__}

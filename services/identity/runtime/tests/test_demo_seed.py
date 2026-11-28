"""Deploy-applied demo seed against a real, migrated Identity database (hosted CI).

Covers the ownership record and the removal command, rows the seed did not create, the password-free class
of seed accounts, replay against live sessions and grants, the signed handoffs to Catalog (each in Identity's
producer order and carrying Identity's assertion over exactly its fields; renewed on every run, withdrawn once
Identity no longer vouches for a holder, and withdrawn by removal; none without the handoff key), the order the
running app cannot draw, each vouched row locked before it is checked (a replacement right before the lock is
caught, one after it waits, a live writer is skipped and never waited for), the sample sign-in's owner check, the
time budget, and the hard deadline of the real pre-deploy step against early and late stalls and a failed deploy
log.
Identity's handoff key pair is made here for these tests only and never stored.
"""
import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from uuid import uuid4

import asyncpg
import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
import pytest
from bt_bulkheads import DependencyClient
from bt_events import OutboxRelay
from bt_runtime import demo_seed, demo_seed_deadline
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from service_app.bootstrap_operator import bootstrap
from service_app.main import create_app

ORIGIN = {"Origin": "http://localhost:3000"}
# The service's runtime folder: the pre-deploy step's working directory in the image (/app) and in hosted CI.
RUNTIME = Path(__file__).resolve().parents[1]
# What sign-up, a pending submission, a sample onboarding and one staff grant write; nothing a review writes.
SEEDED_TABLES = {
    "identity_accounts",
    "identity_private_applications",
    "identity_private_evidence",
    "identity_security_audit",
    "l02_businesses",
    "l02_business_history",
    "l02_memberships",
    "l02_membership_history",
    "identity_access_grants",
    "outbox",
}
STAFF_PERMISSIONS = ["business.stock.write", "business.records.read", "identity.listings.publish"]
PASSWORD = "Cedar-harbour-lantern-42"
NEW_PASSWORD = "Juniper-quarry-signal-77"


def membership_counts(**counts):
    """The membership step's counts: these, and zero for every other."""
    return {"created": 0, "kept": 0, "foreign": 0, "in_use": 0, "busy": 0, "no_business": 0, "no_account": 0,
            "handoff_sent": 0, "handoff_withdrawn": 0, "handoff_waiting": 0, "handoff_busy": 0,
            "handoff_unsigned": 0, **counts}


def seller_counts(**counts):
    """The private-seller step's counts: these, and zero for every other."""
    return {"created": 0, "kept": 0, "foreign": 0, "no_account": 0, "busy": 0, **counts}


def removal(**counts):
    """Removal's result: these, and nothing withdrawn and nothing left unsigned unless given."""
    return {"remove": {"withdrawn": 0, "unsigned": 0, **counts}}


def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


# Identity's disposable handoff key pair for these tests; Catalog would hold only the public half.
HANDOFF_PRIVATE, HANDOFF_PUBLIC = key_pair()


FIRST_RUN = {
    "L01.accounts": {"created": 10, "kept": 0, "foreign": 0},
    "L01.private-seller": seller_counts(created=2),
    "L02.businesses": {"created": 2, "kept": 0, "foreign": 0},
    "L02.membership": membership_counts(created=2, handoff_sent=4),
}
# A healthy rerun writes nothing but four fresh handoffs.
LATER_RUN = {
    "L01.accounts": {"created": 0, "kept": 10, "foreign": 0},
    "L01.private-seller": seller_counts(kept=2),
    "L02.businesses": {"created": 0, "kept": 2, "foreign": 0},
    "L02.membership": membership_counts(kept=2, handoff_sent=4),
}
HANDOFF_KEYS = {demo_seed.handoff_key(sample_set, holder) for sample_set in demo_seed.SETS
                for holder in demo_seed.HOLDERS.values()}
SEED_KEYS = (
    {item.key for item in demo_seed.accounts()}
    | {demo_seed.demo_key(item.sample_set, "application", "seller") for item in demo_seed.accounts("seller")}
    | {item.key for item in demo_seed.businesses()}
    | {item.membership_key for item in demo_seed.businesses()}
    | HANDOFF_KEYS
)
HANDOFFS = "SELECT envelope::text AS envelope FROM outbox WHERE destination=$1 ORDER BY id"
ALL_HOLDERS = sorted((sample_set, holder) for sample_set in demo_seed.SETS for holder in demo_seed.HOLDERS.values())
RESET = "INSERT INTO identity_password_resets(hash,subject_id,expires_at) VALUES($1,$2,now()+interval '20 minutes')"
PRIMARY_KEY = """SELECT array_agg(a.attname::text ORDER BY a.attnum) FROM pg_index i
    JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
    WHERE i.indrelid=$1::text::regclass AND i.indisprimary"""


def seed_settings(url):
    # The pre-deploy step runs the seed with the owner connection, right after migrations.
    return Settings(database_url=url, service_name="identity")


def loaded(module_id, ref):
    """A module's own code, from the same loaded package the app uses."""
    path = Settings(database_url="postgresql://unused/unused", service_name="identity").modules_path
    return next(item for item in discover(path) if item.id == module_id).load(ref)


def key_of(table, row):
    return table, demo_seed.row_key(row)


async def contents(url):
    """Every row of every table except the ownership record itself, keyed by table and primary key."""
    conn = await asyncpg.connect(url)
    try:
        found = {}
        tables = await conn.fetch("SELECT tablename::text FROM pg_tables WHERE schemaname='public' ORDER BY 1")
        for (table,) in tables:
            if table == demo_seed.LEDGER:
                continue
            columns = await conn.fetchval(PRIMARY_KEY, demo_seed.quote(table))
            query = f"SELECT to_jsonb(t)::text AS data, t::text AS text FROM {demo_seed.quote(table)} t"
            for row in await conn.fetch(query):
                if columns:
                    data = json.loads(row["data"])
                    found[key_of(table, {column: data[column] for column in columns})] = row["text"]
                else:
                    found[(table, "row:" + row["text"])] = found.get((table, "row:" + row["text"]), 0) + 1
        return found
    finally:
        await conn.close()


async def ledger(url):
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(f"SELECT table_name, row_key::text AS row_key, demo_key FROM {demo_seed.LEDGER}")
        return {key_of(row["table_name"], json.loads(row["row_key"])): row["demo_key"] for row in rows}
    finally:
        await conn.close()


def unchanged(before, after):
    return all(key in after and after[key] == value for key, value in before.items())


def renewed(before, after, count):
    """Check that a run changed nothing but queue `count` more handoffs; return the rows it added."""
    added = set(after) - set(before)
    assert unchanged(before, after)
    assert {table for table, _ in added} <= {"outbox"} and len(added) == count
    return added


def finished(log):
    """The seed's closing line, read as 'complete' or as the set of steps it did not finish."""
    line = next(line for line in log.splitlines() if line.startswith("DEMO SEED seed: "))
    status = line.removeprefix("DEMO SEED seed: ")
    return status if status == "complete" else set(status.removeprefix("partial; not finished: ").split())


@contextlib.asynccontextmanager
async def owner_connection(url):
    conn = await asyncpg.connect(url)
    try:
        yield conn
    finally:
        await conn.close()


async def seed_backends_gone(url, seconds=15):
    """Wait until no seed connection is left on the server, so a next step never races a dying one."""
    async with owner_connection(url) as conn:
        for _ in range(int(seconds * 10)):
            if not await conn.fetchval("""SELECT count(*) FROM pg_stat_activity
                WHERE application_name='bt-demo-seed' AND datname=current_database()"""):
                return
            await asyncio.sleep(0.1)
    raise AssertionError("A seed connection outlived the seed's lock and statement limits")


async def handoffs(url):
    """Every handoff event Identity's seed queued for Catalog's seed, oldest first."""
    async with owner_connection(url) as conn:
        return [json.loads(row["envelope"]) for row in await conn.fetch(HANDOFFS, demo_seed.HANDOFF_DESTINATION)]


def vouched(envelopes, ordered=True):
    """Check that each handoff is exactly the seed's own for its set and holder, with its own place in Identity's
    order and Identity's assertion over exactly its event id, order, fields and issue time; return each set,
    holder and state, sorted. Envelopes read in outbox order (`ordered`) must also rise in Identity's order."""
    found, order = [], []
    for envelope in envelopes:
        data = dict(envelope["data"])
        seq, assertion = data.pop("seq"), data.pop("assertion")
        assert data == demo_seed.handoff_data(data["sample_set"], data["holder"], data["state"])
        assert type(seq) is int and seq > 0
        assert demo_seed.verify_handoff(HANDOFF_PUBLIC, assertion, envelope["id"], seq, data, issued(envelope))
        assert (envelope["type"], envelope["source"], envelope["subject"], envelope["request_id"]) == (
            demo_seed.HANDOFF_TYPE, "identity", data["subject_id"], demo_seed.REQUEST_ID)
        found.append((data["sample_set"], data["holder"], data["state"]))
        order.append(seq)
    # Identity's order is never reused, and each later handoff in its outbox comes later in it.
    assert len(set(order)) == len(order)
    assert not ordered or order == sorted(order)
    return sorted(found)


def each(state, holders=ALL_HOLDERS):
    return sorted((sample_set, holder, state) for sample_set, holder in holders)


def issued(envelope):
    return datetime.fromisoformat(envelope["time"])


@pytest.fixture(autouse=True)
def handoff_key(monkeypatch):
    """Identity's handoff signing key, as the throwaway environment sets it on Identity only; the pre-deploy
    children below inherit it."""
    monkeypatch.setenv(demo_seed.HANDOFF_PRIVATE_KEY, HANDOFF_PRIVATE)
    monkeypatch.delenv(demo_seed.HANDOFF_PUBLIC_KEY, raising=False)


@pytest.fixture
def keys(monkeypatch):
    private, public = key_pair()
    monkeypatch.setenv("BT_AUTH_PRIVATE_KEY", private)
    monkeypatch.setenv("BT_LOCAL_HTTP", "1")
    monkeypatch.setenv("BT_WEB_ORIGIN", "http://localhost:3000")
    monkeypatch.delenv("BT_ALLOWED_WEB_ORIGINS", raising=False)
    monkeypatch.delenv("BT_EVENT_PRIVATE_KEY", raising=False)
    return private, public


@pytest.fixture
def seeding(monkeypatch):
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)


@contextlib.asynccontextmanager
async def running(database_url, keys):
    app = create_app(Settings(database_url=database_url, service_name="identity", auth_public_key=keys[1]))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost:3000", headers=ORIGIN
        ) as client:
            yield app, client


async def mint_session(app, account_id):
    """A live session as the sample sign-in link would open it, through the app's own session code."""
    new_session = loaded("L01.accounts", "security.py:new_session")
    async with app.state.pool.acquire() as conn:
        async with conn.transaction():
            account = await conn.fetchrow("SELECT * FROM identity_accounts WHERE id=$1 FOR UPDATE", account_id)
            result, _ = await new_session(conn, SimpleNamespace(app=app), account)
    return result["access_token"]


async def insert_account(conn, account_id, email):
    await conn.execute(
        "INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,$2,'Maya Haddad','x')",
        account_id,
        email,
    )


async def insert_business(conn, business_id, creator):
    await conn.execute(
        """INSERT INTO l02_businesses(id,legal_name,public_name,kind,capabilities,assurance_reference,created_by)
        VALUES($1,'Not seeded','Not seeded','dealer',ARRAY['sales'],'NOT-SEEDED',$2)""",
        business_id,
        creator,
    )


async def insert_membership(conn, membership_id, business_id, subject_id):
    await conn.execute(
        """INSERT INTO l02_memberships(id,business_id,subject_id,capabilities,intervention_scope)
        VALUES($1,$2,$3,ARRAY['business.stock.write'],'Not seeded')""",
        membership_id,
        business_id,
        subject_id,
    )


async def insert_grant(conn, subject_id, organization_id):
    await conn.execute(
        """INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
        VALUES($1,$2,$3,'dealer',ARRAY['business.stock.write'])""",
        uuid4(),
        subject_id,
        organization_id,
    )


async def test_switch_off_or_unknown_writes_nothing(database_owner_url, monkeypatch):
    before = await contents(database_owner_url)
    monkeypatch.delenv(demo_seed.SWITCH, raising=False)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {}
    for value in ("true", "1", "Sample-Accounts-Only"):
        monkeypatch.setenv(demo_seed.SWITCH, value)
        assert await demo_seed.apply(seed_settings(database_owner_url)) == {}
    # Removal on a database the seed never wrote finds nothing to delete and no handoff to withdraw.
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == removal(removed=0, kept=0)
    assert await contents(database_owner_url) == before
    assert await ledger(database_owner_url) == {}


async def test_every_row_it_inserts_is_recorded_and_a_rerun_only_renews_the_handoffs(
    database_owner_url, seeding, capsys
):
    before = await contents(database_owner_url)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == FIRST_RUN
    seeded = await contents(database_owner_url)
    record = await ledger(database_owner_url)
    # Exactly the new rows are in the record: grants, history, evidence, audit and events included.
    assert set(seeded) - set(before) == set(record)
    assert unchanged(before, seeded)
    assert {table for table, _ in record} == SEEDED_TABLES
    assert set(record.values()) == SEED_KEYS
    # One signed handoff per set and holder, for Catalog's seed only, after the rows it vouches for committed.
    first = await handoffs(database_owner_url)
    assert vouched(first) == each("ready")
    assert finished(capsys.readouterr().err) == "complete"
    # A rerun writes nothing but one fresh handoff per set and holder, each recorded under its own key, so
    # Catalog's seed keeps acting only while Identity's seed keeps vouching.
    assert await demo_seed.apply(seed_settings(database_owner_url)) == LATER_RUN
    sent = renewed(seeded, await contents(database_owner_url), 4)
    later = await ledger(database_owner_url)
    assert unchanged(record, later) and set(later) - set(record) == sent
    assert {later[key] for key in sent} == HANDOFF_KEYS
    again = (await handoffs(database_owner_url))[len(first):]
    assert vouched(again) == each("ready")
    assert min(map(issued, again)) >= max(map(issued, first))
    assert finished(capsys.readouterr().err) == "complete"
    no_password = loaded("L01.accounts", "deploy_seed.py:NO_PASSWORD")
    password_matches = loaded("L01.accounts", "security.py:password_matches")
    assert not any(password_matches(guess, no_password) for guess in ("", no_password, "seed-only", PASSWORD))
    async with owner_connection(database_owner_url) as conn:
        for account in demo_seed.accounts():
            row = await conn.fetchrow("SELECT * FROM identity_accounts WHERE id=$1", account.id)
            assert (row["email"], row["display_name"], row["status"]) == (account.email, account.display_name, "active")
            assert row["password_hash"] == no_password
        for seller in demo_seed.accounts("seller"):
            case = await conn.fetchrow("SELECT * FROM identity_private_applications WHERE subject_id=$1", seller.id)
            assert (case["status"], case["revision"], case["identity_name"]) == ("pending", 1, seller.display_name)
            kinds = await conn.fetch("SELECT kind FROM identity_private_evidence WHERE application_id=$1", case["id"])
            assert sorted(row["kind"] for row in kinds) == ["identity", "possession"]
        # Nothing a review writes.
        for table in ("identity_private_assignments", "identity_operator_bootstrap"):
            assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0
        # The only grants anywhere are each set's sample staff's, scoped to that set's own sample business.
        grants = await conn.fetch("SELECT * FROM identity_access_grants")
        staff = {item.id: item for item in demo_seed.accounts("staff")}
        assert sorted(row["subject_id"] for row in grants) == sorted(staff)
        for row in grants:
            business = demo_seed.business(staff[row["subject_id"]].sample_set)
            assert (row["organization_id"], row["role"], row["revoked_at"]) == (business.id, "dealer", None)
            assert row["permissions"] == STAFF_PERMISSIONS
        for business in demo_seed.businesses():
            company = await conn.fetchrow("SELECT * FROM l02_businesses WHERE id=$1", business.id)
            assert (company["public_name"], company["kind"], company["capabilities"], company["sample"]) == (
                business.public_name, "dealer", ["sales"], True)
            assert (company["state"], company["created_by"]) == ("active", demo_seed.ACTOR)
            member = await conn.fetchrow("SELECT * FROM l02_memberships WHERE id=$1", business.membership_id)
            assert (member["business_id"], member["subject_id"], member["state"]) == (
                business.id, demo_seed.account(business.sample_set, "staff").id, "active")
            assert member["capabilities"] == list(demo_seed.STAFF_CAPABILITIES)
    # Visible text carries made-up names, never a seed label; the record marks seed rows.
    visible = [*loaded("L01.private-seller", "deploy_seed.py:EVIDENCE").values(),
               loaded("L02.businesses", "deploy_seed.py:REASON"),
               *loaded("L02.membership", "deploy_seed.py:QUALIFICATIONS"),
               loaded("L02.membership", "deploy_seed.py:SCOPE"),
               loaded("L02.membership", "deploy_seed.py:REASON")]
    assert all("DEMO" not in text for text in visible)


async def test_pinned_ids_and_addresses_it_did_not_create_are_skipped(database_owner_url, seeding, capsys):
    buyer, seller, staff = (demo_seed.account("demo", role) for role in ("buyer", "seller", "staff"))
    async with owner_connection(database_owner_url) as conn:
        # The demo buyer's id with another address; the click-test seller's address under another id.
        await insert_account(conn, buyer.id, "someone.else@example.test")
        await insert_account(conn, uuid4(), demo_seed.account("click-test", "seller").email)
        # Exact id and address, but not created by the seed: still someone else's.
        await insert_account(conn, seller.id, seller.email)
        await insert_account(conn, staff.id, staff.email)
        await conn.execute(
            "INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,now()+interval '1 day')",
            uuid4(),
            staff.id,
        )
        await insert_grant(conn, staff.id, uuid4())
        # Someone else's business on the demo business id, and someone else's membership on a pinned id.
        await insert_business(conn, demo_seed.business("demo").id, uuid4())
        await insert_membership(conn, demo_seed.business("click-test").membership_id, uuid4(), uuid4())
    before = await contents(database_owner_url)
    first = {
        "L01.accounts": {"created": 6, "kept": 0, "foreign": 4},
        "L01.private-seller": seller_counts(no_account=2),
        "L02.businesses": {"created": 1, "kept": 0, "foreign": 1},
        "L02.membership": membership_counts(foreign=1, no_account=1, handoff_waiting=4),
    }
    assert await demo_seed.apply(seed_settings(database_owner_url)) == first
    after = await contents(database_owner_url)
    record = await ledger(database_owner_url)
    # Never updated, attached to or synced: every row it found is exactly as it was, and it owns only its own.
    assert unchanged(before, after)
    assert set(after) - set(before) == set(record)
    assert all(key not in record for key in before)
    # No handoff for a holder whose account, business or membership is someone else's: Catalog's seed waits.
    assert await handoffs(database_owner_url) == []
    log = capsys.readouterr().err
    for key in (buyer.key, seller.key, staff.key, demo_seed.account("click-test", "seller").key):
        assert f"DEMO SEED identity-accounts: foreign {key}: pinned id or address already in use\n" in log
    assert (f"DEMO SEED identity-businesses: foreign {demo_seed.business('demo').key}: pinned id already in use\n"
            in log)
    assert (f"DEMO SEED identity-membership: foreign {demo_seed.business('click-test').membership_key}: "
            "a membership the seed did not create exists\n") in log
    # Counts, public keys and error classes only: never an address. And it says the seed is partial.
    assert "@" not in log
    assert finished(log) == set(first)
    later = {
        **first,
        "L01.accounts": {"created": 0, "kept": 6, "foreign": 4},
        "L02.businesses": {"created": 0, "kept": 1, "foreign": 1},
    }
    assert await demo_seed.apply(seed_settings(database_owner_url)) == later
    assert await contents(database_owner_url) == after


async def test_replay_never_revokes_a_session_or_grant_it_did_not_create(
    database_url, database_owner_url, keys, seeding
):
    modules = {item.id: item for item in discover(seed_settings(database_owner_url).modules_path)}
    for module_id in ("L01.accounts", "L02.businesses"):
        await demo_seed.entry(modules[module_id], seed_settings(database_owner_url))
    demo_staff, click_staff = (demo_seed.account(name, "staff") for name in ("demo", "click-test"))
    async with running(database_url, keys) as (app, _):
        # The demo staff signs in through the sample link before the membership step ever ran.
        await mint_session(app, demo_staff.id)
    async with owner_connection(database_owner_url) as conn:
        await insert_grant(conn, click_staff.id, demo_seed.business("click-test").id)
        # Someone else's case already holds one of the click-test seller's pinned evidence ids.
        other = uuid4()
        await insert_account(conn, other, "someone.else@example.test")
        case = await conn.fetchval(
            """INSERT INTO identity_private_applications(id,subject_id,revision,status,identity_name,contact,
            payout_reference) VALUES($1,$2,1,'pending','Maya Haddad','someone.else@example.test',
            'DEMO-FOREIGN-RECIPIENT') RETURNING id""",
            uuid4(),
            other,
        )
        pinned = demo_seed.seed_id(f"{demo_seed.demo_key('click-test', 'application', 'seller')}:evidence:identity")
        content = b"Someone else's evidence"
        await conn.execute(
            """INSERT INTO identity_private_evidence(id,application_id,subject_id,kind,content,sha256)
            VALUES($1,$2,$3,'identity',$4,$5)""",
            pinned,
            case,
            other,
            content,
            hashlib.sha256(content).hexdigest(),
        )
    before = await contents(database_owner_url)
    expected = {
        "L01.accounts": {"created": 0, "kept": 10, "foreign": 0},
        "L01.private-seller": seller_counts(created=1, foreign=1),
        "L02.businesses": {"created": 0, "kept": 2, "foreign": 0},
        "L02.membership": membership_counts(in_use=2, handoff_sent=2, handoff_waiting=2),
    }
    assert await demo_seed.apply(seed_settings(database_owner_url)) == expected
    after = await contents(database_owner_url)
    # The live session and the grant are exactly as they were: nothing revoked, nothing bumped.
    assert unchanged(before, after)
    assert set(after) - set(before) == set(await ledger(database_owner_url)) - set(before)
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM l02_memberships") == 0
        assert await conn.fetchval(
            "SELECT count(*) FROM identity_private_applications WHERE subject_id=$1",
            demo_seed.account("click-test", "seller").id,
        ) == 0
        assert await conn.fetchval("SELECT count(*) FROM identity_sessions WHERE revoked_at IS NULL") == 1
        assert await conn.fetchval("SELECT count(*) FROM identity_access_grants WHERE revoked_at IS NULL") == 1
    # The sellers' own accounts are handed off; the staff, with no membership of the seed's, are not.
    sellers = [("click-test", "seller", "ready"), ("demo", "seller", "ready")]
    assert vouched(await handoffs(database_owner_url)) == sellers
    later = {**expected, "L01.private-seller": seller_counts(kept=1, foreign=1)}
    # The rerun renews only the sellers' handoffs; the staff's still wait.
    assert await demo_seed.apply(seed_settings(database_owner_url)) == later
    renewed(after, await contents(database_owner_url), 2)
    assert vouched(await handoffs(database_owner_url)) == sorted(sellers * 2)


async def test_seed_accounts_refuse_every_password_path_and_ordinary_accounts_keep_them(
    database_url, database_owner_url, keys, seeding
):
    assert await demo_seed.apply(seed_settings(database_owner_url)) == FIRST_RUN
    buyer, seller = demo_seed.account("demo", "buyer"), demo_seed.account("demo", "seller")
    hash_password = loaded("L01.accounts", "security.py:hash_password")
    digest = loaded("L01.accounts", "security.py:digest")
    no_password = loaded("L01.accounts", "deploy_seed.py:NO_PASSWORD")
    raw = secrets.token_urlsafe(48)
    async with owner_connection(database_owner_url) as conn:
        # Even with a real password hash on the row, the seed's record keeps password sign-in refused.
        await conn.execute(
            "UPDATE identity_accounts SET password_hash=$2 WHERE id=$1", buyer.id, hash_password(PASSWORD)
        )
        # A captured or guessed reset token for a seed account.
        await conn.execute(
            RESET,
            digest(raw),
            seller.id,
        )
    async with running(database_url, keys) as (app, client):
        for account in demo_seed.accounts():
            for guess in ("A-long-sample-passphrase!", account.email):
                login = await client.post("/v1/accounts/login", json={"email": account.email, "password": guess})
                assert login.status_code == 401, login.text
        login = await client.post("/v1/accounts/login", json={"email": buyer.email, "password": PASSWORD})
        assert login.status_code == 401, login.text
        recovery = await client.post(
            "/v1/accounts/recovery", json={"email": seller.email}, headers={"Idempotency-Key": "recovery-seller-01"}
        )
        assert (recovery.status_code, recovery.json()) == (202, {"accepted": True, "delivery": "simulated"})
        reset = await client.post(
            "/v1/accounts/reset", json={"token": raw, "password": NEW_PASSWORD},
            headers={"Idempotency-Key": "reset-seller-0001"},
        )
        assert reset.status_code == 400 and "invalid_reset" in reset.text, reset.text
        token = await mint_session(app, buyer.id)
        bearer = {"Authorization": f"Bearer {token}"}
        change = await client.post(
            "/v1/accounts/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers={**bearer, "Idempotency-Key": "password-buyer-01"},
        )
        assert change.status_code == 401, change.text
        reauthenticate = await client.post(
            "/v1/accounts/reauthenticate",
            json={"password": PASSWORD, "purpose": "contact-change", "binding": "contact-change-test"},
            headers=bearer,
        )
        assert reauthenticate.status_code == 401, reauthenticate.text
        # An ordinary account keeps every password path.
        register = await client.post(
            "/v1/accounts/register",
            json={"email": "reader@example.test", "password": PASSWORD, "display_name": "Maya Haddad"},
            headers={"Idempotency-Key": "register-reader-01"},
        )
        assert register.status_code == 201, register.text
        recovery = await client.post(
            "/v1/accounts/recovery", json={"email": "reader@example.test"},
            headers={"Idempotency-Key": "recovery-reader-01"},
        )
        assert recovery.status_code == 202, recovery.text
        reader_raw = secrets.token_urlsafe(48)
        async with owner_connection(database_owner_url) as conn:
            reader_id = await conn.fetchval("SELECT id FROM identity_accounts WHERE email='reader@example.test'")
            assert await conn.fetchval(
                "SELECT count(*) FROM identity_password_resets WHERE subject_id=$1", reader_id
            ) == 1
            assert await conn.fetchval("SELECT count(*) FROM identity_demo_mail WHERE subject_id=$1", reader_id) == 1
            await conn.execute(
                RESET,
                digest(reader_raw),
                reader_id,
            )
        reset = await client.post(
            "/v1/accounts/reset", json={"token": reader_raw, "password": NEW_PASSWORD},
            headers={"Idempotency-Key": "reset-reader-0001"},
        )
        assert (reset.status_code, reset.json()) == (200, {"sign_in_required": True})
        login = await client.post("/v1/accounts/login", json={"email": "reader@example.test", "password": NEW_PASSWORD})
        assert login.status_code == 200, login.text
    async with owner_connection(database_owner_url) as conn:
        # Nothing was issued, consumed or changed for the seed seller.
        assert await conn.fetchval("SELECT password_hash FROM identity_accounts WHERE id=$1", seller.id) == no_password
        assert await conn.fetchval("SELECT count(*) FROM identity_password_resets WHERE subject_id=$1", seller.id) == 1
        assert await conn.fetchval(
            "SELECT consumed_at FROM identity_password_resets WHERE hash=$1", digest(raw)
        ) is None
        assert await conn.fetchval("SELECT count(*) FROM identity_demo_mail WHERE subject_id=$1", seller.id) == 0
        assert await conn.fetchval("SELECT count(*) FROM identity_sessions WHERE subject_id=$1", seller.id) == 0


async def test_removal_deletes_exactly_its_own_rows_after_the_live_revoke(
    database_url, database_owner_url, keys, seeding, monkeypatch, capsys
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    buyer, seller, staff = (demo_seed.account("demo", role) for role in ("buyer", "seller", "staff"))
    other, company, member = uuid4(), uuid4(), uuid4()
    async with owner_connection(database_owner_url) as conn:
        # Rows someone else made, and a seed row someone edited after the seed made it.
        await insert_account(conn, other, "someone.else@example.test")
        await insert_business(conn, company, other)
        await insert_membership(conn, member, company, other)
        await insert_grant(conn, other, company)
        await conn.execute("UPDATE identity_accounts SET display_name='Karim N.' WHERE id=$1", buyer.id)
    async with running(database_url, keys) as (app, _):
        await mint_session(app, seller.id)
        await mint_session(app, staff.id)
    signed_in = await contents(database_owner_url)
    # Replay against live sessions and the seed's own grants: nothing revoked, bumped or rewritten; only the
    # handoffs are renewed.
    assert await demo_seed.apply(settings) == LATER_RUN
    replayed = await contents(database_owner_url)
    renewed(signed_in, replayed, 4)
    record = await ledger(database_owner_url)
    # While a seed grant is active, removal refuses to delete: the operator revokes the businesses first. It
    # still withdraws every handoff, so Catalog's seed admits nothing more meanwhile.
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    capsys.readouterr()
    assert await demo_seed.apply(settings) == removal(blocked="active-grant", withdrawn=4)
    blocked = await contents(database_owner_url)
    renewed(replayed, blocked, 4)
    assert vouched((await handoffs(database_owner_url))[-4:]) == each("withdrawn")
    held = await ledger(database_owner_url)
    assert unchanged(record, held) and len(held) == len(record) + 4
    log = capsys.readouterr().err
    assert "DEMO SEED remove: blocked: revoke the sample businesses in the app first\n" in log
    assert "DEMO SEED remove: blocked=active-grant unsigned=0 withdrawn=4\n" in log
    # Blocked again, it sends none again: every latest handoff already says withdrawn.
    assert await demo_seed.apply(settings) == removal(blocked="active-grant")
    assert await contents(database_owner_url) == blocked
    assert await ledger(database_owner_url) == held
    async with running(database_url, keys) as (app, client):
        register = await client.post(
            "/v1/accounts/register",
            json={"email": "reviewer@example.test", "password": PASSWORD, "display_name": "Rami Khoury"},
            headers={"Idempotency-Key": "register-reviewer-01"},
        )
        assert register.status_code == 201, register.text
        await bootstrap(app.state.pool, "reviewer@example.test", "Demonstration operator for the removal test")
        login = await client.post("/v1/accounts/login", json={"email": "reviewer@example.test", "password": PASSWORD})
        assert login.status_code == 200, login.text
        bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for business in demo_seed.businesses():
            revoke = await client.patch(
                f"/v1/businesses/{business.id}",
                json={"revision": 1, "state": "revoked", "reason": "The demonstration is over"},
                headers={**bearer, "Idempotency-Key": f"revoke-{business.sample_set}-01"},
            )
            assert revoke.status_code == 200, revoke.text
    async with owner_connection(database_owner_url) as conn:
        # The relay's own edits as it delivers the handoffs: still the rows the seed inserted.
        await conn.execute("UPDATE outbox SET attempts=attempts+1, delivered_at=now() WHERE destination=$1",
                           demo_seed.HANDOFF_DESTINATION)
    revoked = await contents(database_owner_url)
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
    # A later deploy never grants a revoked sample business's staff back: their handoffs stay withdrawn, and the
    # sellers', vouched for again, say ready.
    assert await demo_seed.apply(settings) == {
        **LATER_RUN, "L02.membership": membership_counts(kept=2, handoff_sent=2, handoff_withdrawn=2)}
    reseeded = await contents(database_owner_url)
    renewed(revoked, reseeded, 4)
    assert vouched((await handoffs(database_owner_url))[-4:]) == sorted(
        each("ready", [("demo", "seller"), ("click-test", "seller")])
        + each("withdrawn", [("demo", "staff"), ("click-test", "staff")]))
    assert finished(capsys.readouterr().err) == {"L02.membership"}
    record = await ledger(database_owner_url)
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    result = await demo_seed.apply(settings)
    remaining = await ledger(database_owner_url)
    # The only rows it added: a withdrawal for each seller, whose latest handoff said ready.
    withdrawals = {key: value for key, value in remaining.items() if key not in record}
    left = {key: value for key, value in remaining.items() if key in record}
    assert {table for table, _ in withdrawals} == {"outbox"} and len(withdrawals) == 2
    assert result == removal(removed=len(record) - len(left), kept=4, withdrawn=2)
    # Kept whole and still recorded: the businesses the operator's revoke history refers to, and the two
    # accounts with sessions, which stay password-free.
    kept = {demo_seed.business("demo").key, demo_seed.business("click-test").key, seller.key, staff.key}
    assert set(left.values()) == kept
    after = await contents(database_owner_url)
    # Exactly the recorded rows were deleted, the edited buyer and every earlier handoff included; every other
    # row is as it was.
    assert set(reseeded) - set(after) == set(record) - set(left)
    assert set(after) - set(reseeded) == set(withdrawals)
    assert unchanged({key: value for key, value in after.items() if key not in withdrawals}, reseeded)
    assert key_of("identity_accounts", {"id": buyer.id}) not in after
    assert vouched(await handoffs(database_owner_url)) == each("withdrawn", [("demo", "seller"),
                                                                            ("click-test", "seller")])
    for row in (("identity_accounts", other), ("l02_businesses", company), ("l02_memberships", member)):
        assert key_of(row[0], {"id": row[1]}) in after
    log = capsys.readouterr().err
    for key in sorted(kept):
        assert f"DEMO SEED remove: kept {key}: referenced\n" in log
    assert f"DEMO SEED remove: kept=4 removed={len(record) - len(left)} unsigned=0 withdrawn=2\n" in log
    # A second removal deletes only the first one's withdrawals and sends none: the record ends holding only
    # what it kept, and a third changes nothing.
    assert await demo_seed.apply(settings) == removal(removed=2, kept=4)
    rested = await contents(database_owner_url)
    assert set(after) - set(rested) == set(withdrawals) and unchanged(rested, after)
    assert await ledger(database_owner_url) == left
    assert await handoffs(database_owner_url) == []
    assert await demo_seed.apply(settings) == removal(removed=0, kept=4)
    assert await contents(database_owner_url) == rested
    assert await ledger(database_owner_url) == left
    async with running(database_url, keys) as (_, client):
        login = await client.post("/v1/accounts/login", json={"email": seller.email, "password": PASSWORD})
        assert login.status_code == 401, login.text


async def test_a_locked_table_never_holds_up_the_pre_deploy_step(database_owner_url):
    holder = await asyncpg.connect(database_owner_url)
    environment = {**os.environ, "BT_DATABASE_URL": database_owner_url, demo_seed.SWITCH: demo_seed.SWITCH_VALUE,
                   "BT_SERVICE_NAME": "identity"}
    command = [sys.executable, "-m", "service_app.migrate"]
    try:
        transaction = holder.transaction()
        await transaction.start()
        # A live writer holds the accounts table for longer than the whole deploy step may wait.
        await holder.execute("LOCK TABLE identity_accounts IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        step = await asyncio.to_thread(
            subprocess.run, command, cwd=RUNTIME, env=environment, capture_output=True, text=True, timeout=90
        )
        spent = time.monotonic() - started
        await transaction.rollback()
    finally:
        await holder.close()
    assert step.returncode == 0, step.stderr
    assert spent < demo_seed.TOTAL_SECONDS
    # Each step that reads the locked accounts table gives up at the lock limit; the businesses step never reads it.
    for line in (
        "DEMO SEED L01.accounts: skipped=busy",
        "DEMO SEED L01.private-seller: skipped=busy",
        "DEMO SEED L02.businesses: created=2 foreign=0 kept=0",
        "DEMO SEED L02.membership: skipped=busy",
    ):
        assert line + "\n" in step.stderr
    # Partial, and said so: the three skipped steps did not finish.
    assert finished(step.stderr) == {"L01.accounts", "L01.private-seller", "L02.membership"}
    secret = urlparse(database_owner_url).password
    for output in (step.stdout, step.stderr):
        assert database_owner_url not in output and secret not in output and unquote(secret) not in output
    # The next deploy, with the writer gone, completes what the locked one skipped.
    await seed_backends_gone(database_owner_url)
    step = await asyncio.to_thread(
        subprocess.run, command, cwd=RUNTIME, env=environment, capture_output=True, text=True, timeout=90
    )
    assert step.returncode == 0, step.stderr
    for line in (
        "DEMO SEED L01.accounts: created=10 foreign=0 kept=0",
        "DEMO SEED L01.private-seller: busy=0 created=2 foreign=0 kept=0 no_account=0",
        "DEMO SEED L02.businesses: created=0 foreign=0 kept=2",
        "DEMO SEED L02.membership: busy=0 created=2 foreign=0 handoff_busy=0 handoff_sent=4 handoff_unsigned=0"
        " handoff_waiting=0 handoff_withdrawn=0 in_use=0 kept=0 no_account=0 no_business=0",
        "DEMO SEED seed: complete",
    ):
        assert line + "\n" in step.stderr


async def test_the_total_budget_ends_a_seed_stuck_behind_a_lock(database_owner_url, seeding, monkeypatch):
    budget = demo_seed.TOTAL_SECONDS
    holder = await asyncpg.connect(database_owner_url)
    try:
        async with holder.transaction():
            await holder.execute(f"LOCK TABLE {demo_seed.LEDGER} IN ACCESS EXCLUSIVE MODE")
            monkeypatch.setattr(demo_seed, "TOTAL_SECONDS", 1)
            started = time.monotonic()
            result = await demo_seed.apply(seed_settings(database_owner_url))
            spent = time.monotonic() - started
    finally:
        await holder.close()
    assert set(result) == set(FIRST_RUN)
    assert sorted(result.values(), key=json.dumps) == sorted(
        [{"failed": "timeout"}] + [{"skipped": "time"}] * 3, key=json.dumps)
    assert spent < 3
    await seed_backends_gone(database_owner_url)
    monkeypatch.setattr(demo_seed, "TOTAL_SECONDS", budget)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == FIRST_RUN


async def test_the_handoffs_and_their_withdrawals_are_relayed_signed_for_catalog_only(
    database_url, database_owner_url, keys, seeding, monkeypatch
):
    assert await demo_seed.apply(seed_settings(database_owner_url)) == FIRST_RUN
    destinations = loaded("L01.accounts", "workers.py:destinations")
    signer = loaded("L01.accounts", "workers.py:signer")
    # Off, or set to anything else, Identity relays nothing to Catalog's seed. Seeding, or removing so that the
    # withdrawals reach it too, only to Catalog's own event ingress.
    for environ in ({}, {demo_seed.SWITCH: "true"}):
        assert set(destinations(environ)) == {"communications"}
    for value in (demo_seed.SWITCH_VALUE, demo_seed.REMOVE_VALUE):
        routes = destinations({demo_seed.SWITCH: value, "BT_CATALOG_API_URL": "http://catalog.railway.internal:8000"})
        assert set(routes) == {"communications", demo_seed.HANDOFF_DESTINATION}
        assert routes[demo_seed.HANDOFF_DESTINATION] == ("catalog", "http://catalog.railway.internal:8000")
    received = []

    def catalog(request):
        received.append(request)
        return httpx.Response(200, json={"accepted": True})

    settings = Settings(database_url=database_url, service_name="identity")

    async def relay():
        """Everything the app's relay worker delivers now, built as the worker builds it, with the routes above."""
        received.clear()
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
        client = DependencyClient(demo_seed.HANDOFF_DESTINATION, "http://catalog.test",
                                  transport=httpx.MockTransport(catalog))
        try:
            worker = OutboxRelay(
                pool, {demo_seed.HANDOFF_DESTINATION: client},
                headers=signer(settings, keys[0], {name: audience for name, (audience, _) in routes.items()}),
                batch_size=8, concurrency=2)
            delivered = await worker.tick()
            assert await worker.tick() == 0
        finally:
            await client.aclose()
            await pool.close()
        for request in received:
            assert (request.method, request.url.path, request.headers["x-request-id"]) == (
                "POST", "/internal/v1/events", demo_seed.REQUEST_ID)
            scheme, _, token = request.headers["authorization"].partition(" ")
            claims = jwt.decode(token, keys[1], algorithms=["RS256"], audience="catalog", issuer=settings.auth_issuer)
            assert (scheme, claims["sub"], claims["type"]) == ("Bearer", "identity", "service")
        assert delivered == len(received)
        # Delivered two at a time, so in any order.
        return vouched([json.loads(request.content) for request in received], ordered=False)

    assert await relay() == each("ready")
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM outbox WHERE destination=$1 AND delivered_at IS NOT NULL",
                                   demo_seed.HANDOFF_DESTINATION) == 4
        # Nothing else was sent or attempted.
        assert await conn.fetchval("SELECT count(*) FROM outbox WHERE destination<>$1 AND attempts > 0",
                                   demo_seed.HANDOFF_DESTINATION) == 0
    # Delivered, they stay the seed's own; a later deploy renews them, and a removal then withdraws them, even
    # while a seed grant still blocks its deletions. Both are relayed the same way.
    assert await demo_seed.apply(seed_settings(database_owner_url)) == LATER_RUN
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == removal(blocked="active-grant", withdrawn=4)
    assert await relay() == sorted(each("ready") + each("withdrawn"))
    assert await relay() == []


async def test_a_holder_suspended_revoked_made_again_or_busy_in_identity_has_its_handoff_withdrawn(
    database_owner_url, seeding
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    seller, click_seller = demo_seed.account("demo", "seller"), demo_seed.account("click-test", "seller")
    staff, click_staff = demo_seed.account("demo", "staff"), demo_seed.account("click-test", "staff")
    click_case = demo_seed.seed_id(demo_seed.demo_key("click-test", "application", "seller"))
    async with owner_connection(database_owner_url) as conn:
        # Suspended in the app.
        await conn.execute("UPDATE identity_accounts SET status='suspended' WHERE id=$1", seller.id)
        # Deleted and made again at the same id and address, as a hand reseed would: no longer the seed's row.
        async with conn.transaction():
            await conn.execute("DELETE FROM identity_private_evidence WHERE subject_id=$1", click_seller.id)
            await conn.execute("DELETE FROM identity_private_applications WHERE subject_id=$1", click_seller.id)
            row = await conn.fetchrow("DELETE FROM identity_accounts WHERE id=$1 RETURNING *", click_seller.id)
            await conn.execute("""INSERT INTO identity_accounts(id,email,display_name,password_hash)
                VALUES($1,$2,$3,$4)""", row["id"], row["email"], row["display_name"], row["password_hash"])
        # The demo staff's grant revoked.
        await conn.execute("UPDATE identity_access_grants SET revoked_at=now() WHERE subject_id=$1", staff.id)
    async with owner_connection(database_owner_url) as conn:
        assert not await demo_seed.owned(conn, "identity_accounts", {"id": click_seller.id}, click_seller.key)
        assert await demo_seed.recorded(conn, "identity_accounts", {"id": click_seller.id})
        assert await conn.fetchval("SELECT count(*) FROM identity_private_applications WHERE id=$1", click_case) == 0
    before = len(await handoffs(database_owner_url))
    result = await demo_seed.apply(settings)
    # Withdrawn for the three, still ready for the click-test staff, whose rows are untouched.
    assert result["L02.membership"] == membership_counts(kept=2, handoff_sent=1, handoff_withdrawn=3)
    assert result["L01.accounts"] == {"created": 0, "kept": 9, "foreign": 1}
    assert vouched((await handoffs(database_owner_url))[before:]) == sorted(
        each("withdrawn", [("demo", "seller"), ("click-test", "seller"), ("demo", "staff")])
        + each("ready", [("click-test", "staff")]))
    # Restored in the app, the demo seller is vouched for again; while a live writer holds the click-test
    # staff's account, its handoff is withdrawn rather than waited for (busy).
    async with owner_connection(database_owner_url) as conn:
        await conn.execute("UPDATE identity_accounts SET status='active' WHERE id=$1", seller.id)
    writer = await asyncpg.connect(database_owner_url)
    try:
        async with writer.transaction():
            await writer.execute("SELECT 1 FROM identity_accounts WHERE id=$1 FOR UPDATE", click_staff.id)
            before = len(await handoffs(database_owner_url))
            result = await demo_seed.apply(settings)
    finally:
        await writer.close()
    assert result["L02.membership"] == membership_counts(kept=2, handoff_sent=1, handoff_withdrawn=2,
                                                         handoff_busy=1)
    assert vouched((await handoffs(database_owner_url))[before:]) == sorted(
        each("withdrawn", [("click-test", "seller"), ("demo", "staff"), ("click-test", "staff")])
        + each("ready", [("demo", "seller")]))


async def test_only_the_seed_draws_identitys_handoff_order(database_url, database_owner_url):
    # The running app's role can neither draw, set nor read Identity's handoff order; only the owner role can.
    app = await asyncpg.connect(database_url)
    try:
        for query in (f"SELECT nextval('{demo_seed.HANDOFF_SEQUENCE}')",
                      f"SELECT setval('{demo_seed.HANDOFF_SEQUENCE}', 1000)",
                      f"SELECT last_value FROM {demo_seed.HANDOFF_SEQUENCE}"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await app.fetchval(query)
    finally:
        await app.close()
    async with owner_connection(database_owner_url) as conn:
        first = await conn.fetchval(f"SELECT nextval('{demo_seed.HANDOFF_SEQUENCE}')")
        assert await conn.fetchval(f"SELECT nextval('{demo_seed.HANDOFF_SEQUENCE}')") == first + 1


async def test_without_its_key_identity_sends_no_handoff_and_a_key_paired_with_another_fails_the_step(
    database_owner_url, seeding, monkeypatch, capsys
):
    settings = seed_settings(database_owner_url)
    monkeypatch.delenv(demo_seed.HANDOFF_PRIVATE_KEY)
    capsys.readouterr()
    # Without the key every row is still seeded, but nothing is sent, and the seed says it is partial.
    assert await demo_seed.apply(settings) == {
        **FIRST_RUN, "L02.membership": membership_counts(created=2, handoff_unsigned=4)}
    assert await handoffs(database_owner_url) == []
    log = capsys.readouterr().err
    assert f"DEMO SEED identity-handoff: unsigned: {demo_seed.HANDOFF_PRIVATE_KEY} is not set; nothing sent\n" in log
    assert finished(log) == {"L02.membership"}
    # A handoff key that is no key, or the pair of another key Identity holds, fails the step: nothing is sent.
    for name, value in ((demo_seed.HANDOFF_PRIVATE_KEY, "not a key"), ("BT_EVENT_PRIVATE_KEY", HANDOFF_PRIVATE),
                        ("BT_AUTH_PRIVATE_KEY", HANDOFF_PRIVATE), ("BT_SERVICE_AUTH_PUBLIC_KEY", HANDOFF_PUBLIC)):
        with monkeypatch.context() as patched:
            patched.setenv(demo_seed.HANDOFF_PRIVATE_KEY, HANDOFF_PRIVATE)
            patched.setenv(name, value)
            assert (await demo_seed.apply(settings))["L02.membership"] == {"failed": "HandoffKey"}
    assert await handoffs(database_owner_url) == []
    # With the key, the next run hands off all four.
    monkeypatch.setenv(demo_seed.HANDOFF_PRIVATE_KEY, HANDOFF_PRIVATE)
    assert await demo_seed.apply(settings) == LATER_RUN
    assert vouched(await handoffs(database_owner_url)) == each("ready")
    # Removal without the key cannot sign a withdrawal: each still ready is counted and logged, and none is sent.
    monkeypatch.delenv(demo_seed.HANDOFF_PRIVATE_KEY)
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    capsys.readouterr()
    assert await demo_seed.apply(settings) == removal(blocked="active-grant", unsigned=4)
    log = capsys.readouterr().err
    for sample_set, holder in ALL_HOLDERS:
        assert (f"DEMO SEED remove: unsigned {demo_seed.handoff_key(sample_set, holder)}: "
                f"{demo_seed.HANDOFF_PRIVATE_KEY} is not set; not withdrawn\n") in log
    assert vouched(await handoffs(database_owner_url)) == each("ready")
    # A wrongly paired key fails the whole removal, which then writes and deletes nothing.
    before = await contents(database_owner_url)
    monkeypatch.setenv(demo_seed.HANDOFF_PRIVATE_KEY, HANDOFF_PRIVATE)
    monkeypatch.setenv("BT_EVENT_PRIVATE_KEY", HANDOFF_PRIVATE)
    assert await demo_seed.apply(settings) == {"remove": {"failed": "HandoffKey"}}
    assert await contents(database_owner_url) == before


async def test_each_row_a_handoff_vouches_for_stays_locked_from_before_its_check_until_the_handoff_commits(
    database_owner_url, seeding, monkeypatch
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    locked_owned, born = demo_seed.locked_owned, demo_seed.born
    checking, held = [], []

    async def locking(tx, table, row, *args, **kwargs):
        checking.append((table, row))
        try:
            return await locked_owned(tx, table, row, *args, **kwargs)
        finally:
            checking.pop()

    async def checked(tx, table):
        # Called after the row's lock and before its check: another connection tries to delete exactly that row,
        # the first half of any replacement, and finds it held.
        if checking and checking[-1][0] == table:
            row = checking[-1][1]
            async with owner_connection(database_owner_url) as other:
                await other.execute("SET lock_timeout = '200ms'")
                attempt = other.transaction()
                await attempt.start()
                try:
                    with pytest.raises(asyncpg.LockNotAvailableError):
                        await other.execute(f"DELETE FROM {demo_seed.quote(table)} WHERE id=$1", row["id"])
                finally:
                    await attempt.rollback()
            held.append(table)
        return await born(tx, table)

    monkeypatch.setattr(demo_seed, "locked_owned", locking)
    monkeypatch.setattr(demo_seed, "born", checked)
    before = await contents(database_owner_url)
    count = len(await handoffs(database_owner_url))
    assert await demo_seed.apply(settings) == LATER_RUN
    # Every account, and each staff's business, membership and grant, was held across its check.
    assert sorted(held) == sorted(["identity_accounts"] * 4
                                  + ["l02_businesses", "l02_memberships", "identity_access_grants"] * 2)
    renewed(before, await contents(database_owner_url), 4)
    assert vouched((await handoffs(database_owner_url))[count:]) == each("ready")


async def test_a_row_replaced_or_changed_right_before_its_lock_is_caught_on_the_locked_row(
    database_owner_url, seeding, monkeypatch
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    staff, click_seller = demo_seed.account("demo", "staff"), demo_seed.account("click-test", "seller")
    async with owner_connection(database_owner_url) as conn:
        grant = await conn.fetchrow("SELECT * FROM identity_access_grants WHERE subject_id=$1", staff.id)
    targets = {("identity_access_grants", grant["id"]), ("identity_accounts", click_seller.id)}
    locked_owned, changed = demo_seed.locked_owned, []

    async def change_first(tx, table, row, *args, **kwargs):
        # Committed by another connection after this handoff's earlier checks, right before this row's lock.
        if (table, row["id"]) in targets and table not in changed:
            async with owner_connection(database_owner_url) as other:
                async with other.transaction():
                    if table == "identity_accounts":
                        await other.execute("UPDATE identity_accounts SET status='suspended' WHERE id=$1", row["id"])
                    else:
                        # Made again at the same id with the same fields: only its incarnation differs.
                        await other.execute("DELETE FROM identity_access_grants WHERE id=$1", grant["id"])
                        await other.execute(
                            """INSERT INTO identity_access_grants(id,subject_id,organization_id,role,permissions)
                            VALUES($1,$2,$3,$4,$5)""", grant["id"], grant["subject_id"], grant["organization_id"],
                            grant["role"], grant["permissions"])
            changed.append(table)
        return await locked_owned(tx, table, row, *args, **kwargs)

    monkeypatch.setattr(demo_seed, "locked_owned", change_first)
    count = len(await handoffs(database_owner_url))
    result = await demo_seed.apply(settings)
    assert sorted(changed) == ["identity_access_grants", "identity_accounts"]
    # The grant made again and the seller suspended are each caught on the row the handoff then holds.
    assert result["L02.membership"] == membership_counts(kept=2, handoff_sent=2, handoff_withdrawn=2)
    assert vouched((await handoffs(database_owner_url))[count:]) == sorted(
        each("withdrawn", [("demo", "staff"), ("click-test", "seller")])
        + each("ready", [("demo", "seller"), ("click-test", "staff")]))


async def test_a_live_writer_on_a_seller_or_staff_account_skips_that_holder_without_waiting(
    database_owner_url, seeding, capsys
):
    settings = seed_settings(database_owner_url)
    modules = {item.id: item for item in discover(settings.modules_path)}
    for module_id in ("L01.accounts", "L02.businesses"):
        assert await demo_seed.entry(modules[module_id], settings) == FIRST_RUN[module_id]
    seller, staff = demo_seed.account("demo", "seller"), demo_seed.account("demo", "staff")

    async def held(account_id, module_id):
        """The step's counts while a live writer holds this account, as a password change would; a wait would
        end at the lock limit with an error instead."""
        writer = await asyncpg.connect(database_owner_url)
        try:
            async with writer.transaction():
                await writer.execute("SELECT 1 FROM identity_accounts WHERE id=$1 FOR UPDATE", account_id)
                return await demo_seed.entry(modules[module_id], settings)
        finally:
            await writer.close()

    capsys.readouterr()
    assert await held(seller.id, "L01.private-seller") == seller_counts(created=1, busy=1)
    # The staff's membership is skipped, and its handoff, with none sent before, waits for a later run.
    assert await held(staff.id, "L02.membership") == membership_counts(
        created=1, busy=1, handoff_sent=3, handoff_busy=1)
    log = capsys.readouterr().err
    case = demo_seed.demo_key("demo", "application", "seller")
    assert f"DEMO SEED identity-private-seller: busy {case}: the seller account is being changed\n" in log
    assert (f"DEMO SEED identity-membership: busy {demo_seed.business('demo').membership_key}: "
            "the staff account is being changed\n") in log
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM identity_private_applications WHERE subject_id=$1", seller.id) == 0
        assert await conn.fetchval("SELECT count(*) FROM l02_memberships WHERE subject_id=$1", staff.id) == 0
    assert vouched(await handoffs(database_owner_url)) == each(
        "ready", [("demo", "seller"), ("click-test", "seller"), ("click-test", "staff")])
    # Released, the next run completes both.
    assert await demo_seed.entry(modules["L01.private-seller"], settings) == seller_counts(created=1, kept=1)
    assert await demo_seed.entry(modules["L02.membership"], settings) == membership_counts(
        created=1, kept=1, handoff_sent=4)


async def test_a_live_writer_on_the_staff_grant_withdraws_that_handoff_rather_than_waiting(
    database_owner_url, seeding
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    staff = demo_seed.account("demo", "staff")
    writer = await asyncpg.connect(database_owner_url)
    try:
        async with writer.transaction():
            # A live writer holds the demo staff's grant itself, as the app's revoke would.
            await writer.execute("SELECT 1 FROM identity_access_grants WHERE subject_id=$1 FOR UPDATE", staff.id)
            count = len(await handoffs(database_owner_url))
            result = await demo_seed.apply(settings)
    finally:
        await writer.close()
    assert result == {**LATER_RUN, "L02.membership": membership_counts(kept=2, handoff_sent=3, handoff_busy=1)}
    assert vouched((await handoffs(database_owner_url))[count:]) == sorted(
        each("withdrawn", [("demo", "staff")])
        + each("ready", [("demo", "seller"), ("click-test", "seller"), ("click-test", "staff")]))
    # Released, the next run vouches for it again.
    count = len(await handoffs(database_owner_url))
    assert await demo_seed.apply(settings) == LATER_RUN
    assert vouched((await handoffs(database_owner_url))[count:]) == each("ready")


async def test_the_sign_in_owner_check_tells_owned_foreign_stale_and_missing(database_owner_url, seeding):
    async def owners():
        async with owner_connection(database_owner_url) as conn:
            async with conn.transaction():
                return {(sample_set, role): await demo_seed.account_owner(conn, sample_set, role)
                        for sample_set in demo_seed.SETS for role in demo_seed.SIGN_IN_ROLES}

    assert set((await owners()).values()) == {"missing"}
    buyer, rival = demo_seed.account("demo", "buyer"), demo_seed.account("click-test", "rival")
    async with owner_connection(database_owner_url) as conn:
        # Someone else's account at one pinned id, and at another pinned address.
        await insert_account(conn, buyer.id, "someone.else@example.test")
        await insert_account(conn, uuid4(), rival.email)
    assert (await demo_seed.apply(seed_settings(database_owner_url)))["L01.accounts"] == {
        "created": 8, "kept": 0, "foreign": 2}
    found = await owners()
    assert {key for key, value in found.items() if value == "foreign"} == {("demo", "buyer"), ("click-test", "rival")}
    assert {value for key, value in found.items() if key not in {("demo", "buyer"), ("click-test", "rival")}} == {
        "owned"}
    moved, remade, gone_account = (demo_seed.account("demo", "seller"), demo_seed.account("click-test", "buyer"),
                                   demo_seed.account("demo", "rival"))
    async with owner_connection(database_owner_url) as conn:
        # An ordinary edit keeps it the seed's own: its incarnation is its creation time.
        await conn.execute("UPDATE identity_accounts SET display_name='Lina S.' WHERE id=$1",
                           demo_seed.account("demo", "staff").id)
        # Moved to another address; deleted and made again at the same id and address; deleted outright.
        await conn.execute("UPDATE identity_accounts SET email='someone.moved@example.test' WHERE id=$1", moved.id)
        async with conn.transaction():
            row = await conn.fetchrow("DELETE FROM identity_accounts WHERE id=$1 RETURNING *", remade.id)
            await conn.execute("""INSERT INTO identity_accounts(id,email,display_name,password_hash)
                VALUES($1,$2,$3,$4)""", row["id"], row["email"], row["display_name"], row["password_hash"])
        await conn.execute("DELETE FROM identity_accounts WHERE id=$1", gone_account.id)
    found = await owners()
    assert {key for key, value in found.items() if value == "stale"} == {
        ("demo", "seller"), ("click-test", "buyer"), ("demo", "rival")}
    assert found[("demo", "staff")] == "owned"
    seed_only = loaded("L01.accounts", "security.py:seed_only")
    async with owner_connection(database_owner_url) as conn:
        # A stale account stays password-free: the record still holds its id.
        for person in (moved, remade, gone_account):
            assert await seed_only(conn, person.id)
            # Moved, it is still the seed's row (id, demo key, incarnation) and reads stale only for sign-in.
            assert await demo_seed.owned(conn, "identity_accounts", {"id": person.id}, person.key) == (person is moved)
        assert not await seed_only(conn, buyer.id)
        # It locks what it read until the sign-in's transaction ends, so the answer cannot change meanwhile.
        other = await asyncpg.connect(database_owner_url)
        try:
            async with conn.transaction():
                staff = demo_seed.account("demo", "staff")
                assert await demo_seed.account_owner(conn, "demo", "staff") == "owned"
                with pytest.raises(asyncpg.LockNotAvailableError):
                    await other.execute("SELECT 1 FROM identity_accounts WHERE id=$1 FOR UPDATE NOWAIT", staff.id)
        finally:
            await other.close()
        for sample_set, role in (("demo", "operator"), ("live", "buyer")):
            with pytest.raises(ValueError):
                await demo_seed.account_owner(conn, sample_set, role)


# Seed steps that stall, for the hard deadline: one at import, before any real step, and one after every real
# step, holding the seed's transaction with the server's own limits off, so only the dropped client ends it.
EARLY_STALL = '''import os
import time

with open(os.environ["STALL_MARK"], "w") as mark:
    mark.write(str(os.getpid()))
time.sleep(3600)
'''
LATE_STALL = '''import asyncio
import os
import time
from bt_runtime import demo_seed


async def apply(settings):
    async with demo_seed.transaction(settings.database_url, "stall") as tx:
        await tx.execute("SET LOCAL statement_timeout = 0")
        await tx.execute("SET LOCAL idle_in_transaction_session_timeout = 0")
        if os.environ["STALL_IN"] == "statement":
            asyncio.ensure_future(tx.execute("SELECT pg_sleep(3600)"))
            await asyncio.sleep(0.5)
        with open(os.environ["STALL_MARK"], "w") as mark:
            mark.write(str(os.getpid()))
        time.sleep(3600)
'''
STALLED = {"statement": "state='active' AND query='SELECT pg_sleep(3600)'", "idle": "state='idle in transaction'"}
ENTRY_COMMAND = [sys.executable, "-m", "service_app.migrate"]


def stall_modules(tmp_path, stage):
    """The service's real modules, copied (they migrate as the same steps), plus one seed step that stalls."""
    real = Settings(database_url="postgresql://unused/unused", service_name="identity").modules_path
    root = tmp_path / "modules"
    shutil.copytree(real, root, ignore=shutil.ignore_patterns("__pycache__"))
    stub = root / f"stall-{stage}"
    stub.mkdir()
    manifest = {"version": 1, "fixtures": {demo_seed.ENTRY: "deploy_seed.py:apply"}}
    if stage == "early":
        manifest["id"] = "L00.stall-early"
        (stub / "deploy_seed.py").write_text(EARLY_STALL)
    else:
        # After every real module, with a migration of its own that the same pre-deploy step applies first.
        manifest.update(id="L25.stall-late", migration_dependencies=[item.id for item in discover(real)],
                        migrations=["migrations/L25_0001_stall_probe.sql"])
        (stub / "migrations").mkdir()
        (stub / "migrations" / "L25_0001_stall_probe.sql").write_text("CREATE TABLE stall_probe (id integer);\n")
        (stub / "deploy_seed.py").write_text(LATE_STALL)
    (stub / "module.json").write_text(json.dumps(manifest))
    return root


def predeploy_environment(url, **extra):
    return {**os.environ, "BT_DATABASE_URL": url, "BT_SERVICE_NAME": "identity",
            demo_seed.SWITCH: demo_seed.SWITCH_VALUE, **extra}


def lowered(hard):
    """The same pre-deploy entry, run as its own __main__, with only the hard limit lowered."""
    return [sys.executable, "-c",
            "import runpy, bt_runtime.demo_seed_deadline as d; "
            f"d.HARD_SECONDS = {hard}; d.BOUND_SECONDS = d.HARD_SECONDS + d.REAP_SECONDS + d.RELAY_SECONDS; "
            "runpy.run_module('service_app.migrate', run_name='__main__', alter_sys=True)"]


async def predeploy(command, environment, **streams):
    """Run the pre-deploy step as the deploy does: in the runtime folder, with the migration connection."""
    started = time.monotonic()
    step = await asyncio.to_thread(subprocess.run, command, cwd=RUNTIME, env=environment, timeout=120, **streams)
    return step, time.monotonic() - started


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


async def test_a_seed_stalled_before_its_first_step_is_stopped_at_the_hard_limit(database_owner_url, tmp_path):
    mark = tmp_path / "stalled.pid"
    environment = predeploy_environment(
        database_owner_url, BT_MODULES_PATH=str(stall_modules(tmp_path, "early")), STALL_MARK=str(mark))
    # The real entry and the real limit: module discovery and import are inside it too.
    step, spent = await predeploy(ENTRY_COMMAND, environment, capture_output=True, text=True)
    assert step.returncode == 0, step.stderr
    assert demo_seed_deadline.HARD_SECONDS <= spent < demo_seed_deadline.BOUND_SECONDS + 15
    assert demo_seed_deadline.STOPPED.decode() in step.stderr
    assert "DEMO SEED L01" not in step.stderr
    assert gone(int(mark.read_text()))
    assert await ledger(database_owner_url) == {}


@pytest.mark.parametrize("stall", ["idle", "statement"])
async def test_a_seed_stalled_after_its_steps_is_stopped_and_the_server_ends_its_session(
    database_owner_url, tmp_path, stall
):
    hard = 12
    mark = tmp_path / "stalled.pid"
    environment = predeploy_environment(
        database_owner_url, BT_MODULES_PATH=str(stall_modules(tmp_path, "late")), STALL_MARK=str(mark),
        STALL_IN=stall)
    running_step = asyncio.ensure_future(predeploy(lowered(hard), environment, capture_output=True, text=True))
    while not mark.exists() and not running_step.done():
        await asyncio.sleep(0.1)
    async with owner_connection(database_owner_url) as conn:
        # Stalled inside the seed's transaction: in a server statement, or idle with the transaction open.
        stalled = await conn.fetchval(f"""SELECT count(*) FROM pg_stat_activity WHERE application_name='bt-demo-seed'
            AND datname=current_database() AND {STALLED[stall]}""")
    step, spent = await running_step
    assert step.returncode == 0, step.stderr
    assert stalled == 1
    assert spent < hard + demo_seed_deadline.REAP_SECONDS + demo_seed_deadline.RELAY_SECONDS + 15
    # Every real step's line came through, and then the deadline's own.
    assert "DEMO SEED L01.accounts: created=10 foreign=0 kept=0\n" in step.stderr
    assert step.stderr.index("DEMO SEED L02.membership: ") < step.stderr.index(demo_seed_deadline.STOPPED.decode())
    assert gone(int(mark.read_text()))
    # The server ends the killed seed's session on its own: at once when idle, at its next check of the client
    # in a statement. Then nothing of the seed's is held: its lock is free.
    await seed_backends_gone(database_owner_url, 5)
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT to_regclass('stall_probe') IS NOT NULL")
        assert await conn.fetchval("SELECT pg_try_advisory_lock(hashtextextended('demo-seed',0))")
        await conn.execute("SELECT pg_advisory_unlock(hashtextextended('demo-seed',0))")
    # What the real steps committed before the stall stays recorded.
    assert set((await ledger(database_owner_url)).values()) == SEED_KEYS


@pytest.mark.parametrize("log", ["closed", "broken", "full"])
async def test_a_failed_deploy_log_never_changes_or_holds_up_the_pre_deploy_step(database_owner_url, log):
    command, streams, ends = ENTRY_COMMAND, {"stdout": subprocess.DEVNULL}, []
    if log == "closed":
        command = ["sh", "-c", 'exec 2>&-; exec "$0" -m service_app.migrate', sys.executable]
    else:
        read, write = os.pipe()
        ends = [write]
        if log == "broken":
            os.close(read)
        else:
            # A deploy log nobody reads any more: every write to it would block.
            ends.append(read)
            os.set_blocking(write, False)
            with contextlib.suppress(BlockingIOError):
                while True:
                    os.write(write, b"x" * 65536)
            os.set_blocking(write, True)
        streams["stderr"] = write
    try:
        step, spent = await predeploy(command, predeploy_environment(database_owner_url), **streams)
    finally:
        for end in ends:
            os.close(end)
    assert step.returncode == 0
    assert spent < demo_seed_deadline.BOUND_SECONDS + 15
    # The seed itself ran to the end; only its lines were lost.
    assert set((await ledger(database_owner_url)).values()) == SEED_KEYS


@contextlib.contextmanager
def silent_server():
    """A port that accepts a connection and never answers it."""
    server = socket.create_server(("127.0.0.1", 0))
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


def unreachable(port):
    return Settings(database_url=f"postgresql://seed@127.0.0.1:{port}/none", service_name="identity")


def test_a_database_that_never_answers_costs_only_the_connect_limit(monkeypatch, capsys):
    monkeypatch.setattr(demo_seed, "CONNECT_SECONDS", 0.5)
    with silent_server() as port:
        started = time.monotonic()
        assert demo_seed.run(unreachable(port), {demo_seed.SWITCH: demo_seed.REMOVE_VALUE}) == {
            "remove": {"failed": "timeout"}}
        monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
        result = demo_seed.run(unreachable(port))
        spent = time.monotonic() - started
    assert set(result) == set(FIRST_RUN) and all(value == {"failed": "timeout"} for value in result.values())
    assert spent < 6
    assert "127.0.0.1" not in capsys.readouterr().err


def test_a_database_that_refuses_costs_nothing(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
    started = time.monotonic()
    result = demo_seed.run(unreachable(port))
    assert set(result) == set(FIRST_RUN) and all(set(value) == {"failed"} for value in result.values())
    assert time.monotonic() - started < 10

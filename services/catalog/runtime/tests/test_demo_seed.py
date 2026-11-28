"""Deploy-applied demo seed against a real, migrated Catalog database (hosted CI).

Covers the ownership record and the removal command, Identity's signed handoff (none yet; ready, withdrawn,
stale and out of order by Identity's order, whatever its clock says; receipts the record does not hold, edited,
made again, lost or replaced, and a newest withdrawal lost or replaced with an older ready behind it; receipts the
running app's role stores itself, which never admit; the receipt function's own refusals and its signed ingress;
a withdrawal arriving between a step's check and its write, and a step meeting a handoff that is arriving), drafts
and photo ids the seed did not create, a removal racing a writer, rows made again or edited on a recorded key, and
a photo step that hangs, both inside the seed's own budget and inside the real pre-deploy step.
Identity's handoff key pair is made here for these tests only and never stored; Catalog gets only its public half.
"""
import asyncio
import contextlib
import errno
import hashlib
import io
import itertools
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

import asyncpg
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from PIL import Image
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import consume
from bt_runtime import demo_seed
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from modules.listings.handoff import REASONS, fields as signed_fields, receive

# What saving a draft and attaching its photo write, and nothing publishing, quoting or auctioning writes.
SEEDED_TABLES = {"catalog_listings", "catalog_media", "catalog_media_variants", "outbox"}
# Identity's handoff receipts and their ingress entries, which the receipt function records.
HANDOFF_TABLES = {"demo_seed_handoffs", "inbox"}
# Each holder's newest order received, which only the receipt function moves and removal keeps.
MARKS = "demo_seed_handoff_marks"
INVALID = "the newest Identity handoff is missing or fails its check"
CONSUMER = "catalog.moderation.v1"
RUNTIME = Path(__file__).resolve().parents[1]


def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


# Identity's disposable handoff key pair for these tests, and Identity's order for every handoff they send.
HANDOFF_PRIVATE, HANDOFF_PUBLIC = key_pair()
ORDER = itertools.count(1)


@pytest.fixture(autouse=True)
def handoff_key(monkeypatch):
    # Catalog holds only the public half, as in the throwaway environment.
    monkeypatch.setenv(demo_seed.HANDOFF_PUBLIC_KEY, HANDOFF_PUBLIC)
    monkeypatch.delenv(demo_seed.HANDOFF_PRIVATE_KEY, raising=False)


def drafts_counts(**counts):
    return {"created": 0, "kept": 0, "foreign": 0, **dict.fromkeys(REASONS, 0), **counts}


def photo_counts(**counts):
    return {"attached": 0, "unchanged": 0, **dict.fromkeys(REASONS, 0), **counts}


FIRST_RUN = {"L03.listings": drafts_counts(created=6), "L03.media": photo_counts(attached=6)}
LATER_RUN = {"L03.listings": drafts_counts(kept=6), "L03.media": photo_counts(unchanged=6)}
PRIMARY_KEY = """SELECT array_agg(a.attname::text ORDER BY a.attnum) FROM pg_index i
    JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
    WHERE i.indrelid=$1::text::regclass AND i.indisprimary"""


def seed_settings(url):
    # The pre-deploy step runs the seed with the owner connection, right after migrations.
    return Settings(database_url=url, service_name="catalog")


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


def drafts_only(record):
    """The record's entries for the seed's own drafts, photos and events, without Identity's handoff receipts."""
    return {key: value for key, value in record.items() if key[0] not in HANDOFF_TABLES}


def unchanged(before, after):
    return all(key in after and after[key] == value for key, value in before.items())


@contextlib.asynccontextmanager
async def owner_connection(url):
    conn = await asyncpg.connect(url)
    try:
        yield conn
    finally:
        await conn.close()


def demo_root(path):
    # Synthetic stand-ins for the repository photos, attributed the way the real files are.
    root = path / "demo"
    (root / "watches").mkdir(parents=True)
    assets = []
    for number, colour in ((1, (140, 90, 60)), (2, (60, 90, 140)), (3, (90, 140, 60))):
        asset = {
            "id": f"IMG-0{number}",
            "file": f"watch-{number}.jpg",
            "author": "Fixture author",
            "credit": "Synthetic image fixture, CC0 1.0",
            "license": "CC0 1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "source_url": f"https://example.test/fixture-{number}",
        }
        output = io.BytesIO()
        Image.new("RGB", (800, 600), colour).save(output, "JPEG")
        content = output.getvalue()
        text = (
            f"Author: {asset['author']}\nSource: {asset['source_url']}\n"
            f"License: {asset['license_url']}\nLicense name: {asset['license']}\n"
        ).encode()
        content = content[:2] + b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text + content[2:]
        (root / "watches" / asset["file"]).write_bytes(content)
        asset["local_sha256"] = hashlib.sha256(content).hexdigest()
        assets.append(asset)
    (root / "images-manifest.json").write_text(json.dumps({"assets": assets}))
    return root


def stuck_root(path):
    """A photo folder whose manifest never arrives: reading it blocks until someone writes to it."""
    root = path / "stuck"
    root.mkdir(parents=True)
    os.mkfifo(root / "images-manifest.json")
    return root


def release(root):
    """Unblock a reader still waiting on a stuck manifest, so no thread outlives the test."""
    for _ in range(50):
        try:
            handle = os.open(root / "images-manifest.json", os.O_WRONLY | os.O_NONBLOCK)
        except OSError as error:
            if error.errno != errno.ENXIO:
                raise
            time.sleep(0.1)
            continue
        os.write(handle, b"{}")
        os.close(handle)
        return


@pytest.fixture
def seeding(tmp_path, monkeypatch):
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
    monkeypatch.setenv("BT_DEMO_ROOT", str(demo_root(tmp_path)))


def item(sample_set, name):
    return next(entry for entry in demo_seed.listings() if (entry.sample_set, entry.item) == (sample_set, name))


async def insert_listing(conn, listing_id, demo_key=None):
    await conn.execute(
        """INSERT INTO catalog_listings(id,owner_subject_id,seller_type,seller_label,physical_watch_id,
        facts,is_demo,demo_key) VALUES($1,$2,'private','Not seeded',$3,'{}'::jsonb,$4,$5)""",
        listing_id,
        uuid4(),
        uuid4(),
        demo_key is not None,
        demo_key,
    )


def handoff_event(sample_set, holder, state="ready", issued=None, seq=None):
    """Identity's signed handoff as its relay delivers it: by default ready, issued just now and Identity's newest."""
    return demo_seed.handoff_event(
        HANDOFF_PRIVATE, sample_set, holder, state, next(ORDER) if seq is None else seq, issued=issued
    )


async def consume_once(runtime_url, envelope):
    """One delivery through Catalog's own event ingress, as the running app's role receives it."""
    conn = await asyncpg.connect(runtime_url)
    try:
        async with conn.transaction():
            return await consume(conn, CONSUMER, envelope, receive)
    finally:
        await conn.close()


async def deliver(runtime_url, sample_set, holder, state="ready", issued=None, seq=None):
    envelope = handoff_event(sample_set, holder, state, issued, seq)
    assert await consume_once(runtime_url, envelope)
    return envelope


async def marks(url):
    async with owner_connection(url) as conn:
        rows = await conn.fetch(f"SELECT sample_set, holder, seq, event_id FROM {MARKS}")
    return {(row["sample_set"], row["holder"]): (row["seq"], row["event_id"]) for row in rows}


async def insert_foreign_handoff(conn, sample_set, holder, subject=None, business=None, state="ready"):
    """A receipt the receipt function never stored, as only the owner role could write it, signed with Identity's
    own key and at Identity's newest order: neither the record nor the holder's mark names it, so it never counts."""
    vouched_subject, vouched_business = demo_seed.handoff_ids(sample_set, holder)
    row = {"event_id": uuid4(), "sample_set": sample_set, "holder": holder, "subject_id": subject or vouched_subject,
           "business_id": business or vouched_business, "state": state, "seq": next(ORDER),
           "issued_at": datetime.now(timezone.utc)}
    row["assertion"] = demo_seed.sign_handoff(
        HANDOFF_PRIVATE, row["event_id"], row["seq"], signed_fields(row), row["issued_at"]
    )
    await conn.execute(
        f"""INSERT INTO demo_seed_handoffs({",".join(row)}) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""", *row.values()
    )
    return row["event_id"]


async def resign(conn, sample_set, holder, **changes):
    """The owner role's edit of one holder's stored receipts, signed again with Identity's own key over the edited
    fields, so only the comparison with the expected account and business can refuse them."""
    rows = await conn.fetch("SELECT * FROM demo_seed_handoffs WHERE sample_set=$1 AND holder=$2", sample_set, holder)
    for row in rows:
        edited = {**dict(row), **changes}
        assertion = demo_seed.sign_handoff(
            HANDOFF_PRIVATE, edited["event_id"], edited["seq"], signed_fields(edited), edited["issued_at"]
        )
        await conn.execute(
            "UPDATE demo_seed_handoffs SET subject_id=$2,business_id=$3,assertion=$4 WHERE event_id=$1",
            edited["event_id"],
            edited["subject_id"],
            edited["business_id"],
            assertion,
        )


async def deliver_all(runtime_url, state="ready", issued=None):
    for sample_set in demo_seed.SETS:
        for holder in demo_seed.HOLDERS.values():
            await deliver(runtime_url, sample_set, holder, state, issued)


@pytest_asyncio.fixture
async def handed(database_url, monkeypatch):
    """Identity's ready handoff for every set and holder, as its relay delivers them once its own seed committed."""
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
    await deliver_all(database_url)


async def test_switch_off_or_unknown_writes_nothing(database_owner_url, seeding, monkeypatch):
    before = await contents(database_owner_url)
    monkeypatch.delenv(demo_seed.SWITCH)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {}
    for value in ("true", "Sample-Accounts-Only"):
        monkeypatch.setenv(demo_seed.SWITCH, value)
        assert await demo_seed.apply(seed_settings(database_owner_url)) == {}
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {"remove": {"removed": 0, "kept": 0}}
    assert await contents(database_owner_url) == before
    assert await ledger(database_owner_url) == {}


async def test_every_row_it_inserts_is_recorded_and_a_rerun_writes_nothing(database_owner_url, seeding, handed):
    before = await contents(database_owner_url)
    receipts = await ledger(database_owner_url)
    # The receipt function recorded each handoff and its ingress entry under that holder's handoff key.
    assert {table for table, _ in receipts} == HANDOFF_TABLES and len(receipts) == 8
    assert set(receipts.values()) == {
        demo_seed.handoff_key(sample_set, holder) for sample_set in demo_seed.SETS for holder in ("seller", "staff")
    }
    # Each holder's newest order received is marked, outside the record.
    assert set(await marks(database_owner_url)) == {
        (sample_set, holder) for sample_set in demo_seed.SETS for holder in ("seller", "staff")
    }
    assert await demo_seed.apply(seed_settings(database_owner_url)) == FIRST_RUN
    seeded = await contents(database_owner_url)
    record = await ledger(database_owner_url)
    # Exactly the new rows are in the record: every photo variant and event included.
    assert set(seeded) - set(before) == set(drafts_only(record))
    assert unchanged(before, seeded)
    assert {table for table, _ in drafts_only(record)} == SEEDED_TABLES
    assert set(drafts_only(record).values()) == {listing.key for listing in demo_seed.listings()}
    assert sum(table == "catalog_media_variants" for table, _ in record) == 18
    assert await demo_seed.apply(seed_settings(database_owner_url)) == LATER_RUN
    assert await contents(database_owner_url) == seeded
    assert await ledger(database_owner_url) == record
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM catalog_publications") == 0
        for listing in demo_seed.listings():
            row = await conn.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing.id)
            assert (row["demo_key"], row["is_demo"], row["status"], row["revision"]) == (listing.key, True, "draft", 2)
            assert (row["photo_ids"], row["cover_id"]) == ([listing.photo_id], listing.photo_id)
            assert row["physical_watch_id"] == listing.watch_id and row["seller_type"] == listing.seller
            if listing.seller == "private":
                owner = demo_seed.account(listing.sample_set, "seller").id
                assert (row["owner_subject_id"], row["organization_id"]) == (owner, None)
                assert row["seller_label"] == "Demonstration private seller"
            else:
                # Owned by that set's seeded sample staff, for that set's seeded sample business.
                staff = demo_seed.account(listing.sample_set, "staff").id
                business = demo_seed.business(listing.sample_set)
                assert (row["owner_subject_id"], row["organization_id"]) == (staff, business.id)
                assert row["seller_label"] == "Demonstration " + business.public_name
            assert "DEMO" not in row["seller_label"]
            facts = json.loads(row["facts"])
            if listing.item == "buy-now":
                assert (facts["reference"], facts["sale_mode"], facts["currency"], facts["price_minor"]) == (
                    "DEMO-WATCH-02",
                    "fixed_price",
                    "USD",
                    18000,
                )
            media = await conn.fetchrow("SELECT * FROM catalog_media WHERE id=$1", listing.photo_id)
            assert (media["listing_id"], media["kind"], media["private_bytes"]) == (listing.id, "public_photo", None)
            variants = await conn.fetch("SELECT variant FROM catalog_media_variants WHERE media_id=$1", media["id"])
            assert sorted(entry["variant"] for entry in variants) == ["card", "detail", "thumb"]


async def test_drafts_and_photo_ids_it_did_not_create_are_never_touched(database_owner_url, seeding, handed, capsys):
    taken, holder = item("demo", "auction"), item("click-test", "buy-now")
    other = uuid4()
    async with owner_connection(database_owner_url) as conn:
        # Someone else's draft on the auction's exact id and demo key, in the shape the photo step looks for.
        await insert_listing(conn, taken.id, taken.key)
        # Someone else's photo on one of the seed's pinned photo ids, and an ordinary listing.
        await insert_listing(conn, other)
        await conn.execute(
            """INSERT INTO catalog_media(id,listing_id,kind,content_hash,source_bytes,mime)
            VALUES($1,$2,'public_photo',$3,10,'image/jpeg')""",
            holder.photo_id,
            other,
            "0" * 64,
        )
    before = await contents(database_owner_url)
    first = {"L03.listings": drafts_counts(created=5, foreign=1), "L03.media": photo_counts(attached=4, unchanged=2)}
    assert await demo_seed.apply(seed_settings(database_owner_url)) == first
    after = await contents(database_owner_url)
    record = drafts_only(await ledger(database_owner_url))
    # Never updated, given a photo or recorded: every row it found is exactly as it was.
    assert unchanged(before, after)
    assert set(after) - set(before) == set(record)
    assert all(key not in record for key in before)
    log = capsys.readouterr().err
    assert f"DEMO SEED catalog-listings: foreign {taken.key}: pinned id, key or watch already in use\n" in log
    assert f"DEMO SEED catalog-media: foreign {holder.key}: pinned photo id already in use\n" in log
    async with owner_connection(database_owner_url) as conn:
        draft = await conn.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", holder.id)
        assert (draft["revision"], draft["photo_ids"], draft["cover_id"]) == (1, [], None)
        # The seller then edits a seeded draft in the app; the next deploy must not undo or re-photo it.
        edited = item("click-test", "auction")
        await conn.execute(
            "UPDATE catalog_listings SET photo_ids='{}',cover_id=NULL,revision=revision+1 WHERE id=$1", edited.id
        )
    later = await contents(database_owner_url)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(kept=5, foreign=1),
        "L03.media": photo_counts(unchanged=6),
    }
    assert await contents(database_owner_url) == later


async def test_removal_deletes_exactly_its_own_rows(database_owner_url, seeding, handed, monkeypatch, capsys):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    published, edited = item("demo", "buy-now"), item("click-test", "spare")
    other = uuid4()
    async with owner_connection(database_owner_url) as conn:
        # Someone else's listing, a publication that refers to one seed draft, and a seed draft its seller edited.
        await insert_listing(conn, other)
        await conn.execute(
            """INSERT INTO catalog_publications(id,listing_id,actor_id,base_revision,request)
            VALUES($1,$2,$3,2,'{}'::jsonb)""",
            uuid4(),
            published.id,
            demo_seed.account("demo", "staff").id,
        )
        await conn.execute(
            "UPDATE catalog_listings SET seller_label='Edited by its seller',revision=revision+1 WHERE id=$1", edited.id
        )
        # The relay's own edits to every event it delivered: a row's creation time, not its text, is its identity.
        await conn.execute("UPDATE outbox SET attempts=attempts+1,delivered_at=now()")
        # A receipt and an ingress entry the receipt function never stored, and another consumer's ingress entry:
        # removal goes by the record only, so it keeps them all, in the handoff table and the inbox alike.
        foreign = await insert_foreign_handoff(conn, "demo", "seller")
        await conn.execute("INSERT INTO inbox(consumer,event_id,source) VALUES($1,$2,'identity')", CONSUMER, foreign)
        await conn.execute("INSERT INTO inbox(consumer,event_id,source) VALUES('catalog.other.v1',$1,'trust')", uuid4())
    before = await contents(database_owner_url)
    record = await ledger(database_owner_url)
    handoffs = {key for key in before if key[0] == "demo_seed_handoffs"}
    assert len(handoffs) == 5 and sum(table == "demo_seed_handoffs" for table, _ in record) == 4
    capsys.readouterr()
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    removal = await demo_seed.apply(settings)
    remaining = await ledger(database_owner_url)
    assert removal == {"remove": {"removed": len(record) - len(remaining), "kept": 1}}
    # The draft a publication refers to is kept whole, its photo and events included, and stays recorded.
    assert set(remaining.values()) == {published.key}
    assert set(remaining) == {key for key, value in record.items() if value == published.key}
    after = await contents(database_owner_url)
    # Exactly the recorded rows were deleted, the edited draft and the four recorded receipts and their ingress
    # entries included; every other row is as it was.
    assert set(before) - set(after) == set(record) - set(remaining)
    assert set(after) <= set(before) and unchanged(after, before)
    assert key_of("catalog_listings", {"id": edited.id}) not in after
    assert key_of("catalog_listings", {"id": other}) in after
    assert {key for key in after if key[0] == "demo_seed_handoffs"} == {
        key_of("demo_seed_handoffs", {"event_id": str(foreign)})
    }
    assert sum(table == "inbox" for table, _ in after) == 2
    # Each holder's mark stays, so no receipt older than the newest one received can ever count again.
    assert len(await marks(database_owner_url)) == 4
    assert f"DEMO SEED remove: kept {published.key}: referenced\n" in capsys.readouterr().err
    # A second removal changes nothing.
    assert await demo_seed.apply(settings) == {"remove": {"removed": 0, "kept": 1}}
    assert await contents(database_owner_url) == after
    assert await ledger(database_owner_url) == remaining


async def test_drafts_wait_until_identity_hands_off_their_owner(database_url, database_owner_url, seeding, capsys):
    # Identity's seed failed, skipped a collision, or has not committed yet: no handoff has arrived.
    before = await contents(database_owner_url)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(waiting=6),
        "L03.media": photo_counts(unchanged=6),
    }
    assert await contents(database_owner_url) == before
    assert await ledger(database_owner_url) == {}
    # Each handoff admits exactly its own holder's drafts: here the private sellers', not yet the staff's.
    for sample_set in demo_seed.SETS:
        await deliver(database_url, sample_set, "seller")
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=2, waiting=4),
        "L03.media": photo_counts(attached=2, unchanged=4),
    }
    drafts = drafts_only(await ledger(database_owner_url))
    assert set(drafts.values()) == {item(name, "auction").key for name in demo_seed.SETS}
    log = capsys.readouterr().err
    assert "refused" not in log and "waiting" not in log


async def test_a_recorded_handoff_edited_to_name_another_account_or_business_refuses_its_drafts(
    database_url, database_owner_url, seeding, tmp_path, monkeypatch, capsys
):
    photos = os.environ["BT_DEMO_ROOT"]
    await deliver_all(database_url)
    async with owner_connection(database_owner_url) as conn:
        # Only the owner role can edit a stored receipt. The demo staff's now names another business, which
        # Identity's signature no longer covers; the click-test staff's names another account and is signed again
        # with Identity's own key, so only the comparison with the expected account refuses it. A fresh, ready,
        # signed receipt naming the right ones that the receipt function never stored changes nothing.
        await conn.execute(
            "UPDATE demo_seed_handoffs SET business_id=gen_random_uuid() WHERE sample_set='demo' AND holder='staff'"
        )
        await resign(conn, "click-test", "staff", subject_id=uuid4())
        await insert_foreign_handoff(conn, "click-test", "staff")
    before = await contents(database_owner_url)
    monkeypatch.setenv("BT_DEMO_ROOT", str(tmp_path / "missing"))
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=2, invalid=2, mismatched=2),
        "L03.media": {"failed": "FileNotFoundError"},
    }
    after = await contents(database_owner_url)
    record = drafts_only(await ledger(database_owner_url))
    assert unchanged(before, after) and set(after) - set(before) == set(record)
    assert set(record.values()) == {item(name, "auction").key for name in demo_seed.SETS}
    log = capsys.readouterr().err
    for listing in demo_seed.listings():
        differs = f"DEMO SEED catalog-listings: refused {listing.key}: the Identity handoff differs\n"
        fails = f"DEMO SEED catalog-listings: refused {listing.key}: {INVALID}\n"
        assert (differs in log, fails in log) == (
            (listing.seller, listing.sample_set) == ("dealer", "click-test"),
            (listing.seller, listing.sample_set) == ("dealer", "demo"),
        )
    # A recorded receipt edited to name another account after its draft was made: its photo is never attached.
    refused = item("demo", "auction")
    async with owner_connection(database_owner_url) as conn:
        await conn.execute(
            "UPDATE demo_seed_handoffs SET subject_id=gen_random_uuid() WHERE sample_set='demo' AND holder='seller'"
        )
    monkeypatch.setenv("BT_DEMO_ROOT", photos)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(kept=2, invalid=2, mismatched=2),
        "L03.media": photo_counts(attached=1, invalid=1, unchanged=4),
    }
    async with owner_connection(database_owner_url) as conn:
        draft = await conn.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", refused.id)
        assert (draft["revision"], draft["photo_ids"]) == (1, [])
        assert await conn.fetchval("SELECT count(*) FROM catalog_media WHERE id=$1", refused.photo_id) == 0


async def test_only_identitys_newest_fresh_ready_handoff_by_its_order_admits_its_drafts(
    database_url, database_owner_url, seeding, capsys
):
    now = datetime.now(timezone.utc)
    first, second, third, fourth = (next(ORDER) for _ in range(4))
    # Ready, then withdrawn: Identity's next run found the holder disabled, revoked, removed or made again.
    await deliver(database_url, "demo", "seller", issued=now - timedelta(minutes=2), seq=first)
    await deliver(database_url, "demo", "seller", "withdrawn", issued=now - timedelta(minutes=1), seq=second)
    # An older ready arriving after a withdrawal, as a retried delivery can, changes nothing, even when Identity's
    # clock was set back in between so the withdrawal carries the earlier time: Identity's order decides.
    await deliver(database_url, "click-test", "seller", "withdrawn", issued=now - timedelta(minutes=3), seq=fourth)
    await deliver(database_url, "click-test", "seller", issued=now - timedelta(minutes=1), seq=third)
    # Too old, as when Catalog deploys long after Identity sent it, and from a clock running far ahead.
    await deliver(database_url, "demo", "staff", issued=now - timedelta(seconds=demo_seed.HANDOFF_FRESH_SECONDS + 60))
    await deliver(
        database_url, "click-test", "staff", issued=now + timedelta(seconds=demo_seed.HANDOFF_SKEW_SECONDS + 60)
    )
    before = await contents(database_owner_url)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(withdrawn=2, stale=4),
        "L03.media": photo_counts(unchanged=6),
    }
    assert await contents(database_owner_url) == before
    assert drafts_only(await ledger(database_owner_url)) == {}
    log = capsys.readouterr().err
    for listing in demo_seed.listings():
        if listing.seller == "private":
            assert f"DEMO SEED catalog-listings: waiting {listing.key}: Identity withdrew its handoff\n" in log
        else:
            line = "the Identity handoff is not fresh; deploy Identity, then Catalog"
            assert f"DEMO SEED catalog-listings: waiting {listing.key}: {line}\n" in log
    newest = await marks(database_owner_url)
    assert (newest[("demo", "seller")][0], newest[("click-test", "seller")][0]) == (second, fourth)
    # Identity's next run, finding its rows current again, sends a fresh ready that admits them.
    await deliver(database_url, "demo", "seller")
    await deliver(database_url, "demo", "staff")
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=3, withdrawn=1, stale=2),
        "L03.media": photo_counts(attached=3, unchanged=3),
    }
    assert set(drafts_only(await ledger(database_owner_url)).values()) == {
        listing.key for listing in demo_seed.listings() if listing.sample_set == "demo"
    }


async def test_receipts_the_record_does_not_hold_or_that_were_made_again_never_admit(
    database_url, database_owner_url, seeding, monkeypatch, capsys
):
    async with owner_connection(database_owner_url) as conn:
        # Rows only the owner role could write, never through the receipt function: ready, fresh, naming exactly
        # the right account and business and signed with Identity's own key at its newest order, and still
        # ignored, as no holder's mark names them.
        for sample_set in demo_seed.SETS:
            await insert_foreign_handoff(conn, sample_set, "staff")
    for sample_set in demo_seed.SETS:
        await deliver(database_url, sample_set, "seller")
    async with owner_connection(database_owner_url) as conn:
        # The sellers' recorded receipts deleted and made again on the same event ids, orders and signatures:
        # rows the function never stored, which the record tells apart by their creation time.
        columns = ("event_id", "sample_set", "holder", "subject_id", "business_id", "state", "issued_at", "seq",
                   "assertion")
        rows = await conn.fetch("SELECT * FROM demo_seed_handoffs WHERE holder='seller'")
        await conn.execute("DELETE FROM demo_seed_handoffs WHERE holder='seller'")
        for row in rows:
            await conn.execute(
                f"""INSERT INTO demo_seed_handoffs({",".join(columns)}) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                *(row[name] for name in columns),
            )
    before = await contents(database_owner_url)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(waiting=4, invalid=2),
        "L03.media": photo_counts(unchanged=6),
    }
    assert await contents(database_owner_url) == before
    log = capsys.readouterr().err
    for listing in demo_seed.listings():
        line = f"DEMO SEED catalog-listings: refused {listing.key}: {INVALID}\n"
        assert (line in log) == (listing.seller == "private")
    # Removal keeps each made-again receipt with its ingress entry, and never touches the unrecorded ones.
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {"remove": {"removed": 0, "kept": 2}}
    log = capsys.readouterr().err
    for sample_set in demo_seed.SETS:
        assert f"DEMO SEED remove: kept {demo_seed.handoff_key(sample_set, 'seller')}: replaced\n" in log
    assert await contents(database_owner_url) == before


async def test_only_identitys_signed_pinned_handoff_is_received_and_only_while_the_seed_is_on(
    database_url, database_owner_url, tmp_path, monkeypatch
):
    service_key, public = key_pair()
    settings = Settings(database_url=database_url, service_name="catalog", service_auth_public_key=public)
    app = create_app(settings)

    def token(**patch):
        claims = {"sub": "identity", "iss": settings.auth_issuer, "aud": settings.service_name,
                  "iat": int(time.time()), "exp": int(time.time()) + 60, "type": "service"}
        return jwt.encode({**claims, **patch}, service_key, algorithm="RS256")

    def event(sample_set, holder, data=None, signer=HANDOFF_PRIVATE, **patch):
        """Identity's ready handoff with `data` changed, signed over the result by `signer`."""
        envelope = handoff_event(sample_set, holder)
        changed = {**envelope.data, **(data or {})}
        changed["assertion"] = demo_seed.sign_handoff(signer, envelope.id, changed["seq"], changed, envelope.time)
        return EventEnvelope(**{**envelope.model_dump(), "data": changed, **patch})

    def tampered(envelope, data=None, **patch):
        """Identity's handoff changed after it was signed."""
        return EventEnvelope(**{**envelope.model_dump(), "data": {**envelope.data, **(data or {})}, **patch})

    async def received():
        async with owner_connection(database_owner_url) as conn:
            return await conn.fetchval("SELECT count(*) FROM demo_seed_handoffs")

    staff = demo_seed.handoff_data("demo", "staff", "ready")
    other_seller = demo_seed.handoff_data("click-test", "seller", "ready")["subject_id"]
    seller = event("demo", "seller")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

            async def post(envelope, signed=None):
                headers = {} if signed is None else {"Authorization": "Bearer " + signed}
                return await client.post("/internal/v1/events", json=envelope.model_dump(mode="json"), headers=headers)

            async def refused(envelope, status, code):
                response = await post(envelope, token())
                return (response.status_code, response.json()["error"]["code"]) == (status, code)

            assert (await post(seller)).status_code == 401
            assert (await post(seller, token(aud="other"))).status_code == 401
            assert (await post(seller, token(sub="catalog"))).status_code == 403
            assert (await post(event("demo", "seller", source="catalog"), token(sub="catalog"))).status_code == 403
            # With Catalog's switch off it is refused, so the event stays pending at Identity.
            assert await refused(seller, 409, "demo_seed_off")
            assert await received() == 0
            monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
            # Catalog's handoff key missing, unreadable, the pair of its own service verifying key, or set beside
            # Identity's private half: refused before anything is read, so the event stays pending at Identity.
            for wrong_key in (
                {demo_seed.HANDOFF_PUBLIC_KEY: ""},
                {demo_seed.HANDOFF_PUBLIC_KEY: "not a key"},
                {demo_seed.HANDOFF_PUBLIC_KEY: public, "BT_SERVICE_AUTH_PUBLIC_KEY": public},
                {demo_seed.HANDOFF_PRIVATE_KEY: HANDOFF_PRIVATE},
            ):
                with monkeypatch.context() as patched:
                    for name, value in wrong_key.items():
                        patched.setenv(name, value)
                    assert await refused(seller, 409, "demo_seed_unkeyed")
            assert await received() == 0
            for wrong in (
                # Signed by Identity's handoff key, but not one of the pinned four or not agreeing with the event.
                event("demo", "seller", subject=str(uuid4())),
                event("demo", "seller", request_id="another-request"),
                event("demo", "staff", data={"business_id": None}),
                event("demo", "seller", data={"business_id": str(uuid4())}),
                event("demo", "seller", data={"holder": "operator"}),
                event("demo", "seller", data={"state": "revoked"}),
                event("demo", "seller", subject=other_seller, data={"subject_id": other_seller}),
                event("demo", "seller", subject=staff["subject_id"], data={"subject_id": staff["subject_id"]}),
                # Identity's order must be a whole number above zero.
                event("demo", "seller", data={"seq": 0}),
                event("demo", "seller", data={"seq": "1"}),
                event("demo", "seller", data={"seq": 2**63}),
                # The pinned tuple, but not Identity's signature over exactly this event: no assertion, an empty or
                # oversized one, junk, one made with Identity's service token key or any other key, or Identity's
                # own changed afterwards in its state, order, event id or time.
                tampered(seller, {"assertion": None}),
                tampered(seller, {"assertion": ""}),
                tampered(seller, {"assertion": "x" * (demo_seed.HANDOFF_ASSERTION_LIMIT + 1)}),
                tampered(seller, {"assertion": "not-a-signature"}),
                event("demo", "seller", signer=service_key),
                event("demo", "seller", signer=key_pair()[0]),
                tampered(seller, {"state": "withdrawn"}),
                tampered(seller, {"seq": seller.data["seq"] + 1}),
                tampered(seller, id=uuid4()),
                tampered(seller, time=seller.time + timedelta(microseconds=1)),
            ):
                assert await refused(wrong, 422, "invalid_event")
            missing = {name: value for name, value in seller.data.items() if name != "assertion"}
            assert await refused(EventEnvelope(**{**seller.model_dump(), "data": missing}), 422, "invalid_event")
            assert await received() == 0
            # While a removal holds the seed's lock the receipt is refused, so the event stays pending at Identity.
            async with owner_connection(database_owner_url) as removal:
                await removal.execute("SELECT pg_advisory_lock(hashtextextended('demo-seed',0))")
                assert await refused(seller, 409, "demo_seed_busy")
                await removal.execute("SELECT pg_advisory_unlock(hashtextextended('demo-seed',0))")
            assert await received() == 0
            first, again = await post(seller, token()), await post(seller, token())
            assert (first.json(), again.json()) == ({"accepted": True}, {"accepted": False})
            for sample_set in demo_seed.SETS:
                for holder in demo_seed.HOLDERS.values():
                    if (sample_set, holder) != ("demo", "seller"):
                        assert (await post(event(sample_set, holder), token())).json() == {"accepted": True}
            assert await received() == 4
    # What the ingress received is exactly what admits the seed's drafts.
    monkeypatch.setenv("BT_DEMO_ROOT", str(demo_root(tmp_path)))
    assert await demo_seed.apply(seed_settings(database_owner_url)) == FIRST_RUN
    # The runtime role may read receipts and marks and call the receipt function, but never write either itself.
    subject, _ = demo_seed.handoff_ids("demo", "seller")
    receipt = "SELECT demo_seed_receive($1,'demo','seller',$2,NULL,'ready',now(),$3,$4)"
    conn = await asyncpg.connect(database_url)
    try:
        for statement in (
            f"""INSERT INTO demo_seed_handoffs(event_id,sample_set,holder,subject_id,state,issued_at,seq,assertion)
            VALUES(gen_random_uuid(),'demo','seller','{subject}','ready',now(),{2**62},'x')""",
            "UPDATE demo_seed_handoffs SET subject_id=gen_random_uuid()",
            "DELETE FROM demo_seed_handoffs",
            "TRUNCATE demo_seed_handoffs",
            f"INSERT INTO {MARKS}(sample_set,holder,seq,event_id) VALUES('demo','seller',{2**62},gen_random_uuid())",
            f"UPDATE {MARKS} SET seq=seq+1",
            f"DELETE FROM {MARKS}",
            f"TRUNCATE {MARKS}",
            f"DELETE FROM {demo_seed.LEDGER}",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(statement)
        # The function stores a receipt only in the transaction that wrote the event's own ingress entry.
        with pytest.raises(asyncpg.InvalidParameterValueError):
            await conn.execute(receipt, uuid4(), subject, next(ORDER), "x")
        earlier = uuid4()
        await conn.execute("INSERT INTO inbox(consumer,event_id,source) VALUES($1,$2,'identity')", CONSUMER, earlier)
        with pytest.raises(asyncpg.InvalidParameterValueError):
            await conn.execute(receipt, earlier, subject, next(ORDER), "x")
        # Nor, even there, for any tuple but the pinned four, an order below one, or an empty or oversized
        # assertion.
        for wrong in (
            (uuid4(), next(ORDER), "x"),
            (demo_seed.handoff_ids("click-test", "seller")[0], next(ORDER), "x"),
            (subject, 0, "x"),
            (subject, next(ORDER), ""),
            (subject, next(ORDER), "x" * (demo_seed.HANDOFF_ASSERTION_LIMIT + 1)),
        ):
            event = uuid4()
            with pytest.raises(asyncpg.InvalidParameterValueError):
                async with conn.transaction():
                    await conn.execute("INSERT INTO inbox(consumer,event_id,source) VALUES($1,$2,'identity')",
                                       CONSUMER, event)
                    await conn.execute(receipt, event, *wrong)
    finally:
        await conn.close()
    assert await received() == 4
    assert len(await marks(database_owner_url)) == 4


async def test_a_receipt_the_running_apps_role_stores_itself_never_admits_a_draft(
    database_url, database_owner_url, seeding, handed, capsys
):
    # The running app's role can call the receipt function with an ingress entry of its own, because the
    # database cannot check Identity's signature. A pinned tuple with junk for a signature, or signed with any
    # key but Identity's, is stored and becomes that holder's newest, even far ahead of Identity's order.
    forge = "SELECT demo_seed_receive($1,$2,'seller',$3,NULL,'ready',$4,$5,$6)"
    ahead, other_key, issued = 2**62, key_pair()[0], datetime.now(timezone.utc)
    async with owner_connection(database_owner_url) as conn:
        genuine = await conn.fetchval("SELECT seq FROM demo_seed_handoffs WHERE sample_set='demo' AND holder='seller'")
    conn = await asyncpg.connect(database_url)
    try:
        for sample_set in demo_seed.SETS:
            event, (subject, _) = uuid4(), demo_seed.handoff_ids(sample_set, "seller")
            data = demo_seed.handoff_data(sample_set, "seller", "ready")
            assertion = "not-a-signature" if sample_set == "demo" else demo_seed.sign_handoff(
                other_key, event, ahead, data, issued
            )
            async with conn.transaction():
                await conn.execute("INSERT INTO inbox(consumer,event_id,source) VALUES($1,$2,'identity')",
                                   CONSUMER, event)
                await conn.execute(forge, event, sample_set, subject, issued, ahead, assertion)
        # It can never take the order of a receipt Identity's relay delivered.
        with pytest.raises(asyncpg.InvalidParameterValueError):
            async with conn.transaction():
                event = uuid4()
                await conn.execute("INSERT INTO inbox(consumer,event_id,source) VALUES($1,$2,'identity')",
                                   CONSUMER, event)
                await conn.execute(forge, event, "demo", demo_seed.handoff_ids("demo", "seller")[0], issued, genuine,
                                   "not-a-signature")
    finally:
        await conn.close()
    newest = await marks(database_owner_url)
    assert [newest[(sample_set, "seller")][0] for sample_set in demo_seed.SETS] == [ahead, ahead]
    # Such a receipt fails the signature check at every step: it blocks its holder and never admits a draft.
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=4, invalid=2),
        "L03.media": photo_counts(attached=4, unchanged=2),
    }
    log = capsys.readouterr().err
    for listing in demo_seed.listings():
        line = f"DEMO SEED catalog-listings: refused {listing.key}: {INVALID}\n"
        assert (line in log) == (listing.seller == "private")
    # Identity's next genuine ready stays behind the forged order, so the holder stays refused, until Catalog's
    # owner resets that holder's mark and Identity sends again.
    await deliver(database_url, "demo", "seller")
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(kept=4, invalid=2),
        "L03.media": photo_counts(unchanged=6),
    }
    async with owner_connection(database_owner_url) as conn:
        await conn.execute(f"DELETE FROM {MARKS} WHERE sample_set='demo' AND holder='seller'")
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(kept=4, waiting=1, invalid=1),
        "L03.media": photo_counts(unchanged=6),
    }
    await deliver(database_url, "demo", "seller")
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=1, kept=4, invalid=1),
        "L03.media": photo_counts(attached=1, unchanged=5),
    }
    assert item("click-test", "auction").key not in set(drafts_only(await ledger(database_owner_url)).values())


async def test_a_lost_or_replaced_newest_withdrawal_never_lets_an_older_ready_back(
    database_url, database_owner_url, seeding, capsys
):
    older, withdrawals = {}, {}
    for sample_set in demo_seed.SETS:
        older[sample_set] = await deliver(database_url, sample_set, "seller")
        withdrawals[sample_set] = await deliver(database_url, sample_set, "seller", "withdrawn")
    async with owner_connection(database_owner_url) as conn:
        # Only the owner role can do either. The demo seller's newest receipt, a withdrawal, is lost. The
        # click-test seller's is replaced in place by a ready on the same event id, order, signature and
        # creation time, so the record still holds it and only Identity's signature tells it apart.
        await conn.execute("DELETE FROM demo_seed_handoffs WHERE event_id=$1", withdrawals["demo"].id)
        await conn.execute(
            "UPDATE demo_seed_handoffs SET state='ready' WHERE event_id=$1", withdrawals["click-test"].id
        )
    before = await contents(database_owner_url)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(invalid=2, waiting=4),
        "L03.media": photo_counts(unchanged=6),
    }
    assert await contents(database_owner_url) == before
    log = capsys.readouterr().err
    for listing in demo_seed.listings():
        line = f"DEMO SEED catalog-listings: refused {listing.key}: {INVALID}\n"
        assert (line in log) == (listing.seller == "private")
    # Each holder's mark still names its withdrawal, so the fresh, ready, recorded receipt behind it never counts
    # again, and Catalog's ingress never takes that ready a second time.
    newest = await marks(database_owner_url)
    assert {sample_set: (newest[(sample_set, "seller")][0], str(newest[(sample_set, "seller")][1]))
            for sample_set in demo_seed.SETS} == {
        sample_set: (envelope.data["seq"], str(envelope.id)) for sample_set, envelope in withdrawals.items()
    }
    for envelope in older.values():
        assert not await consume_once(database_url, envelope)
    # Identity's next run, finding its rows current again, sends a ready at its newer order: that admits them.
    for sample_set in demo_seed.SETS:
        await deliver(database_url, sample_set, "seller")
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=2, waiting=4),
        "L03.media": photo_counts(attached=2, unchanged=4),
    }


async def test_a_withdrawal_never_lands_between_a_steps_check_and_its_write(
    database_url, database_owner_url, seeding, handed, tmp_path, monkeypatch
):
    photos, born, arrivals = os.environ["BT_DEMO_ROOT"], demo_seed.born, []

    async def withdrawing(tx, table):
        # Identity's withdrawal for the demo seller arrives just after the first step took that holder's lock and
        # read its mark, before it reads the receipt and writes the auction draft.
        if table == "demo_seed_handoffs" and not arrivals:
            arrivals.append(None)
            with pytest.raises(PublicError) as refused:
                await deliver(database_url, "demo", "seller", "withdrawn")
            arrivals[0] = refused.value
        return await born(tx, table)

    monkeypatch.setattr(demo_seed, "born", withdrawing)
    # The photo step fails this time, so the withdrawal can land between the two steps.
    monkeypatch.setenv("BT_DEMO_ROOT", str(tmp_path / "missing"))
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=6),
        "L03.media": {"failed": "FileNotFoundError"},
    }
    # It was refused as busy while the step held its holder, and stored nothing, so Identity's relay keeps it.
    assert [(error.status, error.code) for error in arrivals] == [(409, "demo_seed_busy")]
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM demo_seed_handoffs WHERE state='withdrawn'") == 0
    # The relay's next attempt lands once that step committed; the photo step after it never attaches.
    await deliver(database_url, "demo", "seller", "withdrawn")
    monkeypatch.setenv("BT_DEMO_ROOT", photos)
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(kept=6),
        "L03.media": photo_counts(attached=5, withdrawn=1),
    }
    withdrawn = item("demo", "auction")
    async with owner_connection(database_owner_url) as conn:
        draft = await conn.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", withdrawn.id)
        assert (draft["revision"], draft["photo_ids"]) == (1, [])
        assert await conn.fetchval("SELECT count(*) FROM catalog_media WHERE id=$1", withdrawn.photo_id) == 0


async def test_a_step_skips_a_holder_whose_handoff_is_arriving(
    database_url, database_owner_url, seeding, handed, capsys
):
    arriving = await asyncpg.connect(database_url)
    try:
        async with arriving.transaction():
            # As the receipt function holds it while it stores a handoff for the click-test staff.
            await arriving.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", demo_seed.holder_lock("click-test", "staff")
            )
            assert await demo_seed.apply(seed_settings(database_owner_url)) == {
                "L03.listings": drafts_counts(created=4, busy=2),
                "L03.media": photo_counts(attached=4, unchanged=2),
            }
    finally:
        await arriving.close()
    log = capsys.readouterr().err
    for listing in demo_seed.listings():
        line = f"DEMO SEED catalog-listings: busy {listing.key}: an Identity handoff for its holder is arriving\n"
        assert (line in log) == ((listing.sample_set, listing.seller) == ("click-test", "dealer"))
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": drafts_counts(created=2, kept=4),
        "L03.media": photo_counts(attached=2, unchanged=4),
    }


async def test_a_removal_racing_a_writer_never_deletes_the_writers_row(
    database_url, database_owner_url, seeding, handed, monkeypatch
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    target = item("demo", "auction")
    async with owner_connection(database_owner_url) as conn:
        # Its detail variant is gone, so the app may add one: only removal's lock on the photo row can hold it.
        await conn.execute("DELETE FROM catalog_media_variants WHERE media_id=$1 AND variant='detail'", target.photo_id)
    record = await ledger(database_owner_url)
    real, writer = demo_seed.referenced, {}

    async def write():
        conn = await asyncpg.connect(database_url)
        writer["pid"] = conn.get_server_pid()
        try:
            await conn.execute(
                "INSERT INTO catalog_media_variants(media_id,variant,width,height,content) VALUES($1,'detail',1,1,$2)",
                target.photo_id,
                b"\x00",
            )
        finally:
            await conn.close()

    async def racing(tx, relation, table, columns, key):
        if table == "catalog_media" and json.loads(key) == {"id": str(target.photo_id)} and "task" not in writer:
            # The app adds a variant to this photo once removal has locked it and before it checks for references.
            writer["task"] = asyncio.ensure_future(write())
            # Watched as the writer's own role, the only one besides a superuser that sees its wait state.
            async with owner_connection(database_url) as watch:
                for _ in range(100):
                    if writer["task"].done() or (
                        "pid" in writer
                        and await watch.fetchval(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=$1", writer["pid"]
                        )
                        == "Lock"
                    ):
                        break
                    await asyncio.sleep(0.05)
            writer["blocked"] = not writer["task"].done()
        return await real(tx, relation, table, columns, key)

    monkeypatch.setattr(demo_seed, "referenced", racing)
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
    assert await demo_seed.apply(settings) == {"remove": {"removed": len(record), "kept": 0}}
    # The writer waited on the locked photo row; once the removal committed, its row had nothing to refer to.
    assert writer["blocked"]
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await writer["task"]
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM catalog_media WHERE id=$1", target.photo_id) == 0
        variants = "SELECT count(*) FROM catalog_media_variants WHERE media_id=$1"
        assert await conn.fetchval(variants, target.photo_id) == 0
    assert await ledger(database_owner_url) == {}


async def test_removal_keeps_a_row_made_again_edited_or_held_by_a_live_writer(
    database_url, database_owner_url, seeding, handed, monkeypatch, capsys
):
    settings = seed_settings(database_owner_url)
    assert await demo_seed.apply(settings) == FIRST_RUN
    remade, edited, held = item("demo", "auction"), item("demo", "buy-now"), item("click-test", "auction")
    record = await ledger(database_owner_url)
    async with owner_connection(database_owner_url) as conn:
        # Its first event deleted and made again on the same id: a row the seed never inserted.
        event = await conn.fetchrow(
            f"""SELECT * FROM outbox WHERE id=(SELECT min((row_key->>'id')::bigint) FROM {demo_seed.LEDGER}
            WHERE table_name='outbox' AND demo_key=$1)""",
            remade.key,
        )
        await conn.execute("DELETE FROM outbox WHERE id=$1", event["id"])
        await conn.execute(
            """INSERT INTO outbox(id,event_id,destination,envelope) OVERRIDING SYSTEM VALUE
            VALUES($1,$2,$3,$4::jsonb)""",
            event["id"],
            event["event_id"],
            event["destination"],
            event["envelope"],
        )
        # A photo variant, a table without a creation time, edited since the seed wrote it.
        await conn.execute(
            "UPDATE catalog_media_variants SET content=$2 WHERE media_id=$1 AND variant='thumb'",
            edited.photo_id,
            b"\x01",
        )
        # Its detail variant gone and the app part way through adding another, which holds the photo row.
        await conn.execute("DELETE FROM catalog_media_variants WHERE media_id=$1 AND variant='detail'", held.photo_id)
    kept = {remade.key, edited.key, held.key}
    live = await asyncpg.connect(database_url)
    try:
        writing = live.transaction()
        await writing.start()
        await live.execute(
            "INSERT INTO catalog_media_variants(media_id,variant,width,height,content) VALUES($1,'detail',1,1,$2)",
            held.photo_id,
            b"\x00",
        )
        capsys.readouterr()
        monkeypatch.setenv(demo_seed.SWITCH, demo_seed.REMOVE_VALUE)
        started = time.monotonic()
        first = await demo_seed.apply(settings)
        # Refused at once on the held row: waiting out the lock limit in each of its two passes would take longer.
        assert time.monotonic() - started < 2 * demo_seed.LOCK_MS / 1000
        log = capsys.readouterr().err
        await writing.rollback()
    finally:
        await live.close()
    removed = sum(value not in kept for value in record.values())
    assert first == {"remove": {"removed": removed, "kept": 3}}
    for listing, reason in ((remade, "replaced"), (edited, "changed"), (held, "busy")):
        assert f"DEMO SEED remove: kept {listing.key}: {reason}\n" in log
    assert set((await ledger(database_owner_url)).values()) == kept
    # The writer gave up: the next removal deletes that draft whole, and still keeps the other two.
    assert await demo_seed.apply(settings) == {
        "remove": {"removed": sum(value == held.key for value in record.values()), "kept": 2}
    }
    assert set((await ledger(database_owner_url)).values()) == {remade.key, edited.key}
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM catalog_listings WHERE id=$1", held.id) == 0
        assert await conn.fetchval("SELECT count(*) FROM catalog_media WHERE id=$1", held.photo_id) == 0
        assert await conn.fetchval("SELECT count(*) FROM outbox WHERE id=$1", event["id"]) == 1
        thumb = "SELECT content FROM catalog_media_variants WHERE media_id=$1 AND variant='thumb'"
        assert await conn.fetchval(thumb, edited.photo_id) == b"\x01"


async def test_a_hung_photo_step_ends_at_the_seed_budget(database_owner_url, seeding, handed, tmp_path, monkeypatch):
    root, budget = stuck_root(tmp_path), demo_seed.TOTAL_SECONDS
    monkeypatch.setenv("BT_DEMO_ROOT", str(root))
    monkeypatch.setattr(demo_seed, "TOTAL_SECONDS", 3)
    started = time.monotonic()
    try:
        # The deploy hook's own entry, on its own loop, as the pre-deploy step runs it.
        result = await asyncio.to_thread(demo_seed.run, seed_settings(database_owner_url))
        spent = time.monotonic() - started
    finally:
        release(root)
    assert result == {"L03.listings": FIRST_RUN["L03.listings"], "L03.media": {"failed": "timeout"}}
    assert spent < 3 + 2
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM catalog_media") == 0
    # The next deploy, with the photos readable and the full budget, attaches every photo it missed.
    monkeypatch.setattr(demo_seed, "TOTAL_SECONDS", budget)
    monkeypatch.setenv("BT_DEMO_ROOT", str(demo_root(tmp_path / "later")))
    assert await demo_seed.apply(seed_settings(database_owner_url)) == {
        "L03.listings": LATER_RUN["L03.listings"],
        "L03.media": FIRST_RUN["L03.media"],
    }


async def test_a_hung_photo_step_never_holds_up_the_pre_deploy_step(database_owner_url, handed, tmp_path):
    environment = {**os.environ, "BT_DATABASE_URL": database_owner_url, demo_seed.SWITCH: demo_seed.SWITCH_VALUE,
                   "BT_SERVICE_NAME": "catalog", "BT_DEMO_ROOT": str(stuck_root(tmp_path))}
    command = [sys.executable, "-m", "service_app.migrate"]
    started = time.monotonic()
    # Its stuck reader dies with the process, so nothing is left waiting on the manifest afterwards.
    step = await asyncio.to_thread(
        subprocess.run, command, cwd=RUNTIME, env=environment, capture_output=True, text=True, timeout=90
    )
    spent = time.monotonic() - started
    # The stuck read is abandoned at the budget and the process exits cleanly, so the deploy goes on.
    assert step.returncode == 0, step.stderr
    assert spent < demo_seed.TOTAL_SECONDS + 15
    assert (
        "DEMO SEED L03.listings: busy=0 created=6 foreign=0 invalid=0 kept=0 mismatched=0 stale=0 unkeyed=0 "
        "waiting=0 withdrawn=0\n"
    ) in step.stderr
    assert "DEMO SEED L03.media: failed=timeout\n" in step.stderr
    assert "DEMO SEED seed: partial; not finished: L03.media\n" in step.stderr
    secret = urlparse(database_owner_url).password
    for output in (step.stdout, step.stderr):
        assert database_owner_url not in output and secret not in output and unquote(secret) not in output
    # The next deploy, with the photos readable, attaches every photo.
    environment["BT_DEMO_ROOT"] = str(demo_root(tmp_path / "later"))
    step = await asyncio.to_thread(
        subprocess.run, command, cwd=RUNTIME, env=environment, capture_output=True, text=True, timeout=90
    )
    assert step.returncode == 0, step.stderr
    assert (
        "DEMO SEED L03.media: attached=6 busy=0 invalid=0 mismatched=0 stale=0 unchanged=0 unkeyed=0 waiting=0 "
        "withdrawn=0\n"
    ) in step.stderr
    assert "DEMO SEED seed: complete\n" in step.stderr


async def test_a_failed_photo_step_heals_on_the_next_deploy(database_owner_url, seeding, handed, tmp_path, monkeypatch):
    root = demo_root(tmp_path / "later")
    monkeypatch.setenv("BT_DEMO_ROOT", str(tmp_path / "missing"))
    first = await demo_seed.apply(seed_settings(database_owner_url))
    assert first == {
        "L03.listings": FIRST_RUN["L03.listings"],
        "L03.media": {"failed": "FileNotFoundError"},
    }
    async with owner_connection(database_owner_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM catalog_media") == 0
        # Its seller already started this draft before the photos arrived; it stays theirs.
        started = demo_seed.listings()[0]
        await conn.execute("UPDATE catalog_listings SET revision=2 WHERE id=$1", started.id)
        monkeypatch.setenv("BT_DEMO_ROOT", str(root))
        second = await demo_seed.apply(seed_settings(database_owner_url))
        assert second == {
            "L03.listings": LATER_RUN["L03.listings"],
            "L03.media": photo_counts(attached=5, unchanged=1),
        }
        assert await conn.fetchval("SELECT cardinality(photo_ids) FROM catalog_listings WHERE id=$1", started.id) == 0

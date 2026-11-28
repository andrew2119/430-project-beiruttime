"""Pure rules of the deploy-applied demo seed's Catalog drafts and photos: no database, no network.

Identity's handoff key pairs are made here for these tests only and never stored.
"""
import asyncio
import copy
import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import asyncpg
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from PIL import Image
from pydantic import ValidationError
from bt_contracts.catalog.listings.v1 import incomplete
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_runtime import demo_seed
from modules.listings import deploy_seed as drafts
from modules.listings.handoff import REASONS, Handoff, admitted, fields, receive
from modules.media import deploy_seed as photos
from modules.media.images import attribution_matches, embed_attribution, normalize

LISTINGS = Path(__file__).resolve().parents[2] / "modules" / "listings"
RECEIPT = LISTINGS / "migrations" / "L03_0003_demo_seed.sql"


def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


# Identity's disposable handoff key pair, and another pair standing for any key that is not it.
HANDOFF_PRIVATE, HANDOFF_PUBLIC = key_pair()
OTHER_PRIVATE, OTHER_PUBLIC = key_pair()
CREDIT = {
    "author": "Sample Author",
    "credit": "Sample photo - Sample Author, CC BY 4.0",
    "source_url": "https://example.test/source",
    "license": "CC BY 4.0",
    "license_url": "https://example.test/license",
}


def inline_attribution(variants, credit):
    # The media upload route's attribution block before it moved into images.embed_attribution.
    text = (
        "Author: "
        + credit["author"]
        + "\n"
        + credit["credit"]
        + "\nSource: "
        + credit["source_url"]
        + "\nLicense: "
        + credit["license_url"]
        + "\nLicense name: "
        + credit["license"]
        + "\nChanges: oriented, metadata removed, resized and re-encoded."
    ).encode("utf-8")
    for variant in variants.values():
        pixels = variant["content"]
        variant["content"] = pixels[:2] + b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text + pixels[2:]


def test_every_seed_watch_is_complete_once_its_photo_is_attached():
    for listing in demo_seed.listings():
        value = drafts.facts(listing)
        assert incomplete(value, 1) == []
        assert incomplete(value, 0) == ["photos"]
        assert value.currency == "USD" and value.reference.startswith("DEMO-WATCH-0")
        assert value.location == ("Achrafieh, Beirut" if listing.seller == "private" else "Hamra, Beirut")
    buy_now = drafts.facts(next(item for item in demo_seed.listings() if item.item == "buy-now"))
    assert (buy_now.reference, buy_now.sale_mode, buy_now.price_minor) == ("DEMO-WATCH-02", "fixed_price", 18000)
    assert drafts.facts(demo_seed.listings()[0]).sale_mode == "auction"
    assert set(drafts.WATCHES) == set(photos.PHOTOS)


def test_seed_text_is_labeled_plain_and_named_like_a_real_shop():
    labels = {(item.sample_set, item.item): drafts.label(item) for item in demo_seed.listings()}
    assert labels[("demo", "auction")] == labels[("click-test", "auction")] == "Demonstration private seller"
    assert labels[("demo", "buy-now")] == labels[("demo", "spare")] == "Demonstration Zayzafoun Watch House"
    assert labels[("click-test", "buy-now")] == "Demonstration Sanawbar Watch House"
    texts = [drafts.CONDITION, *labels.values()]
    for listing in demo_seed.listings():
        value = drafts.facts(listing)
        texts += [value.brand, value.model, value.reference, value.location, *value.component_wear.values()]
    assert all(text.isascii() for text in texts)
    assert "illustrative" in drafts.CONDITION
    # Visible names carry no seed label; the ownership record marks seed rows instead.
    assert all("DEMO" not in text for text in [drafts.CONDITION, *labels.values()])


def test_drafts_belong_to_the_seed_s_own_sellers():
    for item in demo_seed.listings():
        owner, organization = drafts.seller(item)
        if item.seller == "private":
            assert (owner, organization) == (demo_seed.account(item.sample_set, "seller").id, None)
        else:
            # The sample staff of that set's own sample business, never another business or set.
            assert owner == demo_seed.account(item.sample_set, "staff").id
            assert organization == demo_seed.business(item.sample_set).id


def assertion_for(sample_set, holder, state="ready", seq=7, event_id=None, issued=None, key=None, **data):
    """One handoff's event id, issue time, signed fields and Identity's assertion over them."""
    signed = {**demo_seed.handoff_data(sample_set, holder, state), **data}
    event_id = uuid4() if event_id is None else event_id
    issued = datetime.now(timezone.utc) - timedelta(minutes=2) if issued is None else issued
    return event_id, issued, signed, demo_seed.sign_handoff(key or HANDOFF_PRIVATE, event_id, seq, signed, issued)


def test_a_handoff_assertion_verifies_only_over_exactly_its_own_event_order_fields_and_time():
    event_id, issued, signed, assertion = assertion_for("click-test", "staff", seq=11)
    claims = demo_seed.handoff_claims(event_id, 11, signed, issued)

    def verifies(token=assertion, event=event_id, seq=11, data=signed, time=issued):
        return demo_seed.verify_handoff(HANDOFF_PUBLIC, token, event, seq, data, time)

    def token(key=HANDOFF_PRIVATE, algorithm="RS256", **patch):
        return jwt.encode({**claims, **patch}, key, algorithm=algorithm)

    assert verifies() and verifies(token())
    assert not verifies(event=uuid4())
    for seq in (10, 12):
        assert not verifies(seq=seq)
    for name, value in (("sample_set", "demo"), ("holder", "seller"), ("subject_id", str(uuid4())),
                        ("business_id", None), ("business_id", str(uuid4())), ("state", "withdrawn")):
        assert not verifies(data={**signed, name: value})
    assert not verifies(time=issued + timedelta(microseconds=1))
    # Another key, the service audience or issuer, a missing or extra claim, or no signature at all.
    assert not verifies(token(OTHER_PRIVATE))
    for patch in ({"aud": demo_seed.HANDOFF_AUDIENCE}, {"iss": "catalog"}, {"type": "service"}, {"extra": True},
                  {"seq": "11"}, {"issued_us": demo_seed.issued_us(issued) + 1}):
        assert not verifies(token(**patch))
    for name in demo_seed.HANDOFF_CLAIMS:
        assert not verifies(jwt.encode({k: v for k, v in claims.items() if k != name}, HANDOFF_PRIVATE,
                                       algorithm="RS256"))
    assert not verifies(jwt.encode(claims, "a shared secret of thirty-two bytes or more", algorithm="HS256"))
    header, payload, _ = assertion.split(".")
    oversized = assertion + "x" * demo_seed.HANDOFF_ASSERTION_LIMIT
    for wrong in ("", "not-a-signature", f"{header}.{payload}.", oversized, None, 7, assertion.encode()):
        assert not verifies(wrong)
    assert not demo_seed.verify_handoff(OTHER_PUBLIC, assertion, event_id, 11, signed, issued)


def test_catalog_holds_only_the_public_half_of_its_own_handoff_key():
    public = demo_seed.HANDOFF_PUBLIC_KEY
    assert demo_seed.handoff_verifying_key({public: HANDOFF_PUBLIC}) == HANDOFF_PUBLIC.strip()
    assert demo_seed.handoff_verifying_key({public: HANDOFF_PUBLIC.replace("\n", "\\n")}) == HANDOFF_PUBLIC.strip()
    assert demo_seed.handoff_verifying_key(
        {public: HANDOFF_PUBLIC, "BT_SERVICE_AUTH_PUBLIC_KEY": OTHER_PUBLIC}) == HANDOFF_PUBLIC.strip()
    for wrong in (
        {},
        {public: ""},
        {public: "not a key"},
        # The private half, as either variable, or Catalog's own service key standing in for Identity's.
        {public: HANDOFF_PRIVATE},
        {public: HANDOFF_PUBLIC, demo_seed.HANDOFF_PRIVATE_KEY: HANDOFF_PRIVATE},
        {public: HANDOFF_PUBLIC, "BT_SERVICE_AUTH_PUBLIC_KEY": HANDOFF_PUBLIC},
        {public: HANDOFF_PUBLIC, "BT_SERVICE_AUTH_PRIVATE_KEY": HANDOFF_PRIVATE},
    ):
        with pytest.raises(demo_seed.HandoffKey):
            demo_seed.handoff_verifying_key(wrong)


def wrongly_keyed(monkeypatch):
    """Each way Catalog's handoff key can be set wrongly, one at a time: missing, not a public key, the private
    half beside it, or the pair of Catalog's own service key."""
    for name, value in ((demo_seed.HANDOFF_PUBLIC_KEY, None), (demo_seed.HANDOFF_PUBLIC_KEY, "not a key"),
                        (demo_seed.HANDOFF_PUBLIC_KEY, OTHER_PRIVATE), (demo_seed.HANDOFF_PRIVATE_KEY, HANDOFF_PRIVATE),
                        ("BT_SERVICE_AUTH_PUBLIC_KEY", HANDOFF_PUBLIC)):
        with monkeypatch.context() as patched:
            if value is None:
                patched.delenv(name)
            else:
                patched.setenv(name, value)
            yield name


class Checking:
    """A seed step's transaction, as admitted() sees it: the holder's lock, its mark and the receipt that mark
    names, which the ownership record holds."""

    def __init__(self, mark=None, receipt=None, locked=True):
        self.mark, self.receipt, self.locked, self.queries = mark, receipt, locked, []

    async def fetchval(self, query, *args):
        self.queries.append((query, args))
        return self.locked

    async def fetchrow(self, query, *args):
        if "pg_attribute" in query:
            # born() looking up the receipt table's creation time.
            return {"name": "received_at", "type": "timestamp with time zone"}
        self.queries.append((query, args))
        return self.mark if "demo_seed_handoff_marks" in query else self.receipt


def receipt_row(sample_set, holder, state="ready", seq=7, stale=False, key=None, signed=None, **stored):
    """A stored receipt as the receipt query returns it: signed over `signed` (default: its own fields), then
    stored with `stored` changed."""
    signed = signed or {}
    event_id, issued, data, assertion = assertion_for(sample_set, holder, state, seq, key=key, **signed)
    row = {"event_id": event_id, "sample_set": sample_set, "holder": holder,
           "subject_id": UUID(data["subject_id"]),
           "business_id": None if data["business_id"] is None else UUID(data["business_id"]),
           "state": state, "seq": seq, "issued_at": issued, "assertion": assertion, "stale": stale}
    return {**row, **stored}


def test_only_the_receipt_the_holders_mark_names_admits_a_draft_and_only_when_it_is_identitys(monkeypatch):
    monkeypatch.setenv(demo_seed.HANDOFF_PUBLIC_KEY, HANDOFF_PUBLIC)
    monkeypatch.delenv(demo_seed.HANDOFF_PRIVATE_KEY, raising=False)
    monkeypatch.delenv("BT_SERVICE_AUTH_PUBLIC_KEY", raising=False)
    subject, business = demo_seed.handoff_ids("demo", "staff")
    assert drafts.seller(demo_seed.listings()[1]) == (subject, business)

    def check(row, holder="staff", mark=True, locked=True):
        tx = Checking({"seq": row["seq"], "event_id": row["event_id"]} if mark and row else None, row, locked)
        return asyncio.run(admitted(tx, "demo", holder)), tx.queries

    def reason(row, **options):
        return check(row, **options)[0]

    assert reason(receipt_row("demo", "staff")) is None
    assert reason(receipt_row("demo", "seller"), holder="seller") is None
    assert reason(None) == "waiting"
    assert reason(receipt_row("demo", "staff", "withdrawn")) == "withdrawn"
    assert reason(receipt_row("demo", "staff", stale=True)) == "stale"
    assert reason(receipt_row("demo", "staff", "withdrawn", stale=True)) == "withdrawn"
    # Identity's own signature over another account or business: it verifies, and still differs.
    for wrong in ({"subject_id": str(uuid4())}, {"business_id": str(uuid4())}, {"business_id": None}):
        assert reason(receipt_row("demo", "staff", signed=wrong)) == "mismatched"
        assert reason(receipt_row("demo", "staff", "withdrawn", stale=True, signed=wrong)) == "mismatched"
    # The newest receipt lost (the mark names a row the query no longer finds), edited after it was stored,
    # stored by the running app's role with no or another key's signature, or an older receipt: never a fallback.
    row = receipt_row("demo", "staff")
    lost = Checking({"seq": row["seq"], "event_id": row["event_id"]}, None)
    assert asyncio.run(admitted(lost, "demo", "staff")) == "invalid"
    for edited in ({"state": "withdrawn"}, {"seq": 8}, {"event_id": uuid4()},
                   {"issued_at": row["issued_at"] + timedelta(microseconds=1)}, {"subject_id": uuid4()},
                   {"assertion": ""}, {"assertion": "not-a-signature"}):
        assert reason({**row, **edited}) == "invalid"
    assert reason(receipt_row("demo", "staff", key=OTHER_PRIVATE)) == "invalid"
    assert reason(receipt_row("demo", "staff", "withdrawn", key=OTHER_PRIVATE)) == "invalid"
    withdrawn = receipt_row("demo", "staff", "withdrawn")
    replaced = {**withdrawn, "state": "ready"}
    assert reason(replaced) == "invalid"
    # Busy: the holder's lock is taken (a receipt arriving, or another step), and nothing else is read.
    why, queries = check(row, locked=False)
    assert why == "busy" and len(queries) == 1
    # The checks, in order, on exactly this holder's lock, its mark and the one receipt that mark names.
    why, [(lock, lock_args), (read_mark, mark_args), (latest, latest_args)] = check(row)
    assert why is None
    assert lock == "SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))"
    assert lock_args == (demo_seed.holder_lock("demo", "staff"),) == ("demo-seed-handoff:demo:staff",)
    assert "FROM demo_seed_handoff_marks WHERE sample_set=$1 AND holder=$2" in read_mark
    assert mark_args == ("demo", "staff")
    assert "t.seq=$4 AND t.event_id=$5" in latest and "ORDER BY" not in latest and "LIMIT" not in latest
    assert f"JOIN {demo_seed.LEDGER} AS r" in latest and "r.demo_key=$3" in latest and "r.born = 'created:'" in latest
    assert latest_args == ("demo", "staff", demo_seed.handoff_key("demo", "staff"), row["seq"], row["event_id"],
                           demo_seed.HANDOFF_FRESH_SECONDS, demo_seed.HANDOFF_SKEW_SECONDS)
    assert demo_seed.HANDOFF_FRESH_SECONDS == 1800 and 0 < demo_seed.HANDOFF_SKEW_SECONDS < 300
    # No key, or a key set wrongly: refused after the lock, before anything is read.
    for _ in wrongly_keyed(monkeypatch):
        why, queries = check(row)
        assert why == "unkeyed" and len(queries) == 1
    # Every reason a step refuses has its own log line, but waiting, which is only counted.
    assert set(REASONS) == set(drafts.REFUSALS) | {"waiting"}


def test_the_handoff_contract_admits_only_the_seed_s_sets_holders_states_and_orders():
    staff = {**demo_seed.handoff_data("click-test", "staff", "ready"), "seq": 1, "assertion": "signed"}
    assert Handoff.model_validate(staff).business_id == demo_seed.business("click-test").id
    assert Handoff.model_validate({**staff, "seq": 2**63 - 1}).seq == 2**63 - 1
    seller = {**demo_seed.handoff_data("demo", "seller", "withdrawn"), "seq": 3, "assertion": "signed"}
    assert Handoff.model_validate(seller).state == "withdrawn"
    assert Handoff.model_validate({**seller, "state": "ready"}).business_id is None
    for wrong in ({**staff, "sample_set": "live"}, {**staff, "holder": "operator"}, {**staff, "subject_id": "x"},
                  {**staff, "state": "revoked"}, {**staff, "extra": True},
                  {**staff, "seq": 0}, {**staff, "seq": -1}, {**staff, "seq": "1"}, {**staff, "seq": 1.0},
                  {**staff, "seq": True}, {**staff, "seq": 2**63}, {**staff, "seq": None},
                  {**staff, "assertion": ""}, {**staff, "assertion": "x" * (demo_seed.HANDOFF_ASSERTION_LIMIT + 1)},
                  {**staff, "assertion": None}, {**staff, "assertion": 7},
                  *({key: value for key, value in staff.items() if key != name}
                    for name in ("subject_id", "business_id", "state", "seq", "assertion"))):
        with pytest.raises(ValidationError):
            Handoff.model_validate(wrong)
    with pytest.raises(ValueError):
        demo_seed.handoff_data("demo", "seller", "revoked")


class Receiving:
    """The ingress transaction, as receive() sees it: what it asks the database to do, and how that answers."""

    def __init__(self, error=None):
        self.calls, self.error = [], error

    async def execute(self, query, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error


def handoff_event(sample_set, holder, state="ready", seq=5, issued=None, key=None, **data):
    """A handoff event signed with `key` (default: Identity's handoff key) over its own, possibly wrong, fields."""
    event_id, issued, signed, assertion = assertion_for(sample_set, holder, state, seq, issued=issued, key=key, **data)
    return EventEnvelope(id=event_id, time=issued, type=demo_seed.HANDOFF_TYPE, source="identity",
                         subject=signed["subject_id"], request_id=demo_seed.REQUEST_ID,
                         data={**signed, "seq": seq, "assertion": assertion})


def test_the_ingress_stores_only_identitys_signed_handoff_for_the_pinned_four(monkeypatch):
    monkeypatch.setenv(demo_seed.SWITCH, demo_seed.SWITCH_VALUE)
    monkeypatch.setenv(demo_seed.HANDOFF_PUBLIC_KEY, HANDOFF_PUBLIC)
    monkeypatch.delenv(demo_seed.HANDOFF_PRIVATE_KEY, raising=False)
    monkeypatch.delenv("BT_SERVICE_AUTH_PUBLIC_KEY", raising=False)

    def outcome(event, tx=None):
        tx = tx or Receiving()
        try:
            asyncio.run(receive(tx, event))
        except PublicError as error:
            return error.status, error.code, tx.calls
        return 200, None, tx.calls

    refused = (422, "invalid_event", [])
    other_seller = demo_seed.handoff_data("click-test", "seller", "ready")["subject_id"]
    other_business = str(demo_seed.business("click-test").id)
    for wrong in (
        # Validly signed, but another set's seller, a staff with another set's business, or another account.
        handoff_event("demo", "seller", subject_id=other_seller),
        handoff_event("demo", "staff", business_id=other_business),
        handoff_event("click-test", "staff", subject_id=str(uuid4())),
        handoff_event("click-test", "staff", business_id=None),
    ):
        assert outcome(wrong) == refused
    issued = datetime.now(timezone.utc) - timedelta(minutes=5)
    good = handoff_event("click-test", "staff", "withdrawn", seq=9, issued=issued)
    code, error, [(query, args)] = outcome(good)
    subject, business = demo_seed.handoff_ids("click-test", "staff")
    assert (code, error) == (200, None) and query == "SELECT demo_seed_receive($1,$2,$3,$4,$5,$6,$7,$8,$9)"
    assert args == (good.id, "click-test", "staff", subject, business, "withdrawn", issued, 9,
                    good.data["assertion"])
    assert fields(good.data) == {name: good.data[name] for name in demo_seed.HANDOFF_FIELDS}
    # Not Identity's handoff signature over exactly this event: another key, no signature, or any part of the
    # event changed after signing, its envelope included.
    for wrong in (
        handoff_event("click-test", "staff", "withdrawn", seq=9, key=OTHER_PRIVATE),
        good.model_copy(update={"data": {**good.data, "assertion": "not-a-signature"}}),
        good.model_copy(update={"data": {**good.data, "state": "ready"}}),
        good.model_copy(update={"data": {**good.data, "seq": 10}}),
        good.model_copy(update={"id": uuid4()}),
        good.model_copy(update={"time": issued + timedelta(microseconds=1)}),
        good.model_copy(update={"subject": other_seller}),
        good.model_copy(update={"request_id": "another-request"}),
        good.model_copy(update={"data": {k: v for k, v in good.data.items() if k != "assertion"}}),
        good.model_copy(update={"data": {**good.data, "seq": 0}}),
    ):
        assert outcome(wrong) == refused
    # While a removal or a seed step holds a lock the event stays pending at Identity; the function's own refusal
    # is a 422.
    assert outcome(good, Receiving(asyncpg.LockNotAvailableError("busy")))[:2] == (409, "demo_seed_busy")
    assert outcome(good, Receiving(asyncpg.InvalidParameterValueError("refused")))[:2] == (422, "invalid_event")
    # No key, or one set wrongly, refuses before anything is written; so does the switch being off.
    for _ in wrongly_keyed(monkeypatch):
        assert outcome(good) == (409, "demo_seed_unkeyed", [])
    monkeypatch.delenv(demo_seed.SWITCH)
    assert outcome(good) == (409, "demo_seed_off", [])


def test_the_receipt_function_pins_exactly_the_seed_s_four_handoffs():
    text = RECEIPT.read_text()
    pinned = re.findall(r"\('([a-z-]+)', '([a-z]+)', '([0-9a-f-]{36})'::uuid, (NULL|'[0-9a-f-]{36}')::uuid\)", text)
    expected = set()
    for sample_set in demo_seed.SETS:
        for holder in demo_seed.HOLDERS.values():
            subject, business = demo_seed.handoff_ids(sample_set, holder)
            expected.add((sample_set, holder, str(subject), "NULL" if business is None else f"'{business}'"))
    assert len(pinned) == 4 and set(pinned) == expected
    # It records its receipts in the very form born() compares, under the key admitted() looks for, and only for
    # the ingress entry of the consumer whose route registers the handoff.
    assert text.count(demo_seed.BORN_FORMAT) == 2
    assert "'DEMO-SEED-' || upper(set_name) || '-HANDOFF-' || upper(holder_name)" in text
    assert demo_seed.handoff_key("click-test", "staff") == "DEMO-SEED-CLICK-TEST-HANDOFF-STAFF"
    assert text.count("'catalog.moderation.v1'") == 3
    assert 'build_event_router(\n    "catalog.moderation.v1"' in (LISTINGS / "moderation.py").read_text()
    assert "SECURITY DEFINER" in text and "SET search_path = pg_catalog, public, pg_temp" in text
    # Under the seed's shared lock, which a removal takes alone, and the holder's own lock, the very one
    # admitted() takes, both without waiting; one order per holder, and a mark that only moves forward.
    assert "pg_try_advisory_xact_lock_shared(hashtextextended('demo-seed', 0))" in text
    assert ("pg_try_advisory_xact_lock(hashtextextended('demo-seed-handoff:' || set_name || ':' || holder_name, 0))"
            in text)
    assert demo_seed.holder_lock("click-test", "seller") == "demo-seed-handoff:click-test:seller"
    assert text.count("ERRCODE = '55P03'") == 2
    assert "UNIQUE (sample_set, holder, seq)" in text and "'Another handoff holds this order'" in text
    assert "ON CONFLICT (sample_set, holder) DO UPDATE SET seq = excluded.seq, event_id = excluded.event_id\n" \
           " WHERE m.seq < excluded.seq;" in text
    assert "length(handoff_assertion) NOT BETWEEN 1 AND 4096" in text
    assert str(demo_seed.HANDOFF_ASSERTION_LIMIT) == "4096"
    # The running app's role may only call it, and never write a receipt or a mark itself.
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON demo_seed_handoffs FROM %I" in text
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON demo_seed_handoff_marks FROM %I" in text
    signature = "demo_seed_receive(uuid, text, text, uuid, uuid, text, timestamptz, bigint, text)"
    assert f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC" in text
    assert re.search(r"GRANT EXECUTE ON FUNCTION demo_seed_receive\(uuid, text, text, uuid, uuid, text, "
                     r"timestamptz, '\s+'bigint, text\) TO %I'", text)
    assert text.count("CREATE FUNCTION demo_seed_receive(") == 1


def test_shared_attribution_is_byte_identical_to_the_upload_route():
    source = io.BytesIO()
    Image.new("RGB", (900, 700), (120, 80, 40)).save(source, format="JPEG")
    variants = normalize(source.getvalue())
    expected = copy.deepcopy(variants)
    inline_attribution(expected, CREDIT)
    embed_attribution(variants, CREDIT)
    assert variants == expected
    assert all(attribution_matches(variant["content"], CREDIT) for variant in variants.values())

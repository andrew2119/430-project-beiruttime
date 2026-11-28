"""Pure rules of the deploy-applied demo seed: no database, no network, safe to run anywhere.

Identity's handoff key pairs are made here for these tests only and never stored.
"""
import asyncio
import contextlib
import io
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid5
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bt_runtime import demo_seed, demo_seed_deadline
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover

ON = {demo_seed.SWITCH: demo_seed.SWITCH_VALUE}
ROLES = ("buyer", "seller", "rival", "operator", "staff")
NOWHERE = SimpleNamespace(database_url="postgresql://seed-must-not-connect.invalid/none",
                          modules_path=Path("/seed-must-not-read"))


def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


def test_switch_acts_only_on_its_two_exact_values():
    assert demo_seed.mode({}) is None and not demo_seed.enabled({})
    assert demo_seed.mode(ON) == "seed" and demo_seed.enabled(ON)
    remove = {demo_seed.SWITCH: demo_seed.REMOVE_VALUE}
    assert demo_seed.mode(remove) == "remove" and not demo_seed.enabled(remove)
    assert (demo_seed.SWITCH_VALUE, demo_seed.REMOVE_VALUE) == ("sample-accounts-only", "remove-sample-accounts")
    warning = f"DEMO SEED switch: ignored; {demo_seed.SWITCH} acts only on its documented values\n"
    for value in ("", "1", "true", "on", "yes", "Sample-Accounts-Only", " sample-accounts-only", "sample-accounts",
                  "remove", "Remove-Sample-Accounts"):
        assert demo_seed.mode({demo_seed.SWITCH: value}) is None
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            # Any other value does nothing: no module discovery, no connection, no write.
            assert asyncio.run(demo_seed.apply(NOWHERE, {demo_seed.SWITCH: value})) == {}
        # A wrong value gets one fixed warning line that never echoes the value.
        assert log.getvalue() == ("" if value == "" else warning)


def test_switch_off_never_connects_or_discovers():
    assert asyncio.run(demo_seed.apply(NOWHERE, {})) == {}
    assert demo_seed.run(NOWHERE, {}) == {}


def test_a_failure_is_reported_and_never_raised_into_the_deploy():
    broken = SimpleNamespace(database_url=NOWHERE.database_url)  # no modules path: discovery itself fails
    log = io.StringIO()
    with contextlib.redirect_stderr(log):
        assert demo_seed.run(broken, ON) == {"failed": "AttributeError"}
    # One line naming the error class only, never a value.
    assert log.getvalue() == "DEMO SEED seed: failed: AttributeError\n"


def test_the_time_budget_is_bounded():
    assert demo_seed.CONNECT_SECONDS <= 5 and demo_seed.LOCK_MS <= 2000 and demo_seed.STATEMENT_MS <= 5000
    assert demo_seed.TOTAL_SECONDS <= 30 and demo_seed.CLOSE_SECONDS <= 2
    assert demo_seed.IDLE_MS >= demo_seed.STATEMENT_MS

    async def slow():
        await asyncio.sleep(10)
        return {"done": True}

    async def bounded():
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await demo_seed.bounded(slow(), started + 0.2)
        late = await demo_seed.bounded(slow(), started - 1)
        return result, late, loop.time() - started

    result, late, spent = asyncio.run(bounded())
    assert result == {"failed": "timeout"} and late == {"skipped": "time"} and spent < 2


def test_busy_and_errors_become_results():
    async def busy():
        raise demo_seed.Busy("scope")

    async def broken():
        raise RuntimeError("never shown")

    async def both():
        deadline = asyncio.get_running_loop().time() + 5
        return await demo_seed.bounded(busy(), deadline), await demo_seed.bounded(broken(), deadline)

    assert asyncio.run(both()) == ({"skipped": "busy"}, {"failed": "RuntimeError"})


def test_abandoned_work_never_holds_the_process():
    executor = demo_seed.AbandonedThreads()
    future = executor.submit(lambda: 7)
    assert future.result(timeout=5) == 7
    assert executor.shutdown(wait=True) is None


def test_ownership_record_keys_and_proof():
    assert demo_seed.row_key({"id": demo_seed.ACTOR}) == '{"id": "96403f23-f325-5330-83cc-1762a35304f1"}'
    assert demo_seed.row_key({"variant": "thumb", "media_id": 5}) == '{"media_id": "5", "variant": "thumb"}'
    assert demo_seed.written_here("t") == "t.xmin::text::bigint = pg_current_xact_id()::text::bigint % 4294967296"
    assert demo_seed.quote('a"b') == '"a""b"'
    assert demo_seed.table_name("identity_accounts") == '"identity_accounts"'
    for bad in ("Identity", "identity accounts", "x;drop", ""):
        with pytest.raises(ValueError):
            demo_seed.table_name(bad)


def test_sample_accounts_are_fixed_named_and_distinct():
    found = demo_seed.accounts()
    assert [(item.sample_set, item.role) for item in found] == [
        (sample_set, role) for sample_set in ("demo", "click-test") for role in ROLES
    ]
    assert len(found) == len({item.id for item in found}) == len({item.email for item in found}) == 10
    assert len({item.display_name for item in found}) == 10
    for item in found:
        assert item.id == demo_seed.seed_id(item.key) == uuid5(demo_seed.NAMESPACE, item.key)
        assert re.fullmatch(r"DEMO-SEED-(DEMO|CLICK-TEST)-ACCOUNT-(BUYER|SELLER|RIVAL|OPERATOR|STAFF)", item.key)
        assert item.email == f"{item.role}.{item.sample_set}@example.test"
        # Made-up first and last names; the ownership record, never the name, marks a seed row.
        assert re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", item.display_name) and len(item.display_name) <= 100
        assert "demo" not in item.display_name.lower()
    assert demo_seed.accounts() == found
    assert demo_seed.account("click-test", "seller").email == "seller.click-test@example.test"
    assert {item.role: item.display_name for item in demo_seed.accounts() if item.sample_set == "demo"} == {
        "buyer": "Karim Nassar", "seller": "Lina Saab", "rival": "Ziad Mansour", "operator": "Nour Bitar",
        "staff": "Elie Daher"}
    assert {item.role: item.display_name for item in demo_seed.accounts() if item.sample_set == "click-test"} == {
        "buyer": "Rania Moussa", "seller": "Fadi Najjar", "rival": "Hiba Tannous", "operator": "Samir Azar",
        "staff": "Joelle Ghanem"}


def test_ids_are_pinned_for_the_sign_in_allowlist():
    # The password-free sample links bind to these exact ids; changing one strands its link.
    assert str(demo_seed.NAMESPACE) == "51ba9d9c-94a2-5604-9c6d-6d0bf31b6409"
    pinned = {
        ("demo", "buyer"): "f45cd555-8b5c-5a27-905c-1fd480191ca6",
        ("demo", "seller"): "b8151b1f-a571-55cf-9b20-0d266c309882",
        ("demo", "rival"): "3d387941-eb86-5b5a-b38f-cfabec73de8b",
        ("click-test", "buyer"): "5068845e-5c35-53e6-9566-86d5879e69b0",
        ("click-test", "seller"): "9489caa0-ab50-5674-bd38-dd896d3d5f72",
        ("click-test", "rival"): "a6c02e3d-e284-5a6d-a44e-1a5ec9a1b303",
        ("demo", "operator"): "57d4a5f4-3728-5524-b31f-81949adfea7c",
        ("demo", "staff"): "27fe364e-a31a-5e87-bd1b-5849dd4a217c",
        ("click-test", "operator"): "67eca4e3-9cee-54ee-b3cb-d6618352df01",
        ("click-test", "staff"): "2b35cdec-1c4c-5196-a772-b7db3c3e7400",
    }
    assert {(item.sample_set, item.role): str(item.id) for item in demo_seed.accounts()} == pinned
    # The sample data layer and the sign-in links read these too.
    assert str(demo_seed.ACTOR) == "96403f23-f325-5330-83cc-1762a35304f1"
    assert {item.sample_set: (str(item.id), str(item.membership_id)) for item in demo_seed.businesses()} == {
        "demo": ("392b6fec-314f-59b9-b572-43ff7ff349bd", "04f5c081-49f9-5ce4-b5f4-3f547b303b1a"),
        "click-test": ("fe3eea0b-92f2-5c16-9b01-9a0fd0e54f13", "01750097-71ac-5258-9f56-d0ddf7b9574e"),
    }
    assert {(item.sample_set, item.item): str(item.id) for item in demo_seed.listings()} == {
        ("demo", "auction"): "49f03e8c-fd6e-5579-ac02-c8058d380433",
        ("demo", "buy-now"): "5df1567e-30a8-51e0-b5b0-72d4e2aaa976",
        ("demo", "spare"): "1c672bab-cb34-51da-9004-d5d6c6e78677",
        ("click-test", "auction"): "07552b9e-75be-550d-9e12-8a4205f019ea",
        ("click-test", "buy-now"): "bada9761-162f-50f2-9e02-8966fbe2fb02",
        ("click-test", "spare"): "a8be7b30-74f2-5105-a720-a531f601b83c",
    }


def test_each_set_has_its_own_sample_business_and_drafts():
    found = demo_seed.businesses()
    assert [item.sample_set for item in found] == ["demo", "click-test"]
    assert [item.public_name for item in found] == ["Zayzafoun Watch House", "Sanawbar Watch House"]
    for item in found:
        assert item.key == f"DEMO-SEED-{item.sample_set.upper()}-BUSINESS-DEALER"
        assert item.id == demo_seed.seed_id(item.key)
        assert item.membership_key == f"DEMO-SEED-{item.sample_set.upper()}-MEMBERSHIP-STAFF"
        assert item.membership_id == demo_seed.seed_id(item.membership_key)
        assert "demo" not in item.public_name.lower() and item.public_name.isascii()
        assert 2 <= len(item.public_name) <= 120
    # Staff may keep and sell that business's stock and read its records; never manage staff or jobs.
    assert demo_seed.STAFF_CAPABILITIES == ("business.stock.write", "business.records.read")
    drafts = demo_seed.listings()
    assert drafts == demo_seed.listings()
    assert {(item.sample_set, item.item, item.seller) for item in drafts} == {
        (sample_set, item, seller) for sample_set in ("demo", "click-test")
        for item, seller in (("auction", "private"), ("buy-now", "dealer"), ("spare", "dealer"))
    }
    ids = [value for item in drafts for value in (item.id, item.watch_id, item.photo_id)]
    ids += [value for item in found for value in (item.id, item.membership_id)]
    ids += [item.id for item in demo_seed.accounts()] + [demo_seed.ACTOR]
    assert len(ids) == len(set(ids))
    for item in drafts:
        assert item.key == f"DEMO-SEED-{item.sample_set.upper()}-LISTING-{item.item.upper()}"
        # Never the app's own DEMO-WATCH import keys, so the two can never collide.
        assert not re.fullmatch(r"DEMO-WATCH-0[1-6]", item.key)
    # The seed's recorded actor is never one of its accounts.
    assert demo_seed.ACTOR not in {item.id for item in demo_seed.accounts()}


def test_each_handoff_vouches_for_exactly_one_holder_of_one_set():
    assert set(demo_seed.HOLDERS.values()) == {"seller", "staff"}
    assert (demo_seed.HANDOFF_AUDIENCE, demo_seed.HANDOFF_DESTINATION) == ("catalog", "catalog-demo-seed")
    assert re.fullmatch(r"[a-z][a-z0-9.-]+\.v[1-9][0-9]*", demo_seed.HANDOFF_TYPE)
    keys = set()
    for sample_set in demo_seed.SETS:
        business = demo_seed.business(sample_set)
        for holder in demo_seed.HOLDERS.values():
            person = demo_seed.account(sample_set, holder)
            for state in ("ready", "withdrawn"):
                assert demo_seed.handoff_data(sample_set, holder, state) == {
                    "sample_set": sample_set,
                    "holder": holder,
                    "subject_id": str(person.id),
                    "business_id": str(business.id) if holder == "staff" else None,
                    "state": state,
                }
            for state in ("revoked", "Ready", ""):
                with pytest.raises(ValueError):
                    demo_seed.handoff_data(sample_set, holder, state)
            keys.add(demo_seed.handoff_key(sample_set, holder))
    assert len(keys) == 4 and all(re.fullmatch(r"DEMO-SEED-[A-Z0-9-]+", key) for key in keys)
    assert not keys & {item.key for item in demo_seed.accounts()}
    # Catalog acts on a handoff for at most half an hour, so a later deploy of Identity renews it; a few
    # minutes of clock difference between the two services are allowed, never more.
    assert demo_seed.HANDOFF_STATES == ("ready", "withdrawn")
    assert (demo_seed.HANDOFF_FRESH_SECONDS, demo_seed.HANDOFF_SKEW_SECONDS) == (1800, 120)


def test_identity_signs_a_handoff_only_with_its_own_disposable_key():
    private, public = key_pair()
    other_private, other_public = key_pair()
    name = demo_seed.HANDOFF_PRIVATE_KEY
    # Unset, nothing is signed, so nothing is sent.
    for unset in ({}, {name: ""}, {name: " \n"}):
        assert demo_seed.handoff_signing_key(unset) is None
    assert demo_seed.handoff_signing_key({name: private}) == private.strip()
    assert demo_seed.handoff_signing_key({name: private.replace("\n", "\\n")}) == private.strip()
    # Identity's other keys may sit beside it, as long as none of them is its pair.
    assert demo_seed.handoff_signing_key(
        {name: private, "BT_EVENT_PRIVATE_KEY": other_private, "BT_AUTH_PRIVATE_KEY": other_private,
         "BT_SERVICE_AUTH_PUBLIC_KEY": other_public}) == private.strip()
    for wrong in (
        {name: "not a key"},
        # The public half in its place, or Identity's event, token or service verifying key standing in for it.
        {name: public},
        {name: private, "BT_EVENT_PRIVATE_KEY": private},
        {name: private, "BT_AUTH_PRIVATE_KEY": private.replace("\n", "\\n")},
        {name: private, "BT_SERVICE_AUTH_PUBLIC_KEY": public},
    ):
        with pytest.raises(demo_seed.HandoffKey):
            demo_seed.handoff_signing_key(wrong)
    # Each handoff carries Identity's order and an assertion over exactly its fields that only its pair verifies.
    event = demo_seed.handoff_event(private, "demo", "staff", "ready", 5)
    data = dict(event.data)
    seq, assertion = data.pop("seq"), data.pop("assertion")
    assert seq == 5 and data == demo_seed.handoff_data("demo", "staff", "ready")
    assert (event.type, event.source, event.subject, event.request_id) == (
        demo_seed.HANDOFF_TYPE, "identity", data["subject_id"], demo_seed.REQUEST_ID)
    assert demo_seed.verify_handoff(public, assertion, event.id, 5, data, event.time)
    assert not demo_seed.verify_handoff(other_public, assertion, event.id, 5, data, event.time)
    assert not demo_seed.verify_handoff(public, assertion, event.id, 6, data, event.time)


def test_only_identitys_membership_module_has_a_removal_step():
    modules = discover(Settings(database_url="postgresql://unused/unused", service_name="identity").modules_path)
    steps = {item.id: item.fixtures[demo_seed.REMOVE_ENTRY] for item in modules
             if demo_seed.REMOVE_ENTRY in item.fixtures}
    assert demo_seed.REMOVE_ENTRY == "deploy-remove"
    assert steps == {"L02.membership": "deploy_seed.py:withdraw"}


def test_a_seed_is_complete_only_when_every_step_put_its_rows_in_place():
    assert demo_seed.complete({"created": 2, "kept": 8, "handoff_sent": 4, "foreign": 0, "handoff_waiting": 0})
    assert demo_seed.complete({"attached": 3, "unchanged": 3, "waiting": 0})
    for result in ({"created": 9, "foreign": 1}, {"handoff_sent": 3, "handoff_withdrawn": 1},
                   {"handoff_busy": 1}, {"handoff_unsigned": 4}, {"created": 2, "handoff_unsigned": 4},
                   {"waiting": 2}, {"skipped": "busy"}, {"failed": "timeout"},
                   {"skipped": "switch"}, None, "done"):
        assert not demo_seed.complete(result)
    assert demo_seed.COMPLETE_COUNTS == ("created", "kept", "attached", "unchanged", "handoff_sent")


def test_the_sign_in_owner_check_is_only_for_the_sample_sign_in_roles():
    # The Operator tab is its own separately reviewed link (decision 252): never a seed sign-in.
    assert demo_seed.SIGN_IN_ROLES == ("buyer", "seller", "rival", "staff")
    for sample_set, role in (("demo", "operator"), ("live", "buyer"), ("demo", "admin"), ("", "")):
        with pytest.raises(ValueError):
            # Refused before it touches the transaction.
            asyncio.run(demo_seed.account_owner(None, sample_set, role))


def test_the_hard_deadline_bounds_the_whole_optional_seed():
    # One switch for both; the child is this module, and the seed's own budget ends well inside the hard limit.
    assert demo_seed.SWITCH is demo_seed_deadline.SWITCH
    assert demo_seed_deadline.CHILD == demo_seed_deadline.__name__
    assert demo_seed.TOTAL_SECONDS + demo_seed.CLOSE_SECONDS < demo_seed_deadline.HARD_SECONDS
    assert demo_seed_deadline.BOUND_SECONDS == 43
    # Unset, the migration step starts no child at all.
    started = time.monotonic()
    assert demo_seed_deadline.supervise({}) is None
    assert time.monotonic() - started < 1


def test_the_supervisor_stops_a_stalled_seed_and_ignores_a_failed_one(tmp_path, monkeypatch, capfd):
    mark = tmp_path / "stalled.pid"
    (tmp_path / "seed_stall_probe.py").write_text(
        "import os, time\n"
        "open(os.environ['STALL_MARK'], 'w').write(str(os.getpid()))\n"
        "print('seed started', flush=True)\n"
        "time.sleep(3600)\n"
    )
    (tmp_path / "seed_failed_probe.py").write_text("print('seed failing', flush=True)\nraise SystemExit(3)\n")
    environ = {demo_seed.SWITCH: demo_seed.SWITCH_VALUE, "PYTHONPATH": str(tmp_path), "STALL_MARK": str(mark)}
    monkeypatch.setattr(demo_seed_deadline, "HARD_SECONDS", 1)
    monkeypatch.setattr(demo_seed_deadline, "CHILD", "seed_stall_probe")
    capfd.readouterr()
    started = time.monotonic()
    assert demo_seed_deadline.supervise(environ) is None
    spent = time.monotonic() - started
    assert 1 <= spent < 1 + demo_seed_deadline.REAP_SECONDS + demo_seed_deadline.RELAY_SECONDS + 2
    # Its lines reach the deploy log, then the one stop note; the child is killed and reaped.
    assert capfd.readouterr().err == "seed started\n" + demo_seed_deadline.STOPPED.decode()
    with pytest.raises(ProcessLookupError):
        os.kill(int(mark.read_text()), 0)
    # A child that fails, or cannot even start its module, is ignored: the step goes on once it ends.
    monkeypatch.setattr(demo_seed_deadline, "HARD_SECONDS", 30)
    for child, line in (("seed_failed_probe", "seed failing"), ("seed_missing_probe", "No module named")):
        monkeypatch.setattr(demo_seed_deadline, "CHILD", child)
        started = time.monotonic()
        assert demo_seed_deadline.supervise(environ) is None
        assert time.monotonic() - started < 10
        assert line in capfd.readouterr().err

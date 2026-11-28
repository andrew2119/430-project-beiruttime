import json
import sqlite3
from datetime import timedelta

import pytest

from fixtures import BINDING, DOMAINS, NOW, ROLES, actors, current_case, evidence, outcomes
from restore import CONTRACT, read, reconcile, replay, restore, seed


@pytest.fixture
def snapshot(tmp_path):
    source, target = tmp_path / "backup", tmp_path / "restored"
    seed(source, evidence())
    return source, target


def access(root, **changes):
    arguments = dict(current={"active": True, "binding": dict(BINDING)},
                     binding=dict(BINDING), now=NOW, tombstones=set())
    arguments.update(changes)
    return read(root, "synthetic-file-1", **arguments)


def test_contract_and_actor_matrix():
    assert len(actors()) == len(ROLES) * 4
    assert len(DOMAINS) == CONTRACT["limits"]["stores"] == 9
    assert all(row["synthetic"] for row in actors())
    assert set(BINDING) == set(CONTRACT["required_bindings"])


def test_versioned_result_schema():
    from pathlib import Path

    schema = json.loads(Path(__file__).with_name("envelope.schema.json").read_text())
    for result in outcomes().values():
        assert set(result) == set(schema["required"]) == set(schema["properties"])
        for key, value in result.items():
            rule = schema["properties"][key]
            if "const" in rule:
                assert value == rule["const"]
            elif "enum" in rule:
                assert value in rule["enum"]
            elif rule.get("type") == "integer":
                assert type(value) is int and value >= rule["minimum"]
            elif value is not None:
                assert isinstance(value, str)
                assert rule.get("minLength", 0) <= len(value) <= rule["maxLength"]
        if result["next_review_at"]:
            from restore import instant
            instant(result["next_review_at"])
    assert outcomes()["duplicate"] == outcomes()["success"]


def test_nine_synthetic_stores_files_metadata_and_restart(snapshot):
    source, target = snapshot
    assert restore(source, target, tombstones=set(), current_available=True) == "complete"
    for domain in DOMAINS:
        with sqlite3.connect(target / f"{domain}.db") as connection:
            assert connection.execute("SELECT * FROM synthetic_records").fetchall() == [("synthetic-record", 2)]
    assert access(target) == ("complete", b"synthetic restricted bytes")
    assert json.loads((target / "metadata.json").read_text())[0]["binding"] == BINDING
    # Reopen from disk without retaining an in-memory restore object.
    assert access(type(target)(str(target)))[0] == "complete"


def test_tombstones_precede_access_and_revocation_stays_current(snapshot):
    source, target = snapshot
    assert restore(source, target, tombstones={"synthetic-file-1"}, current_available=True) == "complete"
    assert not (target / "files" / "synthetic-file-1").exists()
    assert json.loads((target / "metadata.json").read_text()) == []
    assert access(target, tombstones={"synthetic-file-1"}) == ("denied", None)
    assert access(source, current={"active": False, "binding": BINDING}) == ("denied", None)


def test_current_provider_unavailable_never_opens_restore(snapshot):
    source, target = snapshot
    assert restore(source, target, tombstones=set(), current_available=False) == "unavailable"
    assert not target.exists()
    assert access(source, current=None) == ("unavailable", None)


@pytest.mark.parametrize("key", list(BINDING))
def test_cross_scope_and_stale_binding(snapshot, key):
    source, _ = snapshot
    binding = dict(BINDING, **{key: "different"})
    state, content = access(source, binding=binding)
    assert state == ("stale" if key.endswith("revision") else "denied")
    assert content is None


@pytest.mark.parametrize("retention,days", [("unsubmitted", 7), ("reviewed", 30), ("audit", 365)])
@pytest.mark.parametrize("offset,expected", [(-1, "complete"), (0, "denied"), (1, "denied")])
def test_retention_boundaries(tmp_path, retention, days, offset, expected):
    source = tmp_path / "backup"
    seed(source, dict(evidence(), retention=retention))
    now = NOW + timedelta(days=days, seconds=offset)
    assert access(source, now=now)[0] == expected
    preserved = "complete" if retention == "reviewed" else expected
    assert access(source, now=now, current=current_case())[0] == preserved


def test_old_case_flag_does_not_extend_retention(tmp_path):
    source = tmp_path / "backup"
    seed(source, dict(evidence(), active_case=True))
    assert access(source, now=NOW + timedelta(days=30))[0] == "denied"


def test_missing_file_is_explicit(snapshot):
    source, target = snapshot
    (source / "files" / "synthetic-file-1").unlink()
    assert restore(source, target, tombstones=set(), current_available=True) == "missing_file"
    assert access(target) == ("missing_file", None)


@pytest.mark.parametrize("damage", ["database", "bytes", "size", "path", "symlink", "count"])
def test_corruption_is_not_complete(snapshot, damage):
    source, target = snapshot
    path = source / "files" / "synthetic-file-1"
    rows = json.loads((source / "metadata.json").read_text())
    if damage == "database":
        (source / "orders.db").unlink()
    elif damage == "bytes":
        path.write_bytes(b"changed")
    elif damage == "size":
        rows[0]["size"] = CONTRACT["limits"]["file_bytes"] + 1
    elif damage == "path":
        rows[0]["file_id"] = "../outside"
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(source / "orders.db")
    else:
        rows *= CONTRACT["limits"]["files"] + 1
    (source / "metadata.json").write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        restore(source, target, tombstones=set(), current_available=True)
    assert not target.exists()


def test_unknown_timeout_duplicate_and_lost_response(snapshot):
    source, target = snapshot
    calls = []

    def timeout(binding):
        calls.append(binding)
        raise TimeoutError

    assert replay(source, BINDING, timeout) == "pending"
    assert calls == [BINDING, BINDING]
    unknown = {"binding": BINDING, "state": "unknown"}
    assert replay(source, BINDING, lambda _: unknown) == "pending"
    confirmed = {"binding": BINDING, "state": "confirmed"}
    assert replay(source, BINDING, lambda _: confirmed) == "confirmed"
    restore(source, target, tombstones=set(), current_available=True)
    assert replay(target, BINDING, lambda _: confirmed) == "confirmed"
    assert len(json.loads((target / "receipts.json").read_text())) == 1
    assert replay(target, dict(BINDING, actor_id="different"), lambda _: confirmed) == "denied"
    assert replay(target, BINDING, lambda _: dict(confirmed, state="declined")) == "denied"
    assert replay(target, BINDING, timeout) == "pending"


def facts():
    return dict(principal_minor=500000, buyer_fee_minor=15000, business_fee_minor=25000,
                refund_minor=500000, currency="USD", money="confirmed", current_authority=True,
                actual_receipt=True, current_checks=True, incident=False, dispute=False,
                now=NOW, window_end=NOW)


@pytest.mark.parametrize("key,value", [
    ("money", "unknown"), ("money", "pending"), ("actual_receipt", False),
    ("current_checks", False), ("incident", True), ("dispute", True), ("current_authority", False),
])
def test_reconciliation_holds_missing_current_facts(key, value):
    assert reconcile(dict(facts(), **{key: value})) == "pending"


@pytest.mark.parametrize("offset,expected", [(-1, "pending"), (0, "review_required"), (1, "review_required")])
def test_receipt_window_boundaries(offset, expected):
    assert reconcile(dict(facts(), now=NOW + timedelta(seconds=offset))) == expected


@pytest.mark.parametrize("value", [True, 1.5, float("inf"), -1, 9000000000000001])
def test_money_is_finite_integer_minor_units(value):
    assert reconcile(dict(facts(), principal_minor=value)) == "denied"


def test_refunds_exclude_fees_and_never_create_release():
    assert reconcile(facts()) == "review_required"
    assert reconcile(dict(facts(), refund_minor=515000)) == "denied"
    assert reconcile(dict(facts(), currency="other")) == "denied"
    job = dict(facts(), buyer_fee_minor=0)
    assert reconcile(job) == "review_required"
    assert job["principal_minor"] - job["business_fee_minor"] == 475000


def test_no_private_output(snapshot, capsys, caplog):
    source, target = snapshot
    restore(source, target, tombstones=set(), current_available=True)
    access(target)
    assert capsys.readouterr() == ("", "")
    assert caplog.text == ""


@pytest.mark.parametrize("damage,expected", [
    ("absent_case", "denied"), ("absent_assignment", "denied"),
    ("revoked_case", "denied"), ("revoked_assignment", "denied"),
    ("not_needed", "denied"), ("other_file", "denied"),
    ("other_case", "denied"), ("stale_case", "stale"),
    ("stale_assignment", "stale"), ("invalid_revision", "denied"),
])
def test_current_case_retention_assertions(snapshot, damage, expected):
    source, _ = snapshot
    current = current_case()
    case, assignment = current["retention_case"], current["assignment"]
    if damage == "absent_case":
        del current["retention_case"]
    elif damage == "absent_assignment":
        del current["assignment"]
    elif damage == "revoked_case":
        case["active"] = False
    elif damage == "revoked_assignment":
        assignment["active"] = False
    elif damage == "not_needed":
        case["needs_evidence"] = False
    elif damage == "other_file":
        case["file_id"] = "synthetic-file-2"
    elif damage == "other_case":
        assignment["case_id"] = "synthetic-case-2"
    elif damage == "stale_case":
        assignment["case_revision"] += 1
    elif damage == "stale_assignment":
        assignment["assignment_revision"] += 1
    else:
        case["case_revision"] = True
    assert access(source, current=current, now=NOW + timedelta(days=31)) == (expected, None)


@pytest.mark.parametrize("assertion", ["retention_case", "assignment"])
@pytest.mark.parametrize("key", list(BINDING))
def test_case_retention_rejects_cross_scope(snapshot, assertion, key):
    source, _ = snapshot
    current = current_case()
    current[assertion]["binding"] = dict(BINDING, **{key: "different"})
    assert access(source, current=current, now=NOW + timedelta(days=31)) == ("denied", None)


def test_case_retention_rechecks_revocation_each_read(snapshot):
    source, _ = snapshot
    current = current_case()
    now = NOW + timedelta(days=31)
    assert access(source, current=current, now=now)[0] == "complete"
    current["assignment"]["active"] = False
    assert access(source, current=current, now=now) == ("denied", None)

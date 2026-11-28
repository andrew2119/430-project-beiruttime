"""Bounded synthetic restore model, never a runtime serving or financial authority."""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fixtures import DOMAINS

CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text())


def digest(content):
    return hashlib.sha256(content).hexdigest()


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("UTC required")
    return parsed


def seed(root, metadata, content=b"synthetic restricted bytes"):
    root.mkdir()
    for domain in DOMAINS:
        with sqlite3.connect(root / f"{domain}.db") as connection:
            connection.execute("CREATE TABLE synthetic_records (id TEXT PRIMARY KEY, revision INTEGER)")
            connection.execute("INSERT INTO synthetic_records VALUES ('synthetic-record', 2)")
    (root / "files").mkdir()
    (root / "files" / metadata["file_id"]).write_bytes(content)
    row = dict(metadata, checksum=digest(content), size=len(content))
    (root / "metadata.json").write_text(json.dumps([row]))
    (root / "receipts.json").write_text("{}")


def restore(source, target, *, tombstones, current_available):
    # A fresh destination is private until every validation and deletion finishes.
    if target.exists():
        raise ValueError("Fresh destination required")
    if not current_available:
        return "unavailable"
    rows = json.loads((source / "metadata.json").read_text())
    if len(rows) > CONTRACT["limits"]["files"]:
        raise ValueError("File count exceeded")
    for row in rows:
        file_id = row["file_id"]
        if not file_id or Path(file_id).name != file_id or file_id in (".", ".."):
            raise ValueError("Opaque file identifier required")
        if type(row["size"]) is not int or not 0 <= row["size"] <= CONTRACT["limits"]["file_bytes"]:
            raise ValueError("File budget exceeded")
    target.mkdir()
    try:
        for domain in DOMAINS:
            origin = source / f"{domain}.db"
            if not origin.is_file() or origin.is_symlink():
                raise ValueError("Missing isolated snapshot")
            with sqlite3.connect(f"file:{origin}?mode=ro", uri=True) as old:
                with sqlite3.connect(target / f"{domain}.db") as new:
                    old.backup(new)
                    if new.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise ValueError("Snapshot integrity failure")
        (target / "files").mkdir()
        missing = False
        for row in rows:
            if row["file_id"] in tombstones:
                continue
            original = source / "files" / row["file_id"]
            if not original.exists():
                missing = True
                continue
            if original.is_symlink() or original.stat().st_size > CONTRACT["limits"]["file_bytes"]:
                raise ValueError("Unsafe file")
            content = original.read_bytes()
            if len(content) != row["size"] or digest(content) != row["checksum"]:
                raise ValueError("File integrity failure")
            (target / "files" / row["file_id"]).write_bytes(content)
        (target / "metadata.json").write_text(json.dumps([
            row for row in rows if row["file_id"] not in tombstones
        ]))
        shutil.copyfile(source / "receipts.json", target / "receipts.json")
        return "missing_file" if missing else "complete"
    except Exception:
        shutil.rmtree(target)
        raise


def read(root, file_id, *, current, binding, now, tombstones):
    if current is None:
        return "unavailable", None
    if not current["active"] or file_id in tombstones:
        return "denied", None
    rows = json.loads((root / "metadata.json").read_text())
    row = next((row for row in rows if row["file_id"] == file_id), None)
    if row is None:
        return "missing_file", None
    for key in CONTRACT["required_bindings"]:
        if binding.get(key) != row["binding"].get(key):
            return ("stale" if key.endswith("revision") else "denied"), None
    if current["binding"] != binding:
        return "denied", None
    # An active case must be asserted by the current provider, never an old backup.
    start = instant(row["retention_start"])
    days = CONTRACT["retention_days"][row["retention"]]
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("UTC required")
    if now >= start + timedelta(days=days):
        if row["retention"] != "reviewed":
            return "denied", None
        case = current.get("retention_case")
        assignment = current.get("assignment")
        if not isinstance(case, dict) or not isinstance(assignment, dict):
            return "denied", None
        if (case.get("active") is not True or case.get("needs_evidence") is not True
                or assignment.get("active") is not True
                or case.get("file_id") != file_id
                or case.get("binding") != binding
                or assignment.get("binding") != binding
                or not isinstance(case.get("case_id"), str) or not case["case_id"]
                or assignment.get("case_id") != case["case_id"]):
            return "denied", None
        for key in ("case_revision", "assignment_revision"):
            if type(case.get(key)) is not int or case[key] < 1:
                return "denied", None
            if type(assignment.get(key)) is not int or assignment[key] != case[key]:
                return "stale", None
    path = root / "files" / file_id
    if not path.is_file():
        return "missing_file", None
    if path.is_symlink() or path.stat().st_size > CONTRACT["limits"]["file_bytes"]:
        return "unavailable", None
    content = path.read_bytes()
    if digest(content) != row["checksum"] or len(content) != row["size"]:
        return "unavailable", None
    return "complete", content


def replay(root, binding, lookup):
    receipts_path = root / "receipts.json"
    receipts = json.loads(receipts_path.read_text())
    operation = binding["operation_id"]
    previous = receipts.get(operation)
    if previous and previous["binding"] != binding:
        return "denied"
    # Even a retained receipt is not current permission or authority to release.
    for _ in range(CONTRACT["limits"]["attempts"]):
        try:
            result = lookup(dict(binding))
        except TimeoutError:
            continue
        if result["binding"] != binding:
            return "denied"
        if result["state"] not in ("confirmed", "declined"):
            return "pending"
        if previous and previous != result:
            return "denied"
        receipts[operation] = result
        temporary = root / "receipts.pending"
        temporary.write_text(json.dumps(receipts))
        temporary.replace(receipts_path)
        return result["state"]
    return "pending"


def reconcile(facts):
    # Findings only: this module cannot charge, acknowledge custody or pay out.
    for key in ("principal_minor", "buyer_fee_minor", "business_fee_minor", "refund_minor"):
        value = facts[key]
        if type(value) is not int or not 0 <= value <= 9_000_000_000_000_000:
            return "denied"
    if facts["currency"] != "USD" or facts["refund_minor"] > facts["principal_minor"]:
        return "denied"
    if facts["money"] in ("unknown", "pending") or not facts["current_authority"]:
        return "pending"
    if facts["incident"] or facts["dispute"] or not facts["actual_receipt"]:
        return "pending"
    if not facts["current_checks"] or facts["now"] < facts["window_end"]:
        return "pending"
    return "review_required"

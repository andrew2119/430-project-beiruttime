"""Bounded lifecycle proof contract; connected execution requires reviewed providers."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


PROOFS = ("dependency-outage", "process-restart", "database-restart", "replay")
SCHEMA = "bt.native.lifecycle.v1"
DOMAINS = ("identity", "eligibility", "catalog", "auction", "pricing",
           "communications", "orders", "trust", "service-operations")


class Refused(ValueError):
    """Ownership or retained-state evidence is insufficient."""


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def validate(record, run_dir):
    """Validate an N01 ownership observation before every process mutation."""
    require(record["schema_version"] == SCHEMA, "Unsupported ownership schema")
    require(record.get("domain") in DOMAINS, "Unknown domain")
    require(Path(record["run_dir"]).resolve() == Path(run_dir).resolve(),
            "Foreign run directory")
    require(record["pid"] > 1 and bool(record["start_time"]), "Invalid process identity")
    require(record["owned_replica"] is True, "Separate owned replica required")
    require(record["runtime_kind"] in {"owning", "foundation-fallback"},
            "Unknown runtime ownership")
    if record["runtime_kind"] == "foundation-fallback":
        require(record["image"] == "beirut-time/foundation-service:local",
                "Foreign fallback image")
    url = urlsplit(record["url"])
    require(url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}
            and url.port is not None and not url.username and not url.password
            and url.path in {"", "/"} and not url.query and not url.fragment,
            "Explicit loopback origin required")
    db = record["database"]
    require(db["disposable"] is True and db["restricted"] is True
            and db["run_id"] == record["run_id"] and bool(db["id"]),
            "Restricted owned disposable database required")


def same_process(expected, observed, run_dir):
    validate(observed, run_dir)
    require(expected == observed, "Foreign or replaced process observation")


def retained(before, after):
    """Health and changed process identity alone never prove durable replay."""
    for key in ("operation_id", "subject_id", "durable_reference", "state_digest"):
        require(bool(before.get(key)) and before[key] == after.get(key),
                "Retained operation evidence missing: " + key)
    require(before["effect_count"] == after["effect_count"] == 1,
            "Operation effect duplicated or absent")
    for key in ("outbox_reference", "inbox_reference"):
        require(bool(before.get(key)) and before[key] == after.get(key),
                "Durable event evidence missing: " + key)
    require(after.get("outbox_pending") == 0 and after.get("inbox_effect_count") == 1,
            "Event replay has not converged exactly once")


def replayed(before, after, operation, record):
    """Require attributable redelivery and duplicate suppression, not final health."""
    bindings = {key: operation[key] for key in
                ("operation_id", "outbox_reference", "inbox_reference")}
    bindings.update(run_id=record["run_id"], database_id=record["database"]["id"])
    for observation in (before, after):
        require(isinstance(observation, dict), "Replay observation missing")
        for key, value in bindings.items():
            require(observation.get(key) == value, "Foreign replay evidence: " + key)
        for key in ("outbox_delivery_count", "inbox_delivery_count", "inbox_duplicate_count"):
            value = observation.get(key)
            require(type(value) is int and value >= 0, "Invalid replay counter: " + key)
    require(before["outbox_delivery_count"] >= 1 and before["inbox_delivery_count"] >= 1,
            "Initial event delivery required")
    for key in ("outbox_delivery_count", "inbox_delivery_count", "inbox_duplicate_count"):
        require(after[key] > before[key], "Replay did not advance: " + key)


def exercise(provider, proof, run_dir):
    """Use only injected bounded provider calls; no default process/network access.

    Each provider method takes timeout in seconds and must enforce it internally.
    start must register each replica durably before exposing it, and roll back a
    partial start itself. cleanup checks live ownership and attempts every recorded
    replica, including replacements. restore is idempotent after partial failure.
    """
    require(proof in PROOFS, "Unknown proof")
    record = provider.start(proof, run_dir, timeout=30)
    try:
        validate(record, run_dir)
        same_process(record, provider.observe(record, timeout=5), run_dir)
        before = provider.operation(record, timeout=10)
        replay_before = None
        if proof == "replay":
            replay_before = provider.replay_evidence(record, before["operation_id"], timeout=5)
        try:
            # Revalidate immediately before a destructive step.
            same_process(record, provider.observe(record, timeout=5), run_dir)
            if proof in {"process-restart", "replay"}:
                require(record["runtime_kind"] == "owning", "Owning runtime required")
            provider.disrupt(record, proof, timeout=10)
            if proof == "dependency-outage":
                isolation = provider.isolation(record, timeout=10)
                require(isolation == {"shell_available": True, "catalog_available": True,
                                      "unavailable_domains": [record["domain"]],
                                      "domain_statuses": {
                                          domain: ("unavailable" if domain == record["domain"]
                                                   else "ready") for domain in DOMAINS},
                                      "dependency_status": 503,
                                      "error_code": "unavailable", "request_id_present": True},
                        "Outage escaped its domain or shell")
        finally:
            provider.restore(record, proof, timeout=30)
        current = provider.observe(record, timeout=5)
        validate(current, run_dir)
        for key in ("run_id", "run_dir", "database", "domain", "url", "runtime_kind"):
            require(current[key] == record[key], "Recovery changed ownership or storage")
        if proof in {"process-restart", "replay"}:
            require(current["pid"] != record["pid"]
                    and current["start_time"] != record["start_time"],
                    "Actual owning process restart required")
        if proof == "database-restart":
            evidence = provider.database_restart_evidence(record, timeout=5)
            require(evidence["database_id"] == record["database"]["id"]
                    and evidence["before_start_time"] != evidence["after_start_time"]
                    and bool(evidence["before_start_time"])
                    and bool(evidence["after_start_time"]),
                    "Owned database process restart required")
        provider.recovered(current, timeout=30)
        after = provider.retry(current, before["operation_id"], timeout=10)
        retained(before, after)
        if proof == "replay":
            replay_after = provider.replay_evidence(current, before["operation_id"], timeout=5)
            replayed(replay_before, replay_after, before, current)
        return {"schema_version": SCHEMA, "proof": proof, "state": "passed"}
    finally:
        provider.cleanup(run_dir, timeout=30)


def plan():
    return {"schema_version": SCHEMA, "proofs": list(PROOFS),
            "state": "deferred", "prerequisites": ["N01", "N02", "N04"],
            "provider_inputs": ["A10", "E04", "E06"],
            "acceptance_checks": {
                "original_mapping_comparison": "deferred",
                "recursive_lease_overlap": "deferred"},
            "contract": "tests/native/n06/README.md",
            "execution_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", choices=("all", *PROOFS), required=True)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if not args.plan and args.run_dir is None:
        parser.error("--run-dir is required for execution")
    result = plan()
    if args.proof != "all":
        result["proofs"] = [args.proof]
    print(json.dumps(result, sort_keys=True))
    return 0 if args.plan else 2


if __name__ == "__main__":
    raise SystemExit(main())

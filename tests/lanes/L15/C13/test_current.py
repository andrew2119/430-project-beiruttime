"""Pure current-scope and stable-response checks without connected providers."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from bt_contracts_core.errors import AccessDenied, PublicError

ROOT = Path(__file__).resolve().parents[4]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load("decision_contract", "packages/contracts-catalog/brand-decisions/current.py")


@pytest.fixture
def authority(monkeypatch):
    dependency = ModuleType("service_app.catalog_dependencies")
    dependency.service_request = None
    monkeypatch.setitem(sys.modules, "service_app.catalog_dependencies", dependency)
    return load("decision_authority", "services/catalog/modules/brand-decisions/authority.py")


def bind(authority, sample):
    return authority.bind(sample["values"], sample["row"], sample["intent"], sample["approver_id"], now=sample["now"])


@pytest.mark.parametrize("expiry", [None, "2020-01-01T00:00:00Z"])
def test_accepted_unchanged_economics_survive_review(authority, expiry):
    sample = contract.fixture()
    sample["values"]["quote"]["expires_at"] = expiry
    result = bind(authority, sample)
    assert result["amount_minor"] == 500000
    assert contract.CurrentBindings.model_validate(result).currency == "USD"
    assert result["consent_revision"] == result["assignment_revision"] == 1


@pytest.mark.parametrize("case", ["denied", "stale"])
def test_contract_negative_cases(authority, case):
    with pytest.raises((PublicError, AccessDenied)):
        bind(authority, contract.fixture(case))


@pytest.mark.parametrize("condition", [
    "wrong_assignee", "self_assessor", "self_reviewer", "buyer_reviewer", "scope", "revoked",
    "withdrawal", "consent_missing", "currency", "boolean_amount", "infeasible", "unassigned",
])
def test_missing_current_conditions_deny(authority, condition):
    sample = contract.fixture()
    assessment, quote, grant = (sample["values"][key] for key in ("assessment", "quote", "grant"))
    if condition == "wrong_assignee":
        assessment["approver_id"] = assessment["assessor_id"]
    elif condition == "self_assessor":
        assessment["assessor_id"] = sample["approver_id"]
    elif condition == "self_reviewer":
        grant["reviewer_id"] = sample["approver_id"]
    elif condition == "buyer_reviewer":
        grant["reviewer_id"] = sample["row"]["buyer_id"]
    elif condition == "scope":
        sample["intent"]["quote_revision"] = 2
    elif condition == "revoked":
        grant["revoked_at"] = "2026-11-16T00:00:00Z"
    elif condition == "withdrawal":
        grant["consent_status"] = "withdrawal_pending"
    elif condition == "consent_missing":
        grant.pop("consent_revision")
    elif condition == "currency":
        quote["currency"] = grant["currency"] = "XXX"
    elif condition == "boolean_amount":
        quote["total_minor"] = grant["amount_minor"] = True
    elif condition == "infeasible":
        assessment["status"] = "infeasible"
    else:
        assessment["approval_assignment_current"] = False
    with pytest.raises((PublicError, AccessDenied)):
        bind(authority, sample)


@pytest.mark.parametrize("second,allowed", [(1, True), (0, False), (-1, False)])
def test_grant_expiry_boundary(authority, second, allowed):
    from datetime import timedelta
    sample = contract.fixture()
    sample["values"]["grant"]["expires_at"] = (sample["now"] + timedelta(seconds=second)).isoformat()
    if allowed:
        assert bind(authority, sample)
    else:
        with pytest.raises((PublicError, AccessDenied)):
            bind(authority, sample)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["lost", "pending", "mismatch", "denied", "success"])
async def test_consume_never_promotes_uncertain_acknowledgement(authority, monkeypatch, response):
    sample = contract.fixture("lost_response")
    bindings = bind(authority, sample)
    calls = []

    async def request(*args, **kwargs):
        calls.append(kwargs["json"])
        if args[3].endswith("prepare"):
            return {**kwargs["json"], "status": "prepared"}
        result = {**kwargs["json"], "status": "succeeded", "current": True}
        if response == "lost":
            return None
        if response in ("pending", "denied"):
            result["status"] = response
        if response == "mismatch":
            result["consent_revision"] += 1
        return result

    monkeypatch.setattr(authority, "service_request", request)
    if response == "success":
        first = await authority.consume(None, "stable", bindings)
        assert await authority.consume(None, "stable", bindings) == first
    else:
        with pytest.raises((PublicError, AccessDenied)):
            await authority.consume(None, "stable", bindings)
    assert all(call == {"operation_id": "stable", **bindings} for call in calls)


@pytest.mark.asyncio
async def test_current_adapter_uses_exact_v3_quote_and_scope(authority, monkeypatch):
    sample = contract.fixture()
    values = sample["values"]
    calls = []

    async def request(*args, **kwargs):
        calls.append((args[3], kwargs))
        if args[1] == "eligibility":
            return values["grant"]
        if args[1] == "pricing":
            quote = values["quote"]
            return {**quote, "quote_id": quote["id"], "quote_revision": quote["revision"],
                    "source_id": quote["request_id"], "source_revision": quote["request_revision"],
                    "organization_id": quote["brand_id"], "kind": "brand", "status": "valid",
                    "schedule_id": "usd-job-v2", "policy_revision": 2, "rounding": "half_up",
                    "economics": "committed", "execution_authority": "not_granted",
                    "accepted_at": "2026-11-01T00:00:00Z"}
        return {**values["assessment"], "organization_id": sample["row"]["brand_id"]}

    monkeypatch.setattr(authority, "service_request", request)
    actual = await authority.current(None, sample["row"], sample["intent"])
    assert actual["quote"]["expires_at"] is None
    assert calls[1] == (
        f'/internal/v3/quotes/{values["quote"]["id"]}/validation',
        {"params": {"buyer_id": sample["row"]["buyer_id"]}},
    )
    assert authority.bind(actual, sample["row"], sample["intent"], sample["approver_id"], now=sample["now"])
    values["grant"]["request_revision"] = 2
    with pytest.raises(PublicError) as error:
        await authority.current(None, sample["row"], sample["intent"])
    assert error.value.code == "stale_scope"


@pytest.mark.parametrize("watch", [None, "invalid", "00000000-0000-0000-0000-000000000099"])
def test_grant_watch_must_match_canonical_request(authority, watch):
    sample = contract.fixture()
    sample["values"]["grant"]["watch_id"] = watch
    with pytest.raises(PublicError):
        bind(authority, sample)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["prepare", "consume"])
@pytest.mark.parametrize("watch", [None, "00000000-0000-0000-0000-000000000099"])
async def test_acknowledgement_requires_exact_watch(authority, monkeypatch, phase, watch):
    bindings = bind(authority, contract.fixture())
    calls = []

    async def response(*args, **kwargs):
        calls.append(args[3])
        result = {**kwargs["json"], "status": "prepared" if args[3].endswith("prepare") else "succeeded",
                  "current": True}
        if args[3].endswith(phase):
            result["watch_id"] = watch
        return result

    monkeypatch.setattr(authority, "service_request", response)
    with pytest.raises(PublicError):
        await authority.consume(None, "stable", bindings)
    assert len(calls) == (1 if phase == "prepare" else 2)

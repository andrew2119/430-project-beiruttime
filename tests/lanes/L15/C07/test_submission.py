"""Submission adapters with local transaction and authority substitutes."""

import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from bt_contracts_core.errors import AccessDenied, PublicError

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "services/catalog/runtime"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


commands = load("bt_contracts.catalog.request_drafts.v2", "packages/contracts-catalog/request-drafts/v2.py")
load("bt_contracts.catalog.brand_decisions.v1", "packages/contracts-catalog/brand-decisions/v1.py")
routes = load("request_submission", "services/catalog/modules/request-drafts/submission/routes.py")


class Store:
    def __init__(self, owner, brand, configuration):
        self.operations = {}
        self.requests = []
        self.revisions = []
        self.events = []
        self.draft = {
            "id": uuid4(), "owner_id": owner, "revision": 1, "submitted_request_id": None,
            "content": {"kind": "customization", "brand_id": str(brand),
                        "configuration_id": str(configuration), "configuration_revision": 3,
                        "watch_context": "seller_base", "watch_reference": "Sample seller listing",
                        "scope_intent": "Review intended changes", "notes": "Private mixed نص ⌚"},
        }

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchrow(self, sql, *args):
        if "FROM l08_request_drafts" in sql:
            return deepcopy(self.draft) if self.draft and args[1] == self.draft["owner_id"] else None
        if "FROM catalog_customization_operations" in sql:
            return self.operations.get((args[0], args[1]))
        if "INSERT INTO catalog_customization_requests" in sql:
            row = dict(zip(("id", "draft_id", "buyer_id", "brand_id"), args), revision=1)
            self.requests.append(row)
            return row
        if "INSERT INTO catalog_customization_revisions" in sql:
            row = {"request_id": args[0], "revision": 1, "configuration_digest": args[1],
                   "configuration": args[2], "content": args[3], "actor_id": args[4],
                   "reason": args[5], "created_at": datetime(2026, 11, 16, tzinfo=timezone.utc)}
            self.revisions.append(row)
            return row
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if "UPDATE l08_request_drafts" in sql:
            self.draft["submitted_request_id"] = args[1]
        elif "INSERT INTO catalog_customization_operations" in sql:
            self.operations[(args[2], args[3])] = {"digest": args[4], "result": args[5]}
        else:
            raise AssertionError(sql)



@pytest.fixture
def case(monkeypatch):
    owner, brand, configuration = uuid4(), uuid4(), uuid4()
    store = Store(owner, brand, configuration)
    person = SimpleNamespace(roles=["buyer"], actor=SimpleNamespace(subject_id=owner, organization_id=None))
    snapshot = {"brand_id": str(brand), "base_model": "Sample base", "caliber": "Sample caliber",
                "reference_ids": [], "movement_mounting": {},
                "selections": {kind: {"option_id": str(uuid4()), "option_revision": 1, "definition": {}}
                               for kind in ("color", "material", "movement", "dial", "sophistication")}}
    authority = {"allowed": True, "error": None, "brand_calls": 0}

    async def principal(request):
        if not authority["allowed"]:
            raise AccessDenied("Current access removed")
        return person

    async def active_brand(request, brand_id):
        assert brand_id == brand
        authority["brand_calls"] += 1

    async def validate(*args):
        if authority["error"]:
            raise authority["error"]
        return {"status": "manual_assessment", "fields": {}, "digest": "a" * 64, "snapshot": snapshot}

    @asynccontextmanager
    async def transaction(pool, **kwargs):
        retained = deepcopy((pool.draft, pool.requests, pool.revisions, pool.operations, pool.events))
        try:
            yield pool
        except Exception:
            pool.draft, pool.requests, pool.revisions, pool.operations, pool.events = retained
            raise

    async def enqueue(tx, event, destinations):
        tx.events.append(event.model_dump(mode="json"))

    monkeypatch.setattr(routes, "principal", principal)
    monkeypatch.setattr(routes, "active_brand", active_brand)
    monkeypatch.setattr(routes, "configuration", validate)
    monkeypatch.setattr(routes, "unit_of_work", transaction)
    monkeypatch.setattr(routes, "enqueue", enqueue)
    request = SimpleNamespace(headers={"Idempotency-Key": "submit-current-1"},
                              state=SimpleNamespace(request_id=str(uuid4())),
                              app=SimpleNamespace(state=SimpleNamespace(pool=store)))
    body = commands.SubmitRequest(draft_revision=1, configuration_id=configuration, configuration_revision=3,
                                  movement_selection_id=uuid4(), movement_revision=1, expected_digest="a" * 64)
    return SimpleNamespace(store=store, person=person, request=request, body=body,
                           authority=authority, snapshot=snapshot)


@pytest.mark.asyncio
async def test_lost_response_replays_same_immutable_five_snapshots(case):
    first = await routes.submit(case.store.draft["id"], case.body, case.request)
    # Forget the response and fail the source: the durable acknowledgement still wins.
    case.authority["error"] = PublicError("source_unavailable", "Retry later.", status=503)
    replay = await routes.submit(case.store.draft["id"], case.body, case.request)
    assert first == replay
    assert len(case.store.requests) == len(case.store.revisions) == len(case.store.events) == 1
    assert len(first["request"]["configuration"]["selections"]) == 5
    assert "Private mixed" not in json.dumps(case.store.events)
    assert case.store.draft["submitted_request_id"] == UUID(first["resource_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{"dial": "missing"}, {"color": "stale_option"}, {"movement": "missing"}])
async def test_precise_dimension_errors_keep_correctable_draft(case, fields):
    before = deepcopy(case.store.draft)
    case.authority["error"] = PublicError("configuration_incomplete", "Review selections.", status=422,
                                          details={"fields": fields})
    with pytest.raises(PublicError) as error:
        await routes.submit(case.store.draft["id"], case.body, case.request)
    assert error.value.details == {"fields": fields}
    assert case.store.draft == before
    assert not case.store.requests and not case.store.operations and not case.store.events


@pytest.mark.asyncio
async def test_seller_base_intent_submits_without_allocation_or_purchase_authority(case):
    # The substitute has no reservation, purchase or allocation operation at all.
    result = await routes.submit(case.store.draft["id"], case.body, case.request)
    assert result["request"]["watch_context"] == "seller_base"
    assert result["request"]["status"] == "submitted"
    assert "execution_authority" not in result["request"]
    assert len(case.store.requests) == 1


@pytest.mark.asyncio
async def test_replay_rechecks_current_identity(case):
    await routes.submit(case.store.draft["id"], case.body, case.request)
    case.authority["allowed"] = False
    with pytest.raises(AccessDenied):
        await routes.submit(case.store.draft["id"], case.body, case.request)
    assert len(case.store.requests) == 1


@pytest.mark.asyncio
async def test_changed_retry_body_conflicts(case):
    await routes.submit(case.store.draft["id"], case.body, case.request)
    changed = case.body.model_copy(update={"draft_revision": 2})
    with pytest.raises(PublicError) as error:
        await routes.submit(case.store.draft["id"], changed, case.request)
    assert error.value.code == "idempotency_conflict"
    assert len(case.store.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "digest", "buyer", "organization"])
async def test_stale_and_cross_account_writes_never_submit(case, change):
    if change == "revision":
        case.store.draft["revision"] = 2
    elif change == "digest":
        case.body = case.body.model_copy(update={"expected_digest": "b" * 64})
    elif change == "buyer":
        case.person.actor.subject_id = uuid4()
    else:
        case.person.actor.organization_id = uuid4()
    with pytest.raises((PublicError, AccessDenied)):
        await routes.submit(case.store.draft["id"], case.body, case.request)
    assert not case.store.requests and not case.store.operations


@pytest.mark.asyncio
async def test_timeout_keeps_same_command_available_for_retry(case):
    case.authority["error"] = PublicError("source_unavailable", "Retry later.", status=503)
    with pytest.raises(PublicError):
        await routes.submit(case.store.draft["id"], case.body, case.request)
    assert not case.store.requests and not case.store.operations
    case.authority["error"] = None
    result = await routes.submit(case.store.draft["id"], case.body, case.request)
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_history_paginates_immutable_revisions_with_server_total(case, monkeypatch):
    result = await routes.submit(case.store.draft["id"], case.body, case.request)
    row = {**case.store.requests[0], "revision": 1000}
    rev = case.store.revisions[0]

    async def current(*args):
        return row, rev

    async def readable(*args):
        return case.person

    async def fetch(sql, request_id, before, limit, current_revision):
        assert request_id == row["id"] and current_revision == 1000
        return [{**rev, "revision": i} for i in range(min((before or 1001) - 1, 1000), 0, -1)][:limit]

    monkeypatch.setattr(routes, "current", current)
    monkeypatch.setattr(routes, "readable", readable)
    monkeypatch.setattr(case.store, "fetch", fetch, raising=False)
    first = await routes.history(UUID(result["resource_id"]), case.request, limit=50, before_revision=None)
    second = await routes.history(UUID(result["resource_id"]), case.request, limit=50, before_revision=first["next_cursor"])
    assert first["total"] == second["total"] == 1000
    assert first["items"][0]["revision"] == 1000 and second["items"][0]["revision"] == 950
    assert len(first["items"]) == len(second["items"]) == 50
    assert first["items"][0]["reason"] == rev["reason"]


def test_deterministic_recovery_responses_match_published_schema():
    from pydantic import ValidationError
    from bt_contracts_core.errors import ErrorEnvelope
    fixtures = json.loads((ROOT / "packages/contracts-catalog/request-drafts/fixtures/recovery.v2.json").read_text())
    successes = []
    for case in fixtures["cases"]:
        if case["http_status"] == 200:
            operation = commands.SubmissionOperation.model_validate(case["response"])
            successes.append(operation)
        else:
            ErrorEnvelope.model_validate(case["response"])
    assert successes[0] == successes[1] == successes[2]
    snapshot = successes[0].request.configuration.model_dump(mode="json")
    snapshot["selections"].pop("dial")
    with pytest.raises(ValidationError):
        commands.RequestSnapshot.model_validate(snapshot)


@pytest.mark.parametrize("revision", [0, True, 2147483648])
def test_command_revisions_are_bounded_strict_integers(case, revision):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        commands.SubmitRequest.model_validate({**case.body.model_dump(), "draft_revision": revision})


@pytest.mark.asyncio
async def test_current_source_validator_reports_missing_dimensions():
    from service_app.configuration import selections
    with pytest.raises(PublicError) as error:
        await selections(None, brand_id=uuid4(), base_model="Sample base", caliber="Sample caliber",
                         chosen={}, mounting={})
    assert error.value.details["fields"] == {
        dimension: "missing" for dimension in ("color", "material", "dial", "sophistication", "movement")
    }


@pytest.mark.asyncio
async def test_current_source_validator_rejects_stale_option_revision():
    from service_app.configuration import selections
    brand = uuid4()

    class Options:
        async def fetchrow(self, sql, *args):
            if "movement_options" in sql:
                return {"id": args[0], "brand_id": brand, "revision": 1, "active": True,
                        "caliber": "Sample caliber", "cases": ["Case"], "dials": ["Dial"], "hands": ["Hands"],
                        "functions": [], "label_en": "Movement", "label_ar": "الحركة",
                        "quote_minor": 100, "currency": "USD"}
            kind = args[1]
            return {"revision": 2 if kind == "color" else 1,
                    "definition": {"available": True, "base_models": ["Sample base"],
                                   "calibers": ["Sample caliber"]}}

    chosen = {dimension: {"option_id": uuid4(), "option_revision": 1}
              for dimension in ("color", "material", "dial", "sophistication", "movement")}
    with pytest.raises(PublicError) as error:
        await selections(Options(), brand_id=brand, base_model="Sample base", caliber="Sample caliber",
                         chosen=chosen, mounting={"case": "Case", "dial": "Dial", "hands": "Hands", "functions": []})
    assert error.value.details["fields"] == {"color": "stale_option"}


def test_response_schema_preserves_private_notes_exactly():
    fixture = json.loads((ROOT / "packages/contracts-catalog/request-drafts/fixtures/request.v2.json").read_text())
    fixture["request"]["notes"] = "  ملاحظة mixed ⌚\n  "
    response = commands.SubmittedRequest.model_validate(fixture["request"])
    assert response.notes == fixture["request"]["notes"]

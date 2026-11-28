import asyncio
import copy
import json
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from conftest import ROOT, load
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import CurrentPrincipal

package = types.ModuleType("service_app")
package.__path__ = [str(ROOT / "services/pricing/runtime/service_app")]
sys.modules["service_app"] = package
routes = load("c09_brand_routes", "services/pricing/modules/brand-quotes/routes.py")
FIXTURE = json.loads(
    (
        ROOT / "packages/contracts-pricing/brand-quotes/fixtures/assessed.v1.json"
    ).read_text()
)
BODY = routes.IssueQuote.model_validate(FIXTURE["issue"])
BUYER = UUID(FIXTURE["expected"]["buyer_id"])
ORG = UUID(FIXTURE["expected"]["organization_id"])
QUOTE = UUID(int=20)
NOW = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)


def principal(buyer=True, org=ORG):
    if buyer:
        return CurrentPrincipal(
            actor={"subject_id": BUYER, "session_id": "synthetic"}, roles=["buyer"]
        )
    return CurrentPrincipal(
        actor={
            "subject_id": UUID(int=99),
            "session_id": "synthetic",
            "organization_id": org,
        },
        organizations=[org],
        roles=["brand"],
        organization_grants=[
            {
                "organization_id": org,
                "permissions": ["business.jobs.write", "business.records.read"],
                "roles": ["brand"],
            }
        ],
    )


def facts():
    fixture = json.loads(
        (
            ROOT / "packages/contracts-pricing/brand-quotes/fixtures/providers.v1.json"
        ).read_text()
    )
    return fixture["providers"]


def install_facts(monkeypatch, data=None):
    data = data or facts()

    async def call(request, name, method, path, **kwargs):
        assert method == "GET"
        if "/access?" in path:
            return copy.deepcopy(data["record_access"])
        return copy.deepcopy(data[name])

    monkeypatch.setattr(routes.peers, "call", call)
    return data


class Store:
    """Deterministic transaction adapter; never substitutes for database proof."""

    def __init__(self):
        self.now = NOW
        self.row = None
        self.decision = None
        self.receipts = {}
        self.events = []
        self.writes = 0

    async def execute(self, sql, *args):
        if "INSERT INTO l14_quote_decisions" in sql:
            self.decision = {
                "actor_id": args[1],
                "decision": args[2],
                "selected_line_ids": json.loads(args[3]),
                "amounts": json.loads(args[4]),
                "terms_digest": args[5],
                "decided_at": args[6],
                "accepted_fee_lines": json.loads(args[7]),
            }
            self.writes += 1
        elif "SET state='superseded'" in sql:
            if self.row:
                self.row["state"] = "superseded"
        else:
            assert "pg_advisory_xact_lock" in sql

    async def fetchval(self, sql, *args):
        if "clock_timestamp" in sql:
            return self.now
        if "count(*)" in sql:
            return 1000
        return self.row["revision"] if self.row else None

    async def fetchrow(self, sql, *args):
        if "INSERT INTO l14_assessed_quotes" in sql:
            self.row = dict(
                zip(
                    (
                        "id",
                        "kind",
                        "source_id",
                        "source_revision",
                        "buyer_id",
                        "organization_id",
                        "author_id",
                        "revision",
                        "snapshot",
                        "expires_at",
                    ),
                    args,
                )
            )
            self.row["snapshot"] = json.loads(self.row["snapshot"])
            self.row["state"] = "issued"
            return self.row
        if "UPDATE l14_assessed_quotes SET state=$2" in sql:
            self.row["state"] = args[1]
            return self.row
        if "l14_quote_decisions" in sql:
            return self.decision
        return self.row

    async def fetch(self, sql, *args):
        if "l14_quote_decisions" in sql:
            return (
                [{**self.decision, "quote_id": self.row["id"]}] if self.decision else []
            )
        assert args[-2:] == (10, 990)
        return [self.row] * 10

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def setup(monkeypatch, store=None):
    store = store or Store()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return store.now

    monkeypatch.setattr(routes, "datetime", Clock)

    @asynccontextmanager
    async def transaction(*args):
        yield store

    async def replay(tx, p, key, fingerprint):
        prior = tx.receipts.get((p.actor.subject_id, key))
        if prior:
            if prior[:2] != (p.actor.organization_id, fingerprint):
                raise PublicError(
                    "idempotency_conflict", "Retry the original operation.", status=409
                )
            return copy.deepcopy(prior[2])

    async def remember(tx, p, key, fingerprint, result):
        tx.receipts[(p.actor.subject_id, key)] = (
            p.actor.organization_id,
            fingerprint,
            copy.deepcopy(result),
        )
        return result

    async def enqueue(tx, envelope, targets):
        tx.events.append(envelope)

    monkeypatch.setattr(routes, "unit_of_work", transaction)
    monkeypatch.setattr(routes, "replay", replay)
    monkeypatch.setattr(routes, "remember", remember)
    monkeypatch.setattr(routes, "enqueue", enqueue)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(pool=SimpleNamespace(acquire=lambda: store))
        ),
        state=SimpleNamespace(request_id="synthetic-request"),
    )
    return store, request


def endpoint(method, suffix=""):
    return next(
        r.endpoint
        for r in routes.router.routes
        if r.path == "/v1/brand-quotes" + suffix and method in r.methods
    )


def issue(request, body=BODY, key="issue-one", p=None):
    return asyncio.run(endpoint("POST")(body, request, p or principal(False), key))


def accept_body(quote):
    return routes.AcceptQuote(
        quote_revision=quote["revision"],
        selected_line_ids=[line["id"] for line in quote["lines"]],
        payable_minor=quote["full_total"]["payable_minor"],
        terms_digest=quote["terms_digest"],
        accept_assessment_fee=True,
    )


def test_fixture_and_business_only_fee(monkeypatch):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    result = issue(request)
    quote = result["quote"]
    assert (
        quote["full_total"]["payable_minor"]
        == FIXTURE["accept"]["payable_minor"]
        == 16000
    )
    assert (
        quote["full_total"]["platform_fee_minor"]
        == quote["full_total"]["seller_commission_minor"]
        == 800
    )
    assert quote["full_total"]["seller_net_minor"] == 15200
    assert quote["expires_at"] == "2026-11-05T10:15:00+00:00"
    for amount, fee in [(500000, 25000), (10, 1), (9, 0)]:
        assert (
            routes.amounts(
                [
                    {
                        "id": "one",
                        "kind": "part",
                        "mandatory": True,
                        "amount_minor": amount,
                    }
                ],
                ["one"],
                0,
            )["platform_fee_minor"]
            == fee
        )
    assert len(store.events) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"currency": "EUR"},
        {
            "lines": [
                {
                    "id": str(UUID(int=1)),
                    "kind": "part",
                    "label": "Part",
                    "mandatory": False,
                    "amount_minor": 1,
                }
            ]
        },
        {"assessment_fee_minor": True},
        {"assessment_fee_minor": 1.5},
        {"assessment_fee_minor": -1},
        {"indicative_min_minor": 30000},
        {"expires_at": "2026-11-05T10:00:00"},
    ],
)
def test_schema_rejects_invalid_money_scope_and_time(patch):
    with pytest.raises(ValueError):
        routes.IssueQuote.model_validate({**FIXTURE["issue"], **patch})


@pytest.mark.parametrize(
    "provider,field,value,code",
    [
        ("catalog", "revision", 5, "source_changed"),
        ("catalog", "buyer_id", str(UUID(int=88)), "source_changed"),
        ("catalog", "brand_id", str(UUID(int=88)), "source_changed"),
        ("service-operations", "revision", 3, "source_changed"),
        ("service-operations", "current", False, "source_changed"),
        ("service-operations", "request_revision", True, "source_changed"),
        ("service-operations", "lines", None, "dependency_unavailable"),
        ("service-operations", "qualified", False, "source_changed"),
        ("service-operations", "assignment_current", False, "source_changed"),
        ("service-operations", "assignment_revision", True, "source_changed"),
        ("service-operations", "watch_id", str(UUID(int=80)), "source_changed"),
        ("identity", "state", "suspended", "authority_revoked"),
        ("catalog", "consent_effective", False, "consent_withdrawn"),
    ],
)
def test_source_denies_without_writes(monkeypatch, provider, field, value, code):
    data = facts()
    data[provider][field] = value
    install_facts(monkeypatch, data)
    store, request = setup(monkeypatch)
    with pytest.raises(PublicError) as error:
        issue(request)
    assert error.value.code == code
    assert not store.events and store.row is None


@pytest.mark.parametrize("offset,allowed", [(-1, True), (0, False), (1, False)])
def test_accept_expiry_boundary(monkeypatch, offset, allowed):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    body = accept_body(quote)
    store.now = NOW + timedelta(minutes=15, seconds=offset)
    if allowed:
        result = asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                body,
                request,
                principal(),
                "accept-one",
                accepting=True,
            )
        )
        assert result["quote"]["state"] == "accepted"
        assert result["quote"]["economics_expires_at"] is None
    else:
        with pytest.raises(PublicError, match="quote_expired"):
            asyncio.run(
                routes.decide(
                    "brand",
                    store.row["id"],
                    body,
                    request,
                    principal(),
                    "accept-one",
                    accepting=True,
                )
            )
        assert store.writes == 0


def test_lost_response_restart_duplicate_and_frozen_reissue(monkeypatch):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    body = accept_body(quote)
    first = asyncio.run(
        routes.decide(
            "brand",
            store.row["id"],
            body,
            request,
            principal(),
            "accept-one",
            accepting=True,
        )
    )
    # A new adapter instance restores only serialized durable records.
    restored = copy.deepcopy(store)
    restored.now = NOW + timedelta(days=40)
    store, request = setup(monkeypatch, restored)
    retry = asyncio.run(
        routes.decide(
            "brand",
            store.row["id"],
            body,
            request,
            principal(),
            "accept-one",
            accepting=True,
        )
    )
    assert retry == first and store.writes == 1 and len(store.events) == 2
    again = issue(request, key="issue-two")
    assert (
        again["quote"]["id"] == quote["id"]
        and again["quote"]["economics_expires_at"] is None
    )
    changed = body.model_copy(update={"payable_minor": 1})
    with pytest.raises(PublicError, match="idempotency_conflict"):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                changed,
                request,
                principal(),
                "accept-one",
                accepting=True,
            )
        )
    data["catalog"]["revision"] += 1
    with pytest.raises(PublicError, match="source_changed"):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                body,
                request,
                principal(),
                "accept-one",
                accepting=True,
            )
        )
    assert store.decision["amounts"] == first["quote"]["decision"]["amounts"]


@pytest.mark.parametrize("actor", ["other_buyer", "brand", "other_business"])
def test_wrong_actor_cannot_accept(monkeypatch, actor):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    p = (
        principal()
        if actor == "other_buyer"
        else principal(False, UUID(int=77) if actor == "other_business" else ORG)
    )
    if actor == "other_buyer":
        p.actor.subject_id = UUID(int=77)
    with pytest.raises(AccessDenied):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                accept_body(quote),
                request,
                p,
                "denied",
                accepting=True,
            )
        )
    assert store.writes == 0


@pytest.mark.parametrize(
    "change", ["total", "digest", "revision", "selection", "assessment_fee"]
)
def test_exact_acceptance_binding(monkeypatch, change):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    body = accept_body(quote)
    patch = {
        "total": {"payable_minor": 1},
        "digest": {"terms_digest": "b" * 64},
        "revision": {"quote_revision": 2},
        "selection": {"selected_line_ids": body.selected_line_ids[:1]},
        "assessment_fee": {"accept_assessment_fee": False},
    }[change]
    body = body.model_copy(update=patch)
    with pytest.raises(PublicError):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                body,
                request,
                principal(),
                "bad",
                accepting=True,
            )
        )
    assert store.writes == 0


def test_timeout_is_unavailable_not_acceptance(monkeypatch):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]

    async def timeout(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(routes.peers, "call", timeout)
    with pytest.raises(PublicError, match="dependency_unavailable"):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                accept_body(quote),
                request,
                principal(),
                "retry-me",
                accepting=True,
            )
        )
    assert store.writes == 0


def test_current_scope_rechecked_under_write_lock(monkeypatch):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    original = store.execute

    async def execute(sql, *args):
        await original(sql, *args)
        if args and str(args[0]).startswith("assessed:"):
            data["service-operations"]["revision"] += 1

    store.execute = execute
    with pytest.raises(PublicError, match="source_changed"):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                accept_body(quote),
                request,
                principal(),
                "retry-me",
                accepting=True,
            )
        )
    assert store.writes == 0


def test_private_read_and_paginated_total(monkeypatch):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    issue(request)
    page = asyncio.run(endpoint("GET")(request, page=100, page_size=10, p=principal()))
    assert page["total"] == 1000 and len(page["items"]) == 10 and page["page"] == 100
    other = principal()
    other.actor.subject_id = UUID(int=77)
    with pytest.raises(AccessDenied):
        asyncio.run(endpoint("GET", "/{quote_id}")(store.row["id"], request, other))


def test_malformed_business_capability_is_unavailable(monkeypatch):
    data = facts()
    data["identity"]["capabilities"] = None
    install_facts(monkeypatch, data)
    store, request = setup(monkeypatch)
    with pytest.raises(PublicError, match="dependency_unavailable"):
        issue(request)
    assert store.row is None


def test_revised_quote_remains_visible_beside_stale_history(monkeypatch):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    old = copy.deepcopy(issue(request)["quote"])
    old_row = copy.deepcopy(store.row)
    data["catalog"]["revision"] += 1
    data["service-operations"]["request_revision"] += 1
    data["record_access"]["request_revision"] += 1
    revised_body = BODY.model_copy(update={"source_revision": BODY.source_revision + 1})
    revised = issue(request, body=revised_body, key="revised")["quote"]
    assert revised["revision"] > old["revision"] and revised["state"] == "issued"
    new_row = copy.deepcopy(store.row)

    async def fetch(sql, *args):
        return [] if "l14_quote_decisions" in sql else [old_row, new_row]

    store.fetch = fetch
    page = asyncio.run(endpoint("GET")(request, page=1, page_size=10, p=principal()))
    assert [quote["id"] for quote in page["items"]] == [revised["id"]]
    assert page["unavailable"] == [{"quote_id": old["id"], "code": "source_changed",
                                    "revision": old["revision"], "terms_digest": old["terms_digest"]}]
    result = asyncio.run(
        routes.decide(
            "brand",
            store.row["id"],
            accept_body(revised),
            request,
            principal(),
            "reaccept",
            accepting=True,
        )
    )
    assert result["quote"]["state"] == "accepted"
    assert old["full_total"] == revised["full_total"]


def test_wrong_business_cannot_issue_or_replay(monkeypatch):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    with pytest.raises(AccessDenied):
        issue(request, p=principal(False, UUID(int=77)))
    issue(request)
    data = facts()
    data["identity"]["state"] = "suspended"
    install_facts(monkeypatch, data)
    with pytest.raises(PublicError, match="authority_revoked"):
        issue(request)
    assert len(store.events) == 1


def test_command_schema_files_match_published_models():
    for name, model in [
        ("issue", routes.IssueQuote),
        ("accept", routes.AcceptQuote),
        ("decline", routes.DeclineQuote),
    ]:
        schema = json.loads(
            (
                ROOT / f"packages/contracts-pricing/brand-quotes/{name}.v1.schema.json"
            ).read_text()
        )
        schema.pop("$schema")
        assert schema == model.model_json_schema()


@pytest.mark.parametrize(
    "field,value",
    [
        ("assessor_id", str(UUID(int=90))),
        ("assignment_revision", 2),
        ("capability_revision", 2),
    ],
)
def test_retained_assessment_bindings_require_new_review(monkeypatch, field, value):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    data["service-operations"][field] = value
    with pytest.raises(PublicError, match="source_changed"):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                accept_body(quote),
                request,
                principal(),
                "accept-one",
                accepting=True,
            )
        )
    with pytest.raises(PublicError, match="source_changed"):
        asyncio.run(
            endpoint("GET", "/{quote_id}")(store.row["id"], request, principal())
        )
    assert store.writes == 0
    renewed = issue(request, key="renewed")["quote"]
    assert renewed["id"] != quote["id"]
    assert renewed["full_total"] == quote["full_total"]


def test_reassignment_blocks_lost_response_disclosure_without_repricing(monkeypatch):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    body = accept_body(quote)
    accepted = asyncio.run(
        routes.decide(
            "brand",
            store.row["id"],
            body,
            request,
            principal(),
            "accepted",
            accepting=True,
        )
    )
    retained = copy.deepcopy(store.decision)
    data["service-operations"]["assignment_revision"] += 1
    with pytest.raises(PublicError, match="source_changed"):
        issue(request)
    with pytest.raises(PublicError, match="source_changed"):
        asyncio.run(
            routes.decide(
                "brand",
                store.row["id"],
                body,
                request,
                principal(),
                "accepted",
                accepting=True,
            )
        )
    assert store.decision == retained
    assert accepted["quote"]["decision"]["amounts"]["payable_minor"] == 16000


def test_price_only_change_cannot_replace_accepted_terms(monkeypatch):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    asyncio.run(routes.decide("brand", store.row["id"], accept_body(quote), request,
                             principal(), "accept-frozen", accepting=True))
    changed = BODY.model_copy(deep=True)
    changed.lines[0].amount_minor += 100
    store.now += timedelta(days=40)
    retained = issue(request, body=changed, key="price-change")["quote"]
    assert retained["id"] == quote["id"]
    assert retained["state"] == "accepted"
    assert retained["full_total"] == quote["full_total"]
    assert len(store.events) == 2


@pytest.mark.parametrize("action", ["issue", "read", "list", "replay"])
@pytest.mark.parametrize("field", ["allowed", "assignment_current"])
def test_current_record_assignment_required(monkeypatch, action, field):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    data["record_access"][field] = False
    with pytest.raises(AccessDenied):
        if action in ("issue", "replay"):
            issue(request, key="issue-one" if action == "replay" else "unassigned")
        elif action == "read":
            asyncio.run(endpoint("GET", "/{quote_id}")(UUID(quote["id"]), request, principal(False)))
        else:
            asyncio.run(endpoint("GET")(request, page=100, page_size=10, p=principal(False)))
    assert len(store.events) == 1


def test_support_recorded_once_without_a_quote_decision(monkeypatch):
    install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    quote = issue(request)["quote"]
    body = routes.DeclineQuote(quote_revision=quote["revision"], terms_digest=quote["terms_digest"])
    action_reference = f"brand-quote-support-{quote['id']}-{quote['revision']}"
    def send(p=None, command=body):
        return asyncio.run(endpoint("POST", "/{quote_id}/support")(
            UUID(quote["id"]), command, request, p or principal(), action_reference))
    from service_app.current import remember as real_remember
    monkeypatch.setattr(routes, "remember", real_remember)
    original_execute = store.execute

    async def execute(sql, *args):
        if "INSERT INTO l14_pricing_operations" in sql:
            receipt_id, actor, organization, key, fingerprint, result = args
            result = json.loads(result)
            assert receipt_id == UUID(result["operation_id"])
            store.receipts[(actor, key)] = (organization, fingerprint, result)
        else:
            await original_execute(sql, *args)

    store.execute = execute
    first = send()
    assert first == send()
    assert UUID(first["operation_id"])
    assert first["action_reference"] == action_reference
    assert first["status"] == "pending" and first["next_actor"] == "support"
    assert store.events[-1].data["operation_id"] == first["operation_id"]
    assert store.decision is None and store.row["state"] == "issued"
    assert len(store.events) == 2
    assert store.events[-1].type == "pricing.brand-quote.support-requested.v1"
    other = principal()
    other.actor.subject_id = UUID(int=77)
    with pytest.raises(AccessDenied):
        send(other)
    with pytest.raises(PublicError, match="idempotency_conflict"):
        send(command=body.model_copy(update={"quote_revision": 2}))
    async def timeout(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(routes.peers, "call", timeout)
    assert send() == first
    assert len(store.events) == 2


@pytest.mark.parametrize("patch", [{"actor_id": str(UUID(int=88))}, {"request_revision": True}, {"allowed": None}])
def test_record_access_malformed_or_denied_fails_closed(monkeypatch, patch):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    data["record_access"].update(patch)
    with pytest.raises((PublicError, AccessDenied)):
        issue(request)
    assert store.row is None


def test_support_reference_passes_http_key_validation():
    key = f"brand-quote-support-{QUOTE}-1"
    assert routes.idempotency(SimpleNamespace(headers={"Idempotency-Key": key})) == key


@pytest.mark.parametrize("provider,field,value", [
    ("catalog", "revision", 5),
    ("catalog", "consent_effective", False),
    ("identity", "state", "suspended"),
    ("service-operations", "revision", 3),
])
def test_stale_quote_keeps_minimal_buyer_support(monkeypatch, provider, field, value):
    data = install_facts(monkeypatch)
    store, request = setup(monkeypatch)
    issue(request)
    data[provider][field] = value
    page = asyncio.run(endpoint("GET")(request, page=100, page_size=10, p=principal()))
    assert not page["items"]
    retained = page["unavailable"][0]
    assert set(retained) == {"quote_id", "code", "revision", "terms_digest"}
    body = routes.DeclineQuote(quote_revision=retained["revision"], terms_digest=retained["terms_digest"])
    result = asyncio.run(endpoint("POST", "/{quote_id}/support")(
        UUID(retained["quote_id"]), body, request, principal(), "support-stale"))
    assert result["status"] == "pending"
    assert store.decision is None and store.row["state"] == "issued"
    assert len(store.events) == 2


@pytest.mark.parametrize("provider,field", [
    ("service-operations", "assessor_id"),
    ("service-operations", "buyer_id"),
    ("catalog", "watch_id"),
    ("catalog", "buyer_id"),
])
@pytest.mark.parametrize("value", [42, True, None, [], {}])
def test_malformed_identifier_is_unavailable(monkeypatch, provider, field, value):
    data = install_facts(monkeypatch)
    data[provider][field] = value
    store, request = setup(monkeypatch)
    with pytest.raises(PublicError, match="dependency_unavailable") as error:
        issue(request)
    assert error.value.status == 503
    assert store.row is None and not store.events

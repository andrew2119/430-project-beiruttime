from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from bt_contracts_core.errors import PublicError


def identifier(number):
    return UUID(int=number)


def financial(contract, **changes):
    data = dict(operation_key="refund:one", actor_id=identifier(1), organization_id=identifier(2),
                order_id=identifier(3), watch_id=identifier(4), expected_revision=1,
                source_id=identifier(5), source_revision=1, quote_id=identifier(6), quote_revision=1,
                policy_revision=1, kind="refund", recipient_id=identifier(7), amount_minor=500000,
                receipt_id=identifier(8), receipt_revision=1, dispute_revision=1, incident_revision=1)
    return contract.FinancialCommand(**(data | changes))


@pytest.fixture
def modules(lane_modules):
    contract = lane_modules("bt_contracts.orders.allocation.guarded_v3", "packages/contracts-orders/allocation/guarded_v3.py")
    module = lane_modules("guarded_money", "services/orders/modules/allocation/commitment/guarded.py")
    return contract, module


@pytest.mark.parametrize("change", [{"amount_minor": True}, {"amount_minor": 0}, {"currency": "LBP"},
    {"source_revision": 0}, {"expected_revision": True}, {"policy_revision": 0}])
def test_strict_binding(modules, change):
    with pytest.raises(ValidationError):
        financial(modules[0], **change)


@pytest.fixture
def execution(modules, monkeypatch):
    contract, module = modules
    binding = financial(contract)
    order = dict(id=binding.order_id, watch_id=binding.watch_id, quote_id=binding.quote_id,
                 organization_id=binding.organization_id, currency="USD", revision=1,
                 buyer_id=binding.recipient_id, seller_id=identifier(9))
    decision = contract.CurrentDecision(binding=binding, state="authorized", revision=1,
        next_actor=identifier(10), next_review_at=datetime(2026, 11, 18, tzinfo=timezone.utc), reason="Current decision")
    authority = SimpleNamespace(decision=AsyncMock(return_value=decision))
    outcome = contract.GuardedResult(operation_key=binding.operation_key, status="succeeded", revision=2,
        code="reserved", message_en="Refund amount reserved.", message_ar="تم حجز مبلغ الاسترداد.",
        next_actor=decision.next_actor, next_review_at=decision.next_review_at)
    boundary = SimpleNamespace(apply=AsyncMock(return_value=outcome))
    tx = SimpleNamespace(fetchval=AsyncMock())
    monkeypatch.setattr(module, "lock_order", AsyncMock(return_value=order))
    monkeypatch.setattr(module, "paid_fact", AsyncMock(return_value=dict(paid=True, quote_revision=1,
        retained_economics=dict(refundable_max_minor=500000, seller_net_minor=475000))))

    async def command(pool, actor, key, action, payload, handler, **kwargs):
        response = await handler(tx)
        await kwargs["retain_result"](tx, response)
        return response

    monkeypatch.setattr(module, "command", command)
    kwargs = dict(request_id="synthetic", authority=authority, boundary=boundary, responsible_actor=identifier(10))
    return contract, module, binding, order, authority, boundary, kwargs, tx


@pytest.mark.asyncio
async def test_exact_full_principal_reserved_through_one_boundary(execution):
    _, module, binding, _, authority, boundary, kwargs, tx = execution
    response = await module.refund(None, binding, **kwargs)
    assert response["status"] == "succeeded"
    boundary.apply.assert_awaited_once_with(tx, binding, authority.decision.return_value)
    assert authority.decision.await_count == 2
    assert response["payment_authority"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["authority", "boundary"])
async def test_absent_producer_is_pending(execution, missing):
    _, module, binding, _, _, boundary, kwargs, _ = execution
    kwargs[missing] = None
    response = await module.refund(None, binding, **kwargs)
    assert response["status"] == "pending" and response["message_ar"]
    assert response["next_actor"] == str(identifier(10))
    boundary.apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_does_not_reserve(execution):
    _, module, binding, order, _, boundary, kwargs, _ = execution
    order["revision"] = 2
    response = await module.refund(None, binding, **kwargs)
    assert response["code"] == "stale_revision"
    boundary.apply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"amount_minor": 515000}, {"recipient_id": identifier(99)}])
async def test_fees_and_redirect_cannot_enter_refund(execution, change):
    contract, module, _, _, _, boundary, kwargs, _ = execution
    binding = financial(contract, **change)
    kwargs["authority"].decision.return_value = kwargs["authority"].decision.return_value.model_copy(update={"binding": binding})
    with pytest.raises(PublicError, match="financial_binding_mismatch"):
        await module.refund(None, binding, **kwargs)
    boundary.apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_preserves_original_reference_for_retry(execution):
    _, module, binding, _, _, boundary, kwargs, _ = execution
    boundary.apply.side_effect = TimeoutError()
    pending = await module.refund(None, binding, **kwargs)
    assert pending["status"] == "pending" and pending["operation_key"] == binding.operation_key
    boundary.apply.side_effect = None
    assert (await module.refund(None, binding, **kwargs))["status"] == "succeeded"
    assert boundary.apply.await_args_list[0] == boundary.apply.await_args_list[1]


@pytest.mark.asyncio
async def test_replay_hook_rechecks_revocation(execution, monkeypatch):
    _, module, binding, _, authority, boundary, kwargs, tx = execution
    authority.decision.return_value = authority.decision.return_value.model_copy(update={"state": "denied"})

    async def replay(*args, **options):
        await options["retain_result"](tx, {"status": "succeeded"})

    monkeypatch.setattr(module, "command", replay)
    with pytest.raises(PublicError, match="current_authority_denied"):
        await module.refund(None, binding, **kwargs)
    boundary.apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_takes_order_before_existing_processor(lane_modules, monkeypatch):
    module = lane_modules("callback_entry", "services/orders/modules/allocation/commitment/callbacks.py")
    calls = []
    async def lock(tx, order):
        calls.append(("order", order))
    async def process(tx, body, request_id):
        calls.append(("processor", request_id))
        return {"status": "succeeded"}
    monkeypatch.setattr(module, "lock_order", lock)
    tx = SimpleNamespace(fetchval=AsyncMock(return_value=identifier(3)))
    await module.apply_callback(tx, SimpleNamespace(attempt_id=identifier(11)), "synthetic", process)
    assert calls == [("order", identifier(3)), ("processor", "synthetic")]


@pytest.mark.asyncio
async def test_historical_receipt_uses_original_audit_without_stock_mutation(lane_modules):
    module = lane_modules("release_recovery", "services/orders/modules/allocation/commitment/recovery.py")
    original = datetime(2026, 11, 10, tzinfo=timezone.utc)
    tx = SimpleNamespace(fetch=AsyncMock(return_value=[dict(id=identifier(3), watch_id=identifier(4),
        revision=2, occurred_at=original)]), execute=AsyncMock())
    assert await module.recover_releases(tx) == 1
    query = tx.fetch.await_args.args[0]
    assert "NOT EXISTS (SELECT 1 FROM l13_payment_attempts" in query
    assert "FOR UPDATE OF o SKIP LOCKED" in query
    statement, *values = tx.execute.await_args.args
    assert statement.lstrip().startswith("INSERT INTO l13_unpaid_release_receipts")
    assert values == [identifier(3), identifier(4), 2, original]


def test_protocol_fixtures_validate_as_exact_contracts(modules):
    import json
    from pathlib import Path

    contract, _ = modules
    path = Path(__file__).resolve().parents[4] / "packages/contracts-orders/allocation/fixtures/guarded.v3.json"
    cases = json.loads(path.read_text())["cases"]
    assert {case["name"] for case in cases} == {"success", "denied", "stale", "lost_response"}
    for case in cases:
        request = contract.FinancialCommand.model_validate(case["request"])
        outcome = contract.GuardedResult.model_validate(case["result"])
        assert request.operation_key == outcome.operation_key
        assert outcome.message_en and outcome.message_ar


@pytest.mark.asyncio
async def test_hanging_producer_is_bounded_and_pending(execution, monkeypatch):
    import asyncio

    _, module, binding, _, authority, boundary, kwargs, _ = execution
    cancelled = []

    async def hang(*args, **options):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(module, "PROVIDER_TIMEOUT_SECONDS", 0.01)
    authority.decision.side_effect = hang
    outcome = await module.refund(None, binding, **kwargs)
    assert cancelled and outcome["status"] == "pending"
    boundary.apply.assert_not_awaited()


def job_binding(contract, **changes):
    common = financial(contract).model_dump()
    for name in ("kind", "recipient_id", "amount_minor", "receipt_id", "receipt_revision", "dispute_revision", "incident_revision", "currency", "refund_basis"):
        common.pop(name)
    return contract.JobBinding(**(common | dict(order_kind="customization_job", buyer_id=identifier(7),
        request_id=identifier(20), request_revision=2, assessment_id=identifier(21), assessment_revision=3,
        consent_revision=4, grant_id=identifier(22), grant_revision=5, accepted_terms_revision=6,
        accepted_line_ids=[identifier(23)], total_minor=500000) | changes))


@pytest.mark.parametrize("change", [{"organization_id": None}, {"grant_revision": 0},
    {"accepted_line_ids": []}, {"accepted_line_ids": [identifier(23), identifier(23)]},
    {"total_minor": True}, {"request_revision": 0}])
def test_job_requires_current_typed_scope(modules, change):
    with pytest.raises(ValidationError):
        job_binding(modules[0], **change)


@pytest.mark.asyncio
@pytest.mark.parametrize("watch_change,denial", [({}, None), ({"revision": 2}, "stale_revision"),
    ({"status": "reserved"}, "watch_committed")])
async def test_typed_job_allocates_once_with_original_bindings_and_no_clock(modules, lane_modules, monkeypatch, watch_change, denial):
    contract, _ = modules
    module = lane_modules("typed_jobs", "services/orders/modules/allocation/commitment/jobs.py")
    binding = job_binding(contract)
    watch = dict(id=binding.watch_id, listing_id=identifier(30), revision=1,
                 listing_revision=2, status="available", is_demo=True)
    order = dict(id=binding.order_id, watch_id=binding.watch_id, listing_id=watch["listing_id"],
        buyer_id=binding.buyer_id, seller_id=identifier(9), organization_id=binding.organization_id,
        quote_id=binding.quote_id, state="awaiting_notification", currency="USD", total_minor=500000,
        deadline=None, notified_at=None, revision=1, is_demo=True, order_kind=binding.order_kind)
    proof = contract.CurrentJobDecision(binding=binding, state="authorized", seller_id=identifier(9),
        seller_type="brand", next_actor=identifier(10), next_review_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
        money=dict(order_kind=binding.order_kind,currency="USD",price_minor=500000,buyer_fee_minor=0,
            seller_commission_minor=25000,seller_net_minor=475000,shipping_minor=0,tax_minor=0,
            payable_minor=500000,refundable_max_minor=500000))
    authority = SimpleNamespace(decision=AsyncMock(return_value=proof))
    tx = SimpleNamespace(fetchrow=AsyncMock(return_value=order), execute=AsyncMock())
    monkeypatch.setattr(module, "lock_watch", AsyncMock(return_value=watch))
    monkeypatch.setattr(module, "retain", AsyncMock())
    monkeypatch.setattr(module, "ensure_payment_notice", AsyncMock())
    monkeypatch.setattr(module, "audit", AsyncMock())
    watch.update(watch_change)
    grant = {"usable": True}
    async def decision(tx, supplied, *, recovery):
        assert supplied == binding
        if not recovery:
            assert grant["usable"]
            grant["usable"] = False
        return proof
    authority.decision.side_effect = decision
    receipts = {}
    async def command(pool, actor, key, action, payload, apply, **options):
        if key not in receipts:
            receipts[key] = await apply(tx)
        await options["retain_result"](tx, receipts[key])
        return receipts[key]
    monkeypatch.setattr(module, "command", command)
    for _ in range(2):
        outcome = await module.allocate_job(None, binding, request_id="synthetic", authority=authority)
        if denial:
            assert outcome["status"] == "denied" and outcome["code"] == denial
            assert grant["usable"] is True
            assert all(call.kwargs["recovery"] for call in authority.decision.await_args_list)
            tx.fetchrow.assert_not_awaited()
            tx.execute.assert_not_awaited()
            module.retain.assert_not_awaited()
            module.ensure_payment_notice.assert_not_awaited()
            module.audit.assert_not_awaited()
            continue
        assert grant["usable"] is False
        assert outcome["order"]["state"] == "awaiting_notification"
        assert outcome["order"]["deadline"] is None
    if denial:
        return
    tx.fetchrow.assert_awaited_once()
    module.retain.assert_awaited_once()
    assert module.retain.await_args.args[2]["accepted_line_ids"] == [str(identifier(23))]
    stored = [call.args for call in tx.execute.await_args_list if "l13_job_bindings" in call.args[0]]
    import json
    assert json.loads(stored[0][2]) == binding.model_dump(mode="json")
    module.ensure_payment_notice.assert_awaited_once_with(tx, order, "synthetic")


@pytest.mark.asyncio
async def test_lookup_timeout_is_bilingual_unavailable(execution, monkeypatch):
    import asyncio
    import bt_runtime.app.db as database

    _, module, binding, _, authority, _, _, tx = execution
    @asynccontextmanager
    async def transaction(pool):
        yield tx
    async def hang(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(database, "unit_of_work", transaction)
    monkeypatch.setattr(module, "PROVIDER_TIMEOUT_SECONDS", 0.01)
    authority.decision.side_effect = hang
    with pytest.raises(PublicError, match="authority_unavailable"):
        await module.lookup(None, binding, authority=authority)


@pytest.mark.asyncio
async def test_lookup_different_binding_cannot_recover_another_receipt(execution, monkeypatch):
    import bt_runtime.app.db as database

    _, module, binding, _, authority, _, _, tx = execution
    @asynccontextmanager
    async def transaction(pool):
        yield tx
    tx.fetchrow = AsyncMock(return_value={"digest": "different"})
    monkeypatch.setattr(database, "unit_of_work", transaction)
    reader = AsyncMock()
    monkeypatch.setattr(module, "operation", reader)
    with pytest.raises(PublicError, match="idempotency_conflict"):
        await module.lookup(None, binding, authority=authority)
    reader.assert_not_awaited()


@pytest.mark.parametrize("basis", ["pre_dispatch", "failure_exception"])
def test_refund_can_bind_recorded_exception_without_invented_receipt(modules, basis):
    binding = financial(modules[0], refund_basis=basis, receipt_id=None, receipt_revision=None)
    assert binding.receipt_id is None and binding.refund_basis == basis


@pytest.mark.parametrize("change", [dict(kind="release"), dict(refund_basis="controlled_return"),
    dict(kind="release", refund_basis="pre_dispatch")])
def test_release_and_controlled_return_require_actual_receipt(modules, change):
    with pytest.raises(ValidationError):
        financial(modules[0], receipt_id=None, receipt_revision=None, **change)

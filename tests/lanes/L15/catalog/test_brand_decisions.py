from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from .conftest import sources, headers
from .test_configuration_submission import validate, validation_body

pytestmark = pytest.mark.asyncio


async def request_scope(api):
    source = await sources(api)
    value = (await validate(api, source)).json()
    body = {
        **validation_body(source),
        "configuration_id": str(source.configuration_id),
        "draft_revision": 1,
        "expected_digest": value["digest"],
    }
    result = await api.client.post(
        f"/v2/request-drafts/{source.draft_id}/submit", headers=headers(), json=body
    )
    assert result.status_code == 200, result.text
    request = result.json()["request"]
    base = {
        "request_id": request["id"],
        "request_revision": 1,
        "brand_id": str(api.brand),
        "revision": 1,
    }
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    assessment = {**base, "id": str(uuid4()), "status": "feasible", "qualified": True}
    quote = {
        **base,
        "id": str(uuid4()),
        "assessment_id": assessment["id"],
        "assessment_revision": 1,
        "status": "accepted",
        "buyer_id": str(api.owner),
        "total_minor": 500000,
        "currency": "USD",
        "expires_at": None,
    }
    grant = {
        **base,
        "id": str(uuid4()),
        "quote_id": quote["id"],
        "quote_revision": 1,
        "status": "valid",
        "current": True,
        "subject_id": str(api.owner),
        "purpose": "brand_approval",
        "reviewer_id": str(uuid4()),
        "amount_minor": 500000,
        "currency": "USD",
        "expires_at": expiry,
    }
    api.authority.update(assessment=assessment, quote=quote, grant=grant)
    decision = {
        "expected_revision": 1,
        "decision": "approve",
        "reason": "Approve the exact current feasible scope",
        **{
            kind + suffix: value["id" if suffix == "_id" else "revision"]
            for kind, value in api.authority.items()
            for suffix in ("_id", "_revision")
        },
    }
    return request, decision


async def test_pending_before_http_lost_consume_reply_and_reconciliation(api):
    request, body = await request_scope(api)
    api.fail["consume_reply"] = True
    response = await api.client.post(
        f"/v2/customization-requests/{request['id']}/decisions",
        headers=headers("brand"),
        json=body,
    )
    assert response.status_code == 503, response.text
    current = (
        await api.client.get(
            f"/v2/customization-requests/{request['id']}/decision", headers=headers()
        )
    ).json()
    assert current["status"] == "pending" and current["execution_authority"] is False
    assert api.authority.get("consumed")
    api.fail["consume_reply"] = False
    # The grant disappears from the current list after consuming. Same-operation
    # reconciliation must not interpret absence as permission or a new grant.
    api.authority["grant"] = {}
    replay = await api.client.post(
        f"/v2/brand-decision-operations/{current['id']}/resume",
        headers=headers("brand"),
    )
    assert replay.status_code == 200 and replay.json()["status"] == "approved", (
        replay.text
    )
    again = await api.client.post(
        f"/v2/brand-decision-operations/{current['id']}/resume",
        headers=headers("brand"),
    )
    assert again.json() == replay.json()
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.brand-decision.confirmed.v1'"
        )
        == 1
    )


@pytest.mark.parametrize(
    "condition",
    [
        "reviewer_is_approver",
        "quote_changed",
        "revoked",
        "expired",
        "wrong_amount",
        "wrong_currency",
        "wrong_subject",
        "wrong_purpose",
        "reviewer_is_buyer",
        "assessment_not_feasible",
        "assessment_unqualified",
        "assessment_qualification_absent",
        "assessment_revision_changed",
        "grant_not_current",
        "quote_has_preview_expiry",
        "quote_unaccepted",
        "amount_boolean",
        "unsupported_currency",
    ],
)
async def test_stale_or_self_review_never_approves(api, condition):
    request, body = await request_scope(api)
    if condition == "reviewer_is_approver":
        api.authority["grant"]["reviewer_id"] = str(api.approver)
    elif condition == "quote_changed":
        api.authority["quote"]["revision"] = 2
    elif condition == "revoked":
        api.authority["revoked"] = True
    elif condition == "wrong_amount":
        api.authority["grant"]["amount_minor"] += 1
    elif condition == "wrong_currency":
        api.authority["grant"]["currency"] = "LBP"
    elif condition == "wrong_subject":
        api.authority["grant"]["subject_id"] = str(api.other)
    elif condition == "wrong_purpose":
        api.authority["grant"]["purpose"] = "execution"
    elif condition == "reviewer_is_buyer":
        api.authority["grant"]["reviewer_id"] = str(api.owner)
    elif condition == "assessment_not_feasible":
        api.authority["assessment"]["status"] = "infeasible"
    elif condition == "assessment_unqualified":
        api.authority["assessment"]["qualified"] = False
    elif condition == "assessment_qualification_absent":
        api.authority["assessment"].pop("qualified")
    elif condition == "assessment_revision_changed":
        api.authority["assessment"]["revision"] = 2
    elif condition == "grant_not_current":
        api.authority["grant"]["current"] = False
    elif condition == "quote_has_preview_expiry":
        api.authority["quote"]["expires_at"] = datetime.now(timezone.utc).isoformat()
    elif condition == "quote_unaccepted":
        api.authority["quote_projection"] = {"accepted_at": None}
    elif condition == "amount_boolean":
        api.authority["quote"]["total_minor"] = True
        api.authority["grant"]["amount_minor"] = True
    elif condition == "unsupported_currency":
        api.authority["quote"]["currency"] = "EUR"
        api.authority["grant"]["currency"] = "EUR"
    else:
        api.authority["grant"]["expires_at"] = datetime.now(timezone.utc).isoformat()
    result = await api.client.post(
        f"/v2/customization-requests/{request['id']}/decisions",
        headers=headers("brand"),
        json=body,
    )
    assert result.status_code == 200 and result.json()["status"] == "denied", (
        result.text
    )
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.brand-decision.confirmed.v1'"
        )
        == 0
    )


@pytest.mark.parametrize("token", ["buyer", "other_brand", "self_brand"])
async def test_buyer_and_wrong_org_cannot_decide(api, token):
    request, body = await request_scope(api)
    result = await api.client.post(
        f"/v2/customization-requests/{request['id']}/decisions",
        headers=headers(token),
        json=body,
    )
    assert result.status_code == 403
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM catalog_brand_decisions"
        )
        == 0
    )


async def test_forged_eligible_flag_is_not_an_authority_input(api):
    request, body = await request_scope(api)
    result = await api.client.post(
        f"/v2/customization-requests/{request['id']}/decisions",
        headers=headers("brand"),
        json={**body, "eligible": True},
    )
    assert result.status_code == 422
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM catalog_brand_decisions"
        )
        == 0
    )


async def test_optional_readiness_outage_is_not_an_approval_or_catalog_failure(api):
    request, body = await request_scope(api)
    url = f'/v2/customization-requests/{request["id"]}'
    available = await api.client.get(url+'/decision-readiness',headers=headers('brand'))
    assert available.status_code == 200 and available.json()['status'] == 'available', available.text
    assert available.json()['execution_authority'] is False
    assert available.json()['bindings']['amount_minor'] == 500000
    api.fail['eligibility'] = True
    unavailable = await api.client.get(url+'/decision-readiness',headers=headers('brand'))
    assert unavailable.status_code == 200 and unavailable.json() == {
        'status':'unavailable','code':'approval_unavailable','execution_authority':False}, unavailable.text
    assert (await api.client.get(url,headers=headers())).status_code == 200
    assert await api.app.state.pool.fetchval('SELECT count(*) FROM catalog_brand_decisions') == 0
    command = await api.client.post(url+'/decisions',headers=headers('brand'),json=body)
    assert command.status_code == 503, command.text
    current = (await api.client.get(url+'/decision',headers=headers())).json()
    assert current['status'] == 'pending' and current['execution_authority'] is False
    api.fail['eligibility'] = False
    resumed = await api.client.post(f'/v2/brand-decision-operations/{current["id"]}/resume',headers=headers('brand'))
    assert resumed.status_code == 200 and resumed.json()['status'] == 'approved', resumed.text
    assert resumed.json()['execution_authority'] is False

import asyncio
from uuid import UUID, uuid4
import asyncpg
import pytest
from .conftest import sources, headers

pytestmark = pytest.mark.asyncio


def validation_body(source):
    return {
        "configuration_revision": 4,
        "movement_selection_id": str(source.selection_id),
        "movement_revision": 1,
    }


async def validate(api, source):
    return await api.client.post(
        f"/v2/configurations/{source.configuration_id}/validate",
        json=validation_body(source),
        headers=headers(),
    )


async def test_five_dimension_digest_and_distinct_states(api):
    source = await sources(api)
    result = await validate(api, source)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["status"] == "manual_assessment"
    assert len(value["snapshot"]["selections"]) == 5
    assert (
        value["physical_feasibility_pass"] is False
        and value["price_acceptance"] is False
    )
    assert (await validate(api, source)).json()["digest"] == value["digest"]
    rule = await api.client.put(
        f"/v2/brands/{api.brand}/compatibility/{uuid4()}",
        headers=headers("brand"),
        json={
            "expected_revision": 0,
            "base_model": "Base",
            "caliber": "Caliber",
            "option_ids": [str(v) for v in source.chosen.values()],
            "option_revisions": {str(v): 1 for v in source.chosen.values()},
            "mounting": {
                "case": "Base",
                "dial": "Dial",
                "hands": "Hands",
                "functions": [],
            },
            "status": "valid",
            "reason": "Supported combination for review",
        },
    )
    assert rule.status_code == 200, rule.text
    assert (await validate(api, source)).json()["status"] == "valid"
    await api.app.state.pool.execute(
        "UPDATE movement_options SET active=false WHERE id=$1", source.movement_id
    )
    assert (await validate(api, source)).json()["status"] == "parts_unavailable"


async def test_stale_missing_cross_owner_and_brand_are_not_valid(api):
    source = await sources(api)
    denied = await api.client.post(
        f"/v2/configurations/{source.configuration_id}/validate",
        headers=headers("other"),
        json=validation_body(source),
    )
    assert denied.status_code == 404
    await api.app.state.pool.execute(
        "DELETE FROM l10_selections WHERE configuration_id=$1 AND kind='dial'",
        source.configuration_id,
    )
    missing = await validate(api, source)
    assert (
        missing.status_code == 422
        and missing.json()["error"]["details"]["fields"]["dial"] == "missing"
    )
    source = await sources(api)
    definition = await api.app.state.pool.fetchval(
        "SELECT definition FROM l10_options WHERE option_id=$1", source.chosen["color"]
    )
    await api.app.state.pool.execute(
        "INSERT INTO l10_options(brand_id,kind,option_id,revision,definition,created_by) VALUES($1,'color',$2,2,$3::jsonb,$4)",
        api.brand,
        source.chosen["color"],
        definition,
        api.approver,
    )
    stale = await validate(api, source)
    assert (
        stale.status_code == 422
        and stale.json()["error"]["details"]["fields"]["color"] == "stale_option"
    )


async def test_immutable_submit_replay_and_competing_requests(api):
    source = await sources(api)
    validated = (await validate(api, source)).json()
    body = {
        **validation_body(source),
        "configuration_id": str(source.configuration_id),
        "draft_revision": 1,
        "expected_digest": validated["digest"],
    }
    operation_key = uuid4().hex
    url = f"/v2/request-drafts/{source.draft_id}/submit"
    first, replay = await asyncio.gather(
        *(
            api.client.post(url, json=body, headers=headers(key=operation_key))
            for _ in range(2)
        )
    )
    assert first.status_code == replay.status_code == 200, first.text
    assert first.json() == replay.json()
    request_id = first.json()["resource_id"]
    assert first.json()["request"]["notes"] == "Private neutral note"
    duplicate = await api.client.post(url, json=body, headers=headers())
    assert duplicate.status_code == 409
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM catalog_customization_requests WHERE draft_id=$1",
            source.draft_id,
        )
        == 1
    )
    assert (
        await api.client.get(
            f"/v2/customization-requests/{request_id}", headers=headers("other")
        )
    ).status_code == 403
    assert (
        await api.client.get(
            f"/v2/customization-requests/{request_id}", headers=headers("brand")
        )
    ).status_code == 200
    operation = await api.client.get(
        f"/v2/customization-operations/{first.json()['id']}", headers=headers()
    )
    assert operation.json() == first.json()
    with pytest.raises(asyncpg.RaiseError):
        await api.app.state.pool.execute(
            "UPDATE catalog_customization_revisions SET reason='overwrite'"
        )
    outbox = await api.app.state.pool.fetchval(
        "SELECT envelope::text FROM outbox WHERE envelope->>'type'='catalog.customization.submitted.v2'"
    )
    assert outbox is not None and "Private neutral note" not in outbox


async def test_stale_digest_does_not_submit_or_freeze_draft(api):
    source = await sources(api)
    body = {
        **validation_body(source),
        "configuration_id": str(source.configuration_id),
        "draft_revision": 1,
        "expected_digest": "a" * 64,
    }
    response = await api.client.post(
        f"/v2/request-drafts/{source.draft_id}/submit", headers=headers(), json=body
    )
    assert response.status_code == 409, response.text
    assert (
        await api.app.state.pool.fetchval(
            "SELECT submitted_request_id FROM l08_request_drafts WHERE id=$1",
            source.draft_id,
        )
        is None
    )


async def test_unattached_reference_inventory_never_enters_submission_snapshot(api):
    source = await sources(api)
    reference_id = uuid4()
    await api.app.state.pool.execute(
        "INSERT INTO l10_references(id,configuration_id,owner_id,content,sha256) VALUES($1,$2,$3,$4,$5)",
        reference_id,
        source.configuration_id,
        api.owner,
        b"private image fixture",
        "a" * 64,
    )
    before = await validate(api, source)
    assert before.json()["snapshot"]["reference_ids"] == []
    await api.app.state.pool.execute(
        "UPDATE l10_selections SET reference_ids=$2::uuid[] WHERE configuration_id=$1 AND kind='dial'",
        source.configuration_id,
        [reference_id],
    )
    attached = await validate(api, source)
    assert attached.json()["snapshot"]["reference_ids"] == [str(reference_id)]
    assert attached.json()["digest"] != before.json()["digest"]


async def test_another_brand_movement_is_incompatible_not_feasible(api):
    source = await sources(api)
    await api.app.state.pool.execute(
        "UPDATE movement_options SET brand_id=$2 WHERE id=$1",
        source.movement_id,
        uuid4(),
    )
    result = await validate(api, source)
    assert result.status_code == 200
    assert result.json()["status"] == "incompatible"
    assert result.json()["fields"]["movement"] == "other_brand"
    assert result.json()["physical_feasibility_pass"] is False


async def test_current_correction_retains_prior_immutable_revision(api):
    source = await sources(api)
    validated = (await validate(api, source)).json()
    body = {
        **validation_body(source),
        "configuration_id": str(source.configuration_id),
        "draft_revision": 1,
        "expected_digest": validated["digest"],
    }
    submitted = await api.client.post(
        f"/v2/request-drafts/{source.draft_id}/submit", headers=headers(), json=body
    )
    assert submitted.status_code == 200, submitted.text
    request_id = submitted.json()["resource_id"]
    correction = {
        "expected_revision": 1,
        "reason": "Current technical scope correction",
        "selections": {
            kind: {"option_id": str(option), "option_revision": 1}
            for kind, option in source.chosen.items()
        },
    }
    direct = await api.client.post(
        f"/v2/customization-requests/{request_id}/corrections",
        headers=headers("brand"),
        json=correction,
    )
    assert direct.status_code == 401
    corrected = await api.client.post(
        f"/v2/customization-requests/{request_id}/corrections",
        headers=headers("brand", service_token=api.service_token),
        json=correction,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["request"]["revision"] == 2
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM catalog_customization_revisions WHERE request_id=$1",
            UUID(request_id),
        )
        == 2
    )
    stale = await api.client.post(
        f"/v2/customization-requests/{request_id}/corrections",
        headers=headers("brand", service_token=api.service_token),
        json=correction,
    )
    assert stale.status_code == 409


async def test_rule_cannot_survive_a_changed_option_revision(api):
    source = await sources(api)
    rule_id = uuid4()
    rule = {
        "expected_revision": 0,
        "base_model": "Base",
        "caliber": "Caliber",
        "option_ids": [str(v) for v in source.chosen.values()],
        "option_revisions": {str(v): 1 for v in source.chosen.values()},
        "mounting": {"case": "Base", "dial": "Dial", "hands": "Hands", "functions": []},
        "status": "valid",
        "reason": "Current all-five combination",
    }
    published = await api.client.put(
        f"/v2/brands/{api.brand}/compatibility/{rule_id}",
        headers=headers("brand"),
        json=rule,
    )
    assert published.status_code == 200, published.text
    assert (await validate(api, source)).json()["status"] == "valid"
    definition = await api.app.state.pool.fetchval(
        "SELECT definition FROM l10_options WHERE option_id=$1", source.chosen["color"]
    )
    await api.app.state.pool.execute(
        "INSERT INTO l10_options(brand_id,kind,option_id,revision,definition,created_by) VALUES($1,'color',$2,2,$3::jsonb,$4)",
        api.brand,
        source.chosen["color"],
        definition,
        api.approver,
    )
    await api.app.state.pool.execute(
        "UPDATE l10_selections SET option_revision=2 WHERE configuration_id=$1 AND kind='color'",
        source.configuration_id,
    )
    result = await validate(api, source)
    assert (
        result.status_code == 200 and result.json()["status"] == "manual_assessment"
    ), result.text
    stale = await api.client.put(
        f"/v2/brands/{api.brand}/compatibility/{rule_id}",
        headers=headers("brand"),
        json={**rule, "expected_revision": 1},
    )
    assert stale.status_code == 409


async def test_request_pages_and_cursor_are_current_party_scoped(api):
    ids = []
    for _ in range(2):
        source = await sources(api)
        validation = (await validate(api, source)).json()
        body = {
            **validation_body(source),
            "configuration_id": str(source.configuration_id),
            "draft_revision": 1,
            "expected_digest": validation["digest"],
        }
        response = await api.client.post(
            f"/v2/request-drafts/{source.draft_id}/submit", headers=headers(), json=body
        )
        assert response.status_code == 200, response.text
        ids.append(response.json()["resource_id"])
    first = await api.client.get(
        "/v2/customization-requests?limit=1", headers=headers()
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor and len(first.json()["items"]) == 1
    second = await api.client.get(
        "/v2/customization-requests?limit=1&before=" + cursor, headers=headers()
    )
    assert second.status_code == 200 and second.json()["next_cursor"] is None
    assert {first.json()["items"][0]["id"], second.json()["items"][0]["id"]} == set(ids)
    foreign = await api.client.get(
        "/v2/customization-requests?before=" + cursor, headers=headers("other")
    )
    assert foreign.status_code == 422


async def test_rule_put_replays_exact_ack_without_duplicate_version_or_event(api):
    source = await sources(api)
    url = f'/v2/brands/{api.brand}/compatibility/{uuid4()}'
    body = {'expected_revision':0,'base_model':'Base','caliber':'Caliber',
        'option_ids':[str(value) for value in source.chosen.values()],
        'option_revisions':{str(value):1 for value in source.chosen.values()},
        'mounting':{'case':'Base','dial':'Dial','hands':'Hands','functions':[]},
        'status':'valid','reason':'Exact current compatibility basis'}
    first = await api.client.put(url,headers=headers('brand'),json=body)
    assert first.status_code == 200, first.text
    replay = await api.client.put(url,headers=headers('brand'),json=body)
    assert replay.json() == first.json()
    changed = await api.client.put(url,headers=headers('brand'),json={**body,'reason':'Different command'})
    assert changed.status_code == 409
    other_actor = await api.client.put(url,headers=headers('self_brand'),json=body)
    assert other_actor.status_code == 409
    other_brand = await api.client.put(url,headers=headers('other_brand'),json=body)
    assert other_brand.status_code == 403
    next_version = await api.client.put(url,headers=headers('brand'),json={**body,
        'expected_revision':1,'status':'manual_assessment','reason':'New current technical review'})
    assert next_version.status_code == 200 and next_version.json()['revision'] == 2, next_version.text
    # Recover an old lost acknowledgement without reactivating its old verdict.
    old_replay = await api.client.put(url,headers=headers('brand'),json=body)
    assert old_replay.json() == first.json()
    assert (await validate(api,source)).json()['status'] == 'manual_assessment'
    assert await api.app.state.pool.fetchval('SELECT count(*) FROM catalog_compatibility_rules') == 2
    assert await api.app.state.pool.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.compatibility.published.v1'") == 2

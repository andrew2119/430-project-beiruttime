from uuid import UUID, uuid4
import pytest
from .conftest import headers

pytestmark = pytest.mark.asyncio


def facts(price=20000):
    return {
        "brand": "Sample",
        "model": "Watch",
        "reference": "REF",
        "year": 2020,
        "condition": "Known wear",
        "component_wear": {"case": "Light wear"},
        "location": "Beirut",
        "included": [],
        "no_documents": True,
        "modified": False,
        "modifications": [],
        "ownership_confirmed": True,
        "sale_mode": "fixed_price",
        "currency": "USD",
        "price_minor": price,
    }


async def published(api):
    created = await api.client.post(
        "/v1/seller/listings", headers=headers(), json={"facts": facts()}
    )
    assert created.status_code == 201, created.text
    row = created.json()
    # Controlled publication fixture; tests exercise edit fencing, not publication.
    photo = uuid4()
    await api.app.state.pool.execute(
        "UPDATE catalog_listings SET status='published',photo_ids=$2::uuid[],cover_id=$3,registration='{}',fee_snapshot='{}',rules_version='sample-v1',published_at=now() WHERE id=$1",
        UUID(row["id"]),
        [photo],
        photo,
    )
    api.orders["watch"] = {
        "watch_id": row["physical_watch_id"],
        "listing_id": row["id"],
        "listing_revision": row["revision"],
        "revision": 1,
        "status": "available",
        "source_id": None,
    }
    return row


async def test_price_change_once_and_revision_race(api):
    row = await published(api)
    url = f"/v2/seller/listings/{row['id']}/revisions"
    key = uuid4().hex
    body = {"facts": facts(21000), "reason": "Correct price"}
    first = await api.client.post(url, headers=headers(revision=1, key=key), json=body)
    assert first.status_code == 200, first.text
    assert (
        first.json()["status"] == "succeeded"
        and first.json()["listing"]["revision"] == 2
    )
    assert (
        await api.client.post(url, headers=headers(revision=1, key=key), json=body)
    ).json() == first.json()
    assert (
        await api.client.post(url, headers=headers(revision=1), json=body)
    ).status_code == 409
    history = await api.client.get(url, headers=headers())
    assert len(history.json()["items"]) == 1
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.price-changed.v1'"
        )
        == 1
    )


async def test_denial_keeps_source_until_confirmed_abort_then_explicit_retry(api):
    row = await published(api)
    api.orders["deny"] = True
    api.fail['abort_unknown'] = True
    result = await api.client.post(
        f"/v2/seller/listings/{row['id']}/revisions",
        headers=headers(revision=1),
        json={"facts": facts(22000), "reason": "New price"},
    )
    assert result.status_code == 503, result.text
    url = f"/v2/seller/listings/{row['id']}/revisions"
    history = (await api.client.get(url, headers=headers())).json()
    operation = history["pending_operation_id"]
    assert operation and not history["items"]
    retained = await api.client.get(
        f"/v2/seller/listing-edit-operations/{operation}", headers=headers()
    )
    assert retained.json()["status"] == "pending"
    assert retained.json()["listing"]["facts"]["price_minor"] == 20000
    # A known Orders denial does not erase the already prepared Auction hold.
    competing = await api.client.post(
        url,
        headers=headers(revision=1),
        json={"facts": facts(24000), "reason": "Competing new edit"},
    )
    assert competing.status_code == 409
    replay = await api.client.post(
        f"/v2/seller/listing-edit-operations/{operation}/resume", headers=headers()
    )
    assert replay.status_code == 503
    assert not any(
        host == "auction" and path.endswith("/commit")
        for host, path, _method in api.calls
    )
    assert await api.app.state.pool.fetchval(
        "SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.price-changed.v1'") == 0
    api.fail['abort_unknown'] = False
    resolved = await api.client.post(
        f'/v2/seller/listing-edit-operations/{operation}/resume', headers=headers())
    assert resolved.status_code == 200 and resolved.json()['status'] == 'denied', resolved.text
    assert (await api.client.get(url, headers=headers())).json()['pending_operation_id'] is None
    api.orders['deny'] = False
    # A fresh explicit user command may retry the facts only after confirmed abort.
    retried = await api.client.post(url, headers=headers(revision=1),
        json={'facts':facts(22000), 'reason':'Try after confirmed abort'})
    assert retried.status_code == 200 and retried.json()['status'] == 'succeeded', retried.text
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM catalog_listing_history"
        )
        == 1
    )
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.price-changed.v1'"
        )
        == 1
    )


async def test_unknown_fence_retains_intent_and_reconciles_after_restart(api):
    row = await published(api)
    api.fail["orders"] = True
    url = f"/v2/seller/listings/{row['id']}/revisions"
    result = await api.client.post(
        url,
        headers=headers(revision=1),
        json={"facts": facts(23000), "reason": "Correct amount"},
    )
    assert result.status_code == 503, result.text
    history = (await api.client.get(url, headers=headers())).json()
    operation = history["pending_operation_id"]
    assert operation and history["items"] == []
    competing = await api.client.post(
        url,
        headers=headers(revision=1),
        json={"facts": facts(24000), "reason": "Other editor"},
    )
    assert competing.status_code == 409
    api.fail["orders"] = False
    finished = await api.client.post(
        f"/v2/seller/listing-edit-operations/{operation}/resume", headers=headers()
    )
    assert finished.status_code == 200 and finished.json()["status"] == "succeeded", (
        finished.text
    )
    assert finished.json()["listing"]["facts"]["price_minor"] == 23000
    denied = await api.client.get(url, headers=headers("other"))
    assert denied.status_code == 403


async def test_auction_precedes_orders_and_hashes_normalized_arabic_public_facts(api):
    import hashlib
    import json

    row = await published(api)
    value = facts(25000)
    value["condition"] = "محتوى تجريبي مع خدوش معلنة"
    result = await api.client.post(
        f"/v2/seller/listings/{row['id']}/revisions",
        headers=headers(revision=1),
        json={"facts": value, "reason": "Correct public facts"},
    )
    assert result.status_code == 200 and result.json()["status"] == "succeeded", (
        result.text
    )
    prepare = next(
        i
        for i, call in enumerate(api.calls)
        if call[:2] == ("auction", "/internal/v3/listing-edits/prepare")
    )
    commitment = next(
        i
        for i, call in enumerate(api.calls)
        if call[:2] == ("orders", "/internal/v2/commitments")
    )
    dispatch = next(i for i, call in enumerate(api.calls) if call[0] == 'auction' and call[1].endswith('/dispatch'))
    assert prepare < dispatch < commitment
    retained = next(iter(api.auctions.values()))
    assert retained['orders_operation_key'] == retained['operation_id']
    assert retained['orders_expected_revision'] == 1
    assert (
        retained["facts_digest"]
        == hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    )


async def test_known_auction_denial_before_orders_is_terminal_without_an_edit(api):
    row = await published(api)
    api.fail["auction_denied"] = True
    result = await api.client.post(
        f"/v2/seller/listings/{row['id']}/revisions",
        headers=headers(revision=1),
        json={"facts": facts(26000), "reason": "Restricted edit"},
    )
    assert result.status_code == 200 and result.json()["status"] == "denied", (
        result.text
    )
    assert not any(
        host == "orders" and method == "POST" for host, path, method in api.calls
    )
    assert (
        await api.app.state.pool.fetchval(
            "SELECT count(*) FROM catalog_listing_history"
        )
        == 0
    )


@pytest.mark.parametrize('failure', ['dispatch_reply', 'dispatch_binding'])
async def test_dispatch_must_confirm_exactly_before_orders_http(api, failure):
    row = await published(api)
    api.fail[failure] = True
    url = f'/v2/seller/listings/{row["id"]}/revisions'
    result = await api.client.post(url, headers=headers(revision=1),
        json={'facts':facts(27000), 'reason':'Exact dispatch boundary'})
    assert result.status_code == 503, result.text
    assert not any(host == 'orders' and method == 'POST' for host, _, method in api.calls)
    pending = await api.app.state.pool.fetchrow('SELECT * FROM catalog_listing_edits')
    assert pending['auction_prepared'] and not pending['auction_dispatched'] and not pending['orders_started']
    api.fail[failure] = False
    resumed = await api.client.post(f'/v2/seller/listing-edit-operations/{pending["id"]}/resume', headers=headers())
    assert resumed.status_code == 200 and resumed.json()['status'] == 'succeeded', resumed.text


async def test_expired_undispatched_lease_is_terminal_without_orders(api):
    row = await published(api)
    api.fail['expire_dispatch'] = True
    result = await api.client.post(f'/v2/seller/listings/{row["id"]}/revisions',
        headers=headers(revision=1), json={'facts':facts(28000),'reason':'Lease expired before dispatch'})
    assert result.status_code == 200 and result.json()['status'] == 'denied', result.text
    assert result.json()['code'] == 'prepare_expired' and result.json()['listing']['revision'] == 1
    assert not any(host == 'orders' and method == 'POST' for host, _, method in api.calls)
    assert await api.app.state.pool.fetchval('SELECT count(*) FROM catalog_listing_history') == 0


@pytest.mark.parametrize('failure', ['orders_reply','abort_reply'])
async def test_lost_denial_or_abort_reply_recovers_same_retained_operation(api, failure):
    row = await published(api)
    api.orders['deny'] = True
    api.fail[failure] = True
    url = f'/v2/seller/listings/{row["id"]}/revisions'
    result = await api.client.post(url, headers=headers(revision=1),
        json={'facts':facts(29000),'reason':'Retain denial operation identity'})
    assert result.status_code == 503, result.text
    pending = (await api.client.get(url, headers=headers())).json()['pending_operation_id']
    assert pending
    api.fail[failure] = False
    resumed = await api.client.post(f'/v2/seller/listing-edit-operations/{pending}/resume', headers=headers())
    assert resumed.status_code == 200 and resumed.json()['status'] == 'denied', resumed.text
    again = await api.client.post(f'/v2/seller/listing-edit-operations/{pending}/resume', headers=headers())
    assert again.json() == resumed.json()
    assert await api.app.state.pool.fetchval('SELECT count(*) FROM catalog_listing_history') == 0
    assert await api.app.state.pool.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.price-changed.v1'") == 0


async def test_expiry_ack_cannot_release_an_already_dispatched_source(api):
    row = await published(api)
    api.fail['orders_reply'] = True
    url = f'/v2/seller/listings/{row["id"]}/revisions'
    initial = await api.client.post(url, headers=headers(revision=1),
        json={'facts':facts(30000),'reason':'Physical invocation already dispatched'})
    assert initial.status_code == 503
    pending = (await api.client.get(url, headers=headers())).json()['pending_operation_id']
    api.fail['orders_reply'] = False
    api.fail['expire_dispatch'] = True  # Adversarial impossible provider acknowledgement.
    result = await api.client.post(f'/v2/seller/listing-edit-operations/{pending}/resume', headers=headers())
    assert result.status_code == 503, result.text
    assert (await api.client.get(url, headers=headers())).json()['pending_operation_id'] == pending
    assert await api.app.state.pool.fetchval('SELECT count(*) FROM catalog_listing_history') == 0


async def test_existing_v2_intent_keeps_original_protocol_and_key(api):
    import json
    row = await published(api)
    operation = uuid4()
    await api.app.state.pool.execute('''INSERT INTO catalog_listing_edits
        (id,listing_id,actor_id,operation_key,digest,base_revision,facts,reason,auction_protocol)
        VALUES($1,$2,$3,$4,$5,1,$6::jsonb,$7,2)''', operation,UUID(row['id']),api.owner,
        uuid4().hex,'0'*64,json.dumps(facts(31000)),'Resume retained legacy edit')
    result = await api.client.post(f'/v2/seller/listing-edit-operations/{operation}/resume',headers=headers())
    assert result.status_code == 200 and result.json()['status'] == 'succeeded', result.text
    assert any(host == 'auction' and path == '/internal/v2/listing-edits/prepare' for host,path,_ in api.calls)
    assert not any(path.endswith('/dispatch') for _,path,_ in api.calls)


@pytest.mark.parametrize('failure', ['orders_http_denied','auction_commit_denied'])
async def test_remote_http_denial_is_pending_not_a_terminal_command_denial(api, failure):
    row = await published(api)
    api.fail[failure] = True
    url = f'/v2/seller/listings/{row["id"]}/revisions'
    result = await api.client.post(url,headers=headers(revision=1),
        json={'facts':facts(32000),'reason':'Keep unknown finalization recoverable'})
    assert result.status_code == 503 and result.json()['error']['code'] == 'edit_pending', result.text
    operation = await api.app.state.pool.fetchrow('SELECT * FROM catalog_listing_edits')
    assert operation['status'] == ('committed' if failure == 'auction_commit_denied' else 'pending')
    history = (await api.client.get(url,headers=headers())).json()
    assert history['pending_operation_id'] == str(operation['id'])
    assert len(history['items']) == (1 if failure == 'auction_commit_denied' else 0)
    api.fail[failure] = False
    resumed = await api.client.post(f'/v2/seller/listing-edit-operations/{operation["id"]}/resume',headers=headers())
    assert resumed.status_code == 200 and resumed.json()['status'] == 'succeeded', resumed.text
    assert await api.app.state.pool.fetchval('SELECT count(*) FROM catalog_listing_history') == 1
    assert await api.app.state.pool.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='catalog.listing.price-changed.v1'") == 1

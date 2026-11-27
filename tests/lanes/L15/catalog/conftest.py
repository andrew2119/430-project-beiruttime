import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import asyncpg
import httpx
import jwt
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def headers(token="buyer", revision=None, key=None, service_token=None):
    return {
        "Authorization": "Bearer " + token,
        "Idempotency-Key": key or uuid4().hex,
        **({"If-Match": str(revision)} if revision else {}),
        **(
            {"X-Service-Authorization": "Bearer " + service_token}
            if service_token
            else {}
        ),
    }


@pytest_asyncio.fixture
async def api(database_url, monkeypatch):
    owner, other, brand, approver = uuid4(), uuid4(), uuid4(), uuid4()
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = signing.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setenv("BT_SERVICE_AUTH_PRIVATE_KEY", private)
    tokens = {
        "buyer": {
            "actor": {"subject_id": str(owner), "session_id": "buyer-session"},
            "roles": ["buyer", "private_seller"],
            "permissions": ["identity.listings.publish"],
        },
        "other": {
            "actor": {"subject_id": str(other), "session_id": "other-session"},
            "roles": ["buyer"],
            "permissions": [],
        },
        "brand": {
            "actor": {
                "subject_id": str(approver),
                "organization_id": str(brand),
                "session_id": "brand-session",
            },
            "roles": ["brand"],
            "permissions": [],
            "organizations": [str(brand)],
            "organization_grants": [
                {
                    "organization_id": str(brand),
                    "permissions": ["business.jobs.write", "business.stock.write"],
                    "roles": ["brand"],
                }
            ],
        },
    }
    other_brand_id = uuid4()
    tokens["other_brand"] = {
        "actor": {
            "subject_id": str(other),
            "organization_id": str(other_brand_id),
            "session_id": "other-brand-session",
        },
        "roles": ["brand"],
        "permissions": [],
        "organizations": [str(other_brand_id)],
        "organization_grants": [
            {
                "organization_id": str(other_brand_id),
                "roles": ["brand"],
                "permissions": ["business.jobs.write"],
            }
        ],
    }
    tokens["self_brand"] = {
        "actor": {
            "subject_id": str(owner),
            "organization_id": str(brand),
            "session_id": "self-brand-session",
        },
        "roles": ["brand"],
        "permissions": [],
        "organizations": [str(brand)],
        "organization_grants": [
            {
                "organization_id": str(brand),
                "roles": ["brand"],
                "permissions": ["business.jobs.write"],
            }
        ],
    }
    fail, orders, calls, authority, auctions, auction_phases = {}, {}, [], {}, {}, {}

    async def remote(request):
        host, path = request.url.host, request.url.path
        calls.append((host, path, request.method))
        if fail.get(host):
            return httpx.Response(503)
        if host == "identity":
            if path.startswith("/v1/businesses/"):
                return httpx.Response(
                    200,
                    json={
                        "id": str(brand),
                        "kind": "brand",
                        "state": "active",
                        "platform_onboarded": True,
                        "authenticated_business": True,
                        "capabilities": ["customization", "sales"],
                        "public_name": "Sample brand",
                    },
                )
            token = request.headers.get("Authorization", "")[7:]
            return (
                httpx.Response(200, json=tokens[token])
                if token in tokens
                else httpx.Response(401)
            )
        if host == "orders":
            if request.method == 'POST' and fail.get('orders_http_denied'):
                return httpx.Response(409)
            if request.method == "GET":
                return httpx.Response(200, json=orders.get("watch", {}))
            body = json.loads(request.content)
            operations = orders.setdefault('operations', {})
            if body['operation_key'] in operations:
                return httpx.Response(200, json=operations[body['operation_key']])
            if path == '/internal/v2/commitments':
                retained = await app.state.pool.fetchrow(
                    'SELECT auction_protocol,auction_prepared,auction_dispatched,orders_started FROM catalog_listing_edits WHERE id=$1',
                    UUID(body['source_id']))
                if retained and retained['auction_protocol'] == 3:
                    assert retained['auction_prepared'] and retained['auction_dispatched'] and retained['orders_started']
                if orders.get('deny'):
                    result = {'id': str(uuid4()), 'status': 'denied', 'code': 'watch_committed'}
                else:
                    watch = {**orders['watch'], 'revision': orders['watch']['revision']+1,
                             'status': 'editing', 'source_id': body['source_id']}
                    orders['watch'] = watch
                    result = {'id': str(uuid4()), 'status': 'succeeded', 'watch': watch}
            else:
                orders['watch'] = {**orders['watch'], 'status': 'available',
                    'listing_revision': body['listing_revision'], 'revision': orders['watch']['revision']+1}
                result = {'id': str(uuid4()), 'status': 'succeeded', 'watch': orders['watch']}
            operations[body['operation_key']] = result
            if fail.get('orders_reply'):
                return httpx.Response(503)
            return httpx.Response(200, json=result)
        if host in ("service-operations", "pricing", "eligibility"):
            kind = {
                "service-operations": "assessment",
                "pricing": "quote",
                "eligibility": "grant",
            }[host]
            if request.method == "GET":
                if kind == "grant":
                    assert request.url.params.get("purpose") == "brand_approval"
                if kind == "quote":
                    assert request.url.params.get("buyer_id") == str(owner)
                    assert "organization_id" not in request.url.params
                value = authority.get(kind, {})
                if kind == "quote" and value:
                    value = {
                        **value,
                        "quote_id": value["id"],
                        "quote_revision": value["revision"],
                        "source_id": value["request_id"],
                        "source_revision": value["request_revision"],
                        "organization_id": value["brand_id"],
                        "kind": "brand",
                        "status": "valid",
                        "accepted_at": datetime.now(timezone.utc).isoformat(),
                        "schedule_id": "sample-v1",
                        "policy_revision": 1,
                        "rounding": "half_up",
                    }
                if kind == "assessment" and value:
                    value = {
                        **value,
                        "organization_id": value["brand_id"],
                        "current": True,
                    }
                value = {**value, **authority.get(kind + "_projection", {})}
                return httpx.Response(200, json=value)
            body = json.loads(request.content)
            assert (
                await app.state.pool.fetchval(
                    "SELECT status FROM catalog_brand_decisions WHERE id=$1",
                    UUID(body["operation_id"]),
                )
                == "pending"
            )
            if authority.get("revoked"):
                return httpx.Response(
                    200, json={"operation_id": body["operation_id"], "status": "denied"}
                )
            if path.endswith("/prepare"):
                return httpx.Response(
                    200,
                    json={"operation_id": body["operation_id"], "status": "prepared"},
                )
            result = {**body, "status": "succeeded", "current": True}
            authority["consumed"] = result
            if fail.get("consume_reply"):
                return httpx.Response(503)
            return httpx.Response(200, json=result)
        if host == 'auction':
            if fail.get('auction_denied') or (fail.get('auction_commit_denied') and path.endswith('/commit')):
                return httpx.Response(409)
            body = json.loads(request.content) if request.content else {}
            if path.endswith('/prepare'):
                operation_id = body['operation_id']
                if operation_id in auctions:
                    assert auctions[operation_id] == body
                auctions[operation_id] = body
                auction_phases.setdefault(operation_id, 'prepared')
            else:
                operation_id = path.split('/')[-2]
            retained = auctions[operation_id]
            is_v3 = '/v3/' in path
            result = {**retained, 'status': 'succeeded', 'phase': 'prepared',
                      'auction_id': None, 'auction_revision': None}
            if is_v3:
                result.update(protocol=3, expires_at=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat())
            if path.endswith('/prepare'):
                return httpx.Response(200, json=result)
            if path.endswith('/dispatch'):
                if fail.get('expire_dispatch'):
                    auction_phases[operation_id] = 'aborted'
                    return httpx.Response(200, json={**result, 'phase':'aborted', 'code':'prepare_expired'})
                auction_phases[operation_id] = 'dispatched'
                if fail.get('dispatch_reply'):
                    return httpx.Response(503)
                if fail.get('dispatch_binding'):
                    result['orders_expected_revision'] += 1
                return httpx.Response(200, json={**result, 'phase':'dispatched'})
            if path.endswith(('/abort','/reconcile')):
                denied = orders.get('operations', {}).get(retained.get('orders_operation_key',operation_id), {}).get('status') == 'denied'
                if auction_phases[operation_id] == 'aborted' or (denied and not fail.get('abort_unknown')):
                    auction_phases[operation_id] = 'aborted'
                    if fail.get('abort_reply'):
                        return httpx.Response(503)
                    return httpx.Response(200, json={**result, 'phase':'aborted', 'code':'orders_denied'})
                return httpx.Response(200, json={**result, 'status':'pending', 'phase':auction_phases[operation_id]})
            auction_phases[operation_id] = 'committed'
            return httpx.Response(200, json={**result, 'listing_revision':body['listing_revision'], 'phase':'committed'})
        return httpx.Response(503)

    settings = Settings(
        service_name="catalog",
        database_url=database_url,
        modules_path=Path("/app/modules"),
        service_auth_public_key=signing.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode(),
    )
    app = create_app(settings)
    app.state.pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    app.state.catalog_clients = {
        name: DependencyClient(
            name,
            f"http://{name}",
            transport=httpx.MockTransport(remote),
            failure_threshold=100,
        )
        for name in (
            "identity",
            "orders",
            "auction",
            "pricing",
            "service-operations",
            "eligibility",
        )
    }
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://catalog"
    )
    yield SimpleNamespace(
        client=client,
        app=app,
        owner=owner,
        other=other,
        brand=brand,
        approver=approver,
        fail=fail,
        orders=orders,
        calls=calls,
        tokens=tokens,
        authority=authority,
        auctions=auctions,
        service_token=jwt.encode(
            {
                "sub": "service-operations",
                "type": "service",
                "aud": "catalog",
                "iss": "beirut-time-identity",
                "iat": datetime.now(timezone.utc),
                "exp": datetime.now(timezone.utc) + timedelta(seconds=60),
            },
            private,
            algorithm="RS256",
        ),
    )
    await client.aclose()
    for dependency in app.state.catalog_clients.values():
        await dependency.aclose()
    await app.state.pool.close()


async def sources(api):
    pool = api.app.state.pool
    config_id, movement_id, selection_id, draft_id = uuid4(), uuid4(), uuid4(), uuid4()
    chosen = {}
    async with pool.acquire() as tx:
        await tx.execute(
            "INSERT INTO l10_configurations(id,owner_id,brand_id,base_model,caliber,revision) VALUES($1,$2,$3,'Base','Caliber',4)",
            config_id,
            api.owner,
            api.brand,
        )
        for kind in ("color", "material", "dial", "sophistication"):
            option_id = uuid4()
            chosen[kind] = option_id
            definition = {
                "component": "case" if kind != "dial" else "dial",
                "label": {"en": kind, "ar": kind},
                "base_models": ["Base"],
                "calibers": ["Caliber"],
                "available": True,
                "details": {},
            }
            await tx.execute(
                "INSERT INTO l10_options(brand_id,kind,option_id,revision,definition,created_by) VALUES($1,$2,$3,1,$4::jsonb,$5)",
                api.brand,
                kind,
                option_id,
                json.dumps(definition),
                api.approver,
            )
            await tx.execute(
                "INSERT INTO l10_selections(configuration_id,kind,component,brand_id,option_id,option_revision) VALUES($1,$2,$3,$4,$5,1)",
                config_id,
                kind,
                definition["component"],
                api.brand,
                option_id,
            )
        await tx.execute(
            "INSERT INTO movement_options(id,brand_id,revision,label_en,label_ar,caliber,cases,dials,hands,functions,quote_minor,currency,active) VALUES($1,$2,1,'Movement','حركة','Caliber',ARRAY['Base'],ARRAY['Dial'],ARRAY['Hands'],ARRAY[]::text[],100,'USD',true)",
            movement_id,
            api.brand,
        )
        mounting = {"case": "Base", "dial": "Dial", "hands": "Hands", "functions": []}
        await tx.execute(
            "INSERT INTO movement_selections(actor_id,brand_id,id,option_id,revision,option_revision,configuration,result) VALUES($1,$2,$3,$4,1,1,$5::jsonb,'{}') ON CONFLICT(actor_id,brand_id) DO UPDATE SET id=EXCLUDED.id,option_id=EXCLUDED.option_id,revision=1,option_revision=1,configuration=EXCLUDED.configuration",
            api.owner,
            api.brand,
            selection_id,
            movement_id,
            json.dumps(mounting),
        )
        content = {
            "kind": "customization",
            "brand_id": str(api.brand),
            "configuration_id": str(config_id),
            "configuration_revision": 4,
            "watch_context": "owned_watch",
            "watch_reference": "My declared watch",
            "scope_intent": "Review current scope",
            "notes": "Private neutral note",
            "options": {},
        }
        await tx.execute(
            "INSERT INTO l08_request_drafts(id,owner_id,content) VALUES($1,$2,$3::jsonb)",
            draft_id,
            api.owner,
            json.dumps(content),
        )
    chosen["movement"] = movement_id
    return SimpleNamespace(
        configuration_id=config_id,
        movement_id=movement_id,
        selection_id=selection_id,
        draft_id=draft_id,
        chosen=chosen,
    )

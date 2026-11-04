"""CP B-04/B-18: locks, outcome and outbox share one SQL transaction."""
import hashlib
import json
from uuid import UUID, uuid4
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work


def order_view(row):
    return {key: ((str(row[key]) if row[key] is not None else None) if key.endswith('_id') or key=='id' else row[key].isoformat() if key=='deadline' else row[key])
        for key in ('id','watch_id','listing_id','buyer_id','seller_id','organization_id','state','currency','total_minor','revision','deadline','is_demo')} | {'payment_authority':False}


def watch_view(row):
    return {key: str(row[key]) if key.endswith('_id') else row[key]
        for key in ('listing_id','sale_mode','status','revision','is_demo')} | {'watch_id':str(row['id'])}


async def outcome(tx, actor_key, key):
    row = await tx.fetchrow('SELECT * FROM l08_operations WHERE actor_key=$1 AND idempotency_key=$2', actor_key, key)
    return json.loads(row['result']) if row else None


async def command(pool, actor_key, key, action, payload, handler, *, request_id):
    if not key or len(key)>100 or any(ord(c)<33 or ord(c)>126 for c in key):
        raise PublicError('idempotency_required', 'Provide one stable Idempotency-Key.', status=422)
    digest = hashlib.sha256(json.dumps({'action':action,'body':payload},sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    async with unit_of_work(pool, lock_key='l08-op:'+actor_key+':'+key) as tx:
        prior = await tx.fetchrow('SELECT * FROM l08_operations WHERE actor_key=$1 AND idempotency_key=$2',actor_key,key)
        if prior:
            if prior['digest'] != digest:
                raise PublicError('idempotency_conflict', 'This operation key has different content.', status=409)
            return json.loads(prior['result'])
        result = {'id':str(uuid4()), 'request_id':request_id, **await handler(tx)}
        await tx.execute('INSERT INTO l08_operations(id,actor_key,idempotency_key,digest,result) VALUES($1,$2,$3,$4,$5::jsonb)',
            UUID(result['id']),actor_key,key,digest,json.dumps(result))
        return result


async def audit(tx, resource_id, actor_key, action, reason, revision):
    await tx.execute('INSERT INTO l08_audit(resource_id,actor_key,action,reason,revision) VALUES($1,$2,$3,$4,$5)',
        resource_id,actor_key,action,reason,revision)


async def event(tx, request, kind, resource_id, revision):
    await enqueue(tx, EventEnvelope(type='orders.'+kind+'.v1',source='orders',subject=str(resource_id),
        request_id=request.state.request_id, data={'resource_id':str(resource_id),'revision':revision}), ['catalog','communications'])


def denied(code):
    return {'status':'denied','code':code,'payment_authority':False}

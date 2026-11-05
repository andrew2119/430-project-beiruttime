"""Pricing current/v2 policy and transactional operation helpers (CP B-09)."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from bt_contracts_core.errors import AccessDenied, PublicError


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def percentage(amount, bps):
    return (amount * bps + 5000) // 10000


# Same Pricing-owned schedule as Q01. Always disclosed as sample policy, not
# silently substituted for a real approved commercial commission schedule.
POLICY = {'schedule_id': 'sample-v1', 'revision': 1, 'buyer_fee_bps': 300,
          'seller_commission_bps': 500, 'rounding': 'half_up', 'minor_unit_exponent': 2,
          'sample': True}


def amounts(lines, selected, assessment_fee):
    known = {line['id']: line for line in lines}
    if not set(selected) <= set(known) or not {k for k, v in known.items() if v['mandatory']} <= set(selected):
        raise PublicError('scope_mismatch', 'Select every mandatory line and only assessed optional lines.', status=409)
    parts = sum(known[k]['amount_minor'] for k in selected if known[k]['kind'] == 'part')
    labor = sum(known[k]['amount_minor'] for k in selected if known[k]['kind'] == 'labor')
    base = parts + labor + assessment_fee
    fee = percentage(base, POLICY['buyer_fee_bps'])
    commission = percentage(base, POLICY['seller_commission_bps'])
    if base <= 0:
        raise PublicError('invalid_total', 'The accepted quote must have a positive total.', status=409)
    return {'parts_minor': parts, 'labor_minor': labor, 'assessment_fee_minor': assessment_fee,
            'platform_fee_minor': fee, 'seller_commission_minor': commission,
            'seller_net_minor': base - commission, 'payable_minor': base + fee}


def current_time(row, now=None):
    if (now or datetime.now(timezone.utc)) >= row['expires_at']:
        raise PublicError('quote_expired', 'Review a current quote and explicitly accept it.', status=409)


async def replay(tx, principal, key, fingerprint):
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                     f'pricing-operation:{principal.actor.subject_id}:{key}')
    row = await tx.fetchrow('SELECT * FROM l14_pricing_operations WHERE actor_id=$1 AND operation_key=$2',
                            principal.actor.subject_id, key)
    if row:
        if row['request_hash'] != fingerprint or row['organization_id'] != principal.actor.organization_id:
            raise PublicError('idempotency_conflict', 'This operation key has different fields or scope.', status=409)
        return decoded(row['result'])


async def remember(tx, principal, key, fingerprint, result):
    result = {'operation_id': str(uuid4()), **result}
    await tx.execute('''INSERT INTO l14_pricing_operations(id,actor_id,organization_id,operation_key,request_hash,result)
        VALUES($1,$2,$3,$4,$5,$6::jsonb)''', UUID(result['operation_id']),
        principal.actor.subject_id, principal.actor.organization_id, key, fingerprint, json.dumps(result))
    return result


def buyer(principal):
    if principal.actor.organization_id is not None or 'buyer' not in principal.roles:
        raise AccessDenied('Current personal buyer capability required')

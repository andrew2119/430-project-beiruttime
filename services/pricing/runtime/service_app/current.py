"""Versioned USD fee policy and transactional operation helpers."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from bt_contracts_core.errors import AccessDenied, PublicError

MAX_MINOR = 9_000_000_000_000


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def percentage(amount, bps):
    if type(amount) is not int or not 0 <= amount <= MAX_MINOR or type(bps) is not int or not 0 <= bps <= 10000:
        raise PublicError('invalid_money', 'Use exact bounded USD cents.', status=422)
    return (amount * bps + 5000) // 10000


POLICY = {'schedule_id': 'usd-v2', 'revision': 2, 'buyer_fee_bps': 300,
          'seller_commission_bps': 500, 'rounding': 'half_up', 'minor_unit_exponent': 2,
          'sample': True}
JOB_POLICY = {**POLICY, 'schedule_id': 'usd-job-v2', 'buyer_fee_bps': 0,
              'business_fee_bps': 500, 'fee_refundable': False,
              'full_refund_fee_funding': 'business_saved_simulated_method',
              'fee_deducted_from_customer_refund': False}


def require_usd(snapshot):
    if snapshot.get('currency') != 'USD':
        raise PublicError('legacy_reconciliation', 'Historic currency is read-only; reconcile before payment or release.', status=409)


def amounts(lines, selected, assessment_fee):
    known = {line['id']: line for line in lines}
    if (len(set(selected)) != len(selected) or not set(selected) <= set(known)
            or not {k for k, v in known.items() if v['mandatory']} <= set(selected)):
        raise PublicError('scope_mismatch', 'Select every mandatory line and only assessed optional lines.', status=409)
    values = [known[k]['amount_minor'] for k in selected] + [assessment_fee]
    if any(type(value) is not int or not 0 <= value <= MAX_MINOR for value in values):
        raise PublicError('invalid_money', 'Use exact bounded USD cents.', status=422)
    parts = sum(known[k]['amount_minor'] for k in selected if known[k]['kind'] == 'part')
    labor = sum(known[k]['amount_minor'] for k in selected if known[k]['kind'] == 'labor')
    base = parts + labor + assessment_fee
    if not 0 < base <= MAX_MINOR:
        raise PublicError('invalid_total', 'The accepted quote must have a positive bounded total.', status=409)
    commission = percentage(base, JOB_POLICY['business_fee_bps'])
    return {'parts_minor': parts, 'labor_minor': labor, 'assessment_fee_minor': assessment_fee,
            'platform_fee_minor': commission, 'seller_commission_minor': commission,
            'seller_net_minor': base - commission, 'payable_minor': base}


def unchanged_terms(snapshot, candidate):
    """Price expiry and presentation order cannot rewrite an accepted promise."""
    keys = set(candidate) - {'expires_at'}
    def terms(value):
        result = {key: value.get(key) for key in keys}
        result['lines'] = sorted(result.get('lines') or [], key=lambda line: line['id'])
        return result
    return terms(snapshot) == terms(candidate)


def current_time(row, now=None):
    if row.get('state') == 'accepted':
        return  # Only uncommitted economics expire; execution is checked separately.
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

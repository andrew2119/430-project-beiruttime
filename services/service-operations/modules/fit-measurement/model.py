"""Serialized, private buyer targets with stable operation receipts."""
import hashlib
import json
from datetime import datetime, timezone


class Rejected(Exception):
    def __init__(self, code, status):
        self.code, self.status = code, status
        super().__init__(code)


def digest(body):
    return hashlib.sha256(body.model_dump_json().encode()).hexdigest()


def require_authority(proof, actor, body, buyer_only=True):
    expected = {
        'actor_id': str(actor), 'subject_id': str(body.subject_id),
        'watch_id': str(body.watch_id), 'organization_id': str(body.organization_id),
    }
    if buyer_only and str(actor) != str(body.subject_id):
        raise Rejected('denied', 403)
    if not isinstance(proof, dict) or any(proof.get(k) != v for k, v in expected.items()):
        raise Rejected('denied', 403)
    if proof.get('allowed') is not True:
        raise Rejected('denied', 403)
    if type(proof.get('source_revision')) is not int or proof['source_revision'] < 1:
        raise Rejected('unavailable', 503)
    if proof['source_revision'] != body.source_revision:
        raise Rejected('stale_revision', 409)


def resolve(body, actor, proof, prior, current, mm, now=None):
    require_authority(proof, actor, body)
    if prior:
        if (str(prior['actor_id']) != str(actor)
                or str(prior['organization_id']) != str(body.organization_id)
                or prior['request_hash'] != digest(body)):
            raise Rejected('operation_conflict', 409)
        result = prior['result']
        return json.loads(result) if isinstance(result, str) else result
    revision = current['revision'] if current else 0
    if revision != body.expected_revision:
        raise Rejected('stale_revision', 409)
    return {
        'schema_version': 'fit-measurement.v1', 'operation_id': str(body.operation_id),
        'subject_id': str(body.subject_id), 'watch_id': str(body.watch_id), 'actor_id': str(actor),
        'organization_id': str(body.organization_id), 'expected_revision': body.expected_revision,
        'source_revision': body.source_revision, 'state': 'recorded', 'revision': revision + 1,
        'circumference_mm': mm, 'method': body.method, 'source': body.source, 'target': body.target,
        'final_fit_pass': False, 'recorded_at': (now or datetime.now(timezone.utc)).isoformat(),
        'pending_reason': None, 'next_actor': None, 'next_review_at': None,
    }

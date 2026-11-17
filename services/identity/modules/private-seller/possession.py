"""Listing-bound private proof; submission never grants publication."""
import base64
import binascii
import copy
import hashlib
import io
import json
import re
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from bt_contracts_core.errors import PublicError


def deny(code, status=409):
    raise PublicError(code, 'Reload the current private proof or retry the same request.', status=status)


def authorize(actor, authority):
    required = {'subject_id', 'organization_id', 'seller_status', 'watch_id', 'watch_revision', 'listing_revision'}
    if not isinstance(authority, dict) or not required.issubset(authority):
        deny('unavailable', 503)
    if authority['subject_id'] != actor or authority['organization_id'] is not None or authority['seller_status'] != 'approved':
        deny('forbidden', 403)
    if not authority.get('watch_id') or any(type(authority.get(k)) is not int or authority[k] < 1 for k in ('watch_revision', 'listing_revision')):
        deny('unavailable', 503)


def bound(proof, authority):
    return all(proof[k] == authority[k] for k in ('subject_id', 'watch_id', 'watch_revision', 'listing_revision'))


def current(proof, authority, now):
    if proof is None:
        return None
    result = copy.deepcopy(proof)
    if not bound(proof, authority):
        result.update(state='stale', next_actor='seller', pending_reason='fresh_proof_required')
    elif proof['state'] == 'issued' and now >= datetime.fromisoformat(proof['expires_at']):
        result.update(state='expired', next_actor='seller', pending_reason='fresh_proof_required')
    elif proof['state'] == 'pending' and authority.get('review') is not None:
        review = authority['review']
        required = {'challenge_id', 'proof_revision', 'watch_revision', 'listing_revision', 'verdict',
                    'reviewer_id', 'assignment_revision', 'review_revision', 'reason'}
        if not isinstance(review, dict) or set(review) != required:
            deny('unavailable', 503)
        if any(type(review[k]) is not int or review[k] < 1 for k in ('proof_revision', 'watch_revision', 'listing_revision', 'assignment_revision', 'review_revision')):
            deny('unavailable', 503)
        if (review['challenge_id'] != proof['challenge_id'] or review['proof_revision'] != proof['revision']
                or review['watch_revision'] != proof['watch_revision'] or review['listing_revision'] != proof['listing_revision']):
            deny('unavailable', 503)
        if (not isinstance(review['verdict'], str) or review['verdict'] not in {'approved', 'correction', 'rejected', 'suspended'}
                or not isinstance(review['reviewer_id'], str) or not review['reviewer_id'].strip()
                or review['reviewer_id'] != review['reviewer_id'].strip() or review['reviewer_id'] == proof['subject_id']
                or not isinstance(review['reason'], str) or not review['reason'].strip()
                or any(type(review[k]) is not int or review[k] < 1 for k in ('assignment_revision', 'review_revision'))):
            deny('unavailable', 503)
        result.update(state=review['verdict'], review=copy.deepcopy(review), pending_reason=None,
                      next_actor='seller', next_review_at=None)
    return result


def issue(actor, listing, authority, previous, revision, operation, now, code=None, challenge=None):
    authorize(actor, authority)
    if revision != (previous['revision'] if previous else 0):
        deny('stale_proof')
    if previous and bound(previous, authority) and current(previous, authority, now)['state'] in {'pending', 'approved', 'suspended'}:
        deny('proof_pending')
    return dict(schema_version='identity.listing-possession.v1', operation_id=operation,
        subject_id=actor, actor_id=actor, organization_id=None, watch_id=authority['watch_id'],
        listing_id=listing, listing_revision=authority['listing_revision'], watch_revision=authority['watch_revision'],
        expected_revision=revision, revision=revision+1, challenge_id=challenge or str(uuid4()),
        code=code or f'{secrets.randbelow(1000000):06d}', issued_at=now.isoformat(),
        expires_at=(now+timedelta(hours=24)).isoformat(), submitted_at=None,
        state='issued', pending_reason=None, next_actor='seller', next_review_at=None)


def normalize_code(value):
    return value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))


def submit(actor, authority, proof, revision, challenge, code, operation, now):
    authorize(actor, authority)
    if not proof or not bound(proof, authority) or proof['revision'] != revision:
        deny('stale_proof')
    if proof['state'] != 'issued':
        deny('proof_pending')
    if now >= datetime.fromisoformat(proof['expires_at']):
        deny('proof_expired')
    normalized = normalize_code(code)
    if not re.fullmatch(r'[0-9]{6}', normalized) or challenge != proof['challenge_id'] or not secrets.compare_digest(normalized, proof['code']):
        deny('invalid_proof', 422)
    return dict(proof, operation_id=operation, expected_revision=revision, revision=revision+1,
        state='pending', submitted_at=now.isoformat(), pending_reason='assigned_review_required',
        next_actor='assigned_reviewer', next_review_at=(now+timedelta(hours=24)).isoformat())


def private_png(encoded):
    try:
        content = base64.b64decode(encoded, validate=True)
        if len(content) > 1048576:
            raise ValueError()
        with Image.open(io.BytesIO(content)) as image:
            if image.format != 'PNG' or image.width * image.height > 4000000 or image.width < 1 or image.height < 1:
                raise ValueError()
            image.load()
            clean = Image.new('RGB', image.size)
            clean.paste(image.convert('RGB'))
            output = io.BytesIO()
            clean.save(output, format='PNG')
            return output.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, binascii.Error):
        deny('bad_photo', 422)


def request_digest(kind, body):
    return hashlib.sha256(json.dumps({'kind': kind, 'body': body}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def replay(receipt, digest, authority):
    if receipt['digest'] != digest:
        deny('operation_conflict')
    result = receipt['result']
    if not bound(result, authority):
        deny('stale_proof')
    return copy.deepcopy(result)

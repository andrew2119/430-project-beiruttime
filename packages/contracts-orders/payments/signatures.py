"""Bounded signed simulated results shared by checkout and journal movements."""

import hashlib
import hmac
import os
import re
from bt_contracts_core.errors import PublicError


def secret():
    key = os.environ.get('BT_SIMULATED_PAYMENT_SECRET', '')
    if len(key.encode()) < 32:
        raise PublicError('simulator_unavailable', 'Simulated payment signing is unavailable.', status=503)
    return key.encode()


def sign(raw):
    return hmac.new(secret(), raw, hashlib.sha256).hexdigest()


def verify_payload(raw, signature, model):
    if len(raw) > 8192:
        raise PublicError('callback_too_large', 'The callback exceeds its bound.', status=413)
    if not isinstance(signature, str) or re.fullmatch(r'[0-9a-f]{64}', signature) is None or not hmac.compare_digest(sign(raw), signature):
        raise PublicError('signature_invalid', 'The simulated payment signature is invalid.', status=401)
    try:
        return model.model_validate_json(raw)
    except ValueError:
        raise PublicError('callback_invalid', 'The simulated callback has invalid fields.', status=422) from None


async def callback_bytes(request):
    chunks = bytearray()
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 8192:
            raise PublicError('callback_too_large', 'The callback exceeds its bound.', status=413)
        chunks.extend(chunk)
    return bytes(chunks)

"""Bounded route adapter; the host supplies verified authentication and bindings."""
import json


def command_response(service, raw, authenticated_actor):
    if not authenticated_actor or not isinstance(raw, bytes) or len(raw) > 4096:
        return 403, {'state': 'denied'}
    try:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate_field')
                result[key] = value
            return result
        command = json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError):
        return 400, {'state': 'denied'}
    result = service.save(command, authenticated_actor)
    status = {'saved': 200, 'denied': 403, 'stale': 409, 'pending': 202, 'unavailable': 503}[result['state']]
    return status, result


def private_headers():
    return {'Cache-Control': 'no-store', 'Vary': 'Authorization'}


def read_response(service, trusted_binding, authenticated_actor, operation_id=None):
    """GET scope is resolved by the host from the path and selected business.

    trusted_binding contains current provider-bound identifiers, never caller
    monetary input. The service independently rechecks it under the fence.
    """
    if not authenticated_actor or not isinstance(trusted_binding, dict):
        return 403, {'state': 'denied'}
    command = dict(trusted_binding, operation_id=operation_id or 'current',
                   minimum_minor=None, expected_revision=0)
    result = service.read(command, authenticated_actor, operation=operation_id is not None)
    status = {'denied': 403, 'unavailable': 503}.get(result.get('state'), 200)
    return status, result

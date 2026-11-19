"""Composition boundary; identity and current provider admission stay caller-owned."""
import sqlite3
from pydantic import ValidationError
from .service import Rejected


def command_response(service, actor_id, body):
    try:
        return 200, service.execute(actor_id, body)
    except sqlite3.OperationalError:
        return 503, {"code": "unavailable"}
    except ValidationError:
        return 422, {"code": "invalid_input"}
    except (KeyError, TypeError, ValueError):
        return 422, {"code": "invalid_input"}
    except Rejected as error:
        status = 403 if error.code == "denied" else 503 if error.code == "unavailable" else 422 if error.code in {"measurement", "scope", "required_detail", "invalid_time", "money", "too_large"} else 409
        return status, {"code": error.code}


def read_response(service, actor_id, request_id):
    try:
        return 200, service.read(actor_id, request_id)
    except Rejected as error:
        return (503 if error.code == "unavailable" else 403), {"code": error.code}

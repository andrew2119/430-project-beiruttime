"""Transport-neutral internal adapter; composition supplies authenticated context."""

import sqlite3

from .domain import CustodyError


STATUS = {"invalid": 422, "denied": 403, "conflict": 409, "stale": 409,
          "held": 409, "pending": 202, "unavailable": 503}


class Adapter:
    def __init__(self, custody):
        self.custody = custody

    def call(self, operation, context, **parameters):
        try:
            if operation == "command":
                result = self.custody.execute(context, parameters["command"])
            elif operation == "lookup":
                result = self.custody.lookup(context, parameters["order_id"], parameters["operation_id"])
            elif operation == "read":
                result = self.custody.read(context, parameters["order_id"])
            elif operation == "history":
                result = self.custody.history(context, **parameters)
            else:
                raise CustodyError("invalid")
            return 200, {"schema_version": "custody.v1", "result": result}
        except CustodyError as error:
            return STATUS[error.code], {"schema_version": "custody.v1", "state": error.code,
                                      "retry_same_operation": error.code in {"pending", "unavailable"}}
        except (TimeoutError, ConnectionError, sqlite3.OperationalError):
            return 503, {"schema_version": "custody.v1", "state": "unavailable", "retry_same_operation": True}

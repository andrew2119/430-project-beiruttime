"""Composition boundary for authenticated private requests."""
import json


class Adapter:
    def __init__(self, service, command_type):
        self.service = service
        self.command_type = command_type

    async def command(self, body: bytes, principal):
        if len(body) > 16384:
            raise ValueError('request_too_large')
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError('invalid_request')
        command = self.command_type(**payload)
        return await self.service.submit(command, principal)

    async def operation(self, operation_id, bound_command, principal):
        # Lookup needs the immutable binding from restricted request storage.
        if operation_id != bound_command.operation_id:
            raise ValueError('operation_conflict')
        return await self.service.lookup(bound_command, principal)

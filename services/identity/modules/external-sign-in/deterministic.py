"""Synthetic exchange adapter for local contract checks only."""
from .service import Denied


class DeterministicProvider:
    def __init__(self, fixtures):
        self.fixtures = dict(fixtures)
        self.calls = 0

    async def exchange(self, code):
        self.calls += 1
        if code not in self.fixtures:
            raise Denied()
        result = self.fixtures[code]
        if isinstance(result, Exception):
            raise result
        return result

"""Composition boundary: authenticated scope and server time are supplied upstream."""
from store import token


class Adapter:
    def __init__(self, store, clock):
        self.store = store
        self.clock = clock

    def command(self, scope, body):
        if set(body) != {'schema_version', 'operation_id', 'kind', 'expected_revision'} or body['schema_version'] != 'data-requests.v1':
            raise ValueError('invalid')
        result = self.store.create(token(body['operation_id']), scope.actor_id, scope.subject_id,
                                   scope.organization_id, body['kind'], body['expected_revision'], self.clock())
        return self.store._public(result)

    def lookup(self, scope, operation_id):
        return self.store.lookup(operation_id, scope.actor_id, scope.subject_id, scope.organization_id, self.clock())

    def page(self, scope, page=0, page_size=20):
        return self.store.page(scope.actor_id, scope.subject_id, scope.organization_id, self.clock(), page, page_size)

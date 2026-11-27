"""Private opening and assigned-record authority composition."""
from service_app.sources import prerequisite


class CurrentAuthority:
    def __init__(self, request):
        self.request = request

    async def current(self, actor, organization, order):
        return await prerequisite(self.request, 'intake_opening_authority', actor, organization, order)

    async def record_access(self, actor, organization, order, permission):
        return await prerequisite(self.request, 'intake_record_access', actor, organization, order, permission)

    async def readable_orders(self, actor, organization):
        return await prerequisite(self.request, 'intake_readable_orders', actor, organization)

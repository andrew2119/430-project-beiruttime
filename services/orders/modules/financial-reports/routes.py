"""Host-composed private route boundary; no runtime registration here."""
from dataclasses import dataclass
from .model import Projection, export_csv


@dataclass(frozen=True)
class Response:
    status: int
    body: object
    headers: dict


class Reports:
    def __init__(self, projection: Projection, authorize, feed_reader):
        self.projection = projection
        self.authorize = authorize
        self.feed_reader = feed_reader

    def get(self, principal, request, locale='en', now=None):
        answer = self.projection.read(request, principal, self.authorize, self.feed_reader, now)
        headers = {'Cache-Control':'private, no-store', 'Vary':'Cookie, Authorization', 'X-Content-Type-Options':'nosniff'}
        status = {'ready':200, 'denied':403, 'stale':409, 'pending':202, 'drift':200, 'unavailable':503}[answer['state']]
        if request.get('action') == 'export' and answer['state'] == 'ready':
            try:
                content = export_csv(answer, locale)
            except ValueError:
                return Response(503, {'state':'unavailable','operation_id':answer['operation_id']}, headers)
            headers.update({'Content-Type':'text/csv; charset=utf-8', 'Content-Disposition':'attachment; filename="receipts.csv"'})
            return Response(200, content, headers)
        return Response(status, answer, headers)

    def lookup(self, principal, operation_id, now=None):
        answer = self.projection.operation(operation_id, principal, self.authorize, self.feed_reader, now)
        return Response({'ready':200,'drift':200,'pending':202,'denied':403,'stale':409,'unavailable':503}[answer['state']], answer, {'Cache-Control':'private, no-store'})

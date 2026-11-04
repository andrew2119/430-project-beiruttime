"""Real API negative proofs against connected-proof.py's disposable services."""
import json
import os
import time
import urllib.error
import urllib.request
from uuid import uuid4

ORIGIN = os.environ.get('BT_BROWSER_ORIGIN', 'http://127.0.0.1:3177')
BODY = {'subject_id': '00000000-0000-4000-8000-000000005000', 'subject_revision': 1,
        'purpose': 'purchase', 'currency': 'USD', 'price_minor': 500000, 'schedule_id': 'sample-v1'}


def request(port, path, token=None, body=None, key=None):
    headers = {'Origin': ORIGIN, 'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if key:
        headers['Idempotency-Key'] = key
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', json.dumps(body).encode() if body is not None else None, headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def buyer():
    status, session = request(18101, '/v1/accounts/register', body={'email': 'sample-l07-api-' + uuid4().hex + '@example.invalid',
        'password': 'Sample-' + uuid4().hex, 'display_name': 'Sample API buyer'}, key=uuid4().hex)
    assert status == 201
    return session['access_token']


def main():
    alice, bob = buyer(), buyer()
    status, quote = request(18104, '/v1/quotes', alice, BODY, uuid4().hex)
    assert status == 201 and quote['sample'] and quote['payable_minor'] == 515000
    assert request(18104, '/v1/quotes/' + quote['id'], bob)[0] == 404
    assert request(18104, '/internal/v1/quotes/' + quote['id'] + '/validation', alice)[0] == 403
    review = {**BODY, 'quote_revision': 1, 'payable_minor': 515000}
    assert request(18104, '/v1/quotes/' + quote['id'] + '/review', alice, review, uuid4().hex)[0] == 200
    for _ in range(30):
        _, inbox = request(18108, '/v1/inbox', alice)
        if inbox['items']:
            break
        time.sleep(.2)
    assert len(inbox['items']) == 1 and inbox['unread_count'] == 1
    notice = inbox['items'][0]
    assert request(18108, '/v1/inbox/' + notice['id'] + '/read', bob, {'expected_revision': 1}, uuid4().hex)[0] == 404
    assert request(18108, '/v1/inbox/' + notice['id'] + '/read', alice, {'expected_revision': 1}, uuid4().hex)[0] == 200
    _, destination = request(18108, '/v1/inbox/' + notice['id'] + '/destination', alice)
    assert destination['url'] == '/prices?quote_id=' + quote['id']
    assert request(18108, '/v1/inbox/' + notice['id'] + '/clear', alice, {'expected_revision': 2}, uuid4().hex)[0] == 200
    assert request(18108, '/v1/inbox', alice)[1]['items'] == []
    draft_body = {'subject_id': BODY['subject_id'], 'subject_revision': 1, 'currency': 'USD', 'amount_minor': 480000}
    status, draft = request(18108, '/v1/buying/drafts', alice, draft_body, uuid4().hex)
    assert status == 201 and draft['status'] == 'draft'
    assert request(18108, '/v1/buying/drafts/' + draft['id'], bob)[0] == 404
    for path in ('/v1/buying/payment', '/v1/buying/drafts/' + draft['id'] + '/send', '/v1/buying/drafts/' + draft['id'] + '/accept'):
        status, error = request(18108, path, alice, {})
        assert status == 403 and error['error']['code'] == 'capability_not_released'
    _, readiness = request(18108, '/v1/buying/readiness?reservation_id=' + str(uuid4()) + '&quote_id=' + quote['id'], alice)
    assert readiness['reservation']['status'] == 'unavailable' and readiness['quote']['status'] == 'available'
    assert not any(readiness['release'].values())
    print('Connected real Identity/Pricing/Communications proofs pass: exact quote, signed outbox/inbox, private scopes, canonical links, read/clear, retained draft, dependency outage and server release denials.')


if __name__ == '__main__':
    main()

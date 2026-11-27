"""Exact reviewed boundary inputs, evaluated by code in the built Auction image."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

from bt_runtime.modules import discover
from service_app.engine import time_denial

cases = json.loads(sys.argv[1])
fixed, refused = cases['fixed_end'], cases['deadline_refusal']
end = datetime.fromisoformat(fixed['ends_at'])
policy = next(module for module in discover(Path('/app/modules')) if module.id == 'L12.extension-policy')
accept = policy.load('policy.py:accepted_bid')
compat = policy.load('policy.py:extension')
lot = {'mode': 'bidding', 'starts_at': end - timedelta(hours=1), 'ends_at': end}
result = []
for remaining in (*fixed['remaining_seconds'], *refused['remaining_seconds']):
    now = end - timedelta(seconds=remaining)
    denial = time_denial(lot, now)
    assert denial == (None if remaining > 0 else refused['code'])
    for stored in ('none.v1', 'last-two-minutes.v1'):
        state = {'ends_at': end + timedelta(minutes=5), 'scheduled_ends_at': end, 'server_time': now,
                 'end_version': fixed['end_version'], 'extension_policy': stored}
        before = state.copy()
        for kind in fixed['kinds']:
            bid = {'kind': kind, 'accepted_at': now}
            if remaining > 0:
                expected = {'ends_at': fixed['ends_at'], 'end_version': fixed['end_version'], 'extended': fixed['extended']}
                assert accept(state) == compat(state, bid) == expected
                assert accept(state) == expected  # Re-evaluation retains the original deadline.
            else:
                for evaluate in (lambda: accept(state), lambda: compat(state, bid)):
                    try:
                        evaluate()
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('packaged policy accepted at or after the deadline')
            assert state == before
            result.append([remaining, kind, stored, denial])
print(json.dumps(result))

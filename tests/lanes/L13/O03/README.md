# Focused payment checks

Run the unchanged earlier callback and checkout assertions with the current
transaction fixtures:

```sh
PYTHONPATH=tests/lanes/L13/O03 /opt/bt/bin/python -m pytest -p legacy_boundaries tests/lanes/L13/unit/test_callback_replay.py tests/lanes/L13/unit/test_checkout_window.py tests/lanes/L13/O03 -q
```

`legacy_boundaries` extends only the two named fixtures. It supplies empty movement
reads, durable reconciliation receipts, financial revisions and bounded transaction
contexts. All other SQL delegates to the original fixtures, including their strict
query rejection. Original test functions and assertions remain unchanged.

These checks cover local transaction adapters. Database constraints and connected
producer, restart, delivery and browser journeys require separate verification.

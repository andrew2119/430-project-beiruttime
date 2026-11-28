"""Bounded scheduled polling; source events can request the same observation."""
from .store import Failure


def tick(store, now, after='', limit=20):
    if not 1 <= limit <= 50:
        raise Failure('invalid')
    with store.lock:
        rows = store.db.execute('SELECT watch FROM l22_sources WHERE watch>? ORDER BY watch LIMIT ?',
                                (after, limit)).fetchall()
    pending = held = 0
    for row in rows:
        try:
            store.observe(row['watch'], now)
        except (Failure, TimeoutError):
            pending += 1
    try:
        delivery = store.dispatch(now, limit)
        pending += delivery['pending']
        held = delivery['held']
    except (Failure, TimeoutError):
        pending += 1
    return {'next': rows[-1]['watch'] if len(rows) == limit else '', 'pending': pending,
            'held': held, 'next_actor': 'communications_support' if held else None}

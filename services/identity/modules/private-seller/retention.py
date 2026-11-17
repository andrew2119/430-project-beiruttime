"""Transactional private-photo removal from current review and case facts."""
from datetime import datetime, timedelta

from bt_contracts_core.errors import PublicError


def removal_due(photo, facts, now):
    """Missing review or case authority never grants removal permission."""
    required = {'photo_id', 'listing_id', 'subject_id', 'challenge_id', 'final_review_at',
                'reviewer_id', 'assignment_revision', 'active_case'}
    if (not isinstance(facts, dict) or set(facts) != required
            or any(str(photo[k]) != facts[k] for k in ('listing_id', 'subject_id', 'challenge_id'))
            or str(photo['id']) != facts['photo_id']
            or type(facts['active_case']) is not bool
            or not isinstance(facts['reviewer_id'], str) or not facts['reviewer_id'].strip()
            or facts['reviewer_id'] == facts['subject_id']
            or type(facts['assignment_revision']) is not int or facts['assignment_revision'] < 1):
        raise PublicError('unavailable', 'Current evidence retention is unavailable.', status=503)
    final = facts['final_review_at']
    if final is not None and (not isinstance(final, datetime) or final.tzinfo is None or final > now):
        raise PublicError('unavailable', 'Current evidence retention is unavailable.', status=503)
    return final is not None and not facts['active_case'] and now >= final + timedelta(days=30)


async def reconcile_photo(tx, photo_id, facts, now):
    """Use a transaction serialized with the producer's review and case changes.

    The scheduler supplies fresh private authority for this exact historical
    challenge, including after relisting. Unknown facts abort without changing
    the hold. Releasing a hold removes already-due bytes in the same transaction.
    """
    photo = await tx.fetchrow('SELECT * FROM identity_l19_possession_photos WHERE id=$1 FOR UPDATE', photo_id)
    if photo is None:
        return False
    due = removal_due(photo, facts, now)
    if due:
        await tx.execute('DELETE FROM identity_l19_possession_photos WHERE id=$1', photo_id)
    else:
        await tx.execute('''UPDATE identity_l19_possession_photos
            SET final_review_at=$2, retained_for_case=$3 WHERE id=$1''', photo_id, facts['final_review_at'], facts['active_case'])
    return due

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


CURRENT_REVIEW = """EXISTS (
    SELECT 1 FROM identity_data_possession_reviews r WHERE r.photo_id=f.id
    AND r.final_review_at IS NOT DISTINCT FROM $2 AND r.active_case=$5
    AND r.reviewer_id::text=$3 AND r.revision=$4 FOR SHARE
)"""


async def reconcile_photo(tx, photo_id, facts, now):
    """Reconcile only facts that still match the owning review under lock."""
    binding = await tx.fetchrow(
        'SELECT subject_id FROM identity_l19_possession_photos WHERE id=$1', photo_id)
    if binding is None:
        return False
    await tx.fetchrow('SELECT id FROM identity_accounts WHERE id=$1 FOR UPDATE', binding['subject_id'])
    photo = await tx.fetchrow('SELECT * FROM identity_l19_possession_photos WHERE id=$1 FOR UPDATE', photo_id)
    if photo is None:
        return False
    due = removal_due(photo, facts, now)
    authority = (photo_id, facts['final_review_at'], facts['reviewer_id'],
                 facts['assignment_revision'], facts['active_case'])
    if due:
        admitted = await tx.execute(f"""INSERT INTO identity_possession_tombstones
            (photo_id,listing_id,subject_id,challenge_id,removed_at,final_review_at,reviewer_id,assignment_revision)
            SELECT f.id,f.listing_id,f.subject_id,f.challenge_id,clock_timestamp(),$2,$3,$4
            FROM identity_l19_possession_photos f WHERE f.id=$1 AND {CURRENT_REVIEW}
            AND clock_timestamp()>=$2::timestamptz+interval '30 days'
            AND NOT identity_data_subject_has_hold(f.subject_id,NULL)
            AND NOT EXISTS (
                SELECT 1 FROM identity_data_requests r
                WHERE r.scope=json_build_array(f.subject_id::text,f.subject_id::text,NULL)::text
                AND r.body::jsonb->>'kind'='delete'
                AND coalesce(r.body::jsonb->'domains'->'identity'->>'state', '') NOT IN ('deleted','redacted')
            )
            AND NOT identity_data_object_has_hold('identity_l19_possession_photos',f.id,encode(sha256(f.content),'hex'))
            ON CONFLICT(photo_id) DO NOTHING""", *authority)
        if admitted == 'INSERT 0 0':
            return False
        status = await tx.execute("""DELETE FROM identity_l19_possession_photos f WHERE id=$1
            AND EXISTS (SELECT 1 FROM identity_possession_tombstones t
                        WHERE t.photo_id=f.id AND t.subject_id=f.subject_id
                        AND t.assignment_revision=$2)""", photo_id, facts['assignment_revision'])
        return status != 'DELETE 0'
    await tx.execute(f"""WITH admitted AS (
            UPDATE identity_l19_possession_photos f
            SET final_review_at=$2,retained_for_case=$5
            WHERE f.id=$1 AND {CURRENT_REVIEW} RETURNING f.id,f.content
        )
        INSERT INTO identity_possession_retention
            (photo_id,revision,sha256,expires_at,final_review_at,active_case,assignment_revision)
        SELECT id,1,encode(sha256(content),'hex'),clock_timestamp()+interval '120 seconds',$2,$5,$4 FROM admitted
        ON CONFLICT(photo_id) DO UPDATE SET revision=identity_possession_retention.revision+1,
            sha256=excluded.sha256,expires_at=excluded.expires_at,final_review_at=excluded.final_review_at,
            active_case=excluded.active_case,assignment_revision=excluded.assignment_revision""", *authority)
    return False

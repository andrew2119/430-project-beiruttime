"""Pure reduction decisions from current protected facts."""
from datetime import timedelta, timezone
from bt_contracts.service.reduction.v1 import Binding


class Rejected(Exception):
    def __init__(self, code):
        self.code = code


def authorize(command, authority, now):
    if not authority.current or not authority.checked_at <= now < authority.valid_until:
        raise Rejected('unavailable')
    if authority.checked_at.utcoffset() != timezone.utc.utcoffset(None) or authority.valid_until.utcoffset() != timezone.utc.utcoffset(None):
        raise Rejected('unavailable')
    if any(getattr(command, key) != getattr(authority, key) for key in Binding.model_fields):
        raise Rejected('stale')
    if command.kind == 'request':
        if authority.permission != 'buyer_request' or authority.actor_id != command.subject_id:
            raise Rejected('denied')
    elif authority.permission != 'assigned_work':
        raise Rejected('denied')
    choices = [choice for choice in authority.choices if choice.id == command.choice_id and choice.compatible]
    if len(choices) != 1 or command.recipient_id not in authority.authorized_recipient_ids:
        raise Rejected('denied')
    if not now < authority.next_review_at <= now + timedelta(hours=24):
        raise Rejected('unavailable')
    if command.kind == 'request':
        return 'requested'
    if not authority.accepted_scope or not authority.custody_current or authority.payment_state != 'paid_held' or authority.incident_open:
        raise Rejected('denied')
    removed, returned = set(command.removed_link_ids), set(command.returned_link_ids)
    if not removed <= set(authority.removable_link_ids) or not returned <= removed:
        raise Rejected('denied')
    if choices[0].kind == 'removable_links' and not removed:
        raise Rejected('denied')
    if choices[0].kind == 'strap_change':
        replacements = [part for part in authority.accepted_straps
            if part.id == command.actual_strap_id and part.choice_id == command.choice_id
            and part.source_revision == command.source_revision
            and part.quote_revision == command.quote_revision
            and part.policy_revision == command.policy_revision and part.compatible]
        if len(replacements) != 1:
            raise Rejected('denied')
    elif command.actual_strap_id is not None:
        raise Rejected('denied')
    excepted = set()
    if command.exception_id:
        matches = [item for item in authority.accepted_exceptions if item.id == command.exception_id]
        if len(matches) != 1:
            raise Rejected('denied')
        item = matches[0]
        if (item.accepted_by != command.subject_id or item.accepted_at > now
                or item.source_revision != command.source_revision or item.quote_revision != command.quote_revision
                or item.recipient_id != command.recipient_id or not set(item.link_ids) <= removed):
            raise Rejected('denied')
        excepted = set(item.link_ids)
    missing = removed - returned
    if missing & set(authority.buyer_owned_link_ids) or not missing <= excepted or not command.fit_confirmed or not authority.fit_confirmed:
        return 'unresolved'
    return 'recorded'

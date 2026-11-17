"""Civil-time resolution and current authorization boundaries."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class Rejected(Exception):
    def __init__(self, code, status=409, candidates=()):
        self.code, self.status, self.candidates = code, status, candidates
        super().__init__(code)


def resolve(command):
    civil = datetime.strptime(command.civil_time, '%Y-%m-%dT%H:%M')
    zone = ZoneInfo('Asia/Beirut')
    candidates = sorted({civil.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                         for fold in (0, 1)
                         if civil.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                         .astimezone(zone).replace(tzinfo=None) == civil})
    if not candidates:
        raise Rejected('missing_time', 422)
    if len(candidates) == 2 and (not command.repeated_time_confirmed or command.selected_instant not in candidates):
        raise Rejected('repeated_time', 422, tuple(item.isoformat() for item in candidates))
    if command.selected_instant is not None and command.selected_instant not in candidates:
        raise Rejected('instant_mismatch', 422)
    return command.selected_instant or candidates[0]


def authorize(authority, subject, watch, organization, actor):
    if not (authority.active and authority.onboarded and authority.record_allowed
            and authority.actor_id == actor and authority.subject_id == subject
            and authority.watch_id == watch and authority.organization_id == organization):
        raise Rejected('denied', 403)
    if authority.role == 'buyer' and actor != subject:
        raise Rejected('denied', 403)

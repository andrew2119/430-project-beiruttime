"""Pure policy transition, persisted only while holding the consent fence."""
from copy import deepcopy
from uuid import uuid5, NAMESPACE_URL

BINDINGS = ('subject_id', 'organization_id', 'watch_id', 'request_id', 'request_revision',
            'quote_id', 'quote_revision', 'consent_revision', 'reviewer_id',
            'brand_approver_id', 'assignment_revision', 'policy_revision', 'purpose')


def transition(state, command, current, actor, consent):
    state = deepcopy(state)
    def result(status, reason):
        return state, {'state': status, 'reason_code': reason, 'revision': state['revision']}
    if command['expected_revision'] != state['revision']:
        return result('stale', 'revision_changed')
    # UTC instants are parsed by the strict boundary before comparison.
    from datetime import datetime
    if datetime.fromisoformat(current['now']) >= datetime.fromisoformat(current['expires_at']):
        return result('denied', 'permission_expired')
    if command['kind'] == 'revoke':
        grant = next((g for g in state['grants'] if g['grant_id'] == command.get('grant_id')), None)
        if not grant:
            return result('denied', 'grant_missing')
        grant['revoked_at'] = current['now']
        state['revision'] += 1
        return result('revoked', 'grant_revoked')
    if consent['status'] != 'active' or consent['revision'] != current['consent_revision']:
        return result('denied', 'consent_ineffective')
    if (str(consent['buyer_id']) != current['subject_id'] or str(consent['brand_id']) != current['organization_id']
            or str(consent['request_id']) != current['request_id'] or consent['request_revision'] != current['request_revision']):
        return result('denied', 'scope_changed')
    if not all(current[k] for k in ('identity_current', 'organization_current', 'assignment_current',
                                    'accepted_scope_current', 'commitment_current', 'source_facts_current')):
        return result('denied', 'authority_changed')
    if current['reviewer_id'] in (current['subject_id'], current['brand_approver_id']):
        return result('denied', 'independence_required')
    binding = {key: current[key] for key in BINDINGS}
    if len(state['reviews']) >= 1000 or len(state['grants']) >= 1000:
        return result('denied', 'history_limit')
    if command['kind'] == 'review':
        if actor != current['reviewer_id']:
            return result('denied', 'assignment_required')
        verdict = command.get('verdict')
        if verdict not in ('eligible', 'not_eligible', 'correction'):
            return result('denied', 'verdict_required')
        if verdict == 'eligible' and not current['synthetic_identity_pass']:
            return result('denied', 'objective_facts_required')
        state['revision'] += 1
        state['reviews'].append({**binding, 'verdict': verdict, 'reason': command['reason'],
                                 'review_revision': state['revision'], 'reviewed_at': current['now']})
        return result(verdict, 'review_recorded')
    if command.get('use') == 'approval' and actor != current['brand_approver_id']:
        return result('denied', 'brand_approver_required')
    review = state['reviews'][-1] if state['reviews'] else None
    if not review or review['verdict'] != 'eligible' or any(review[k] != binding[k] for k in BINDINGS):
        return result('denied', 'current_review_required')
    if not current['synthetic_identity_pass']:
        return result('denied', 'objective_facts_required')
    if command['kind'] == 'prepare':
        use = command.get('use')
        if use not in ('approval', 'execution'):
            return result('denied', 'use_required')
        if any(g['use'] == use and g['review_revision'] == review['review_revision']
               and (g['consumed_at'] or not g['revoked_at']) for g in state['grants']):
            return result('denied', 'grant_already_prepared')
        state['revision'] += 1
        grant = {**binding, 'grant_id': str(uuid5(NAMESPACE_URL, command['operation_id'])),
                 'grant_revision': state['revision'], 'review_revision': review['review_revision'],
                 'use': use, 'expires_at': current['expires_at'], 'revoked_at': None, 'consumed_at': None}
        state['grants'].append(grant)
        return state, {'state': 'prepared', 'reason_code': 'grant_prepared', 'revision': state['revision'],
                       'grant': grant}
    grant = next((g for g in state['grants'] if g['grant_id'] == command.get('grant_id')), None)
    if (not grant or grant['revoked_at'] or grant['consumed_at'] or grant['use'] != command.get('use')
            or grant['review_revision'] != review['review_revision']
            or any(grant[k] != binding[k] for k in BINDINGS)
            or datetime.fromisoformat(current['now']) >= datetime.fromisoformat(grant['expires_at'])):
        return result('denied', 'grant_ineffective')
    grant['consumed_at'] = current['now']
    state['revision'] += 1
    return result('consumed', 'grant_consumed')

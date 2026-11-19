"""Pure, fail-closed native acceptance assembly; never starts provider operations."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PLAN = Path(__file__).with_name('required-proofs.json')
PROVIDERS = {'E06', 'A10', 'E04', 'E08', 'E09'}
DEPENDENCIES = ['N04', 'N05', 'N06', 'N07', 'N08', 'N09']
CORE = {
    'E06': '''allocation_fixed_price allocation_auction allocation_offer allocation_job
        fixed_end_race cancel_race private_maximum_race durable_notice_clock
        callback_expiry_ordering balanced_simulated_journal failed_inspection_collection
        controlled_return independent_brand_approval paid_customization service_maintenance
        service_repair service_cleaning service_polishing service_enlargement service_reduction
        quality_rework actual_receipt dispute_hold principal_only_refund payout_reconciliation
        replay restart purchase_then_customization'''.split(),
    'A10': ['replica_recovery', 'dataset_load', 'viewer_update_2_seconds', 'notice_30_seconds'],
    'E04': ['restore'], 'E08': ['physical_device'], 'E09': ['release_reconciliation'],
}


JOURNEYS = [['registration', '5', 'buyer_registered', 'seller_permission_denied', 'resume_sign_in'],
 ['password_change',
  '5',
  'fresh_sign_in_required',
  'wrong_current_password_denied',
  'retry_current_password'],
 ['password_recovery', '5', 'single_use_reset', 'expired_link_denied', 'new_recovery_request'],
 ['second_factor', '5', 'factor_enrolled', 'invalid_factor_denied', 'recovery_code_used'],
 ['contact_change', '5', 'new_contact_verified', 'expired_code_denied', 'old_contact_retained'],
 ['private_seller_review',
  '5',
  'independent_approval',
  'self_review_denied',
  'correction_resubmitted'],
 ['listing_possession', '5', 'fresh_listing_proof', 'reused_code_denied', 'fresh_proof_requested'],
 ['business_onboarding',
  '5',
  'scoped_business_active',
  'unsupported_scope_denied',
  'authorized_reactivation'],
 ['business_membership',
  '2',
  'ordinary_colleague_granted',
  'self_privilege_change_denied',
  'responsible_replacement'],
 ['private_export_deletion',
  '5',
  'permitted_export',
  'active_record_deletion_denied',
  'redaction_after_obligations'],
 ['listing_draft',
  '6',
  'complete_private_draft',
  'incomplete_publication_denied',
  'corrected_draft'],
 ['safe_photos', '6', 'safe_cover_uploaded', 'oversize_upload_denied', 'replacement_photo'],
 ['publication',
  '6',
  'registered_publication',
  'duplicate_watch_denied',
  'registration_reconciled'],
 ['listing_revision', '6', 'versioned_edit', 'stale_revision_denied', 'reload_current_revision'],
 ['withdrawal',
  '6',
  'confirmed_withdrawal',
  'committed_withdrawal_denied',
  'pending_operation_reconciled'],
 ['relisting', '6', 'fresh_linked_listing', 'sold_stock_relisting_denied', 'possession_rechecked'],
 ['dealer_import', '6', 'private_drafts_imported', 'invalid_row_denied', 'same_operation_retry'],
 ['search', '6', 'combined_usd_filters', 'invalid_range_denied', 'query_preserved'],
 ['watch_detail', '6', 'actual_disclosures', 'private_serial_hidden', 'unavailable_stock_shown'],
 ['comparison', '6', 'three_watch_comparison', 'fourth_watch_denied', 'removed_watch_unavailable'],
 ['similar_watches', '6', 'disclosed_matching', 'invented_match_absent', 'empty_results'],
 ['seller_reviews', '6', 'released_buyer_rating', 'unreleased_rating_denied', 'independent_appeal'],
 ['fixed_price_reservation',
  '7',
  'exclusive_awaiting_payment',
  'second_buyer_denied',
  'same_operation_reconciled'],
 ['payment_notice',
  '7',
  'durable_notice_clock',
  'failed_notice_clock_denied',
  'notice_republished'],
 ['payment_methods',
  '7',
  'simulated_method_selected',
  'unsupported_method_denied',
  'switch_preserves_clock'],
 ['payment_confirmation',
  '7',
  'exact_payment_held',
  'mismatched_callback_held',
  'same_attempt_reconciled'],
 ['payment_expiry',
  '7',
  'declined_only_release',
  'unknown_money_release_denied',
  'late_confirmation_held'],
 ['cancellation_return',
  '7',
  'controlled_cancellation',
  'stock_restore_without_receipt_denied',
  'return_reconciled'],
 ['auction_schedule', '8', 'beirut_time_confirmed', 'ambiguous_time_denied', 'corrected_time'],
 ['ordinary_bid', '8', 'serialized_bid', 'late_self_bid_denied', 'same_operation_retry'],
 ['private_maximum',
  '8',
  'full_increment_response',
  'equal_public_bid_denied',
  'displaced_ceiling_raised'],
 ['auction_close', '8', 'fixed_end_result', 'ceiling_reserve_sale_denied', 'allocation_reconciled'],
 ['auction_cancel', '8', 'no_bid_cancelled', 'after_bid_cancel_denied', 'cancel_race_reconciled'],
 ['auction_purchase_exclusion',
  '8',
  'new_purchase_refused',
  'legacy_unknown_release_denied',
  'ended_legacy_reconciled'],
 ['offers', 'D29', 'retained_offer_accepted', 'auction_offer_denied', 'counteroffer_supersedes'],
 ['private_inspection',
  '10',
  'paid_received_independent_pass',
  'invented_pass_denied',
  'inconclusive_held'],
 ['failed_inspection',
  '10',
  'seller_charge_confirmed',
  'unknown_collection_return_denied',
  'same_collection_reconciled'],
 ['custody', '10', 'actual_signed_receipt', 'dispatch_as_receipt_denied', 'incident_held'],
 ['business_assurance',
  '10',
  'current_business_assurance',
  'fictional_inspection_denied',
  'reasoned_remedy'],
 ['receipt_window',
  '10',
  'actual_receipt_starts_window',
  'dispatch_window_denied',
  'approved_proof_reconciled'],
 ['dispute', '10', 'timely_dispute_hold', 'late_dispute_denied', 'duplicate_same_case'],
 ['refund', '10', 'principal_only_refund', 'fee_refund_denied', 'same_refund_reconciled'],
 ['payout', '10', 'conditional_release', 'held_payout_denied', 'same_recipient_reconciled'],
 ['customization_options',
  '11',
  'five_versioned_dimensions',
  'stale_option_denied',
  'manual_assessment'],
 ['customization_submission',
  '11',
  'immutable_request',
  'incomplete_submission_denied',
  'same_request_retry'],
 ['customization_assessment',
  '11',
  'qualified_assessment',
  'unsupported_feasibility_denied',
  'reasoned_correction'],
 ['customization_quote',
  '11',
  'customer_accepted_scope',
  'changed_quote_execution_denied',
  'renewed_acceptance'],
 ['identity_consent', '11', 'purpose_consent', 'withdrawn_consent_denied', 'serialized_withdrawal'],
 ['eligibility',
  '11',
  'independent_objective_review',
  'conflicting_reviewer_denied',
  'correction_reviewed'],
 ['brand_approval',
  '11',
  'current_distinct_approval',
  'approval_alone_execution_denied',
  'revocation_rechecked'],
 ['paid_customization_job',
  '11',
  'paid_allocated_authorization',
  'unpaid_work_denied',
  'scope_change_pauses'],
 ['purchase_then_customization',
  'D18',
  'sequential_linked_orders',
  'simultaneous_allocation_denied',
  'purchase_window_completed'],
 ['service_intake',
  '12',
  'actual_authorized_intake',
  'symptom_as_diagnosis_denied',
  'new_custody_rechecked'],
 ['service_maintenance',
  '12',
  'accepted_maintenance_completed',
  'unaccepted_overhaul_denied',
  'quality_rework'],
 ['service_repair', '12', 'diagnosed_repair_completed', 'new_fault_spend_denied', 'renewed_quote'],
 ['service_cleaning',
  '12',
  'accepted_external_cleaning',
  'assumed_submersion_denied',
  'quality_rework'],
 ['service_polishing', '12', 'exact_finish_completed', 'silent_expansion_denied', 'renewed_scope'],
 ['service_enlargement',
  '12',
  'compatible_fit_completed',
  'universal_link_formula_denied',
  'fit_rechecked'],
 ['service_reduction',
  '12',
  'removed_parts_returned',
  'missing_parts_completion_denied',
  'parts_reconciled'],
 ['quality_handover',
  '12',
  'actual_quality_receipt',
  'failed_quality_release_denied',
  'rework_rechecked'],
 ['notices_saves_follows',
  '13',
  'required_deduplicated_notice',
  'disabled_required_notice_denied',
  'reconnect_current_state'],
 ['private_conversations',
  '13',
  'ordered_scoped_message',
  'revoked_private_read_denied',
  'same_message_retry'],
 ['moderation_appeals',
  '14',
  'independent_applied_decision',
  'self_review_denied',
  'independent_appeal'],
 ['responsive_private_experience',
  '14',
  'bilingual_mounted_inputs',
  'private_storage_denied',
  'identity_change_clears_private_view']]


def required_contracts():
    contracts = {name: (owner, ['positive', 'negative', 'recovery'])
                 for owner, names in CORE.items() for name in names}
    for number in range(1, 65):
        for locale in ('en', 'ar'):
            for theme in ('light', 'dark'):
                contracts[f'journey_{number:02}_{locale}_{theme}'] = (
                    'E08', ['positive', 'negative', 'recovery', 'keyboard', 'reduced_motion',
                            'width_390', 'input_preservation', 'private_memory_only'])
    return contracts


def content_contract(key):
    if key.startswith('journey_'):
        feature, section, positive, negative, recovery = JOURNEYS[int(key.split('_')[1]) - 1]
    else:
        feature, section = key, 'native requirements'
        positive, negative, recovery = (key + '_observed', key + '_unsafe_transition_denied',
                                        key + '_same_operation_reconciled')
    state = ('awaiting_payment' if (key.startswith('allocation_') and key != 'allocation_job')
             or feature == 'fixed_price_reservation' else 'succeeded')
    return dict(feature=feature, rulebook_section=section, positive=positive,
                negative=negative, recovery=recovery, positive_state=state, recovery_state=state,
                negative_state='held' if negative == 'mismatched_callback_held' else 'denied',
                negative_effects=['reconciliation_hold'] if negative == 'mismatched_callback_held' else [])


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError('plan_shape')
    if plan.get('schema_version') != 'native-plan.v1':
        raise ValueError('plan_version')
    if not isinstance(plan, dict):
        raise ValueError('plan_shape')
    crosswalk = plan['original_crosswalk']
    source = Path(__file__).resolve().parents[3] / crosswalk['source']
    if (crosswalk['source'] != 'tests/integration/sprint-1/runner.py'
            or digest(source) != crosswalk['sha256']
            or crosswalk['final_inventory_status'] != 'missing_final_inventory'):
        raise ValueError('original_inventory_binding')
    import ast
    tree = ast.parse(source.read_text())
    original = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == 'REQUIRED'
                        for target in node.targets))
    coverage = crosswalk['coverage']
    if (len(coverage) != len(original)
            or {item['capability'] for item in coverage} != original
            or any(item['cases'] != 'all_original_assertions_negative_and_recovery'
                   or item['provider_binding'] is not None
                   or not item['journey_slots']
                   or any(type(slot) is not int or not 1 <= slot <= 64
                          for slot in item['journey_slots']) for item in coverage)):
        raise ValueError('original_inventory_accounting')
    rows = plan['requirements']
    ids = [r['id'] for r in rows]
    canonical = required_contracts()
    if len(ids) != len(set(ids)) or set(ids) != set(canonical):
        raise ValueError('requirement_accounting')
    for row in rows:
        owner, assertions = canonical[row['id']]
        reference = dict(provider=owner, scenario=row['id'], assertions=assertions,
                         lifecycle=DEPENDENCIES, contract_version='native-provider.v1')
        for key in ('provider', 'scenario', 'assertions', 'lifecycle', 'contract_version'):
            if row[key] != reference[key]:
                raise ValueError('requirement_contract')
        if row['provider'] not in PROVIDERS or row['lifecycle'] != DEPENDENCIES:
            raise ValueError('provider_ownership')
        if row.get('content') != content_contract(row['id']):
            raise ValueError('content_contract')
        entry = row['entrypoint']
        revision = row['source_revision']
        if (entry is None) != (revision is None):
            raise ValueError('partial_binding')
        if entry is not None and (
            not re.fullmatch(r'[a-zA-Z0-9_./-]+', entry)
            or entry.startswith('/') or '..' in entry.split('/')
            or not re.fullmatch(r'[0-9a-f]{40}', revision)
        ):
            raise ValueError('invalid_binding')
    return rows


def validate_evidence(row, evidence, root, origin, run_id):
    """Validate exact provider-owned result and separately attributable artifacts."""
    if row['entrypoint'] is None:
        raise ValueError('missing_provider_binding')
    expected = {
        'schema_version': row['contract_version'], 'requirement': row['id'],
        'provider': row['provider'], 'scenario': row['scenario'],
        'source_revision': row['source_revision'], 'entrypoint': row['entrypoint'],
        'origin': origin, 'run_id': run_id, 'execution': 'real_provider',
        'result': 'passed', 'fixture_only': False,
        'assertions': {a: True for a in row['assertions']},
        'lifecycle': {d: 'passed' for d in row['lifecycle']},
        'content': row['content'],
    }
    for key, value in expected.items():
        if json.dumps(evidence.get(key), sort_keys=True) != json.dumps(value, sort_keys=True):
            raise ValueError('evidence_' + key)
    artifacts = evidence.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError('missing_artifact')
    for artifact in artifacts:
        relative = Path(artifact['path'])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('artifact_path')
        if digest(path) != artifact['sha256']:
            raise ValueError('artifact_digest')
        validate_outcomes(json.loads(path.read_text()), evidence)
    if row['id'] == 'physical_device':
        if not all(evidence.get(k) for k in ('device_id', 'operator_reference', 'captured_at')):
            raise ValueError('physical_attribution')
    if row['id'] in {'dataset_load', 'viewer_update_2_seconds', 'notice_30_seconds'}:
        if not all(evidence.get(k) for k in ('dataset_sha256', 'connection', 'sample_count')):
            raise ValueError('measurement_basis')
        limit = {'viewer_update_2_seconds': 2000, 'notice_30_seconds': 30000}.get(row['id'])
        if limit and (type(evidence.get('maximum_ms')) is not int or not 0 <= evidence['maximum_ms'] <= limit):
            raise ValueError('speed_target')


def retained_outcome(case):
    return {key: value for key, value in case.items()
            if key not in {'original', 'retry', 'retry_operation_id'}}


def validate_retry(case, evidence):
    original, retry = case['original'], case['retry']
    for observation in (original, retry):
        for key in ('requirement', 'source_revision', 'run_id', 'origin'):
            if observation[key] != evidence[key]:
                raise ValueError('retry_binding')
        if (observation['operation_id'] != case['operation_id']
                or observation['outcome'] != retained_outcome(case)
                or not isinstance(observation['observation_id'], str)
                or not observation['observation_id']):
            raise ValueError('retry_retained_outcome')
    if (case['retry_operation_id'] != original['operation_id']
            or original['observation_id'] == retry['observation_id']
            or type(original['sequence']) is not int or type(retry['sequence']) is not int
            or not 0 <= original['sequence'] < retry['sequence']
            or retry['new_effect_ids'] != []
            or not isinstance(original['new_effect_ids'], list)
            or len(set(original['new_effect_ids'])) != len(original['new_effect_ids'])):
        raise ValueError('retry_reference')


def validate_negative_transition(case, evidence):
    """Bind a denied operation to unchanged financial and custody observations."""
    before, after = case['before'], case['after']
    for observation in (before, after):
        for key in ('requirement', 'source_revision', 'run_id', 'origin'):
            if observation[key] != evidence[key]:
                raise ValueError('negative_binding')
        if (observation['operation_id'] != case['operation_id']
                or not isinstance(observation['observation_id'], str)
                or not observation['observation_id']
                or type(observation['sequence']) is not int):
            raise ValueError('negative_observation')
    if (before['observation_id'] == after['observation_id']
            or not 0 <= before['sequence'] < after['sequence']
            or before['money'] != after['money']
            or before['custody'] != after['custody']
            or after['money'] != case['money']
            or after['custody'] != case['custody']
            or case['money']['operation'] != 'none'
            or case['money']['journal'] != []
            or after['new_effect_ids'] != case['effects']):
        raise ValueError('negative_unauthorized_change')


SERVICE_WORK_FEATURES = {
    'service_maintenance', 'service_repair', 'service_cleaning',
    'service_polishing', 'service_enlargement', 'service_reduction',
}
PAID_WORK_FEATURES = SERVICE_WORK_FEATURES | {
    'paid_customization', 'paid_customization_job', 'purchase_then_customization',
}

JOB_REVIEW_FEATURES = SERVICE_WORK_FEATURES | {
    'independent_brand_approval', 'brand_approval', 'paid_customization',
    'paid_customization_job', 'purchase_then_customization',
}

MONEY_FEATURES = {
    'allocation_fixed_price', 'allocation_auction', 'allocation_offer', 'allocation_job',
    'fixed_price_reservation', 'payment_confirmation', 'balanced_simulated_journal',
    'failed_inspection', 'failed_inspection_collection', 'principal_only_refund',
    'refund', 'payout', 'payout_reconciliation', 'paid_customization',
    'paid_customization_job', 'purchase_then_customization',
    'service_maintenance', 'service_repair', 'service_cleaning',
    'service_polishing', 'service_enlargement', 'service_reduction',
}


def validate_authority(authority, case, job_review=True, service_work=False):
    if (authority['current'] is not True
            or type(authority['revision']) is not int
            or authority['revision'] < 1
            or authority['expected_revision'] != authority['revision']):
        raise ValueError('authority_current')
    if not job_review:
        return
    roles = authority['roles']
    required_roles = {'assessor', 'brand_approver', 'quality_reviewer'}
    if not service_work:
        required_roles.add('eligibility_reviewer')
    if (not required_roles <= set(roles)
            or set(roles) - required_roles - ({'eligibility_reviewer'} if service_work else set())):
        raise ValueError('authority_roles')
    people = []
    for role, binding in roles.items():
        people.append(binding['actor_id'])
        if (not isinstance(binding['actor_id'], str) or not binding['actor_id']
                or binding['organization_id'] != authority['organization_id']
                or binding['subject_id'] != case['watch_id']
                or binding['role'] != role or binding['active'] is not True):
            raise ValueError('authority_scope')
        for field in ('membership_revision', 'assignment_revision'):
            if (type(binding[field]) is not int or binding[field] < 1
                    or binding[field] != binding['current_' + field]):
                raise ValueError('authority_revision')
    if (len(set(people)) != len(roles) or authority['actor_id'] in people
            or authority['buyer_id'] in people or not authority['organization_id']):
        raise ValueError('authority_independence')


def validate_economics(case, confirmation=False):
    money = case['money']
    terms = money['retained_terms']
    if (terms['buyer_id'] != case['authority']['buyer_id']
            or terms['watch_id'] != case['watch_id']):
        raise ValueError('retained_subject_binding')
    principal = terms['principal_minor']
    if type(principal) is not int or principal <= 0 or terms['route'] not in {'watch', 'job'}:
        raise ValueError('retained_principal')
    buyer_fee = (principal * 3 + 50) // 100 if terms['route'] == 'watch' else 0
    business_fee = (principal * 5 + 50) // 100
    components = dict(principal_minor=principal, buyer_fee_minor=buyer_fee,
                      business_fee_minor=business_fee, total_minor=principal + buyer_fee)
    for key, amount in components.items():
        if type(terms[key]) is not int or terms[key] != amount:
            raise ValueError('retained_components')
    if money['principal_minor'] != principal or terms['currency'] != 'USD':
        raise ValueError('retained_money')
    if (type(money['business_fee_receivable_minor']) is not int
            or money['business_fee_receivable_minor'] != business_fee
            or money['collected_fee_minor'] != (
                buyer_fee if money['payment_state'] == 'paid_held' else 0)):
        raise ValueError('fee_components')
    if confirmation:
        payment = money['confirmation']
        for key in ('order_id', 'quote_id', 'quote_revision', 'buyer_id', 'currency',
                    'total_minor', 'route', 'watch_id'):
            if payment[key] != terms[key]:
                raise ValueError('confirmation_binding')
        if (any(not isinstance(terms[k], str) or not terms[k]
                       for k in ('order_id', 'quote_id', 'buyer_id'))
                or type(terms['quote_revision']) is not int or terms['quote_revision'] < 1
                or payment['operation_id'] != case['operation_id']
                or payment['state'] != 'paid_held' or money['payment_state'] != 'paid_held'
                or money['operation'] != 'collection'
                or type(payment['revision']) is not int or payment['revision'] < 1):
            raise ValueError('required_confirmation')


def validate_outcomes(outcome, evidence):
    """Validate proposed native-outcome.v1 observations; connected decoding is deferred."""
    if not isinstance(outcome, dict):
        raise ValueError('outcome_shape')
    if outcome.get('schema_version') != 'native-outcome.v1':
        raise ValueError('outcome_contract')
    for key in ('requirement', 'source_revision', 'run_id', 'origin'):
        if outcome.get(key) != evidence[key]:
            raise ValueError('outcome_binding')
    cases = outcome['cases']
    if set(cases) != {'positive', 'negative', 'recovery'}:
        raise ValueError('outcome_cases')
    operations = set()
    for kind, case in cases.items():
        operation = case['operation_id']
        if not isinstance(operation, str) or not operation or operation in operations:
            raise ValueError('outcome_operation')
        operations.add(operation)
        if case['assertion'] != evidence['content'][kind]:
            raise ValueError('outcome_assertion')
        if kind != 'negative' and case['state'] != evidence['content'][kind + '_state']:
            raise ValueError('outcome_state')
        if kind == 'negative' and (
                case['state'] != evidence['content']['negative_state']
                or case['effects'] != evidence['content']['negative_effects']
                or case['mutated'] is not bool(case['effects'])
                or (case['effects'] and (case['hold'] is not True
                                        or case['settlement_state'] != 'held'))):
            raise ValueError('negative_mutation')
        if kind == 'negative':
            validate_negative_transition(case, evidence)
        if kind == 'recovery':
            validate_retry(case, evidence)
        authority = case['authority']
        feature = evidence['content']['feature']
        validate_authority(authority, case, feature in JOB_REVIEW_FEATURES,
                           feature in SERVICE_WORK_FEATURES)
        money = case['money']
        fields = ('principal_minor', 'collected_fee_minor', 'refund_minor',
                  'reserved_refund_minor', 'refunded_fee_minor', 'payout_minor')
        if any(type(money[k]) is not int or money[k] < 0 for k in fields):
            raise ValueError('money_minor')
        if (feature in PAID_WORK_FEATURES
                and money['retained_terms']['route'] != 'job'):
            raise ValueError('required_job_route')
        if feature in MONEY_FEATURES or money['principal_minor'] > 0:
            validate_economics(case, kind != 'negative' and feature == 'payment_confirmation')
        elif (any(money[k] for k in fields) or money['operation'] != 'none'
              or money['payment_state'] != 'unpaid' or money.get('retained_terms')
              or money.get('business_fee_receivable_minor', 0)):
            raise ValueError('noncommercial_money')
        journal = money['journal']
        if (not isinstance(journal, list) or any(type(v) is not int for v in journal)
                or sum(journal) != 0 or money['currency'] != 'USD'
                or money['refunded_fee_minor'] != 0
                or money['refund_minor'] + money['reserved_refund_minor'] > money['principal_minor']):
            raise ValueError('outcome_money')
        if (money['payout_minor'] + money['refund_minor'] + money['reserved_refund_minor']
                > money['principal_minor']):
            raise ValueError('payout_limit')
        posting = money['operation']
        amounts = {'none': 0, 'collection': money['principal_minor'] + money['collected_fee_minor'],
                   'refund': money['refund_minor'], 'payout': money['payout_minor']}
        if posting not in amounts or sum(v for v in journal if v > 0) != amounts[posting]:
            raise ValueError('journal_amount')
        if ((money['payout_minor'] and posting != 'payout')
                or (money['refund_minor'] and posting != 'refund')):
            raise ValueError('financial_operation')
        if posting == 'none' and journal:
            raise ValueError('unexpected_posting')
        if money['payment_state'] in {'unpaid', 'awaiting_payment'} and (
                posting != 'none' or any(money[k] for k in fields[1:])):
            raise ValueError('unpaid_posting')
        if case['settlement_state'] not in {'not_applicable', 'awaiting_payment', 'paid_held', 'completed', 'paid_out', 'held', 'refunded'}:
            raise ValueError('settlement_state')
        custody = case['custody']
        if custody['received'] is True and (
                not custody['receipt_id'] or custody['watch_id'] != case['watch_id']
                or custody['recipient_id'] != custody['authorized_recipient']
                or custody['proof_kind'] not in {'buyer_acknowledgement', 'approved_receipt'}):
            raise ValueError('outcome_receipt')
        collection_required = (kind != 'negative' and evidence['content']['feature']
                               in {'failed_inspection', 'failed_inspection_collection'})
        if (custody['return_dispatched'] is True or collection_required) and (
                custody['collection_state'] != 'confirmed' or not custody['return_instruction_id']
                or type(custody['return_trip_minor']) is not int or custody['return_trip_minor'] < 0
                or custody['collected_minor'] != (money['principal_minor'] * 5 + 50) // 100
                + custody['return_trip_minor']):
            raise ValueError('outcome_return')
        feature = evidence['content']['feature']
        if kind != 'negative' and feature in {'refund', 'principal_only_refund'} and (
                money['operation'] != 'refund' or money['refund_minor'] <= 0
                or case['settlement_state'] != 'refunded'
                or case['refund_authorization']['operation_id'] != operation
                or case['refund_authorization']['authorized'] is not True
                or case['refund_authorization']['principal_minor'] != money['refund_minor']
                or not case['refund_authorization']['decision_id']):
            raise ValueError('required_refund')
        if kind != 'negative' and feature in {'actual_receipt', 'receipt_window', 'quality_handover'} and custody['received'] is not True:
            raise ValueError('required_receipt')
        if kind != 'negative' and feature in {'payout', 'payout_reconciliation'} and (
                case['settlement_state'] != 'paid_out'
                or money['payout_minor'] != money['principal_minor'] - (money['principal_minor'] * 5 + 50) // 100):
            raise ValueError('required_payout')
        if kind != 'negative' and feature in PAID_WORK_FEATURES and (
                case['settlement_state'] not in {'completed', 'paid_out'}
                or money['payment_state'] != 'paid_held'
                or money['operation'] not in {'collection', 'payout'}):
            raise ValueError('required_paid_work_completion')
        if case['state'] == 'awaiting_payment' and case['settlement_state'] != 'awaiting_payment':
            raise ValueError('reservation_completion')
        if case['settlement_state'] in {'completed', 'paid_out'} and (
                money['payment_state'] != 'paid_held' or custody['received'] is not True
                or case['quality'] != 'passed' or case['window_expired'] is not True
                or case['hold'] is not False):
            raise ValueError('outcome_completion')
        if money['payout_minor'] and case['settlement_state'] != 'paid_out':
            raise ValueError('outcome_payout')


def assemble(plan, records, root, origin, run_id):
    rows = check_plan(plan)
    indexed = {}
    errors = []
    for record in records:
        key = record.get('requirement')
        if key in indexed or key not in {r['id'] for r in rows}:
            errors.append('duplicate_or_unknown_evidence')
        indexed[key] = record
    missing = []
    for row in rows:
        try:
            validate_evidence(row, indexed.get(row['id'], {}), root, origin, run_id)
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            missing.append(row['id'])
    # No exact provider outcome decoder is published on this input revision.
    # Claimed labels and arbitrary hashed bytes cannot establish business facts.
    errors.extend(['provider_outcome_contracts_deferred', 'original_inventory_alignment_deferred'])
    return {'schema_version': 'native-acceptance.v1', 'complete': not missing and not errors,
            'missing_capabilities': missing, 'errors': errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-plan', action='store_true')
    parser.add_argument('--origin')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--require-all', action='store_true')
    args = parser.parse_args(argv)
    plan = json.loads(PLAN.read_text())
    rows = check_plan(plan)
    if args.check_plan:
        print(json.dumps({'plan_valid': True, 'requirements': len(rows),
                          'deferred_bindings': [r['id'] for r in rows if r['entrypoint'] is None]}))
        return 0
    if not args.origin or not args.run_dir or not args.require_all:
        parser.error('origin, run-dir and require-all are required')
    origin = urlsplit(args.origin)
    if (origin.scheme not in {'http', 'https'} or origin.hostname not in {'localhost', '127.0.0.1'}
            or origin.username or origin.password or origin.path not in {'', '/'}
            or origin.query or origin.fragment):
        parser.error('local origin required')
    try:
        envelope = json.loads((args.run_dir / 'provider-evidence.json').read_text())
        if envelope['schema_version'] != 'native-run.v1' or not envelope['run_id']:
            raise ValueError('run_contract')
        report = assemble(plan, envelope['records'], args.run_dir, args.origin, envelope['run_id'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report = {'complete': False, 'errors': ['missing_or_invalid_provider_evidence'],
                  'missing_capabilities': [r['id'] for r in rows]}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

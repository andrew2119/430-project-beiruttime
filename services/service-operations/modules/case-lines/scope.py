"""Verify an accepted scope against its current authoritative binding."""
from bt_contracts.service.case_lines.v1 import RetainedTerms, ScopeAcceptance, ScopeBinding


def current_acceptance(scope, acceptance: ScopeAcceptance, *, binding: ScopeBinding,
                       current_terms_revision: int, current_terms: RetainedTerms) -> bool:
    if not isinstance(acceptance, ScopeAcceptance) or not isinstance(binding, ScopeBinding):
        return False
    if any(getattr(acceptance, key) != getattr(binding, key) for key in ScopeBinding.model_fields):
        return False
    if (acceptance.request_id != scope.request_id
            or acceptance.request_revision != scope.request_revision
            or acceptance.expected_revision != scope.revision
            or type(current_terms_revision) is not int
            or acceptance.accepted_terms_revision != current_terms_revision
            or acceptance.reviewed_terms != current_terms
            or set(acceptance.accepted_line_ids) != set(scope.accepted_line_ids)):
        return False
    try:
        return scope.accepted_total() == acceptance.total_minor
    except ValueError:
        return False

"""Shared current-context fixtures for policy and adapter checks."""
from uuid import UUID
import pytest


def identifier(number):
    return str(UUID(int=number))


@pytest.fixture
def current():
    return dict(schema_version='eligibility-current.v1', subject_id=identifier(1), organization_id=identifier(2),
                watch_id=identifier(3), request_id=identifier(4), request_revision=1, quote_id=identifier(5),
                quote_revision=1, consent_revision=1, reviewer_id=identifier(6), brand_approver_id=identifier(7),
                assignment_revision=1, policy_revision='objective-identity-v1', purpose='brand-request-identity',
                identity_current=True, organization_current=True, assignment_current=True,
                accepted_scope_current=True, commitment_current=True, source_facts_current=True,
                synthetic_identity_pass=True, now='2026-11-16T12:00:00+00:00', expires_at='2026-11-16T13:00:00+00:00')


@pytest.fixture
def consent(current):
    return dict(buyer_id=current['subject_id'], brand_id=current['organization_id'], request_id=current['request_id'],
                request_revision=1, revision=1, status='active')

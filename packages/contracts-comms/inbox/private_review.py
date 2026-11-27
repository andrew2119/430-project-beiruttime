"""Identity private-review event data, version 1."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt
from bt_contracts_core.models import Contract


class PrivateReviewV1(Contract):
    subject_id: UUID
    review_id: UUID
    application_id: UUID
    application_revision: StrictInt = Field(ge=1)
    revision: StrictInt = Field(ge=1)
    state: Literal["assigned", "correction", "approved", "rejected", "suspended"]
    reviewer_id: UUID

"""Brand-only commands retain the complete assessed configuration."""

from pydantic import model_validator
from bt_contracts.pricing.quotes.assessed import (
    IssueQuote as AssessedIssueQuote,
    AcceptQuote,
    DeclineQuote,
)


class IssueQuote(AssessedIssueQuote):
    @model_validator(mode="after")
    def complete_configuration(self):
        if any(not line.mandatory for line in self.lines):
            raise ValueError("Review the complete assessed configuration")
        if (
            not any(line.amount_minor for line in self.lines)
            and not self.assessment_fee_minor
        ):
            raise ValueError("Quote a positive assessed amount")
        return self


__all__ = ["IssueQuote", "AcceptQuote", "DeclineQuote"]

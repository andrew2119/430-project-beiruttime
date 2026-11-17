import re
from typing import Literal
from bt_contracts.catalog.options import SophisticationDetails


class FinishingPackage(SophisticationDetails):
    currency: Literal["USD"]


def validate(details, component):
    if component != "package":
        raise ValueError("Sophistication is a named package, not a component score")
    package = FinishingPackage.model_validate(details)
    # V1 packages may finish existing work, never advertise complication conversions.
    forbidden = re.compile(r"tourbillon|chronograph|conversion|توربيون|كرونوغراف|تحويل", re.IGNORECASE)
    if any(forbidden.search(text) for entry in package.interventions for text in (entry.en, entry.ar)):
        raise ValueError("Complication conversion is outside defined finishing packages")
    return package.model_dump(mode="json")

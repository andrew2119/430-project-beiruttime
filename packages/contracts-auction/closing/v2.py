"""Fixed-end temporal results. A legacy review does not resolve held money."""

from typing import Literal
from pydantic import Field, StrictInt
from . import CloseResult


class CloseResultV2(CloseResult):
    status: Literal["not_closed", "no_sale", "allocation_pending", "allocation_denied", "closed", "ended_legacy_review"]
    close_version: StrictInt | None = Field(default=None, ge=0)

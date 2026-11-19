"""Exact buyer targets; never a quality verdict."""
import re
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class MeasurementError(ValueError):
    pass


def millimeters(value: str, unit: str) -> int:
    if not isinstance(value, str) or len(value) > 32 or unit not in ('cm', 'mm'):
        raise MeasurementError('invalid_measurement')
    value = value.strip().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫', '01234567890123456789.'))
    match = re.fullmatch(r'([0-9]{1,3}(?:\.[0-9])?)\s*(cm|mm|سم|مم)?', value)
    if not match or match[2] and match[2] not in ({'cm', 'سم'} if unit == 'cm' else {'mm', 'مم'}):
        raise MeasurementError('invalid_measurement')
    exact = Decimal(match[1]) * (10 if unit == 'cm' else 1)
    if exact != exact.to_integral_value() or not 80 <= exact <= 300:
        raise MeasurementError('invalid_measurement')
    return int(exact)


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal['fit-measurement.v1']
    operation_id: UUID
    subject_id: UUID
    watch_id: UUID
    organization_id: UUID
    expected_revision: StrictInt = Field(ge=0, le=2147483646)
    source_revision: StrictInt = Field(ge=1, le=2147483647)
    circumference: str = Field(min_length=1, max_length=32)
    unit: Literal['cm', 'mm']
    method: Literal['tape', 'string_and_ruler']
    source: Literal['buyer_measured']
    target: Literal['close', 'comfortable', 'loose']
    final_fit_pass: Literal[False]

    @field_validator('final_fit_pass', mode='before')
    @classmethod
    def never_final_pass(cls, value):
        if value is not False:
            raise ValueError('invalid_measurement')
        return value

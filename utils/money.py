"""Monetary precision utilities.

Centralizes Decimal type handling for all monetary fields in the system.
Replaces IEEE 754 float with exact decimal arithmetic (12 digits, 2 decimal places).

Design: ADR-1 (Money alias), ADR-2 (Decimal128 storage), ADR-3 (ROUND_HALF_UP).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Union

from bson import Decimal128
from pydantic import AfterValidator, BeforeValidator, Field
from typing_extensions import Annotated


def _bson_to_decimal(v: Any) -> Decimal:
    """BeforeValidator: convert Decimal128 (DB reads) to Decimal; reject float.

    Float rejection MUST happen in the BeforeValidator because Pydantic's
    built-in Decimal schema coerces float → Decimal before the AfterValidator
    runs, making it impossible to detect float inputs later.
    """
    if isinstance(v, float):
        raise ValueError(
            "float is not accepted for monetary fields; "
            "use Decimal, string, or int instead"
        )
    if isinstance(v, Decimal128):
        return v.to_decimal()
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, str)):
        try:
            return Decimal(str(v))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid decimal value: {v!r}") from exc
    return v


def _reject_float(v: Any) -> Any:
    """AfterValidator: pass-through (float is rejected in BeforeValidator).

    Kept for schema visibility and documentation. The actual float guard
    runs in _bson_to_decimal because Pydantic's Decimal core schema coerces
    float → Decimal before AfterValidator executes.
    """
    return v


def quantize_money(v: Decimal) -> Decimal:
    """Quantize a Decimal to 2 decimal places with ROUND_HALF_UP.

    ADR-3: commercial rounding convention (spec MUST).
    """
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_decimal128(v: Decimal) -> Decimal128:
    """Convert a Decimal to bson.Decimal128 for MongoDB storage.

    ADR-2: explicit conversion at the service boundary.
    """
    return Decimal128(str(v))


def from_decimal128(v: Any) -> Decimal:
    """Convert bson.Decimal128 back to Decimal.

    Handles both Decimal128 and legacy float (during migration window).
    """
    if isinstance(v, Decimal128):
        return v.to_decimal()
    if isinstance(v, float):
        # Legacy float document — coerce via str to avoid binary noise
        return Decimal(str(v))
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def decimalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert Decimal values to Decimal128 for MongoDB writes.

    Walks nested dicts and lists. Non-Decimal values pass through unchanged.
    pymongo raises InvalidDocument on raw Decimal — this helper makes it one
    line per write site.
    """
    result: Dict[str, Any] = {}
    for key, value in doc.items():
        result[key] = _decimalize_value(value)
    return result


def _decimalize_value(value: Any) -> Any:
    """Recursively convert a single value to Decimal128 if it's a Decimal."""
    if isinstance(value, Decimal):
        return Decimal128(str(value))
    if isinstance(value, dict):
        return {k: _decimalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimalize_value(item) for item in value]
    return value


# --- Pydantic annotated type alias ---

Money = Annotated[
    Decimal,
    Field(max_digits=12, decimal_places=2),
    BeforeValidator(_bson_to_decimal),
    AfterValidator(_reject_float),
]

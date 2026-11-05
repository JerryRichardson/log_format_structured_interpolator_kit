"""Public surface for log_format_structured_interpolator_kit.

Only the names re-exported here are part of the documented API; everything
else in :mod:`core` is an implementation detail and may change.
"""

from .core import (
    FormatError,
    ParsedFormat,
    Segment,
    Literal,
    Field,
    parse_format,
    interpolate,
    structured,
)

__all__ = [
    "FormatError",
    "ParsedFormat",
    "Segment",
    "Literal",
    "Field",
    "parse_format",
    "interpolate",
    "structured",
]

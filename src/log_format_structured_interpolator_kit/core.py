"""Parse printf-style log format strings into structured key/value data.

The problem this solves: log lines are frequently produced by a printf-style
template such as ``"user=%s action=%s took=%dms"``. Downstream observability
pipelines want named fields, but the template only carries positional
arguments. Rather than re-parse the rendered line with a regex (which is
brittle when a ``%s`` value itself contains ``=`` or spaces), we parse the
*template* once and walk the arguments in order.

Design decisions worth calling out:

* Only the conversions that appear in real log templates are supported:
  ``%s``, ``%d``, ``%i``, ``%f``, ``%x``, ``%X``, ``%o``, ``%%``. Unknown
  conversions raise :class:`FormatError` instead of being passed through
  silently, because a silently-wrong field name is worse than a crash.
* Width, precision and flags are accepted and preserved on the segment so a
  caller can re-render, but they do not affect interpolation semantics here:
  we always use ``str()`` for ``%s`` and ``repr``-free formatting for
  numbers, matching what a logging pipeline expects.
* Field *names* are not part of the format string. A printf template has no
  names, so :func:`structured` takes an explicit ``names`` sequence. This is
  the one interpretation we commit to; there is no attempt to guess names
  from surrounding literals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple, Union


class FormatError(ValueError):
    """Raised when a format string cannot be parsed or interpolated."""


_CONVERSIONS = frozenset("sdi fxXo")
# ``%i`` is an alias for ``%d`` in C; keep it as its own conversion code so we
# can report the original spelling back to the caller.
_INT_CONVERSIONS = frozenset("di")
_FLOAT_CONVERSIONS = frozenset("f")
_HEX_CONVERSIONS = frozenset("xX")
_OCT_CONVERSIONS = frozenset("o")

_FLAG_CHARS = "-+ #0"


@dataclass(frozen=True)
class Literal:
    """A run of text copied verbatim from the template."""

    text: str


@dataclass(frozen=True)
class Field:
    """A single conversion, consuming one positional argument.

    ``flags``/``width``/``precision`` are kept so a caller can round-trip the
    original template. ``conversion`` is the bare letter (``"s"``, ``"d"``,
    ...). ``percent`` is True only for the ``%%`` escape, which consumes no
    argument.
    """

    conversion: str
    flags: str = ""
    width: str = ""
    precision: str = ""
    percent: bool = False


Segment = Union[Literal, Field]


@dataclass(frozen=True)
class ParsedFormat:
    """The result of :func:`parse_format`.

    ``segments`` preserves order. ``field_count`` counts only real
    conversions (``%%`` excluded) so callers can validate arity cheaply.
    """

    segments: Tuple[Segment, ...]
    field_count: int

    def render(self, *args: object) -> str:
        """Re-render the template using the stored widths and flags."""
        return interpolate(self, *args)


class _Parser:
    """Hand-rolled scanner. A regex would be shorter but harder to keep
    honest about which conversions are accepted, and the error messages
    would point at a group index instead of an offset."""

    def __init__(self, template: str) -> None:
        if not isinstance(template, str):
            raise TypeError("template must be a str")
        self.template = template
        self.i = 0
        self.n = len(template)

    def parse(self) -> ParsedFormat:
        segments: List[Segment] = []
        buf: List[str] = []
        field_count = 0

        def flush() -> None:
            if buf:
                segments.append(Literal("".join(buf)))
                buf.clear()

        while self.i < self.n:
            ch = self.template[self.i]
            if ch != "%":
                buf.append(ch)
                self.i += 1
                continue
            # ch == "%"
            self.i += 1
            if self.i >= self.n:
                raise FormatError(
                    "trailing '%%' at offset %d" % (self.i - 1)
                )
            if self.template[self.i] == "%":
                # An escaped percent is a literal, not a field.
                buf.append("%")
                self.i += 1
                continue
            field = self._parse_field()
            flush()
            segments.append(field)
            if not field.percent:
                field_count += 1

        flush()
        return ParsedFormat(tuple(segments), field_count)

    def _parse_field(self) -> Field:
        start = self.i - 1  # offset of the '%'
        flags = self._consume_flags()
        width = self._consume_digits()
        precision = ""
        if self.i < self.n and self.template[self.i] == ".":
            self.i += 1
            precision = self._consume_digits(required=False)
        if self.i >= self.n:
            raise FormatError("unterminated conversion at offset %d" % start)
        conv = self.template[self.i]
        if conv not in _CONVERSIONS:
            raise FormatError(
                "unsupported conversion %%%s at offset %d" % (conv, start)
            )
        self.i += 1
        return Field(conversion=conv, flags=flags, width=width, precision=precision)

    def _consume_flags(self) -> str:
        start = self.i
        while self.i < self.n and self.template[self.i] in _FLAG_CHARS:
            self.i += 1
        return self.template[start:self.i]

    def _consume_digits(self, required: bool = True) -> str:
        start = self.i
        while self.i < self.n and self.template[self.i].isdigit():
            self.i += 1
        out = self.template[start:self.i]
        if required and not out:
            # A bare '%' followed by a letter is handled by the caller; the
            # only way to reach here with no digits is a malformed width, so
            # we do not raise. Width is optional in printf, after all.
            return ""
        return out


def parse_format(template: str) -> ParsedFormat:
    """Parse ``template`` into a :class:`ParsedFormat`.

    Raises :class:`FormatError` for a trailing ``%``, an unsupported
    conversion letter, or a conversion that runs off the end of the string.
    """
    return _Parser(template).parse()


def _format_field(field: Field, value: object) -> str:
    conv = field.conversion
    if conv == "s":
        return str(value)
    if conv in _INT_CONVERSIONS:
        if isinstance(value, bool):
            # bool is an int subclass; log pipelines almost always mean the
            # integer 0/1 here rather than the word "True".
            value = int(value)
        if not isinstance(value, int):
            raise FormatError(
                "conversion %%%s requires an int, got %s"
                % (conv, type(value).__name__)
            )
        return str(value)
    if conv in _FLOAT_CONVERSIONS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FormatError(
                "conversion %%%s requires a number, got %s"
                % (conv, type(value).__name__)
            )
        return repr(float(value))
    if conv in _HEX_CONVERSIONS:
        if not isinstance(value, int) or isinstance(value, bool):
            raise FormatError(
                "conversion %%%s requires an int, got %s"
                % (conv, type(value).__name__)
            )
        if conv == "x":
            return format(value, "x")
        return format(value, "X")
    if conv in _OCT_CONVERSIONS:
        if not isinstance(value, int) or isinstance(value, bool):
            raise FormatError(
                "conversion %%%s requires an int, got %s"
                % (conv, type(value).__name__)
            )
        return format(value, "o")
    raise FormatError("unsupported conversion %%%s" % conv)


def interpolate(parsed: ParsedFormat, *args: object) -> str:
    """Render ``parsed`` with ``args``.

    The argument count must match ``parsed.field_count`` exactly. A
    mismatch raises :class:`FormatError` rather than silently dropping or
    padding, since a log line with the wrong arity is a bug worth surfacing.
    """
    if not isinstance(parsed, ParsedFormat):
        raise TypeError("parsed must be a ParsedFormat")
    if len(args) != parsed.field_count:
        raise FormatError(
            "expected %d argument(s), got %d" % (parsed.field_count, len(args))
        )
    out: List[str] = []
    idx = 0
    for seg in parsed.segments:
        if isinstance(seg, Literal):
            out.append(seg.text)
        else:
            out.append(_format_field(seg, args[idx]))
            idx += 1
    return "".join(out)


def structured(
    template: str,
    args: Sequence[object],
    names: Sequence[str],
) -> dict:
    """Parse ``template`` and pair each field with a name from ``names``.

    Returns a plain ``dict`` mapping name -> the *original* argument value,
    not its string rendering. Observability pipelines want the typed value
    (an int stays an int), so we do not stringify here. Literal text is
    discarded; if you need the rendered line, call :func:`interpolate`.

    ``names`` must have exactly one entry per conversion. Duplicate names
    are rejected because a dict would silently keep the last one.
    """
    parsed = parse_format(template)
    if len(names) != parsed.field_count:
        raise FormatError(
            "expected %d name(s) for %d field(s), got %d"
            % (parsed.field_count, parsed.field_count, len(names))
        )
    if len(set(names)) != len(names):
        raise FormatError("duplicate field names in names sequence")
    if len(args) != parsed.field_count:
        raise FormatError(
            "expected %d argument(s), got %d" % (parsed.field_count, len(args))
        )
    result = {}
    idx = 0
    for seg in parsed.segments:
        if isinstance(seg, Field):
            result[names[idx]] = args[idx]
            idx += 1
    return result

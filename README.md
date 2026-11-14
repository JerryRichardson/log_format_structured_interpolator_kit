# log_format_structured_interpolator_kit

Parses printf-style log format strings with positional arguments into a
structured key/value mapping for observability pipelines.

```python
from log_format_structured_interpolator_kit import (
    parse_format,
    interpolate,
    structured,
)

template = "user=%s action=%s took=%dms"

parsed = parse_format(template)
parsed.field_count          # 3
interpolate(parsed, "alice", "login", 12)
# 'user=alice action=login took=12ms'

structured(template, ("alice", "login", 12), ("user", "action", "took_ms"))
# {'user': 'alice', 'action': 'login', 'took_ms': 12}
```

## Why this exists

Log lines are usually produced from a printf template. The template carries
positional arguments, but downstream consumers want named fields. The
obvious alternative is to render the line and re-parse it with a regex, but
that breaks the moment a `%s` value contains `=` or whitespace — which is
exactly when you most want the structured form.

This library parses the *template* once, walks the arguments in order, and
pairs each conversion with a caller-supplied name. The trade-off is that
field names are not inferred: a printf template has no names, so guessing
them from surrounding literals would be unreliable. You pass `names`
explicitly and get back the original typed values (`int` stays `int`).

## The awkward edge

`%%` is a literal percent and consumes no argument, so it also consumes no
name. A template like `"50%% of %d"` has a `field_count` of 1, not 2. If you
derive your `names` list from a naive split on `%`, you will be off by one.

## API

- `parse_format(template) -> ParsedFormat`
- `ParsedFormat.segments`, `ParsedFormat.field_count`, `ParsedFormat.render(*args)`
- `interpolate(parsed, *args) -> str`
- `structured(template, args, names) -> dict`
- `Literal(text)`, `Field(conversion, flags, width, precision, percent)`
- `FormatError`

Supported conversions: `%s`, `%d`, `%i`, `%f`, `%x`, `%X`, `%o`, and `%%`.
Flags, width and precision are parsed and preserved on the segment but do
not change interpolation semantics. Unsupported conversions raise
`FormatError` rather than passing through silently.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.


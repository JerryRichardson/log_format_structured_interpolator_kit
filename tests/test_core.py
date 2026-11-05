import unittest

from log_format_structured_interpolator_kit import (
    Field,
    FormatError,
    Literal,
    ParsedFormat,
    interpolate,
    parse_format,
    structured,
)


class ParseFormatTests(unittest.TestCase):
    def test_plain_literal_only(self):
        parsed = parse_format("no fields here")
        self.assertEqual(parsed.field_count, 0)
        self.assertEqual(parsed.segments, (Literal("no fields here"),))

    def test_single_field(self):
        parsed = parse_format("%s")
        self.assertEqual(parsed.field_count, 1)
        self.assertEqual(len(parsed.segments), 1)
        field = parsed.segments[0]
        self.assertIsInstance(field, Field)
        self.assertEqual(field.conversion, "s")

    def test_literal_field_literal_ordering(self):
        parsed = parse_format("a=%d b=%s")
        self.assertEqual(
            parsed.segments,
            (
                Literal("a="),
                Field(conversion="d"),
                Literal(" b="),
                Field(conversion="s"),
            ),
        )
        self.assertEqual(parsed.field_count, 2)

    def test_escaped_percent_is_literal_and_not_a_field(self):
        parsed = parse_format("100%% done: %d")
        self.assertEqual(parsed.field_count, 1)
        self.assertEqual(parsed.segments[0], Literal("100% done: "))

    def test_width_precision_and_flags_are_preserved(self):
        parsed = parse_format("%08.3f")
        field = parsed.segments[0]
        self.assertEqual(field.flags, "0")
        self.assertEqual(field.width, "8")
        self.assertEqual(field.precision, "3")
        self.assertEqual(field.conversion, "f")

    def test_trailing_percent_raises(self):
        with self.assertRaises(FormatError):
            parse_format("oops %")

    def test_unsupported_conversion_raises(self):
        with self.assertRaises(FormatError):
            parse_format("%q")

    def test_unterminated_conversion_raises(self):
        with self.assertRaises(FormatError):
            parse_format("value=%")

    def test_non_string_template_raises_type_error(self):
        with self.assertRaises(TypeError):
            parse_format(123)  # type: ignore[arg-type]


class InterpolateTests(unittest.TestCase):
    def test_basic_render(self):
        parsed = parse_format("user=%s action=%s took=%dms")
        self.assertEqual(
            interpolate(parsed, "alice", "login", 12),
            "user=alice action=login took=12ms",
        )

    def test_escaped_percent_renders_once(self):
        parsed = parse_format("progress 50%% of %d")
        self.assertEqual(interpolate(parsed, 4), "progress 50% of 4")

    def test_hex_and_octal(self):
        parsed = parse_format("%x %X %o")
        self.assertEqual(interpolate(parsed, 255, 255, 8), "ff FF 10")

    def test_wrong_arity_raises(self):
        parsed = parse_format("%s %s")
        with self.assertRaises(FormatError):
            interpolate(parsed, "only-one")

    def test_type_mismatch_raises(self):
        parsed = parse_format("%d")
        with self.assertRaises(FormatError):
            interpolate(parsed, "not-an-int")

    def test_bool_is_accepted_for_int_conversion(self):
        parsed = parse_format("%d")
        self.assertEqual(interpolate(parsed, True), "1")

    def test_render_method_matches_interpolate(self):
        parsed = parse_format("%s=%d")
        self.assertEqual(parsed.render("k", 7), interpolate(parsed, "k", 7))

    def test_non_parsed_argument_raises_type_error(self):
        with self.assertRaises(TypeError):
            interpolate("not parsed", 1)  # type: ignore[arg-type]


class StructuredTests(unittest.TestCase):
    def test_basic_mapping_preserves_types(self):
        result = structured(
            "user=%s action=%s took=%dms",
            ("alice", "login", 12),
            ("user", "action", "took_ms"),
        )
        self.assertEqual(
            result,
            {"user": "alice", "action": "login", "took_ms": 12},
        )
        self.assertIsInstance(result["took_ms"], int)

    def test_escaped_percent_consumes_no_name(self):
        result = structured("50%% %d", (3,), ("count",))
        self.assertEqual(result, {"count": 3})

    def test_name_count_mismatch_raises(self):
        with self.assertRaises(FormatError):
            structured("%s %s", ("a", "b"), ("only_one",))

    def test_duplicate_names_raise(self):
        with self.assertRaises(FormatError):
            structured("%s %s", ("a", "b"), ("x", "x"))

    def test_argument_count_mismatch_raises(self):
        with self.assertRaises(FormatError):
            structured("%s %s", ("a",), ("x", "y"))

    def test_zero_fields_returns_empty_dict(self):
        self.assertEqual(structured("static text", (), ()), {})


if __name__ == "__main__":
    unittest.main()

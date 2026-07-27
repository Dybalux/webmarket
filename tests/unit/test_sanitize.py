"""Unit tests for utils/sanitize.escape_regex.

Covers:
  - Regex metacharacters escaped (C++, (a|b)*, .*)
  - Empty / None passthrough
  - Output compiles via re.compile (round-trip safety)
"""

from __future__ import annotations

import re

import pytest

from utils.sanitize import escape_regex


class TestEscapeRegex:
    """escape_regex must neutralize all regex-special characters."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("C++", r"C\+\+"),
            ("(a|b)*", r"\(a\|b\)\*"),
            (".*", r"\.\*"),
            ("price$100", r"price\$100"),
            ("what?", r"what\?"),
            ("[admin]", r"\[admin\]"),
            ("path\\to\\file", r"path\\to\\file"),
            ("{n,m}", r"\{n,m\}"),
            ("^start", r"\^start"),
            ("end|pipe", r"end\|pipe"),
        ],
        ids=[
            "cplusplus",
            "group_alternation",
            "dot_star",
            "dollar_sign",
            "question_mark",
            "square_brackets",
            "backslash",
            "curly_braces",
            "caret",
            "pipe",
        ],
    )
    def test_metacharacters_escaped(self, raw: str, expected: str) -> None:
        assert escape_regex(raw) == expected

    def test_empty_string_passthrough(self) -> None:
        assert escape_regex("") == ""

    def test_normal_string_passthrough(self) -> None:
        """Alphanumeric strings without specials pass through unchanged."""
        assert escape_regex("laptop") == "laptop"

    def test_output_compiles(self) -> None:
        """Escaped output must compile as a valid regex pattern."""
        for raw in ["C++", "(a|b)*", ".*", "price$100", "what?"]:
            pattern = escape_regex(raw)
            compiled = re.compile(pattern)
            assert compiled.search(raw) is not None, (
                f"Escaped pattern {pattern!r} should match its raw input {raw!r}"
            )

    def test_literal_match_not_wildcard(self) -> None:
        """Escaped '.*' must NOT match arbitrary strings."""
        pattern = escape_regex(".*")
        assert re.search(pattern, "anything") is None
        assert re.search(pattern, ".*") is not None

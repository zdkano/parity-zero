"""Tests for the string utility module."""

import pytest
from utils.string_utils import slugify, truncate, strip_html


class TestSlugify:
    def test_basic_slugify(self):
        assert slugify("Hello World") == "hello-world"

    def test_underscores_replaced(self):
        assert slugify("hello_world") == "hello-world"

    def test_strips_leading_trailing(self):
        assert slugify(" Hello ") == "hello"

    def test_empty_string(self):
        assert slugify("") == ""


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hello", max_length=10) == "hello"

    def test_long_text_truncated(self):
        result = truncate("a" * 200, max_length=100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_custom_suffix(self):
        result = truncate("a" * 200, max_length=50, suffix="…")
        assert result.endswith("…")


class TestStripHtml:
    def test_removes_tags(self):
        assert strip_html("<b>bold</b>") == "bold"

    def test_preserves_plain_text(self):
        assert strip_html("no tags here") == "no tags here"

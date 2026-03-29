"""Tests for the date utility module."""

import pytest
from datetime import datetime, timezone, timedelta
from utils.date_utils import (
    utc_now,
    format_iso,
    parse_iso,
    days_ago,
    is_recent,
    format_relative,
)


class TestUtcNow:
    def test_returns_aware_datetime(self):
        now = utc_now()
        assert now.tzinfo is not None

    def test_is_utc(self):
        now = utc_now()
        assert now.tzinfo == timezone.utc


class TestFormatIso:
    def test_formats_correctly(self):
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert format_iso(dt) == "2026-01-15T10:30:00+00:00"


class TestParseIso:
    def test_parses_correctly(self):
        dt = parse_iso("2026-01-15T10:30:00+00:00")
        assert dt.year == 2026
        assert dt.month == 1


class TestDaysAgo:
    def test_returns_past_date(self):
        past = days_ago(7)
        assert past < utc_now()

    def test_correct_offset(self):
        past = days_ago(1)
        delta = utc_now() - past
        assert abs(delta.days - 1) <= 1


class TestIsRecent:
    def test_recent_datetime(self):
        recent = utc_now() - timedelta(hours=1)
        assert is_recent(recent, hours=24)

    def test_old_datetime(self):
        old = utc_now() - timedelta(days=30)
        assert not is_recent(old, hours=24)


class TestFormatRelative:
    def test_days_ago(self):
        dt = utc_now() - timedelta(days=5)
        result = format_relative(dt)
        assert "day" in result

    def test_hours_ago(self):
        dt = utc_now() - timedelta(hours=3)
        result = format_relative(dt)
        assert "hour" in result
